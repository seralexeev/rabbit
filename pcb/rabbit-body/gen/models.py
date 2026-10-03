"""Envelope 3D models (STEP) of the parts on the body board that have no KiCad library model.

Built from the vendor dimension drawings: Raspberry Pi 4 mechanical drawing, AMASS XT30PW-F, TI RGF/RPH/DRR
package outlines (DRV8316, LM61495, LM74800), Littelfuse NANO2 451.
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


def qfn(sx, sy, sz):
    return Compound([box(sx, sy, sz)])


def fuse_2410():
    # NANO2 451: 6.10 x 2.69 x 2.69 body with end caps
    return Compound([box(4.0, 2.5, 2.5, 0, 0, 0.05), box(1.0, 2.69, 2.69, -2.55, 0, 0), box(1.0, 2.69, 2.69, 2.55, 0, 0)])


def xt30pw_f():
    # AMASS XT30PW-F, horizontal female; pins at x 0 / 5, body towards +y (model frame), 10.2 wide, 8 tall
    return Compound([box(10.2, 16.9, 8.0, 2.5, 6.15, 0), box(7.0, 2.0, 5.0, 2.5, 14.6, 1.5)])


def main():
    OUT.mkdir(exist_ok=True)
    for f in OUT.glob("*.step"):
        f.unlink()
    for name, fn in [("rpi4", rpi4), ("xt30pw_f", xt30pw_f), ("vqfn40_5x7", lambda: qfn(5.0, 7.0, 1.0)),
                     ("vqfn16_3.5x4.5", lambda: qfn(3.5, 4.5, 1.0)), ("wson12_3x3", lambda: qfn(3.0, 3.0, 0.8)),
                     ("fuse_2410", fuse_2410)]:
        shape = fn()
        export_step(shape, str(OUT / f"{name}.step"))
        bb = shape.bounding_box()
        print(name, [round(v, 2) for v in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)])


if __name__ == "__main__":
    main()
