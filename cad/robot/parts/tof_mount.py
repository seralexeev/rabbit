"""ToF sensor bracket: one printed L under deck 2 per sensor, the VL53L8CX carrier board on its face.

Local frame: origin on the body board's bottom face at the board edge, +Y the sensor's heading (outward), +X to the
right looking outward, +Z up. The flange lies against the board's bottom and takes two M2.5 screws from the top
(nuts in hex pockets underneath, or a drop of glue instead); the face hangs below the edge, tilted TILT down, and
carries the carrier on two M2 self-tapping screws, with a window for the carrier's GH-6 plug behind it.
The board's two holes set the heading, so every bracket is the same print.
"""

import math

from build123d import Align, Box, Cylinder, Plane, Polygon, Pos, Rot, RegularPolygon, extrude

TILT = 10.0
WIDTH = 26.0
FLANGE_D = 9.0
FLANGE_T = 4.0
FACE_H = 22.0
FACE_T = 3.0
FACE_OUT = 0.5
HOLE_U = 9.0
HOLE_V = -4.5
M25_CLEAR = 2.7
NUT_AF = 5.1
NUT_DEPTH = 2.4
CARRIER = (22.0, 18.0, 1.6)
CARRIER_DOWN = 11.0
SENSOR_UP = 4.0
CARRIER_HOLE_U = 8.5
M2_PILOT = 1.8
WINDOW = (12.5, 7.5)
CONN_DOWN = 4.0


def face_loc():
    """Frame of the face's outer surface: origin at its top edge, Y its outward normal, Z up along the face."""
    return Pos(0, FACE_OUT, -FLANGE_T) * Rot(-TILT, 0, 0)


def bracket():
    flange = Pos(0, -FLANGE_D / 2, -FLANGE_T / 2) * Box(WIDTH, FLANGE_D, FLANGE_T)
    for u in (-HOLE_U, HOLE_U):
        flange -= Pos(u, HOLE_V, -FLANGE_T / 2) * Cylinder(M25_CLEAR / 2, FLANGE_T + 1)
        flange -= Pos(u, HOLE_V, -FLANGE_T) * extrude(RegularPolygon(NUT_AF / math.sqrt(3), 6), NUT_DEPTH)
    face = Box(WIDTH, FACE_T, FACE_H, align=(Align.CENTER, Align.MAX, Align.MAX))
    for u in (-CARRIER_HOLE_U, CARRIER_HOLE_U):
        face -= Pos(u, 0, -CARRIER_DOWN + SENSOR_UP) * Rot(90, 0, 0) * Cylinder(M2_PILOT / 2, 3 * FACE_T)
    face -= Pos(0, 0, -CARRIER_DOWN - CONN_DOWN) * Box(WINDOW[0], 3 * FACE_T, WINDOW[1])
    face = face_loc() * face
    s, c = math.sin(math.radians(TILT)), math.cos(math.radians(TILT))
    low_y = FACE_OUT - FACE_T * c - 12.0 * s
    low_z = -FLANGE_T + FACE_T * s - 12.0 * c
    rib = Polygon((-FLANGE_D, -FLANGE_T), (FACE_OUT - FACE_T, -FLANGE_T), (low_y, low_z), align=None)
    ribs = [Pos(u, 0, 0) * Plane.YZ.location * extrude(rib, 1.0, both=True) for u in (-WIDTH / 2 + 1, WIDTH / 2 - 1)]
    out = flange + face
    for r in ribs:
        out += r
    return out


def carrier():
    """Proxy of the VL53L8CX carrier with the sensor and the GH-6 plug, on the face."""
    w, h, t = CARRIER
    board = Box(w, t, h, align=(Align.CENTER, Align.MIN, Align.CENTER))
    sensor = Pos(0, t, SENSOR_UP) * Box(6.4, 1.75, 3.0, align=(Align.CENTER, Align.MIN, Align.CENTER))
    plug = Pos(0, 0, -CONN_DOWN) * Box(9.0, 4.3, 5.0, align=(Align.CENTER, Align.MAX, Align.CENTER))
    return face_loc() * Pos(0, 0, -CARRIER_DOWN) * (board + sensor + plug)


def sensor_centre():
    """Sensor window centre in the local frame (y, z)."""
    s, c = math.sin(math.radians(TILT)), math.cos(math.radians(TILT))
    d = CARRIER_DOWN - SENSOR_UP
    y = CARRIER[2] + 1.75
    return FACE_OUT + y * c - d * s, -FLANGE_T - y * s - d * c


def board_holes(X, Y, yaw):
    """The two M2.5 holes in the body board frame for a sensor at edge point (X, Y) with heading yaw."""
    a = math.radians(yaw)
    n, u = (math.sin(a), math.cos(a)), (math.cos(a), -math.sin(a))
    return [(round(X + u[0] * du + n[0] * HOLE_V, 3), round(Y + u[1] * du + n[1] * HOLE_V, 3)) for du in (-HOLE_U, HOLE_U)]


def placement(X, Y, yaw):
    """Board-frame location of a bracket (compose with body_pcb.to_chassis)."""
    return Pos(X, Y, 0) * Rot(0, 0, -yaw)
