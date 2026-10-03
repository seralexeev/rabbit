"""Twin ToF holder: two VL53L8CX on Pololu #3419 carriers (12.7 x 22.86 mm, 2x M2 holes 17.78 mm apart).

One holder per end, the same print front and rear (the rear one is turned 180 deg).
It sits on the bumper backbone and is held by 3x M3 screws from below into heat-set inserts
in its foot. Each board faces outward, yawed YAW deg away from the robot axis and pitched
PITCH_UP deg up, so the lowest zone row meets a flat floor ~0.44 m away and the bumper bar
stays below the field of view. The boards lie landscape (long side horizontal, the 9-pin row
at the bottom): the body PCB (deck 2) passes ~3 mm above the heads, so they must stay low.
The zone grid is therefore turned 90 deg; T_base_tof carries that roll.
Wires leave the back of each board, drop through the column and exit at the back of the foot.
Print upright on the foot, no supports.

Local frame (the bumper "end frame"): x across the robot, -y outward, z = 0 on the bottom plate.
"""

import math

from build123d import Plane, Pos, Rot, mirror

from common import (
    FIT,
    M2_PILOT,
    TOF_BOARD,
    TOF_HOLES,
    box,
    cyl,
    gable,
    insert_hole,
    export_part,
    on_bed,
)

YAW = 22.0
PITCH_UP = 15.0
HEAD_X = 19.0
SENSOR_Y = -3.0
SEAT_Z = 8.0
FOOT_T = 7.0
SENSOR_Z = 25.0
WALL = 1.6
POCKET = 4.5
FOOT_HALF_W = 33.0
FOOT_MARGIN = 1.5
CHANNEL = (7.0, 3.6)
EXIT_H = 3.5
INSERTS = ((0.0, -4.5), (26.5, -4.5), (-26.5, -4.5))

BOARD_W = TOF_BOARD[1] + 2 * FIT
BOARD_H = TOF_BOARD[0] + 2 * FIT
HOLES = tuple((v, u) for u, v in TOF_HOLES)
HEAD_W = BOARD_W + 2 * WALL
HEAD_H = BOARD_H + 2 * WALL
HEAD_Z0 = -BOARD_H / 2 - WALL
HEAD_D = TOF_BOARD[2] + POCKET + WALL


def head_loc():
    return Pos(0, 0, SENSOR_Z) * Rot(-PITCH_UP, 0, 0)


def head_point(x, y, z):
    return (head_loc() * Pos(x, y, z)).position


def head_unit():
    """One head + column, sensor at (0, 0, SENSOR_Z), facing -Y, before yaw. Foot bottom at z=0."""
    hl = head_loc()
    head = hl * box(-HEAD_W / 2, HEAD_W / 2, 0, HEAD_D, HEAD_Z0, HEAD_Z0 + HEAD_H)
    front_bottom = head_point(0, 0, HEAD_Z0)
    back_top = head_point(0, HEAD_D, HEAD_Z0 + HEAD_H)
    column = box(-HEAD_W / 2, HEAD_W / 2, front_bottom.Y, back_top.Y, 0, front_bottom.Z)
    return head + column


def head_cuts():
    hl = head_loc()
    pocket = hl * box(-BOARD_W / 2, BOARD_W / 2, -1, TOF_BOARD[2] + POCKET, -BOARD_H / 2, BOARD_H / 2)
    for x, z in HOLES:
        x_edge = math.copysign(BOARD_W / 2 + 1, x)
        x0, x1 = sorted((x - math.copysign(2.3, x), x_edge))
        pocket -= hl * box(x0, x1, TOF_BOARD[2], 20, z - 2.3, BOARD_H / 2 + 1)
    cuts = pocket
    for x, z in HOLES:
        cuts += hl * Pos(x, 0, z) * cyl(M2_PILOT, TOF_BOARD[2] + POCKET + WALL - 0.6, axis="Y", y=-0.5)
    back_top = head_point(0, HEAD_D, HEAD_Z0 + HEAD_H)
    pocket_bottom = head_point(0, TOF_BOARD[2] + POCKET / 2, -BOARD_H / 2 + 1)
    cw, cd = CHANNEL
    cuts += hl * box(-cw / 2, cw / 2, TOF_BOARD[2] + 0.4, TOF_BOARD[2] + POCKET - 0.4, HEAD_Z0 - 1, -BOARD_H / 2 + 2)
    cuts += box(-cw / 2, cw / 2, pocket_bottom.Y - cd / 2, pocket_bottom.Y + cd / 2, FOOT_T, pocket_bottom.Z)
    exit_y0, exit_y1 = pocket_bottom.Y - cd / 2, back_top.Y + 6
    cuts += box(-cw / 2, cw / 2, exit_y0, exit_y1, FOOT_T, FOOT_T + EXIT_H)
    cuts += Pos(0, (exit_y0 + exit_y1) / 2, FOOT_T + EXIT_H) * gable(cw, exit_y1 - exit_y0)
    return cuts


def placed(shape, side):
    """side +1: head at +x yawed toward +x; -1: mirrored."""
    s = Pos(HEAD_X, SENSOR_Y, 0) * (Rot(0, 0, YAW) * shape)
    return s if side > 0 else mirror(s, Plane.YZ)


def build():
    """Twin holder in the end frame with the foot bottom at z=0 (add SEAT_Z to install)."""
    units = placed(head_unit(), 1) + placed(head_unit(), -1)
    bb = units.bounding_box()
    foot = box(-FOOT_HALF_W, FOOT_HALF_W, bb.min.Y - FOOT_MARGIN, bb.max.Y + FOOT_MARGIN, 0, FOOT_T)
    part = foot + units
    part -= placed(head_cuts(), 1) + placed(head_cuts(), -1)
    for x, y in INSERTS:
        part -= insert_hole(x, y)
    return part


def sensors():
    """[(origin, yaw, pitch)] in the end frame (foot bottom at z=0); yaw from -Y toward +X."""
    return [((HEAD_X, SENSOR_Y, SENSOR_Z), YAW, PITCH_UP), ((-HEAD_X, SENSOR_Y, SENSOR_Z), -YAW, PITCH_UP)]


def boards():
    hl = head_loc()
    b = hl * box(-TOF_BOARD[1] / 2, TOF_BOARD[1] / 2, 0, TOF_BOARD[2], -TOF_BOARD[0] / 2, TOF_BOARD[0] / 2)
    b += hl * box(-1.5, 1.5, -1.75, 0, -3.2, 3.2)
    return placed(b, 1) + placed(b, -1)


if __name__ == "__main__":
    p = build()
    export_part("tof_pair", p, on_bed(p))
    print("tof_pair", round(p.volume, 1), p.bounding_box().size, p.is_valid)
