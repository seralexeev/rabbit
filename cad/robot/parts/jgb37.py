"""Hiwonder JGB37-520R30-12 gearbox and output shaft, from the Hiwonder drawing
(datasheet/JGB37-520R30-12/hiwonder-JGB37-520R-encoder-motor-dimension-drawing.png).

The kit model (model/chassis.step) already has this motor's can, encoder cap and board, but not its
gearbox: there is an empty 21.5 mm gap between the can and the bracket, which is the 30:1 gearbox
length on the drawing (18.1 + 3.4). The total behind the face, 56.7 mm, matches the drawing.

Local frame: X is the output shaft axis, origin on the gearbox face (against the bracket's inner face),
+X outboard; the gearbox body axis is 7 mm above (+Z) the output axis.
"""

from build123d import Box, Cylinder, Pos, Rot

GEARBOX_D = 36.9
GEARBOX_L = 18.1
RING_L = 3.4
RING_D = 36.0  # (drawing) the ring between gearbox and motor reads slightly smaller than the gearbox
OFFSET = 7.0
FACE_PCD = 31.0  # the drawing labels "Ø30"; it scales to ~30.6 and the Pololu/NFP drawings and the kit bracket give 31
FACE_HOLE_D = 2.5  # M3 tap drill
FACE_HOLE_DEPTH = 3.0
BOSS_D = 12.0
BOSS_L = 5.9
SHAFT_D = 6.0
SHAFT_L = 19.8  # from the face: 5.9 boss + 13.9
FLAT = 5.48
FLAT_L = 11.4


def _x(d, length, x0, z=0.0):
    return Pos(x0 + length / 2, 0, z) * (Rot(0, 90, 0) * Cylinder(d / 2, abs(length)))


def gearbox():
    body = Pos(-GEARBOX_L / 2, 0, OFFSET) * (Rot(0, 90, 0) * Cylinder(GEARBOX_D / 2, GEARBOX_L))
    ring = Pos(-GEARBOX_L - RING_L / 2, 0, OFFSET) * (Rot(0, 90, 0) * Cylinder(RING_D / 2, RING_L))
    part = body + ring
    import math

    for i in range(6):
        a = math.radians(60 * i)
        y, z = FACE_PCD / 2 * math.cos(a), OFFSET + FACE_PCD / 2 * math.sin(a)
        part -= Pos(-FACE_HOLE_DEPTH / 2, y, z) * (Rot(0, 90, 0) * Cylinder(FACE_HOLE_D / 2, FACE_HOLE_DEPTH))
    return part


def output_shaft():
    boss = _x(BOSS_D, BOSS_L, 0)
    shaft = _x(SHAFT_D, SHAFT_L, 0)
    flat_cut = Pos(SHAFT_L - FLAT_L / 2, 0, FLAT - SHAFT_D / 2 + 2) * Box(FLAT_L, 10, 4)
    return boss + (shaft - flat_cut)


def length():
    return GEARBOX_L + RING_L
