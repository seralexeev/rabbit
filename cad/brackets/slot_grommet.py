"""TPU grommet for the 10.3 x 23.9 mm slots in deck 3 (2 mm aluminium): the cable passthroughs between decks.

Left slot (-25.7, -70.3): the ZED USB 3 cable (down to the Jetson, through the PCB cutout below)
and the lidar lead. Right slot (30.5, -70.3), under the lidar mast foot: the power button and LED
wires. 1 mm walls leave 8.3 x 21.9 mm, enough for the USB-A plug and the lidar's 5-pin connector.
Push in from above; the lip snaps under the plate. Print 2 in TPU 95A, flange down, no supports.
"""

from build123d import Pos, Rot, SlotOverall, extrude

from common import DECK3_BOTTOM, PLATE_T, export_part, on_bed

SLOT = (23.88, 10.3)
SLOTS = ((-25.68, -70.29), (30.54, -70.29))
WALL = 1.0
FLANGE = 2.0
FLANGE_T = 1.2
LIP = 0.5
LIP_T = 0.8


def obround(length, width, z0, z1):
    return Pos(0, 0, z0) * extrude(Rot(0, 0, 90) * SlotOverall(length, width), z1 - z0)


def build():
    length, w = SLOT
    part = obround(length + 2 * FLANGE, w + 2 * FLANGE, PLATE_T, PLATE_T + FLANGE_T)
    part += obround(length, w, -LIP_T, PLATE_T + 0.01)
    part += obround(length + 2 * LIP, w + 2 * LIP, -LIP_T, -0.05)
    part -= obround(length - 2 * WALL, w - 2 * WALL, -2, PLATE_T + FLANGE_T + 1)
    return part


def installed(shape, i):
    x, y = SLOTS[i]
    return Pos(x, y, DECK3_BOTTOM) * shape


if __name__ == "__main__":
    p = build()
    export_part("slot_grommet", installed(p, 0), on_bed(Rot(180, 0, 0) * p))
    print("slot_grommet", round(p.volume, 1), p.bounding_box().size, p.is_valid)
