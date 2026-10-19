"""Tessellation cache and GLB writer for fast rebuilds.

Each part is tessellated once per (key, tolerance) and kept in data/cad/robot/mesh/; a rebuild only
meshes parts that changed. The GLB keeps one named node per part, and parts.json lists them with
group and bounding box for the viewer and for agents.
"""

import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "cad" / "robot"
CACHE = OUT / "mesh"


def shape_key(shape):
    """Content hash of a shape's BREP: any change to the geometry or its placement changes the key."""
    from build123d import export_brep

    buf = io.BytesIO()
    export_brep(shape, buf)
    return hashlib.sha1(buf.getvalue()).hexdigest()


def mesh(shape, key, tol=0.3):
    """(vertices Nx3, triangles Mx3) for a shape, cached under key."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{hashlib.sha1(f'{key}|{tol}'.encode()).hexdigest()}.npz"
    if path.exists():
        d = np.load(path)
        return d["v"], d["f"]
    v, f = triangulate(shape.wrapped, tol)
    np.savez(path, v=v, f=f)
    return v, f


def triangulate(occ_shape, tol):
    """BRepMesh per face; faces the mesher cannot triangulate are skipped instead of failing the part."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(occ_shape, tol, False, 0.5, True)
    verts, tris = [], []
    exp = TopExp_Explorer(occ_shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        exp.Next()
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        base = len(verts)
        for i in range(1, tri.NbNodes() + 1):
            p = tri.Node(i).Transformed(trsf)
            verts.append((p.X(), p.Y(), p.Z()))
        flip = face.Orientation() == TopAbs_REVERSED
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            tris.append((base + a - 1, base + c - 1, base + b - 1) if flip else (base + a - 1, base + b - 1, base + c - 1))
    return np.array(verts, dtype=np.float32).reshape(-1, 3), np.array(tris, dtype=np.int32).reshape(-1, 3)


def write(parts, name="robot"):
    """parts: {name: {"shape", "group", "colour", "key"}} -> OUT/<name>.glb and OUT/parts.json (atomic)."""
    import trimesh

    OUT.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene()
    rows = []
    for pname, p in parts.items():
        v, f = mesh(p["shape"], p["key"])
        if not len(f):
            continue
        m = trimesh.Trimesh(v, f, process=False)
        rgb = [int(p["colour"][i : i + 2], 16) for i in (1, 3, 5)]
        m.visual.face_colors = rgb + [255]
        scene.add_geometry(m, node_name=pname, geom_name=pname)
        lo, hi = v.min(0), v.max(0)
        rows.append({"name": pname, "group": p["group"], "colour": p["colour"], "min": [round(float(x), 2) for x in lo],
                     "max": [round(float(x), 2) for x in hi]})
    tmp = OUT / f".{name}.glb.tmp"
    tmp.write_bytes(scene.export(file_type="glb"))
    os.replace(tmp, OUT / f"{name}.glb")
    (OUT / "parts.json").write_text(json.dumps(rows, indent=0))
    return OUT / f"{name}.glb"
