"""Rear camera mount for a Raspberry Pi Camera Module 3 Wide, on the rear edge of the top plate.

Camera (Raspberry Pi mechanical drawing): board 25 x 23.862 mm, 4x M2 holes (2.2 mm)
21 mm apart across and 12.5 mm apart vertically, 2 mm from the bottom and side edges;
lens centre 14.4 mm above the bottom edge; FoV 102 x 67 deg.
The board sits on 4 bosses (M2 x 6 self-tapping) on a plate pitched PITCH_DOWN deg down,
so the floor is visible from ~0.13 m behind the lens and nothing of the robot is in view.
A window behind the board leaves room for the FPC connector; the ribbon runs down behind
the plate and wraps over the rear edge of the top plate to the Pi.
Foot: 2x M3 from below through the rear slot of the top plate into heat-set inserts.
Print upright on the foot, no supports.

Frame: chassis XY, z = 0 on the top face of the top plate.
"""

from build123d import Pos, Rot

from common import (
    CAM3_BOARD,
    CAM3_HOLES,
    CAM3_LENS,
    CX,
    M2_PILOT,
    TOP_PLATE_TOP,
    box,
    cyl,
    gable,
    insert_hole,
    export_part,
)

PITCH_DOWN = 15.0
BOARD_CENTER = (CX, 133.0, 20.0)
PLATE_T = 4.0
STANDOFF = 3.0
PLATE_HALF_W = 14.5
PLATE_TOP = 14.0
FOOT = (CX - 16.0, CX + 16.0, 116.0, 130.0)
FOOT_T = 7.0
SCREWS = ((CX - 10.0, 124.63), (CX + 10.0, 124.63))
WINDOW = (7.0, -11.5, 4.5)


def board_loc():
    return Pos(*BOARD_CENTER) * Rot(-PITCH_DOWN, 0, 0)


def build():
    bl = board_loc()
    plate = bl * box(-PLATE_HALF_W, PLATE_HALF_W, -STANDOFF - PLATE_T, -STANDOFF, -40, PLATE_TOP)
    plate &= box(-100, 100, 0, 300, 0.01, 100)
    foot = box(*FOOT, 0, FOOT_T)
    part = foot + plate
    for u, v in CAM3_HOLES:
        part += bl * Pos(u, 0, v) * cyl(4.5, STANDOFF + 0.5, axis="Y", y=-STANDOFF - 0.5)
    wx, wz0, wz1 = WINDOW
    part -= bl * box(-wx, wx, -STANDOFF - PLATE_T - 1, -STANDOFF + 0.01, wz0, wz1)
    part -= bl * Pos(0, -STANDOFF - PLATE_T / 2, wz1) * gable(2 * wx, PLATE_T + 2)
    for u, v in CAM3_HOLES:
        part -= bl * Pos(u, 0, v) * cyl(M2_PILOT, 6.0, axis="Y", y=-6.0 + 0.01)
    for x, y in SCREWS:
        part -= insert_hole(x, y)
    return part


def camera_solid():
    bl = board_loc()
    w, hgt, t = CAM3_BOARD
    cam = bl * box(-w / 2, w / 2, 0, t, -hgt / 2, hgt / 2)
    cam += bl * box(-5.4, 5.4, t, t + 4.1, CAM3_LENS[1] - 5.4, CAM3_LENS[1] + 5.4)
    cam += bl * Pos(CAM3_LENS[0], 0, CAM3_LENS[1]) * cyl(6.95, 4.2, axis="Y", y=t + 4.1)
    return cam


def lens_pose():
    """(origin, yaw, pitch) of the lens; yaw measured from -Y toward +X, so 180 = backward."""
    p = (board_loc() * Pos(CAM3_LENS[0], CAM3_BOARD[2] + 8.3, CAM3_LENS[1])).position
    return (p.X, p.Y, p.Z), 180.0, -PITCH_DOWN


def installed(shape):
    return Pos(0, 0, TOP_PLATE_TOP) * shape


if __name__ == "__main__":
    p = build()
    export_part("rear_camera_mount", installed(p), p)
    print("rear_camera_mount", round(p.volume, 1), p.bounding_box().size, p.is_valid)
