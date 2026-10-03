"""Render the body board on the chassis model and check the vertical clearances.

Run: model/.venv/bin/python pcb/rabbit-body/gen/render_chassis.py
Board frame -> chassis model frame: x_m = 2.482 - X, y_m = -3.427 - Y (180 deg about Z), deck bottom at
DECK_Z = bottom plate top + DECK_GAP. The kit upper plate (deck 3: battery, ZED) is drawn
raised to GAP_2_3 above the PCB, translucent; the kit's 50 mm aluminium standoffs are replaced by the brass stack.
"""
import sys
from pathlib import Path

import numpy as np
import pyvista as pv
from build123d import Location, Rot, import_step

ROOT = Path(__file__).resolve().parents[3]
PRJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
from render import to_mesh  # noqa: E402

BOTTOM_PLATE_TOP = 29.12
GAP_1_2 = 45.0            # deck 1 (kit lower plate) top -> PCB bottom: recommended standoff (today ~40 mm)
GAP_2_3 = 45.0            # PCB top -> deck 3 (kit upper plate) bottom: today's ~45 mm brass standoffs
DECK_Z = BOTTOM_PLATE_TOP + GAP_1_2
TOP_PLATE_Z = DECK_Z + 1.6 + GAP_2_3
CX, CY = 2.482, -3.427


def main():
    chassis = import_step(str(ROOT / "model" / "chassis.step"))
    board = import_step(str(PRJ / "rabbit-body.step"))
    board = board.moved(Location((CX, CY, DECK_Z)) * Rot(0, 0, 180))
    meshes, below = [], []
    for s in chassis.solids():
        bb = s.bounding_box()
        size = bb.size
        if abs(bb.max.Z - 81.12) < 0.05 and size.X > 100:           # kit top plate: raise to the stack height
            s = s.moved(Location((0, 0, TOP_PLATE_Z - 79.12)))
            color, opacity = "#3a3a3a", 0.35
        elif size.Z > 45 and size.X < 8:                           # kit 50 mm standoffs: replaced by the owner's
            continue
        elif min(size.X, size.Y, size.Z) < 2.5 and max(size.X, size.Y) > 100:
            color, opacity = "#3a3a3a", 1.0
        elif abs(size.Y - size.Z) < 1 and size.Y > 60:
            color, opacity = "#1c1c1c", 1.0
        else:
            color, opacity = "#b8b8b8", 1.0
            below.append(bb.max.Z)
        m = to_mesh(s)
        if m is not None:
            meshes.append((m, color, opacity))
    for s in board.solids():
        m = to_mesh(s, 0.3)
        if m is not None:
            bb = s.bounding_box()
            flat = bb.size.Z < 1.7 and bb.size.X > 100
            meshes.append((m, "#2f6b3a" if flat else "#d8d2c4", 1.0))
    print("deck bottom Z", DECK_Z, "highest kit part under the deck Z", round(max(z for z in below if z < DECK_Z + 5), 2))
    out = PRJ / "renders"
    views = {"chassis_iso": ((1.0, -1.25, 0.85), (0, 0, 1)), "chassis_side": ((1, 0, 0), (0, 0, 1)),
             "chassis_top": ((0, 0, 1), (0, -1, 0))}
    for name, (d, up) in views.items():
        pl = pv.Plotter(off_screen=True, window_size=(1600, 1200))
        pl.set_background("white")
        for m, c, o in meshes:
            pl.add_mesh(m, color=c, opacity=o, smooth_shading=False, specular=0.2)
        pl.view_vector(d, viewup=up)
        pl.reset_camera()
        pl.camera.zoom(1.25)
        pl.add_text({"chassis_iso": "Body PCB = deck 2 on the Red Ackerman chassis; deck 3 (kit upper plate) translucent",
                     "chassis_side": "Side view: deck 1 (motors, Jetson), deck 2 = body PCB, deck 3",
                     "chassis_top": "Top view, front up"}[name], font_size=10, color="black")
        pl.screenshot(str(out / f"{name}.png"))
        pl.close()
        print(out / f"{name}.png")


if __name__ == "__main__":
    main()
