"""Mast for the Slamtec RPLIDAR C1 on deck 3, in the strip between the ZED and the V-mount plate.

C1 (Slamtec datasheet v1.0, fig. 4-1): 55.6 x 55.6 mm base, 41.3 mm tall, laser plane 29.8 mm
above the base, 4x M2.5 in a 43 x 43 mm square, screws no deeper than 4 mm.
Scan plane: LIDAR_PLANE_H above the floor. Deck 3 is at 118.4 mm; the owner's V-mount plate
(~17 mm, photo 2026-10-03) and the PS099E (56.7 mm) put the battery top at ~192 mm. The lidar
base sits 8 mm above that, so the battery slides out under it, and the plane clears the battery
by 38 mm, far more than the C1's 0-1.5 deg scan-field flatness (5 mm at 0.2 m) needs.
The V-mount plate reaches ~48 mm forward of the deck's centre line, so the foot stays in
front of it (y -98..-57) and behind the ZED (back face ~-115).

Hollow square tube on a foot; a 45 deg flare carries the lidar platform (no supports).
Foot: 2x M3 into heat-set inserts (plate holes 3.2 mm) + 2x M2.5 self-tapping (plate holes 2.7 mm),
screws from under deck 3. The foot extends to +X under the power button pod.
Lidar cable: front window under the flare, down the inside, out of the -X window into the
deck 3 slot at (-25.7, -70.3), the same slot the ZED cable takes down to the Jetson.
Print upright, no supports.

Frame: chassis XY, z = 0 on the top face of deck 3.
"""

from build123d import Plane, Pos, Rectangle, loft

from common import (
    C1_BASE,
    C1_HOLE_SQUARE,
    C1_LASER_H,
    CX,
    M25_CLEAR,
    M25_PILOT,
    M3_INSERT_D,
    M3_INSERT_DEPTH,
    TOP_PLATE_TOP,
    TOP_PLATE_TOP_H,
    box,
    cyl,
    insert_hole,
    export_part,
)

LIDAR_PLANE_H = 230.0
LIDAR_XY = (CX, -76.5)
TUBE = 30.0
WALL = 2.4
FOOT_T = 5.0
PLATFORM_T = 4.0
FLARE = (C1_BASE - TUBE) / 2
FOOT = (CX - 20.0, CX + 42.0, -98.0, -57.0)
M3_SCREWS = ((-4.52, -92.55), (9.48, -92.55))
M25_SCREWS = ((-5.15, -65.96), (10.11, -65.96))
POD_SCREWS_Y = (LIDAR_XY[1] - 12.0, LIDAR_XY[1] + 12.0)
POD_SCREW_Z = 25.0
PLATE_SLOT_RIGHT = (30.54, -70.29)
BOSS_D, BOSS_H = 9.0, 9.0

BASE_H = LIDAR_PLANE_H - C1_LASER_H
HEIGHT = BASE_H - TOP_PLATE_TOP_H
FLARE_Z0 = HEIGHT - PLATFORM_T - FLARE


def square_loft(z0, z1, s0, s1, cx, cy):
    lo = Plane.XY.offset(z0) * Rectangle(s0, s0)
    hi = Plane.XY.offset(z1) * Rectangle(s1, s1)
    return Pos(cx, cy, 0) * loft([lo, hi])


def build():
    lx, ly = LIDAR_XY
    foot = box(*FOOT, 0, FOOT_T)
    tube = box(lx - TUBE / 2, lx + TUBE / 2, ly - TUBE / 2, ly + TUBE / 2, 0, FLARE_Z0)
    flare = square_loft(FLARE_Z0, FLARE_Z0 + FLARE, TUBE, C1_BASE, lx, ly)
    platform = box(lx - C1_BASE / 2, lx + C1_BASE / 2, ly - C1_BASE / 2, ly + C1_BASE / 2, HEIGHT - PLATFORM_T, HEIGHT)
    part = foot + tube + flare + platform

    inner = TUBE - 2 * WALL
    for py in POD_SCREWS_Y:
        part += box(lx + TUBE / 2 - 7.0, lx + TUBE / 2 - 0.5, py - 4.5, py + 4.5, 0, POD_SCREW_Z + 6)
    for x, y in M25_SCREWS:
        part += cyl(7.0, 12.0, x, y, 0)
    for x, y in M3_SCREWS:
        part += cyl(BOSS_D, BOSS_H, x, y, 0)

    cavity = box(lx - inner / 2, lx + inner / 2, ly - inner / 2, ly + inner / 2, FOOT_T, FLARE_Z0)
    cavity += square_loft(FLARE_Z0 - 0.01, FLARE_Z0 + inner / 2 - 0.5, inner, 1.0, lx, ly)
    for py in POD_SCREWS_Y:
        cavity -= box(lx + TUBE / 2 - 7.0, lx + TUBE / 2 - 0.5, py - 4.5, py + 4.5, 0, POD_SCREW_Z + 6)
    for x, y in M25_SCREWS:
        cavity -= cyl(7.0, 12.0, x, y, 0)
    part -= cavity

    for x, y in M3_SCREWS:
        part -= insert_hole(x, y)
    for x, y in M25_SCREWS:
        part -= cyl(M25_PILOT, 10.0, x, y, -0.01)
    for py in POD_SCREWS_Y:
        part -= cyl(M3_INSERT_D, M3_INSERT_DEPTH, lx + TUBE / 2 - M3_INSERT_DEPTH + 0.01, py, POD_SCREW_Z, axis="X")

    half = C1_HOLE_SQUARE / 2
    for sx in (-half, half):
        for sy in (-half, half):
            part -= cyl(M25_CLEAR, PLATFORM_T + 1, lx + sx, ly + sy, HEIGHT - PLATFORM_T - 0.5)
            part -= cyl(6.0, FLARE + 1, lx + sx, ly + sy, HEIGHT - PLATFORM_T - FLARE - 1)

    part -= box(lx - 5, lx + 5, ly - TUBE / 2 - 1, ly - TUBE / 2 + WALL + 1, FLARE_Z0 - 12, FLARE_Z0 - 2)
    part -= box(lx - TUBE / 2 - 1, lx - TUBE / 2 + WALL + 1, ly - 9, ly + 1, FOOT_T, FOOT_T + 10)
    sx, sy = PLATE_SLOT_RIGHT
    part -= box(sx - 7.4, sx + 7.4, sy - 14.2, sy + 14.2, -0.01, FOOT_T + 0.01)
    return part


def lidar_solid():
    lx, ly = LIDAR_XY
    from common import C1_BASE_H, C1_DOME_D, C1_HEIGHT

    base = box(lx - C1_BASE / 2, lx + C1_BASE / 2, ly - C1_BASE / 2, ly + C1_BASE / 2, HEIGHT, HEIGHT + C1_BASE_H)
    dome = cyl(C1_DOME_D, C1_HEIGHT - C1_BASE_H, lx, ly, HEIGHT + C1_BASE_H)
    return base + dome


def installed(shape):
    return Pos(0, 0, TOP_PLATE_TOP) * shape


if __name__ == "__main__":
    p = build()
    export_part("lidar_mast", installed(p), p)
    print("lidar_mast", round(p.volume, 1), p.bounding_box().size, p.is_valid, "height", round(HEIGHT, 1))
