"""Envelope 3D models (STEP) of the modules mounted on the body board.

Built from the vendor dimension drawings: Raspberry Pi 4 mechanical drawing, RoboClaw 2x30A datasheet p.14,
Pololu D36V50Fx / D24V90F5 / Big Pushbutton HP dimension diagrams, Keystone 3557 catalogue page.
Frame: KiCad footprint model frame (X right, Y up = -footprint y, Z up), origin at the footprint origin,
Z = 0 at the bottom of the module (the footprint adds the standoff height as a model offset).

Run: model/.venv/bin/python pcb/rabbit-body/gen/models.py
"""
from pathlib import Path

from build123d import Box, Compound, Cylinder, Pos, Rot, export_step, fillet, Axis

OUT = Path(__file__).resolve().parents[1] / "3d"


def box(sx, sy, sz, x=0, y=0, z=0):
    return Pos(x, y, z + sz / 2) * Box(sx, sy, sz)


def cyl(r, h, x=0, y=0, z=0):
    return Pos(x, y, z + h / 2) * Cylinder(r, h)


def rounded_board(sx, sy, t, r, holes=(), hole_d=2.7):
    b = Box(sx, sy, t)
    b = fillet(b.edges().filter_by(Axis.Z), r)
    for hx, hy in holes:
        b -= Pos(hx, hy, 0) * Cylinder(hole_d / 2, t * 2)
    return Pos(0, 0, t / 2) * b


def rpi4():
    # Pi coordinates (x right, y up, header along the top edge, USB/Ethernet on the right); origin = board centre
    ox, oy = 42.5, 28.0
    holes = [(3.5 - ox, 3.5 - oy), (61.5 - ox, 3.5 - oy), (3.5 - ox, 52.5 - oy), (61.5 - ox, 52.5 - oy)]
    t = 1.4
    parts = [rounded_board(85, 56, t, 3.0, holes)]
    top = t
    parts += [
        box(21.3, 16.0, 13.5, 87.0 - 10.65 - ox, 45.75 - oy, top),            # Ethernet
        box(17.5, 13.1, 16.0, 87.0 - 8.75 - ox, 27.0 - oy, top),              # USB 3 (stacked)
        box(17.5, 13.1, 16.0, 87.0 - 8.75 - ox, 9.0 - oy, top),               # USB 2 (stacked)
        box(51.0, 5.0, 8.5, 32.5 - ox, 52.5 - oy, top),                       # 40-pin header
        box(15.0, 15.0, 2.4, 29.25 - ox, 32.5 - oy, top),                     # SoC
        box(10.0, 15.0, 1.2, 46.0 - ox, 32.5 - oy, top),                      # RAM
        box(9.0, 7.5, 3.2, 3.5 + 7.7 - ox, 3.7 - oy, top),                    # USB-C
        box(7.5, 6.5, 3.0, 3.5 + 7.7 + 14.8 - ox, 3.3 - oy, top),             # micro HDMI 0
        box(7.5, 6.5, 3.0, 3.5 + 7.7 + 14.8 + 13.5 - ox, 3.3 - oy, top),      # micro HDMI 1
        box(7.0, 12.0, 6.0, 53.5 - ox, 6.0 - oy, top),                        # audio jack
        box(2.5, 22.0, 5.5, 45.0 - ox, 11.5 + 4 - oy, top),                   # CSI
        box(2.5, 22.0, 5.5, 4.0 + 1.25 - ox, 24.5 - oy, top),                 # DSI
        box(6.0, 6.0, 2.5, 61.5 - ox + 0.0, 46.0 - oy, top),                  # PoE header block
        box(12.0, 12.0, 1.4, 6.0 - ox, 28.0 - oy, -1.4),                       # microSD under the board
    ]
    for i in range(20):
        for row in (51.23, 53.77):
            parts.append(box(0.64, 0.64, 6.0, 8.37 + 2.54 * i - ox, row - oy, top + 8.5 - 2.5))
    return Compound(parts)


def roboclaw():
    # datasheet top view, terminals at +Y; 52.32 x 73.66, holes 45.72 x 66.68
    w, h = 52.32, 73.66
    holes = [(sx * 22.86, sy * 33.34) for sx in (-1, 1) for sy in (-1, 1)]
    parts = [rounded_board(w, h, 1.6, 0.5, holes, 3.175)]
    top = 1.6
    ytop = h / 2
    parts.append(box(49.5, 12.7, 11.0, 0, ytop - 13.65, top))                 # 6-way screw terminal block
    for xd in (5.5, 13.8, 22.1, 30.5, 38.6, 47.0):
        parts.append(cyl(2.4, 1.0, xd - w / 2, ytop - 13.6, top + 11.0))      # screw heads
    hs_y0, hs_y1 = ytop - 49.0, ytop - 20.0
    parts.append(box(w, hs_y1 - hs_y0, 3.0, 0, (hs_y0 + hs_y1) / 2, top))      # heatsink base
    for i in range(9):
        parts.append(box(1.6, hs_y1 - hs_y0, 12.6, -w / 2 + 2.5 + i * 5.9, (hs_y0 + hs_y1) / 2, top + 3.0))
    for xd in (12.5, 21.0, 29.5, 38.0):
        parts.append(cyl(4.2, 12.0, xd - w / 2, ytop - 23.0, top + 3.0))      # bulk capacitors
    parts.append(box(27.0, 5.0, 8.5, 26.5 - w / 2 + 7.0, ytop - 64.5, top))   # control / encoder headers
    parts.append(box(12.5, 2.5, 8.5, 26.5 - w / 2 + 11.0, ytop - 69.5, top))  # S1..S5 row
    parts.append(box(8.0, 5.5, 3.0, 6.5 - w / 2, -h / 2 + 2.75, top))          # micro USB
    parts.append(box(46.0, 20.0, 1.2, 0, -h / 2 + 12.0, -1.2))                 # bottom-side components
    return Compound(parts)


