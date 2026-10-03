"""Bracket for the Waveshare USB3.2-Gen1-HUB-4U under deck 3, PCB report §10 item 12.

The hub hangs under deck 3 over the front half of the body PCB, where the parts below are no taller
than 14 mm. Its size is not published: HUB is an estimate (100 x 55 x 25 mm); measure it and set HUB.
A 3 mm frame plate lies against the underside of deck 3, held by the lidar mast's own screws
(2x M3 and 2x M2.5 come up from below through the frame and deck 3 into the mast foot, so use
M3 x 12 and M2.5 x 14 button heads, counterbored 2 mm into the frame). Two side rails with 2 mm lips
carry the hub; slide it in from the rear and tie it through the slots. Hub bottom ends 17 mm above
the PCB, the lips 15.5 mm. Print frame down, no supports.

Frame: chassis XY, z = 0 on the underside of deck 3, hub below (negative z).
"""

from build123d import Pos, Rot

from common import CX, DECK3_BOTTOM, M25_CLEAR, M3_CLEAR, box, cyl, export_part, on_bed
import lidar_mast as mast

HUB = (55.0, 100.0, 25.0)
HUB_CENTER_Y = -83.4
FRAME_T = 3.0
RAIL_T = 2.5
LIP = 2.0
LIP_T = 1.5
RAIL_LEN = 70.0
HEAD_RECESS = 2.0
TIE_Z = -14.0


def build():
    hx, hy, hz = HUB
    x0, x1 = CX - hx / 2 - RAIL_T, CX + hx / 2 + RAIL_T
    y0, y1 = HUB_CENTER_Y - hy / 2, HUB_CENTER_Y + hy / 2
    part = box(x0, x1, y0, y1, -FRAME_T, 0)
    part -= box(CX - hx / 2 + 8, CX + hx / 2 - 8, y0 + 8, -101.0, -FRAME_T - 1, 1)
    part -= box(CX - hx / 2 + 8, CX + hx / 2 - 8, -58.0, y1 - 8, -FRAME_T - 1, 1)
    ry0, ry1 = HUB_CENTER_Y - RAIL_LEN / 2, HUB_CENTER_Y + RAIL_LEN / 2
    bottom = -FRAME_T - hz - LIP_T
    for xa, xb, lip0, lip1 in ((x0, x0 + RAIL_T, x0, x0 + RAIL_T + LIP), (x1 - RAIL_T, x1, x1 - RAIL_T - LIP, x1)):
        part += box(xa, xb, ry0, ry1, bottom, -FRAME_T + 0.01)
        part += box(lip0, lip1, ry0, ry1, bottom, bottom + LIP_T)
        for ty in (HUB_CENTER_Y - 20, HUB_CENTER_Y + 20):
            part -= box(xa - 1, xb + 1, ty - 2, ty + 2, TIE_Z - 0.9, TIE_Z + 0.9)
    for (x, y), d, head in [(p, M3_CLEAR, 6.0) for p in mast.M3_SCREWS] + [(p, M25_CLEAR, 5.0) for p in mast.M25_SCREWS]:
        part -= cyl(d, FRAME_T + 2, x, y, -FRAME_T - 1)
        part -= cyl(head, HEAD_RECESS + 0.01, x, y, -FRAME_T - 0.01)
    return part


def hub_solid():
    hx, hy, hz = HUB
    return Pos(0, 0, DECK3_BOTTOM) * box(CX - hx / 2, CX + hx / 2, HUB_CENTER_Y - hy / 2, HUB_CENTER_Y + hy / 2, -FRAME_T - hz, -FRAME_T)


def installed(shape):
    return Pos(0, 0, DECK3_BOTTOM) * shape


if __name__ == "__main__":
    p = build()
    export_part("usb_hub_bracket", installed(p), on_bed(Rot(180, 0, 0) * p))
    print("usb_hub_bracket", round(p.volume, 1), p.bounding_box().size, p.is_valid)
