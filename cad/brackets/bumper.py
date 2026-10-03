"""Compliant bumper with two Omron D2F-01L switches, one print per end (front and rear).

One PETG piece: a pad screwed to the bottom plate, a backbone in front of the plate edge,
a leaf-spring strip (two 40 mm cantilevers from a central stub) and the bumper bar on two posts.
A hit anywhere on the bar pushes it back; the bar rotates for an off-centre hit, which drives
the nearer switch further. Hard stops on the backbone limit travel to TRAVEL so the bar never
reaches the steered front wheels and the switch levers are not crushed.
The switches stand on the backbone with their long axis vertical, held by 2x M2 screws in a post.
Each is struck by an M3 grub screw in the bar (adjust so it clicks after ~1.5 mm of travel).
The ToF pair (tof_pair.py) sits on the backbone and is held by 3x M3 from below.

End frame: x across the robot (0 = plate centreline), -y outward, y = 0 at the plate edge,
z = 0 on the top face of the bottom plate. Print upright (z = 0 on the bed), no supports.
"""

from build123d import Axis, Pos, Rot, fillet

from common import (
    BOTTOM_PLATE_TOP,
    CX,
    D2F_BODY,
    D2F_FP_MAX,
    D2F_HOLE_TO_BOTTOM,
    D2F_HOLE_TO_TOP,
    D2F_HOLES_X,
    D2F_LEVER_TIP_X,
    M2_PILOT,
    M3_CLEAR,
    PLATE_FRONT_Y,
    PLATE_REAR_Y,
    box,
    cyl,
    insert_hole,
    export_part,
)
import tof_pair

BASE_H = 8.0
BACKBONE_D = 7.6
BACKBONE_HALF_W = 50.0
LEAF_T = 1.25
LEAF_H = 6.0
LEAF_Y = -12.6
LEAF_HALF_L = 46.0
STUB_HALF_W = 6.0
POST_X = (43.0, 49.0)
BAR_REAR_Y = -17.6
BAR_T = 6.0
BAR_HALF_W = 102.0
BAR_H = 24.0
BAR_END_R = 2.9
TRAVEL = 3.5
SWITCH_X0 = 35.5
SWITCH_POST_T = 6.0
SWITCH_HOLE_Y = -5.5
SWITCH_POST_Y = (-BACKBONE_D, -2.0)
STRIKER_D = M3_CLEAR
NUT_AF, NUT_T = 5.7, 2.6
STANDOFF_CLEAR_R = 4.8

ENDS = {
    "front": {
        "origin": (CX, PLATE_FRONT_Y),
        "turn": 0,
        "pad": (-25.0, 25.0, 0.0, 11.9),
        "screws": [(-15.0, 4.6), (15.0, 4.6), (0.0, 10.85)],
    },
    "rear": {
        "origin": (CX, PLATE_REAR_Y),
        "turn": 180,
        "pad": (-48.0, 48.0, 0.0, 11.0),
        "screws": [(-43.82, 7.0), (43.82, 7.0), (0.0, 6.91)],
        "standoffs": [(-38.09, 13.08), (38.09, 13.08)],
    },
}


def end_location(end):
    e = ENDS[end]
    return Pos(e["origin"][0], e["origin"][1], BOTTOM_PLATE_TOP) * Rot(0, 0, e["turn"])


def switch_frame(side):
    """Switch body placement: long axis vertical, actuator face toward -y, side +1 at +x."""
    x_mid = SWITCH_X0 + D2F_BODY[2] / 2
    return x_mid if side > 0 else -x_mid


def switch_body(side):
    t = D2F_BODY[2]
    x0 = SWITCH_X0 if side > 0 else -SWITCH_X0 - t
    body = box(x0, x0 + t, SWITCH_HOLE_Y - D2F_HOLE_TO_TOP, SWITCH_HOLE_Y + D2F_HOLE_TO_BOTTOM, BASE_H, BASE_H + D2F_BODY[0])
    lever_x = switch_frame(side)
    lever = box(
        lever_x - 1.5, lever_x + 1.5, SWITCH_HOLE_Y - D2F_FP_MAX, SWITCH_HOLE_Y - D2F_HOLE_TO_TOP, BASE_H + 1, BASE_H + D2F_LEVER_TIP_X
    )
    pins = box(
        x0 + 1,
        x0 + t - 1,
        SWITCH_HOLE_Y + D2F_HOLE_TO_BOTTOM,
        SWITCH_HOLE_Y + D2F_HOLE_TO_BOTTOM + 3.5,
        BASE_H + 1,
        BASE_H + D2F_BODY[0] - 1,
    )
    return body + lever + pins


