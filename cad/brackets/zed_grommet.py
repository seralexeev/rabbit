"""TPU grommet for the ZED cable cutout in the body PCB (7.8 x 13.8 mm), PCB report §10 item 11.

Keeps the board edge off the USB 3 cable's braid. 0.8 mm walls leave 6.2 x 12.2 mm, enough for
the ZED's USB-A plug (12 x 4.5 mm) straight through. Push in from above; the lip snaps under the
board. Print in TPU 95A, flange down, no supports.
"""

from build123d import Pos

from common import DECK2_BOTTOM, PCB_T, board_to_model, box, export_part, on_bed

CUTOUT = ((23.2, 64.8), (31.0, 78.6))
WALL = 0.8
FLANGE = 1.5
FLANGE_T = 1.0
LIP = 0.4
LIP_T = 0.8


def build():
    (x0, y0), (x1, y1) = CUTOUT
    w, l = x1 - x0, y1 - y0
    part = box(-w / 2 - FLANGE, w / 2 + FLANGE, -l / 2 - FLANGE, l / 2 + FLANGE, PCB_T, PCB_T + FLANGE_T)
    part += box(-w / 2, w / 2, -l / 2, l / 2, -LIP_T, PCB_T)
    part += box(-w / 2 - LIP, w / 2 + LIP, -l / 2 - LIP, l / 2 + LIP, -LIP_T, -0.05)
    part -= box(-w / 2 + WALL, w / 2 - WALL, -l / 2 + WALL, l / 2 - WALL, -2, PCB_T + FLANGE_T + 1)
    return part


def installed(shape):
    (x0, y0), (x1, y1) = CUTOUT
    x, y = board_to_model((x0 + x1) / 2, (y0 + y1) / 2)
    return Pos(x, y, DECK2_BOTTOM) * shape


if __name__ == "__main__":
    from build123d import Rot

    p = build()
    export_part("zed_grommet", installed(p), on_bed(Rot(180, 0, 0) * p))
    print("zed_grommet", round(p.volume, 1), p.bounding_box().size, p.is_valid)
