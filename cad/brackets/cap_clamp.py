"""Collar for the 1000 uF motor-bus capacitor C1 (12.5 x 25 mm, standing) on the body PCB, PCB report §10 item 6.

The board has no holes for it, so the collar is glued (CA or hot glue) to the board and to the
capacitor; it keeps the 25 mm can from rocking on its leads when the robot hits something.
It is open toward the rear connectors J7 and J14 so it stays off them.
Print standing on its base, no supports.
"""

from build123d import Pos, Rot

from common import DECK2_BOTTOM, PCB_T, board_to_model, box, cyl, export_part

CAP_D = 12.5
WALL = 1.6
HEIGHT = 10.0
OPENING = 7.0
BOARD_AT = (-2.5, -119.0)


def build():
    part = cyl(CAP_D + 0.4 + 2 * WALL, HEIGHT) - cyl(CAP_D + 0.4, HEIGHT + 2, z=-1)
    part -= box(-OPENING / 2, OPENING / 2, 0, CAP_D, -1, HEIGHT + 1)
    return part


def installed(shape):
    x, y = board_to_model(*BOARD_AT)
    return Pos(x, y, DECK2_BOTTOM + PCB_T) * shape


if __name__ == "__main__":
    p = build()
    export_part("cap_clamp", installed(p), p)
    print("cap_clamp", round(p.volume, 1), p.bounding_box().size, p.is_valid)