def fixed_part(end):
    pad = box(*ENDS[end]["pad"], 0, BASE_H)
    for x, y in ENDS[end].get("standoffs", []):
        pad -= cyl(2 * STANDOFF_CLEAR_R, BASE_H + 2, x, y, -1)
    backbone = box(-BACKBONE_HALF_W, BACKBONE_HALF_W, -BACKBONE_D, 0, 0, BASE_H)
    stub = box(-STUB_HALF_W, STUB_HALF_W, LEAF_Y - 0.5, -BACKBONE_D + 1, 0, BASE_H)
    stops = box(POST_X[0], POST_X[1], LEAF_Y + TRAVEL, -BACKBONE_D + 1, 0, LEAF_H) + box(
        -POST_X[1], -POST_X[0], LEAF_Y + TRAVEL, -BACKBONE_D + 1, 0, LEAF_H
    )
    posts = None
    for side in (1, -1):
        x0 = SWITCH_X0 + D2F_BODY[2] if side > 0 else -SWITCH_X0 - D2F_BODY[2] - SWITCH_POST_T
        p = box(x0, x0 + SWITCH_POST_T, *SWITCH_POST_Y, BASE_H - 1, BASE_H + D2F_BODY[0] + 0.3)
        posts = p if posts is None else posts + p
    part = pad + backbone + stub + stops + posts
    return part


def moving_part():
    leaf = box(-LEAF_HALF_L, LEAF_HALF_L, LEAF_Y - LEAF_T, LEAF_Y, 0, LEAF_H)
    posts = box(POST_X[0], POST_X[1], BAR_REAR_Y - 1, LEAF_Y, 0, LEAF_H) + box(-POST_X[1], -POST_X[0], BAR_REAR_Y - 1, LEAF_Y, 0, LEAF_H)
    bar = box(-BAR_HALF_W, BAR_HALF_W, BAR_REAR_Y - BAR_T, BAR_REAR_Y, 0, BAR_H)
    bar = fillet(bar.edges().filter_by(Axis.Z), BAR_END_R)
    return leaf, posts + bar


def striker_cuts():
    cuts = None
    z = BASE_H + D2F_LEVER_TIP_X - 1.0
    for side in (1, -1):
        x = switch_frame(side)
        c = cyl(STRIKER_D, BAR_T + 2, x, BAR_REAR_Y - BAR_T - 1, z, axis="Y")
        y_mid = BAR_REAR_Y - BAR_T / 2
        c += box(x - NUT_AF / 2, x + NUT_AF / 2, y_mid - NUT_T / 2, y_mid + NUT_T / 2, z - NUT_AF / 2 - 0.2, BAR_H + 1)
        cuts = c if cuts is None else cuts + c
    return cuts


def mount_cuts(end):
    cuts = None
    for x, y in ENDS[end]["screws"]:
        c = insert_hole(x, y)
        cuts = c if cuts is None else cuts + c
    for x, y in tof_pair.INSERTS:
        cuts += cyl(M3_CLEAR, BASE_H + 0.2, x, y, -0.1)
    for side in (1, -1):
        x0 = SWITCH_X0 + D2F_BODY[2] if side > 0 else -SWITCH_X0 - D2F_BODY[2] - SWITCH_POST_T
        for hx in D2F_HOLES_X:
            z = BASE_H + hx
            cuts += cyl(M2_PILOT, SWITCH_POST_T - 1.0, x0 if side > 0 else x0 + 1.0, SWITCH_HOLE_Y, z, axis="X")
    return cuts


def build(end):
    """Bumper in the end frame (bed = z 0). Returns (part, moving) where moving = bar + posts."""
    leaf, moving = moving_part()
    part = fixed_part(end) + leaf + moving
    part -= mount_cuts(end) + striker_cuts()
    return part, moving - striker_cuts()


def installed(end, shape):
    return end_location(end) * shape


def tof_location(end):
    return end_location(end) * Pos(0, 0, tof_pair.SEAT_Z)


def switches(end):
    return [end_location(end) * switch_body(s) for s in (1, -1)]


def screw_points(end):
    loc = end_location(end)
    return [((loc * Pos(x, y, 0)).position.X, (loc * Pos(x, y, 0)).position.Y) for x, y in ENDS[end]["screws"]]


def main(end):
    part, _ = build(end)
    export_part(f"bumper_{end}", installed(end, part), part)
    print(f"bumper_{end}", round(part.volume, 1), part.bounding_box().size, part.is_valid)
