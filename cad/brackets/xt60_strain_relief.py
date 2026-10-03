"""Strain relief for the battery lead into the vertical XT60 (J1) on the body PCB, PCB report §10 item 7.

J1 sits at board (50, -99.3)/(50, -106.5); the lead comes down from the V-mount plate on deck 3
past the right rear corner and plugs in from above. This clip grips the board's right edge at
board Y = -110 (3.5 mm under, 1 mm over) and carries a post outside the edge, up to 4 mm under
deck 3, with three cable-tie slots: tie the lead so a pull on it never reaches the plug.
The post stands 3.8 mm inboard of the rear right tyre. Print upright as used (clip down), no supports.

Local frame: edge along X, board inward at +y, board bottom at z = 0.
"""

import math

from build123d import Pos, Rot

from common import DECK2_BOTTOM, DECK3_BOTTOM, EDGE_FLANGE_T, EDGE_WALL, board_to_model, box, edge_clip, export_part, on_bed

LENGTH = 22.0
POST = (8.0, 4.0)
TOP_GAP = 4.0
TIES_Z = (14.0, 25.0, 36.0)
BOARD_AT = (59.29, -110.0)
EDGE_ANGLE = math.degrees(math.atan2(57.7785 - 59.3646, 20.6388 + 116.5367))


def build():
    part = edge_clip(LENGTH)
    top = DECK3_BOTTOM - DECK2_BOTTOM - TOP_GAP
    w, t = POST
    post = box(-w / 2, w / 2, -EDGE_WALL - t, -EDGE_WALL + 0.01, -EDGE_FLANGE_T, top)
    part += post
    for z in TIES_Z:
        part -= box(-2.0, 2.0, -EDGE_WALL - t - 1, -EDGE_WALL + 1, z - 0.9, z + 0.9)
    return part


def installed(shape):
    x, y = board_to_model(*BOARD_AT)
    return Pos(x, y, DECK2_BOTTOM) * Rot(0, 0, -90 - EDGE_ANGLE) * shape


def print_pose(shape):
    return on_bed(shape)


if __name__ == "__main__":
    p = build()
    export_part("xt60_strain_relief", installed(p), print_pose(p))
    print("xt60_strain_relief", round(p.volume, 1), p.bounding_box().size, p.is_valid)
