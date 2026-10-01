"""Render STEP/BREP models to PNG views with pyvista (offscreen).

Usage: uv run python render.py <model.step|model.brep> [out_prefix]
"""
import sys
from pathlib import Path

import numpy as np
import pyvista as pv
from build123d import import_brep, import_step

# camera direction (from target towards camera), view-up
VIEWS = {
    "iso": ((1.0, -1.2, 0.9), (0, 0, 1)),
    "top": ((0, 0, 1), (0, 1, 0)),
    "side": ((1, 0, 0), (0, 0, 1)),
    "front": ((0, -1, 0), (0, 0, 1)),
}


def load(path: Path):
    return import_brep(str(path)) if path.suffix == ".brep" else import_step(str(path))


def _poly(verts, tris):
    pts = np.array([(v.X, v.Y, v.Z) for v in verts])
    faces = np.hstack([np.full((len(tris), 1), 3), np.array(tris)]).ravel()
    return pv.PolyData(pts, faces)


def to_mesh(solid, tol=0.2):
    try:
        return _poly(*solid.tessellate(tol, 0.3))
    except AttributeError:
        # some imported faces fail to triangulate; mesh face by face and skip those
        parts = []
        for f in solid.faces():
            try:
                verts, tris = f.tessellate(tol, 0.3)
            except AttributeError:
                continue
            if tris:
                parts.append(_poly(verts, tris))
        return pv.merge(parts) if parts else None


def color_for(solid):
    bb = solid.bounding_box()
    sx, sy, sz = bb.size
    if min(sx, sy, sz) < 2.5 and max(sx, sy) > 100:
        return "#3a3a3a"  # sheet-metal plates
    if abs(sy - sz) < 1 and sy > 60:
        return "#1c1c1c"  # wheels
    return "#b8b8b8"


def render(shape, out_prefix: Path, views=VIEWS, size=(1400, 1000)):
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    meshes = [(m, color_for(s)) for s in shape.solids() if (m := to_mesh(s)) is not None]
    paths = []
    for name, (direction, up) in views.items():
        pl = pv.Plotter(off_screen=True, window_size=size)
        pl.set_background("white")
        for m, c in meshes:
            pl.add_mesh(m, color=c, smooth_shading=False, specular=0.2)
        pl.view_vector(direction, viewup=up)
        pl.reset_camera()
        pl.camera.zoom(1.2)
        p = out_prefix.with_name(f"{out_prefix.name}_{name}.png")
        pl.screenshot(str(p))
        pl.close()
        paths.append(p)
    return paths


if __name__ == "__main__":
    src = Path(sys.argv[1])
    prefix = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("renders") / src.stem
    for p in render(load(src), prefix):
        print(p)
