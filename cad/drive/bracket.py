"""Rear drive bracket (one part per side, mirrored) and the motor flange plate.

The bracket is an L: a foot under deck 1 on the kit's two M4 holes, and an upright housing outboard
of the plate edge that carries the wheel on two SKF 61803-2RS1 bearings. The motor never carries
the wheel: its gearhead bolts to a flange plate that spigots into the housing, and an Oldham
coupling inside the hollow stub axle passes torque only (coupling.py).

    uv run --project ../../model python bracket.py     # STEP (CNC), 3MF + STL (print variant)
"""

import math

from build123d import Align, Cylinder, Mesher, Pos, Rot, export_step, export_stl

from geometry import (
    BEARING,
    BRACKET_FACE,
    BRG1_IN,
    BRG1_OUT,
    BRG2_IN,
    CAVITY_D,
    FLANGE_D,
    FLANGE_SCREW_ANGLES,
    FLANGE_SCREW_R,
    FLANGE_T,
    FOOT_BOTTOM,
    FOOT_HOLES,
    FOOT_IN,
    FOOT_SLOT,
    GEAR_FACE,
    HERE,
    HOUSING_OUT,
    HUB_NECK_D,
    INSERT_D,
    M3_CLEAR,
    M3_TAP,
    M4_CLEAR,
    MOTOR,
    MOTORS,
    PLATE_BOTTOM,
    PLATE_CLEAR,
    PLATE_TOP,
    SHOULDER_D,
    SPIGOT_D,
    SPIGOT_DEPTH,
    SPIGOT_ID,
    WIDTH,
    box,
)

PRINT_BORE_EXTRA = 0.10
M3_TAP_DEPTH = 8.0
INSERT_DEPTH = 6.0
FLANGE_FLOOR = PLATE_TOP + PLATE_CLEAR
SEAT_CLEAR = 0.2


def xcyl(d, x0, x1, y=0.0, z=0.0):
    return Pos(x0, y, z) * (Rot(0, 90, 0) * Cylinder(d / 2, x1 - x0, align=(Align.CENTER, Align.CENTER, Align.MIN)))


def zcyl(d, z0, z1, x=0.0, y=0.0):
    return Pos(x, y, z0) * Cylinder(d / 2, z1 - z0, align=(Align.CENTER, Align.CENTER, Align.MIN))


def polar(r, deg):
    a = math.radians(deg)
    return r * math.cos(a), r * math.sin(a)


def housing_outline(x0, x1):
    """Upright: rounded top (R = WIDTH/2 about the axis), flat sides, down to the foot bottom."""
    r = WIDTH / 2
    return xcyl(2 * r, x0, x1) + box(x0, x1, -r, r, FOOT_BOTTOM, 0.0)


def bracket(variant="cnc"):
    """variant 'cnc' (6061-T6, tapped M3) or 'print' (PA-CF/PETG, heat-set inserts, bores +0.1 mm)."""
    extra = PRINT_BORE_EXTRA if variant == "print" else 0.0
    d_brg = BEARING["D"] + extra
    body = housing_outline(BRACKET_FACE, HOUSING_OUT)
    body += box(FOOT_IN, BRACKET_FACE, -WIDTH / 2, WIDTH / 2, FOOT_BOTTOM, PLATE_BOTTOM)
    body -= xcyl(d_brg, BRG2_IN, HOUSING_OUT + 1)
    body -= xcyl(SHOULDER_D, BRG1_OUT - 0.1, BRG2_IN + 0.1)
    body -= xcyl(d_brg, BRG1_IN - 0.01, BRG1_OUT)
    body -= xcyl(CAVITY_D, BRACKET_FACE + SPIGOT_DEPTH, BRG1_IN)
    body -= xcyl(SPIGOT_D + extra, BRACKET_FACE - 1, BRACKET_FACE + SPIGOT_DEPTH + SEAT_CLEAR)
    for deg in FLANGE_SCREW_ANGLES:
        y, z = polar(FLANGE_SCREW_R, deg)
        if variant == "print":
            body -= xcyl(INSERT_D, BRACKET_FACE - 1, BRACKET_FACE + INSERT_DEPTH, y, z)
        else:
            body -= xcyl(M3_TAP, BRACKET_FACE - 1, BRACKET_FACE + M3_TAP_DEPTH, y, z)
    for hx, hy in FOOT_HOLES:
        slot = box(hx - M4_CLEAR / 2, hx + M4_CLEAR / 2, hy - FOOT_SLOT, hy + FOOT_SLOT, FOOT_BOTTOM - 1, PLATE_BOTTOM + 1)
        slot += zcyl(M4_CLEAR, FOOT_BOTTOM - 1, PLATE_BOTTOM + 1, hx, hy - FOOT_SLOT)
        slot += zcyl(M4_CLEAR, FOOT_BOTTOM - 1, PLATE_BOTTOM + 1, hx, hy + FOOT_SLOT)
        body -= slot
    return body


def motor_flange(key=MOTOR):
    """Gearhead adapter: pilot pocket and countersunk gearhead screws, spigot into the bracket, 3 x M3."""
    m = MOTORS[key]
    x0, x1 = GEAR_FACE, BRACKET_FACE
    plate = xcyl(FLANGE_D, x0, x1) - box(x0 - 1, x1 + 1, -FLANGE_D, FLANGE_D, -FLANGE_D, FLANGE_FLOOR)
    plate += xcyl(SPIGOT_D, x1, x1 + SPIGOT_DEPTH) - xcyl(SPIGOT_ID, x1 - 0.1, x1 + SPIGOT_DEPTH + 0.1)
    plate -= xcyl(m["pilot_d"], x0 - 0.1, x0 + m["pilot_h"] + 0.1)
    plate -= xcyl(HUB_NECK_D + 0.6, x0 - 0.1, x1 + 0.1)
    s = m["screws"]
    for i in range(s["n"]):
        y, z = polar(s["pcd"] / 2, s["start_deg"] + i * 360 / s["n"])
        plate -= xcyl(s["clear"], x0 - 0.1, x1 + 0.1, y, z)
    for deg in FLANGE_SCREW_ANGLES:
        y, z = polar(FLANGE_SCREW_R, deg)
        plate -= xcyl(M3_CLEAR, x0 - 0.1, x1 + 0.1, y, z)
    return plate


def print_pose(part):
    """Outboard face (x = HOUSING_OUT) down on the bed: bores vertical; the 2 mm bearing shoulder is the
    only ledge (prints without supports)."""
    p = Rot(0, 90, 0) * part
    bb = p.bounding_box()
    return Pos(-bb.center().X, -bb.center().Y, -bb.min.Z) * p


def write_print(part, name):
    export_stl(part, str(HERE / f"{name}.stl"))
    mesher = Mesher()
    mesher.add_shape(part, linear_deflection=0.02, angular_deflection=0.2)
    mesher.write(str(HERE / f"{name}.3mf"))


def export():
    cnc = bracket("cnc")
    export_step(cnc, str(HERE / "bracket.step"))
    write_print(print_pose(bracket("print")), "bracket_print")
    out = {"bracket_g_6061": round(cnc.volume / 1000 * 2.70, 1)}
    for key in MOTORS:
        flange = motor_flange(key)
        export_step(flange, str(HERE / f"motor_flange_{key}.step"))
        p = Rot(0, 90, 0) * flange
        bb = p.bounding_box()
        write_print(Pos(-bb.center().X, -bb.center().Y, -bb.min.Z) * p, f"motor_flange_{key}_print")
        out[f"flange_{key}_g"] = round(flange.volume / 1000 * 2.70, 1)
    return out


if __name__ == "__main__":
    print(export())
