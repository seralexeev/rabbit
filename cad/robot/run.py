"""One entry point for the design loop: build -> look -> measure -> check.

    uv run --project model python cad/robot/run.py build                 # GLB + parts.json for the viewer
    uv run --project model python cad/robot/run.py render iso,rear --focus motor_can_left --hide fastener
    uv run --project model python cad/robot/run.py measure motor_can_left deck_1
    uv run --project model python cad/robot/run.py info wheel_rear_left
    uv run --project model python cad/robot/run.py list motor
    uv run --project model python cad/robot/run.py check                 # overlaps of new parts with everything
    uv run --project model python cad/robot/run.py export                # exact STEP + GLB (slow)
    uv run --project model python cad/robot/run.py serve                 # live viewer on http://127.0.0.1:8765

Outputs go to data/cad/robot/ (gitignored); renders to data/cad/robot/renders/.
"""

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mesh import OUT, mesh, write  # noqa: E402
from robot import ALLOWED_CONTACTS, build, export_exact  # noqa: E402

VIEWS = {
    "iso": ((1.0, -1.2, 0.9), (0, 0, 1)),
    "iso_rear": ((-1.0, 1.2, 0.8), (0, 0, 1)),
    "top": ((0, 0, 1), (0, -1, 0)),
    "bottom": ((0, 0, -1), (0, -1, 0)),
    "left": ((1, 0, 0), (0, 0, 1)),
    "right": ((-1, 0, 0), (0, 0, 1)),
    "front": ((0, -1, 0), (0, 0, 1)),
    "rear": ((0, 1, 0), (0, 0, 1)),
}


def select(parts, only=None, hide=None):
    def match(name, p, pats):
        return any(pat == p["group"] or pat in name for pat in pats)

    return {n: p for n, p in parts.items()
            if (not only or match(n, p, only)) and not (hide and match(n, p, hide))}


def cmd_build(a):
    t = time.time()
    parts = build(light=True)
    glb = write(parts)
    print(f"{len(parts)} parts -> {glb} ({glb.stat().st_size / 1e6:.1f} MB) in {time.time() - t:.1f} s")


def cmd_render(a):
    import numpy as np
    import pyvista as pv

    parts = select(build(light=True), a.only, a.hide)
    focus = None
    if a.focus:
        boxes = [p["shape"].bounding_box() for n, p in parts.items() if any(f in n for f in a.focus)]
        lo = np.min([[b.min.X, b.min.Y, b.min.Z] for b in boxes], 0) - a.margin
        hi = np.max([[b.max.X, b.max.Y, b.max.Z] for b in boxes], 0) + a.margin
        focus = (lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])
    outdir = OUT / "renders"
    outdir.mkdir(parents=True, exist_ok=True)
    for view in a.views.split(","):
        pl = pv.Plotter(off_screen=True, window_size=(a.width, int(a.width * 0.7)))
        pl.set_background("white")
        for n, p in parts.items():
            v, f = mesh(p["shape"], p["key"])
            if len(f):
                faces = np.hstack([np.full((len(f), 1), 3), f]).ravel()
                pl.add_mesh(pv.PolyData(v, faces), color=p["colour"], specular=0.2,
                            opacity=a.opacity if (a.ghost and any(g in n or g == p["group"] for g in a.ghost)) else 1.0)
        d, up = VIEWS[view]
        pl.view_vector(d, viewup=up)
        if view in ("top", "bottom", "left", "right", "front", "rear"):
            pl.enable_parallel_projection()
        pl.reset_camera(bounds=focus) if focus else pl.reset_camera()
        pl.camera.zoom(a.zoom)
        if a.title:
            pl.add_text(a.title, font_size=12, color="black")
        path = outdir / f"{a.name}_{view}.png"
        pl.screenshot(str(path))
        pl.close()
        print(path)


def exact(names):
    parts = build(light=False)
    missing = [n for n in names if n not in parts]
    if missing:
        sys.exit(f"unknown part(s): {missing}; try `run.py list`")
    return parts


def cmd_measure(a):
    parts = exact([a.a, a.b])
    A, B = parts[a.a]["shape"], parts[a.b]["shape"]
    d, pa, pb = A.distance_to_with_closest_points(B)
    ba, bb = A.bounding_box(), B.bounding_box()
    print(f"min distance {d:.2f} mm between {tuple(round(x, 2) for x in pa)} and {tuple(round(x, 2) for x in pb)}")
    for ax in "XYZ":
        gap = max(getattr(bb.min, ax) - getattr(ba.max, ax), getattr(ba.min, ax) - getattr(bb.max, ax))
        print(f"  {ax}: {'gap' if gap > 0 else 'overlap'} {abs(gap):.2f} mm (box {a.a} {getattr(ba.min, ax):.2f}..{getattr(ba.max, ax):.2f}, {a.b} {getattr(bb.min, ax):.2f}..{getattr(bb.max, ax):.2f})")


def cmd_info(a):
    p = exact([a.name])[a.name]
    s, b = p["shape"], p["shape"].bounding_box()
    print(json.dumps({"name": a.name, "group": p["group"], "volume_mm3": round(s.volume, 1),
                      "min": [round(b.min.X, 2), round(b.min.Y, 2), round(b.min.Z, 2)],
                      "max": [round(b.max.X, 2), round(b.max.Y, 2), round(b.max.Z, 2)],
                      "size": [round(b.size.X, 2), round(b.size.Y, 2), round(b.size.Z, 2)]}, indent=1))


