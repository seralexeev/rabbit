"""Stereolabs ZED 2i as a proxy from the datasheet (datasheet/ZED 2i Datasheet v1.2.pdf p.2: 175.3 x 30.3 x 43.1 mm)
and the technical drawing (datasheet/ZED/ZED 2i technical drawing (Stereolabs, via Clearpath).pdf): a box with
fully rounded ends seen from the front, the two lenses 120 mm apart; on the bottom a 1/4"-20 thread with two M3
holes 18 mm either side (36 mm apart), 21.8 mm from the back face. Local frame: origin at the centre of the bottom
face, +Y forward (lenses), +Z up.
"""

from build123d import Box, Cylinder, Pos, Rot

WIDTH, HEIGHT, DEPTH = 175.3, 30.3, 43.1
BASELINE = 120.0
M3_SPACING = 36.0
HOLE_FROM_BACK = 21.8
STANDOFF_H = 5.0


def camera():
    r = HEIGHT / 2
    body = Pos(0, 0, r) * Box(WIDTH - HEIGHT, DEPTH, HEIGHT)
    for x in (-(WIDTH / 2 - r), WIDTH / 2 - r):
        body += Pos(x, 0, r) * Rot(90, 0, 0) * Cylinder(r, DEPTH)
    for x in (-BASELINE / 2, BASELINE / 2):
        body -= Pos(x, DEPTH / 2, r) * Rot(90, 0, 0) * Cylinder(6.0, 2.0)
    for x in (-M3_SPACING / 2, M3_SPACING / 2):
        body -= Pos(x, -DEPTH / 2 + HOLE_FROM_BACK, 3.0) * Cylinder(1.6, 6.0)
    return body


def hole_y():
    """Mounting-hole row from the camera's front face (negative = behind it)."""
    return -DEPTH + HOLE_FROM_BACK


def standoffs():
    """Two M3 x 5 mm hex standoffs (5.5 mm across flats) under the camera, in the camera frame (z = 0 on the board)."""
    from build123d import RegularPolygon, extrude
    s = None
    for x in (-M3_SPACING / 2, M3_SPACING / 2):
        part = Pos(x, -DEPTH / 2 + HOLE_FROM_BACK, 0) * extrude(RegularPolygon(5.5 / 3 ** 0.5, 6), STANDOFF_H)
        s = part if s is None else s + part
    return s
