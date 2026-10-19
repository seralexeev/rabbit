"""maxon ECX FLAT 22 L High Torque 18 V + GPX 22 UP 2-stage + ENX 22 MILE, modelled from the
maxon Product Range 2026/27 drawings (data/datasheets/maxon/EN_Program_2026-27.pdf), and the
adapter plate that carries it in the kit motor bracket.

Local frame: X is the drive axis, origin on the gearhead's output flange face, +X toward the output
shaft (outboard), the motor extends toward -X. +Z is where the motor's Hall-board tab points.
Values marked (drawing) are read off the drawing outline rather than a dimension.
"""

from build123d import Box, Cylinder, Pos, Rot

# GPX 22 UP, catalogue p. 355
GPX_D = 22.0
GPX_L1 = {1: 22.0, 2: 32.0, 3: 42.0, 4: 52.0}
GPX_PILOT_D = 15.0
GPX_PILOT_H = 2.1
GPX_SHAFT_D = 6.0
GPX_SHAFT_L = 21.0
GPX_FLAT = 5.5
GPX_FLAT_L = 12.0
GPX_SCREW_PCD = 19.0
GPX_SCREW_D = 2.0
GPX_SCREW_DEPTH = 4.5

# ECX FLAT 22 L High Torque, catalogue p. 216
ECX_FLANGE_D = 22.0
ECX_FLANGE_T = 3.0
ECX_BODY_D = 21.8
ECX_LENGTH = 17.0
ECX_TAB_R = 17.0
ECX_TAB_W = 21.7
ECX_TAB_T = 1.6
ECX_CONNECTOR_L = 10.0  # (drawing) axial length of the two Molex headers behind the flange

# ENX 22 MILE, catalogue p. 406
ENX_L = 1.2

# Adapter plate (ours): sits on the bracket's inner face, carries the gearhead pilot in a Ø15 bore
PLATE_T = 4.0
M2_CBORE_D = 4.2
M2_CBORE_DEPTH = 1.5  # low heads sit flush in the plate's outer face, so the kit bracket stays as it is
PLATE_D = 37.0
PLATE_PATTERN_OFFSET = 7.0  # kit bracket: Ø31 hole pattern centre is 7 mm above the wheel axis
KIT_PCD = 31.0
KIT_HOLES_USED = (0, 60, 120, 180)  # degrees from +Y about the pattern centre; 240/300 leave 1 mm to the bore
M3_TAP = 2.5
M2_CLEAR = 2.2
M2_HEAD_D = 3.8  # DIN 7984 M2 low head
M2_HEAD_H = 1.3


def _x(cyl_d, length, x0):
    """Cylinder on the X axis from x0 to x0 + length."""
    return Pos(x0 + length / 2, 0, 0) * (Rot(0, 90, 0) * Cylinder(cyl_d / 2, abs(length)))


def gearhead(stages=2):
    l1 = GPX_L1[stages]
    body = _x(GPX_D, l1, -l1)
    pilot = _x(GPX_PILOT_D, GPX_PILOT_H, 0)
    shaft = _x(GPX_SHAFT_D, GPX_SHAFT_L, 0)
    flat_cut = Pos(GPX_SHAFT_L - GPX_FLAT_L / 2, 0, GPX_FLAT - GPX_SHAFT_D / 2 + 2) * Box(GPX_FLAT_L, 10, 4)
    part = body + pilot + (shaft - flat_cut)
    for i in range(6):
        y, z = _polar(GPX_SCREW_PCD / 2, 60 * i)
        part -= Pos(-GPX_SCREW_DEPTH / 2, y, z) * (Rot(0, 90, 0) * Cylinder(GPX_SCREW_D / 2 * 0.8, GPX_SCREW_DEPTH))
    return part


