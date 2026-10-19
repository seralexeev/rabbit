"""Envelope STEP model of the VL53L8CX (DS14161 Rev 12 p.31 fig. 26): 6.40 x 3.03 x 1.75 mm, substrate 0.25 mm, Rx lens
d 0.51 at the optical centre (1.48 from the left edge, 0.10 below the centre line), Tx window 0.7 square 4.00 to its
right. Frame: KiCad model frame (X right, Y up = -footprint y, Z up), origin at the package centre on the board.

Run: model/.venv/bin/python pcb/rabbit-tof/gen/models.py
"""
from pathlib import Path

from build123d import Box, Compound, Cylinder, Pos, export_step

OUT = Path(__file__).resolve().parents[1] / "3d"


def box(sx, sy, sz, x=0, y=0, z=0):
    return Pos(x, y, z + sz / 2) * Box(sx, sy, sz)


def vl53l8cx():
    sub = box(6.40, 3.03, 0.25)
    cap = box(6.30, 2.93, 1.50, z=0.25)
    rx = Pos(-1.72, -0.10, 1.75 + 0.01) * Cylinder(0.255, 0.02)
    tx = box(0.70, 0.70, 0.02, 2.28, -0.10, 1.75)
    return Compound([sub, cap, rx, tx])


def main():
    OUT.mkdir(exist_ok=True)
    shape = vl53l8cx()
    export_step(shape, str(OUT / "vl53l8cx.step"))
    bb = shape.bounding_box()
    print("vl53l8cx", [round(v, 2) for v in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)])


if __name__ == "__main__":
    main()
