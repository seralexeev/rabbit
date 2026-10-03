"""Shared geometry for the BLDC rear drive: bracket, motor flange, stub axle, Oldham coupling.

Chassis frame (model/chassis.step, mm): forward is -Y, the robot's left is +X, up is +Z, plate centreline
x = 2.48 (see cad/brackets/README.md). Every part here is built in a local drive frame:

    origin  on the wheel axis, in the plane of the kit bracket's inner face after the widening
    +x      outboard (towards the wheel), +z up, +y towards the robot's rear

The owner widened the chassis to 142 mm between the bracket inner faces (kit model: 120.6 mm), so the
plane sits HALF_GAP = 71 mm from the centreline and the wheels keep their kit position relative to it.
Wheel-side numbers were measured on the kit hub, wheel and bracket in model/chassis.step.
"""

import sys
from pathlib import Path

from build123d import Plane, Pos, mirror

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BRACKETS = REPO / "cad" / "brackets"
RENDERS = HERE / "renders"
MAKERS = REPO / "data" / "cad" / "makers"
if str(BRACKETS) not in sys.path:
    sys.path.insert(0, str(BRACKETS))

from common import CX, box, cyl, label_png, load_chassis, render  # noqa: E402

AXLE_Y = 83.16
AXLE_Z = 44.455
FLOOR_Z = 7.0
KIT_HALF_GAP = 60.30
HALF_GAP = 71.0
WIDEN = HALF_GAP - KIT_HALF_GAP

PLATE_EDGE = 60.26 - HALF_GAP
PLATE_TOP = 29.12 - AXLE_Z
PLATE_BOTTOM = 27.117 - AXLE_Z
PLATE_CLEAR = 0.5
FOOT_HOLES = ((46.43 - HALF_GAP, 69.63 - AXLE_Y), (46.43 - HALF_GAP, 96.53 - AXLE_Y))
FOOT_SLOT = 1.0
M4_CLEAR = 4.5

WHEEL_INNER = 8.80
HEX_FACE = 17.90
HEX_AF = 12.0
HEX_LEN = 6.0
WHEEL_HUB_OUTER = 28.01
WHEEL_OUTER = 37.98
WHEEL_CENTRE = (WHEEL_INNER + WHEEL_OUTER) / 2
WHEEL_R = 37.45
KIT_COLLAR_D = 12.0

BEARING = {"name": "SKF 61803-2RS1", "d": 17.0, "D": 26.0, "B": 5.0, "C_kN": 1.74, "C0_kN": 1.04, "da_min": 19.0, "Da_max": 24.0}
CIRCLIP = {"name": "DIN 471 17 x 1.0", "s": 1.0, "groove_d": 16.2, "groove_m": 1.1, "lug_od": 23.4}

HOUSING_OUT = WHEEL_INNER - 1.0
BRG2_OUT = HOUSING_OUT - 0.2
BRG2_IN = BRG2_OUT - BEARING["B"]
SHOULDER_W = 2.0
BRG1_OUT = BRG2_IN - SHOULDER_W
BRG1_IN = BRG1_OUT - BEARING["B"]
SHOULDER_D = 22.0
CIRCLIP_X = BRG1_IN
STUB_END = CIRCLIP_X - CIRCLIP["groove_m"] - 1.0
BRACKET_FACE = PLATE_EDGE + PLATE_CLEAR
SPIGOT_D = 30.0
SPIGOT_DEPTH = 2.0
SPIGOT_ID = 25.0
CAVITY_D = 28.0
FLANGE_T = 3.0
FLANGE_D = 46.0
FLANGE_SCREW_R = 18.5
FLANGE_SCREW_ANGLES = (90.0, 210.0, 330.0)
M3_TAP = 2.5
M3_CLEAR = 3.4
M3_HEAD_D, M3_HEAD_H = 5.5, 3.0
INSERT_D = 4.0

FOOT_T = 4.0
FOOT_IN = FOOT_HOLES[0][0] - 6.0
FOOT_BOTTOM = PLATE_BOTTOM - FOOT_T
WIDTH = 44.0

TUBE_ID = 13.0
BORE_BOTTOM = BRG2_OUT - 2.6
RELIEF_D = 7.0
STUB_SHOULDER_D = 19.5
OLDHAM_D = 12.4
OLDHAM_SLOT_W = 3.5
OLDHAM_TONGUE_H = 2.0
OLDHAM_BODY_T = 2.0
OLDHAM_GAP = 0.3
HUB_NECK_D = 10.0

MOTORS = {
    "maxon": {
        "label": "maxon ECX FLAT 22 L 18 V (sealed) + GPX 22 LN 16:1 + ENX 22 MILE 1024",
        "pilot_d": 13.0,
        "pilot_h": 1.4,
        "shoulder_d": 4.0,
        "shoulder_h": 0.0,
        "shaft_d": 4.0,
        "shaft_len": 14.85,
        "flat_len": 9.3,
        "flat": 3.5,
        "screws": {"thread": "M3", "n": 3, "pcd": 17.0, "start_deg": 90.0, "clear": 3.4, "head_d": 5.5, "head_h": 2.0},
        "segments": [(22.0, 26.4), (22.0, 19.9)],
        "tab": {"r": 17.0, "w": 14.0, "len": 19.9},
    },
    "faulhaber": {
        "label": "Faulhaber 3216W012BXTH + IEF3-4096 + 22GPT 11:1",
        "pilot_d": 15.0,
        "pilot_h": 1.5,
        "shoulder_d": 8.0,
        "shoulder_h": 1.6,
        "shaft_d": 6.0,
        "shaft_len": 16.3,
        "flat_len": 10.0,
        "flat": 5.4,
        "screws": {"thread": "M2", "n": 6, "pcd": 19.0, "start_deg": 0.0, "clear": 2.2, "head_d": 3.8, "head_h": 1.6},
        "segments": [(22.0, 26.2), (32.0, 23.0)],
        "tab": {"r": 21.0, "w": 18.3, "len": 16.8},
    },
}
MOTOR = "maxon"

GEAR_FACE = BRACKET_FACE - FLANGE_T


def to_chassis(shape, side):
    """Local drive frame -> chassis frame. side +1 is the robot's left (+X), -1 the right."""
    if side > 0:
        return Pos(CX + HALF_GAP, AXLE_Y, AXLE_Z) * shape
    return Pos(CX - HALF_GAP, AXLE_Y, AXLE_Z) * mirror(shape, Plane.YZ)


def motor_length(key):
    return sum(length for _, length in MOTORS[key]["segments"])


def motor_rear(key):
    return GEAR_FACE - motor_length(key)


def gap_between_motors(key):
    return 2 * (HALF_GAP + motor_rear(key))