def pololu_d36v50():
    # 25.4 x 25.4, pins along the bottom edge (two rows at 1.27 / 3.81 mm from the edge), components 6.1 mm
    parts = [box(25.4, 25.4, 1.57, 0, 0, 0)]
    t = 1.57
    parts += [box(9.0, 9.0, 6.1, -5.0, 2.0, t),        # inductor
              cyl(3.2, 6.1, 4.5, 8.5, t), cyl(3.2, 6.1, 9.0, 3.0, t),
              box(5.0, 5.0, 1.0, 5.0, -4.0, t)]
    for i in range(6):
        for row in (8.89, 11.43):
            parts.append(box(0.64, 0.64, 8.5, -6.35 + 2.54 * i, -row, -2.54 - 3.0))
    parts.append(box(15.24, 5.08, 2.54, 0, -10.16, -2.54))   # header plastic
    return Compound(parts)


def pololu_d24v90():
    # 20.3 x 40.6, power ends at +-Y, side signal pins at -X; component height 6.1
    parts = [box(20.3, 40.6, 1.57, 0, 0, 0)]
    t = 1.57
    parts += [cyl(3.2, 6.1, 4.0, 12.0, t), cyl(3.2, 6.1, 4.0, -12.0, t), box(8.5, 8.5, 4.5, -2.0, 0.0, t)]
    for y in (-15.24, 15.24):
        parts.append(box(10.16, 2.54, 2.54, 0.0, y, -2.54))
    parts.append(box(2.54, 10.16, 2.54, -8.88, -4.0, -2.54))
    return Compound(parts)


def pololu_switch_hp():
    # 20.3 x 25.4, power holes along the top edge, two 1x8 pin columns, MOSFETs 2.4 mm
    parts = [box(20.3, 25.4, 1.57, 0, 0, 0)]
    t = 1.57
    parts += [box(6.5, 6.0, 2.4, -3.8, 2.0, t), box(6.5, 6.0, 2.4, 3.8, 2.0, t), box(3.0, 2.5, 1.9, 4.5, -8.0, t)]
    for x in (-9.0, 9.0):
        parts.append(box(2.54, 20.32, 2.54, x, -1.27 - 0.6, -2.54))
    return Compound(parts)


def ato_fuse_3557():
    # two Keystone 3557 clips at W = 13.5 mm plus a standard ATO fuse (19.1 x 5.1, 18.5 mm with blades)
    parts = []
    for x in (-6.75, 6.75):
        parts.append(box(3.8, 4.7, 10.2, x, 0, 0))
    parts.append(box(19.1, 5.1, 12.0, 0, 0, 10.2 - 3.0))
    parts.append(box(14.0, 3.6, 1.5, 0, 0, 10.2 + 9.0))
    return Compound(parts)


def dsbga16():
    parts = [box(1.508, 1.508, 0.4, 0, 0, 0.17)]
    for r in range(4):
        for c in range(4):
            parts.append(Pos(-0.6 + 0.4 * c, 0.6 - 0.4 * r, 0.1) * Cylinder(0.12, 0.2))
    return Compound(parts)


def xt30pw_f():
    # AMASS XT30PW-F, horizontal female; pins at x 0 / 5, body towards +y (model frame), 10.2 wide, 8 tall
    return Compound([box(10.2, 16.9, 8.0, 2.5, 6.15, 0), box(7.0, 2.0, 5.0, 2.5, 14.6, 1.5)])


def main():
    OUT.mkdir(exist_ok=True)
    for name, fn in [("rpi4", rpi4), ("roboclaw_2x30a", roboclaw), ("pololu_d36v50fx", pololu_d36v50),
                     ("pololu_d24v90f5", pololu_d24v90), ("pololu_big_pushbutton_hp", pololu_switch_hp),
                     ("ato_fuse_keystone_3557x2", ato_fuse_3557), ("ina4235_dsbga16", dsbga16), ("xt30pw_f", xt30pw_f)]:
        shape = fn()
        export_step(shape, str(OUT / f"{name}.step"))
        bb = shape.bounding_box()
        print(name, [round(v, 2) for v in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)])


if __name__ == "__main__":
    main()
