"""Snap-in cable clip for bundles up to BUNDLE_D, fixed with one M3 screw and nut to any 3.2 mm plate hole.

Use it for the ToF twisted pairs, the bumper switch wires, the lidar cable and the camera ribbon
(the ribbon goes flat under the loop). Print on its side (the profile on the bed), no supports.
"""

import math

from build123d import Pos, Rot

from common import M3_CLEAR, box, cyl, export_part, on_bed

BUNDLE_D = 6.5
WALL = 1.6
TAB_L = 10.0
TAB_T = 2.4
WIDTH = 7.0
OPENING = 4.0


def build():
    r_in = BUNDLE_D / 2
    r_out = r_in + WALL
    cx, cz = TAB_L + r_in, r_out
    tab = box(0, cx, -WIDTH / 2, WIDTH / 2, 0, TAB_T)
    ring = Pos(cx, 0, cz) * (Rot(90, 0, 0) * cyl(2 * r_out, WIDTH, centered=True))
    hole = Pos(cx, 0, cz) * (Rot(90, 0, 0) * cyl(2 * r_in, WIDTH + 2, centered=True))
    a = math.radians(-35)
    gap = Pos(cx + r_in * math.cos(a), 0, cz + r_in * math.sin(a)) * Rot(0, 125, 0) * box(-OPENING / 2, OPENING / 2, -WIDTH, WIDTH, -3, 3)
    part = tab + ring - hole - gap
    part -= cyl(M3_CLEAR, TAB_T + 2, TAB_L / 2 - 1, 0, -1)
    return part


if __name__ == "__main__":
    p = build()
    export_part("cable_clip", p, on_bed(Rot(90, 0, 0) * p))
    print("cable_clip", round(p.volume, 1), p.bounding_box().size, p.is_valid, len(p.solids()))
