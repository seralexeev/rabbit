"""Power button pod on the +X (robot left) side of the lidar mast.

Holds a 16 mm two-pole (2NO) momentary metal push button with a 5 V ring LED
(panel hole 16.2 mm, nut <= 21 mm across corners, <= 32 mm behind the panel; measure yours)
and a 5 mm status LED (GPIO19), both facing up.
Open toward the mast and toward the foot: fit the button and its nut from below/inside,
then fix the pod to the mast with 2x M3 x 8 into heat-set inserts in the mast wall,
driving them through the access holes in the outer wall. Wires drop through the foot hole
into the plate slot at (30.5, -70.3). The button sits outboard of the lidar base so a finger
reaches it from above; the pod overhangs the plate edge by ~10 mm. Print upside down (button face on the bed), no supports.

Frame: chassis XY, z = 0 on the top face of the top plate.
"""

from build123d import Pos, Rot

from common import BUTTON_HOLE, LED_HOLE, M3_CLEAR, TOP_PLATE_TOP, box, cyl, export_part, on_bed
import lidar_mast as mast

WALL = 2.0
TOP_T = 2.5
X0 = mast.LIDAR_XY[0] + mast.TUBE / 2
X1 = mast.LIDAR_XY[0] + 52.0
Y0, Y1 = mast.LIDAR_XY[1] - mast.TUBE / 2 - WALL, mast.LIDAR_XY[1] + mast.TUBE / 2 + WALL
Z0 = mast.FOOT_T
HEIGHT = 41.0
EAR_W = 6.5
BUTTON_XY = (mast.LIDAR_XY[0] + 38.5, mast.LIDAR_XY[1] - 1.0)
LED_XY = (mast.LIDAR_XY[0] + 43.0, mast.LIDAR_XY[1] + 12.0)
ACCESS_D = 7.0


def build():
    z1 = Z0 + HEIGHT
    outer = box(X0, X1, Y0, Y1, Z0, z1)
    inner = box(X0 - 1, X1 - WALL, Y0 + WALL, Y1 - WALL, Z0 - 1, z1 - TOP_T)
    part = outer - inner
    for py in mast.POD_SCREWS_Y:
        side = -1 if py < mast.LIDAR_XY[1] else 1
        ey0, ey1 = (Y0 + WALL - 0.01, py + EAR_W / 2) if side < 0 else (py - EAR_W / 2, Y1 - WALL + 0.01)
        ear = box(X0, X0 + WALL, ey0, ey1, Z0, z1 - TOP_T + 0.01)
        part += ear
        part -= cyl(M3_CLEAR, WALL + 2, X0 - 1, py, mast.POD_SCREW_Z, axis="X")
        part -= cyl(ACCESS_D, WALL + 2, X1 - WALL - 1, py, mast.POD_SCREW_Z, axis="X")
    for x, y in mast.M3_SCREWS:
        r = (mast.BOSS_D + 0.6) / 2
        part -= cyl(2 * r, mast.BOSS_H + 0.3, x, y, 0) + box(x - r, x + r, y, Y1 + 1, 0, mast.BOSS_H + 0.3)
    part -= cyl(BUTTON_HOLE, TOP_T + 2, *BUTTON_XY, z1 - TOP_T - 1)
    part -= cyl(LED_HOLE, TOP_T + 2, *LED_XY, z1 - TOP_T - 1)
    return part


def button_solid():
    z1 = Z0 + HEIGHT
    return cyl(16.0, 32.0, *BUTTON_XY, z1 - 32.0) + cyl(19.0, 1.5, *BUTTON_XY, z1)


def installed(shape):
    return Pos(0, 0, TOP_PLATE_TOP) * shape


def print_pose(shape):
    return on_bed(Rot(180, 0, 0) * shape)


if __name__ == "__main__":
    p = build()
    export_part("power_button_panel", installed(p), print_pose(p))
    print("power_button_panel", round(p.volume, 1), p.bounding_box().size, p.is_valid)