def motor(x0):
    """ECX FLAT 22 L with ENX 22 MILE; x0 is the motor's flange face (against the gearhead)."""
    flange = _x(ECX_FLANGE_D, -ECX_FLANGE_T, x0)
    body = _x(ECX_BODY_D, -(ECX_LENGTH - ECX_FLANGE_T), x0 - ECX_FLANGE_T)
    encoder = _x(ECX_BODY_D, -ENX_L, x0 - ECX_LENGTH)
    tab_x = x0 - ECX_FLANGE_T
    board = Pos(tab_x - ECX_TAB_T / 2, 0, ECX_TAB_R / 2) * Box(ECX_TAB_T, ECX_TAB_W, ECX_TAB_R)
    headers = Pos(tab_x - ECX_CONNECTOR_L / 2, 0, (ECX_BODY_D / 2 + ECX_TAB_R) / 2) * Box(
        ECX_CONNECTOR_L, ECX_TAB_W, ECX_TAB_R - ECX_BODY_D / 2)
    return flange + body + encoder + board + headers


def drive(stages=2):
    """{name: shape} of one drive in the local frame."""
    return {"gearhead": gearhead(stages), "motor": motor(-GPX_L1[stages])}


def length(stages=2):
    return GPX_L1[stages] + ECX_LENGTH + ENX_L


def adapter_plate():
    """Plate in the local frame: from x = 0 (gearhead flange face) to x = PLATE_T (bracket inner face).
    Disc centred on the kit's Ø31 pattern (7 mm above the axis), Ø15 bore on the axis for the pilot,
    4 × M3 tapped holes on the kit pattern, 6 × M2 clearance holes on Ø19 for the gearhead with Ø4.2 × 1.5
    counterbores on the outer face; the counterbores run into the pilot bore (both reach r = 7.5), leaving a
    scalloped edge on the outer 1.5 mm, which carries no load."""
    plate = Pos(PLATE_T / 2, 0, PLATE_PATTERN_OFFSET) * (Rot(0, 90, 0) * Cylinder(PLATE_D / 2, PLATE_T))
    plate -= Pos(PLATE_T / 2, 0, 0) * (Rot(0, 90, 0) * Cylinder(GPX_PILOT_D / 2, PLATE_T + 1))
    for a in KIT_HOLES_USED:
        y, z = _polar(KIT_PCD / 2, a)
        plate -= Pos(PLATE_T / 2, y, z + PLATE_PATTERN_OFFSET) * (Rot(0, 90, 0) * Cylinder(M3_TAP / 2, PLATE_T + 1))
    for i in range(6):
        y, z = _polar(GPX_SCREW_PCD / 2, 60 * i)
        plate -= Pos(PLATE_T / 2, y, z) * (Rot(0, 90, 0) * Cylinder(M2_CLEAR / 2, PLATE_T + 1))
        plate -= Pos(PLATE_T - M2_CBORE_DEPTH / 2 + 0.05, y, z) * (Rot(0, 90, 0) * Cylinder(M2_CBORE_D / 2, M2_CBORE_DEPTH + 0.1))
    return plate


def gearhead_screw_heads():
    """The 6 M2 low-head screws (DIN 7984 M2 x 6) that hold the gearhead to the plate, heads in the counterbores."""
    heads = None
    for i in range(6):
        y, z = _polar(GPX_SCREW_PCD / 2, 60 * i)
        h = Pos(PLATE_T - M2_CBORE_DEPTH + M2_HEAD_H / 2, y, z) * (Rot(0, 90, 0) * Cylinder(M2_HEAD_D / 2, M2_HEAD_H))
        heads = h if heads is None else heads + h
    return heads


def min_wall():
    """Thinnest wall in the plate between the pilot bore, the M3 and the M2 holes (mm)."""
    import math

    holes = [(0.0, 0.0, GPX_PILOT_D / 2)]
    holes += [(*_polar(KIT_PCD / 2, a, PLATE_PATTERN_OFFSET), M3_TAP / 2) for a in KIT_HOLES_USED]
    holes += [(*_polar(GPX_SCREW_PCD / 2, 60 * i), M2_CLEAR / 2) for i in range(6)]
    walls = []
    for i, (y1, z1, r1) in enumerate(holes):
        for y2, z2, r2 in holes[i + 1:]:
            walls.append(math.hypot(y1 - y2, z1 - z2) - r1 - r2)
    return min(walls)


def _polar(r, deg, z0=0.0):
    import math

    return r * math.cos(math.radians(deg)), z0 + r * math.sin(math.radians(deg))
