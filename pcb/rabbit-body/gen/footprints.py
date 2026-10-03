"""Custom footprints of the body board, written to lib/rabbit_body.pretty.

Pad positions come from the vendor drawings (top view, KiCad frame: x right, y down):
- Pololu D36V50Fx: reg24d dimension diagram (same pads as pcb/rabbit-board/lib Pololu_D36V50Fx);
- Pololu D24V90F5: reg15b diagram (bottom view mirrored), 20.3 x 40.6;
- Pololu Big Pushbutton Power Switch HP (#2813): psw03b diagram (bottom view mirrored), 20.3 x 25.4;
- RoboClaw 2x30A: datasheet p.14, 52.32 x 73.66, holes 45.72 x 66.68, 3.175;
- Raspberry Pi 4: mechanical drawing, holes 58 x 49, 3.5 from the edges;
- Keystone 3557 ATO clips: catalogue M65 p.41, W = 13.5 mm, 2 pins 3.4 mm apart, 1.6 mm holes;
- INA4235 YBJ DSBGA-16: SBOSAB5, 0.4 mm pitch (from pcb/rabbit-board/lib).
"""
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib" / "rabbit_body.pretty"


def _f(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


class FP:
    def __init__(self, name, descr, attr="through_hole"):
        self.name, self.descr, self.attr = name, descr, attr
        self.items = []
        self.model = None

    def tht(self, num, x, y, size, drill, shape="circle"):
        sx, sy = (size, size) if not isinstance(size, tuple) else size
        self.items.append(f'  (pad "{num}" thru_hole {shape} (at {_f(x)} {_f(y)}) (size {_f(sx)} {_f(sy)}) '
                          f'(drill {_f(drill)}) (layers "*.Cu" "*.Mask") (remove_unused_layers no))')

    def npth(self, x, y, d):
        self.items.append(f'  (pad "" np_thru_hole circle (at {_f(x)} {_f(y)}) (size {_f(d)} {_f(d)}) '
                          f'(drill {_f(d)}) (layers "*.Cu" "*.Mask"))')

    def smd(self, num, x, y, sx, sy, shape="rect", paste=True, paste_margin=None):
        layers = '"F.Cu" "F.Paste" "F.Mask"' if paste else '"F.Cu" "F.Mask"'
        extra = f' (solder_paste_margin {_f(paste_margin)})' if paste_margin is not None else ""
        self.items.append(f'  (pad "{num}" smd {shape} (at {_f(x)} {_f(y)}) (size {_f(sx)} {_f(sy)}) (layers {layers}){extra})')

    def rect(self, layer, x0, y0, x1, y1, w=None):
        w = w or {"F.CrtYd": 0.05, "F.SilkS": 0.12, "F.Fab": 0.1}.get(layer, 0.1)
        self.items.append(f'  (fp_rect (start {_f(x0)} {_f(y0)}) (end {_f(x1)} {_f(y1)}) '
                          f'(stroke (width {w}) (type solid)) (fill no) (layer "{layer}"))')

    def circle(self, layer, x, y, r, w=0.12, fill=False):
        self.items.append(f'  (fp_circle (center {_f(x)} {_f(y)}) (end {_f(x + r)} {_f(y)}) '
                          f'(stroke (width {w}) (type solid)) (fill {"yes" if fill else "no"}) (layer "{layer}"))')

    def text(self, layer, s, x, y, size=1.0):
        self.items.append(f'  (fp_text user "{s}" (at {_f(x)} {_f(y)}) (layer "{layer}") '
                          f'(effects (font (size {size} {size}) (thickness {max(0.15, size * 0.15):.3f}))))')

    def box(self, x0, y0, x1, y1, crt=0.25, silk=True):
        self.rect("F.Fab", x0, y0, x1, y1)
        if silk:
            self.rect("F.SilkS", x0 - 0.1, y0 - 0.1, x1 + 0.1, y1 + 0.1)
        self.rect("F.CrtYd", x0 - crt, y0 - crt, x1 + crt, y1 + crt)

    def set_model(self, path, z=0.0, rot=0.0):
        self.model = (path, z, rot)

    def write(self, ref_y=None, val_y=None):
        ref_y = ref_y if ref_y is not None else 0
        out = [f'(footprint "{self.name}"', '  (version 20241229)', '  (generator "rabbit_body_gen")',
               '  (layer "F.Cu")', f'  (descr "{self.descr}")', f'  (attr {self.attr})',
               f'  (property "Reference" "REF**" (at 0 {_f(ref_y)} 0) (layer "F.SilkS") '
               f'(effects (font (size 1 1) (thickness 0.15))))',
               f'  (property "Value" "{self.name}" (at 0 {_f(val_y if val_y is not None else 0)} 0) (layer "F.Fab") '
               f'(effects (font (size 1 1) (thickness 0.15))))']
        out += self.items
        if self.model:
            p, z, rot = self.model
            out.append(f'  (model "{p}" (offset (xyz 0 0 {_f(z)})) (scale (xyz 1 1 1)) (rotate (xyz 0 0 {_f(rot)})))')
        out.append(")")
        LIB.mkdir(parents=True, exist_ok=True)
        (LIB / f"{self.name}.kicad_mod").write_text("\n".join(out) + "\n")


M3D = "${KIPRJMOD}/3d/"


def pololu_d36v50():
    f = FP("Pololu_D36V50Fx", "Pololu D36V50Fx step-down regulator, 25.4 x 25.4 mm, 2x6 0.1in pins, top view")
    cols = ["VOUT", "GND", "GND", "VIN", "VRP", None]
    for i, name in enumerate(cols):
        x = -6.35 + 2.54 * i
        for y in (8.89, 11.43):
            num = name or ("EN" if y > 10 else "PG")
            f.tht(num, x, y, 1.7, 1.02, "rect" if (i == 0 and y > 10) else "circle")
    for x, y in ((-10.55, 10.55), (10.55, 10.55), (10.55, -10.55)):
        f.npth(x, y, 2.2)
    f.box(-12.7, -12.7, 12.7, 12.7)
    f.text("F.SilkS", "VOUT", -6.35, 6.6, 0.8); f.text("F.SilkS", "VIN", 1.27, 6.6, 0.8); f.text("F.SilkS", "EN", 6.35, 6.6, 0.8)
    f.set_model(M3D + "pololu_d36v50fx.step", z=2.54)
    f.write(-13.6, 13.6)


def pololu_d24v90():
    f = FP("Pololu_D24V90F5", "Pololu D24V90F5 5V 9A step-down regulator, 20.3 x 40.6 mm, top view")
    # top view = bottom view mirrored: x_fp = 10.15 - x_bottom, y_fp = y_bottom - 20.3
    for yb_big, yb_small, pwr in ((2.5, 5.04, "VOUT"), (38.1, 35.56, "VIN")):
        f.tht(pwr, 10.15 - 7.63, yb_big - 20.3, 3.6, 2.18)
        f.tht("GND", 10.15 - 12.7, yb_big - 20.3, 3.6, 2.18)
        for xb, n in ((6.35, pwr), (8.89, pwr), (11.43, "GND"), (13.97, "GND")):
            f.tht(n, 10.15 - xb, yb_small - 20.3, 1.7, 1.02)
    for yb, n in ((20.24, "VSENSE"), (22.78, "FB"), (25.32, "PG"), (27.86, "EN")):
        f.tht(n, 10.15 - 19.03, yb - 20.3, 1.7, 1.02)
    for x in (-7.65, 7.65):
        for y in (-17.8, 17.8):
            f.npth(x, y, 2.18)
    f.box(-10.15, -20.3, 10.15, 20.3)
    f.text("F.SilkS", "VOUT", 0, -13.0, 0.8); f.text("F.SilkS", "VIN", 0, 13.0, 0.8)
    f.set_model(M3D + "pololu_d24v90f5.step", z=2.54)
    f.write(-21.3, 21.3)


def pololu_switch_hp():
    f = FP("Pololu_BigPushbutton_HP", "Pololu Big Pushbutton Power Switch with Reverse Voltage Protection HP (2813), 20.3 x 25.4, top view")
    big = [(2.64, "VOUT"), (7.64, "GND"), (12.64, "GND"), (17.64, "VIN")]
    for xb, n in big:
        f.tht(n, 10.15 - xb, 2.29 - 12.7, 3.6, 2.18)
    left = ["VOUT", "VOUT", "GND", "GND", "B", "A", "GND", "GND"]       # bottom-view column x = 1.27
    right = ["VIN", "VIN", "GND", "GND", "ON", "OFF", "CTRL", "GND"]    # bottom-view column x = 19.03
    for i in range(8):
        y = 5.08 + 2.54 * i - 12.7
        f.tht(left[i], 10.15 - 1.27, y, 1.7, 1.02)
        f.tht(right[i], 10.15 - 19.03, y, 1.7, 1.02)
    f.box(-10.15, -12.7, 10.15, 12.7)
    f.text("F.SilkS", "VIN", -5.5, -7.6, 0.8); f.text("F.SilkS", "VOUT", 5.0, -7.6, 0.8)
    f.set_model(M3D + "pololu_big_pushbutton_hp.step", z=2.54)
    f.write(-13.6, 13.6)


def roboclaw():
    f = FP("RoboClaw_2x30A", "Basicmicro RoboClaw 2x30A on M3 standoffs, 52.32 x 73.66, holes 45.72 x 66.68, terminals at +y top", "smd")
    f.attr = "board_only exclude_from_pos_files exclude_from_bom"
    for sx in (-1, 1):
        for sy in (-1, 1):
            f.npth(sx * 22.86, sy * 33.34, 3.2)
    f.box(-26.16, -36.83, 26.16, 36.83, crt=0.5)
    f.rect("F.SilkS", -24.75, -36.83 + 7.3, 24.75, -36.83 + 20.0)
    for i, n in enumerate(["M1A", "M1B", "B-", "B+", "M2B", "M2A"]):
        f.text("F.SilkS", n, (5.5, 13.8, 22.1, 30.5, 38.6, 47.0)[i] - 26.16, -36.83 + 22.5, 1.0)
    f.text("F.SilkS", "ROBOCLAW 2x30A", 0, 0, 2.0)
    f.text("F.SilkS", "6 mm M3 standoffs", 0, 4, 1.2)
    f.set_model(M3D + "roboclaw_2x30a.step", z=6.0)
    f.write(-38.5, 38.5)


def rpi4():
    f = FP("RaspberryPi4_Standoffs", "Raspberry Pi 4 on 4x M2.5 x 6 mm standoffs, component side up; origin = board centre", "smd")
    f.attr = "board_only exclude_from_pos_files exclude_from_bom"
    for x, y in ((3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)):
        f.npth(x - 42.5, 28.0 - y, 2.7)
        f.circle("F.Fab", x - 42.5, 28.0 - y, 3.0, 0.1)
    f.rect("F.Fab", -42.5, -28.0, 42.5, 28.0)
    f.rect("F.SilkS", -42.0, -27.2, 42.0, 27.2)
    f.rect("F.CrtYd", -42.75, -28.25, 45.25, 28.25)
    f.rect("F.Fab", 42.5 - 19.0, 28.0 - 53.75, 45.0, 28.0 - 37.75)   # Ethernet
    f.rect("F.Fab", 42.5 - 17.0, 28.0 - 33.5, 44.5, 28.0 - 2.5)       # USB
    f.text("F.SilkS", "RASPBERRY PI 4", -8, 0, 2.5)
    f.text("F.SilkS", "USB / ETH", 34, 0, 1.2)
    f.set_model(M3D + "rpi4.step", z=6.0)
    f.write(-29.5, 29.5)


def ato_fuse():
    f = FP("Fuseholder_ATO_Keystone_3557x2", "Two Keystone 3557 clips for a standard ATO blade fuse, 30 A, W = 13.5 mm")
    for num, x in (("1", -6.75), ("2", 6.75)):
        for y in (-1.7, 1.7):
            f.tht(num, x, y, 2.8, 1.6)
    f.box(-9.9, -3.4, 9.9, 3.4)
    f.set_model(M3D + "ato_fuse_keystone_3557x2.step")
    f.write(-4.6, 4.6)


def ina4235():
    f = FP("TI_DSBGA-16_YBJ_1.5x1.5mm_P0.4mm", "TI YBJ DSBGA-16, 4x4, 0.4 mm pitch, 0.25 mm NSMD pads (INA4235; JLCPCB minimum BGA pad)", "smd")
    for r, row in enumerate("ABCD"):
        for c in range(4):
            f.smd(f"{row}{c + 1}", -0.6 + 0.4 * c, -0.6 + 0.4 * r, 0.25, 0.25, "circle", paste_margin=-0.02)
    f.rect("F.Fab", -0.755, -0.755, 0.755, 0.755)
    f.rect("F.CrtYd", -1.0, -1.0, 1.0, 1.0)
    f.rect("F.SilkS", -0.95, -0.95, 0.95, 0.95)
    f.circle("F.SilkS", -1.25, -1.25, 0.12, 0.1, True)
    f.set_model(M3D + "ina4235_dsbga16.step")
    f.write(-1.8, 1.8)


def shunt_2512():
    f = FP("R_Shunt_2512_Kelvin", "2512 current-sense resistor with split Kelvin pads: 1/2 current, 3/4 sense", "smd")
    for s, ci, si in ((-1, "1", "3"), (1, "2", "4")):
        f.smd(ci, s * 3.05, -0.45, 1.9, 2.5)
        f.smd(si, s * 3.05, 1.55, 1.9, 0.7)
    f.rect("F.Fab", -3.15, -1.6, 3.15, 1.6)
    f.rect("F.CrtYd", -4.25, -2.2, 4.25, 2.2)
    f.set_model("${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_2512_6332Metric.step")
    f.write(-2.6, 2.6)


def net_tie():
    """Star point GND_MOT -> GND: 3.5 mm copper bridge (the library NetTie-2_SMD_Pad2.0mm is 2 mm wide)."""
    f = FP("NetTie_3.5mm", "Net tie, 2 pads, 3.5 mm wide copper bridge for the motor return star point", "smd")
    f.items.append('  (net_tie_pad_groups "1, 2")')
    f.smd("1", -2.0, 0, 3.5, 3.5, "circle", paste=False)
    f.smd("2", 2.0, 0, 3.5, 3.5, "circle", paste=False)
    f.items.append('  (fp_poly (pts (xy -2 -1.75) (xy 2 -1.75) (xy 2 1.75) (xy -2 1.75)) (stroke (width 0) (type solid)) '
                   '(fill yes) (layer "F.Cu"))')
    f.rect("F.CrtYd", -3.75, -1.85, 3.75, 1.85, 0.05)
    f.write(-2.8, 2.8)


def wire_pads():
    f = FP("WirePads_2x_AWG14_P8.4mm", "Two solder holes for AWG14 jumpers to the RoboClaw B+ / B- screw terminals")
    f.tht("1", -4.2, 0, 4.6, 2.2)
    f.tht("2", 4.2, 0, 4.6, 2.2)
    f.rect("F.CrtYd", -6.8, -2.6, 6.8, 2.6, 0.05)
    f.text("F.SilkS", "B+", -4.2, 3.4, 1.0); f.text("F.SilkS", "B-", 4.2, 3.4, 1.0)
    f.write(-3.6, 4.6)


def main():
    for fn in (pololu_d36v50, pololu_d24v90, pololu_switch_hp, roboclaw, rpi4, ato_fuse, ina4235, shunt_2512, net_tie, wire_pads):
        fn()
    print("footprints in", LIB)


if __name__ == "__main__":
    main()