def cmd_list(a):
    for r in json.loads((OUT / "parts.json").read_text()):
        if not a.pattern or a.pattern in r["name"] or a.pattern == r["group"]:
            print(f'{r["name"]:34} {r["group"]:9} {r["min"]} .. {r["max"]}')


def common_volume(a, b):
    """Volume of a & b with a 1e-4 mm fuzzy tolerance, parallel and OBB pre-checks: coincident faces
    (screw in a tapped hole, plate on a bracket) otherwise make OCCT's boolean take ~50 s per pair."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopTools import TopTools_ListOfShape

    la, lb = TopTools_ListOfShape(), TopTools_ListOfShape()
    la.Append(a.wrapped)
    lb.Append(b.wrapped)
    op = BRepAlgoAPI_Common()
    op.SetArguments(la)
    op.SetTools(lb)
    op.SetFuzzyValue(1e-4)
    op.SetRunParallel(True)
    op.SetUseOBB(True)
    op.Build()
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(op.Shape(), g)
    return g.Mass()


def mesh_volume(pa, pb):
    """Overlap volume from the cached tessellations (manifold3d): milliseconds per pair, accurate to the
    0.3 mm mesh tolerance. Returns None if a mesh is not watertight, so the caller falls back to OCCT."""
    import trimesh

    ms = []
    for p in (pa, pb):
        v, f = mesh(p["shape"], p["key"])
        m = trimesh.Trimesh(v, f, process=True)
        if not m.is_watertight:
            return None
        ms.append(m)
    inter = trimesh.boolean.intersection(ms, engine="manifold")
    return float(inter.volume) if inter is not None and len(inter.faces) else 0.0


def cmd_check(a):
    """Overlap volume of every part we added (not from the kit) with every other part.
    Exact geometry, except tyres (their envelope). Each pair's result is cached by the two parts'
    content keys, so a re-check only computes pairs where a part changed; progress is printed."""
    t0 = time.time()
    parts = build(light=False)
    for n, p in build(light=True).items():
        if p["group"] == "wheel":
            parts[n] = p
    cache_path = OUT / "check_cache_v2.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    mine = [n for n, p in parts.items() if not p.get("kit")] if not a.all else list(parts)
    pairs = []
    for n in mine:
        alo, ahi = parts[n]["box"]
        for m, p in parts.items():
            if m == n or (a.all and m < n) or (n, m) in ALLOWED_CONTACTS or (m, n) in ALLOWED_CONTACTS:
                continue
            blo, bhi = p["box"]
            if any(alo[i] > bhi[i] or blo[i] > ahi[i] for i in range(3)):
                continue
            pairs.append((n, m))
    rows, fresh = [], 0
    for k, (n, m) in enumerate(pairs, 1):
        key = ("exact|" if a.exact else "mesh|") + "|".join(sorted((parts[n]["key"], parts[m]["key"])))
        if key not in cache:
            t = time.time()
            v = None if a.exact else mesh_volume(parts[n], parts[m])
            how = "mesh"
            if v is None:
                v, how = common_volume(parts[n]["shape"], parts[m]["shape"]), "exact"
            cache[key] = v
            fresh += 1
            print(f"  [{k}/{len(pairs)}] {n} x {m}: {v:.2f} mm3 ({how}, {time.time() - t:.2f} s)", flush=True)
        if cache[key] > a.tol:
            rows.append({"a": n, "b": m, "overlap_mm3": round(cache[key], 2)})
    cache_path.write_text(json.dumps(cache))
    (OUT / "fit_report.json").write_text(json.dumps(rows, indent=1))
    print(f"{len(mine)} parts, {len(pairs)} close pairs ({fresh} computed, {len(pairs) - fresh} cached), "
          f"{len(rows)} overlaps > {a.tol} mm3 in {time.time() - t0:.1f} s")
    for r in rows:
        print(f'  {r["a"]} x {r["b"]}: {r["overlap_mm3"]} mm3')


def cmd_export(a):
    t = time.time()
    print(export_exact(), f"{time.time() - t:.0f} s")


def cmd_serve(a):
    import serve

    serve.main(a.port)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    r = sub.add_parser("render")
    r.add_argument("views", nargs="?", default="iso,iso_rear,top")
    r.add_argument("--name", default="robot")
    r.add_argument("--focus", nargs="*")
    r.add_argument("--margin", type=float, default=15.0)
    r.add_argument("--only", nargs="*")
    r.add_argument("--hide", nargs="*")
    r.add_argument("--ghost", nargs="*", help="parts or groups drawn translucent")
    r.add_argument("--opacity", type=float, default=0.25)
    r.add_argument("--zoom", type=float, default=1.1)
    r.add_argument("--width", type=int, default=1400)
    r.add_argument("--title")
    r.set_defaults(fn=cmd_render)
    m = sub.add_parser("measure")
    m.add_argument("a")
    m.add_argument("b")
    m.set_defaults(fn=cmd_measure)
    i = sub.add_parser("info")
    i.add_argument("name")
    i.set_defaults(fn=cmd_info)
    li = sub.add_parser("list")
    li.add_argument("pattern", nargs="?")
    li.set_defaults(fn=cmd_list)
    c = sub.add_parser("check")
    c.add_argument("--all", action="store_true", help="every pair, kit included (slow)")
    c.add_argument("--tol", type=float, default=1.0)
    c.add_argument("--exact", action="store_true", help="OCCT booleans on the B-rep instead of the meshes (slow first time on threads)")
    c.set_defaults(fn=cmd_check)
    sub.add_parser("export").set_defaults(fn=cmd_export)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_serve)
    args = ap.parse_args()
    args.fn(args)
