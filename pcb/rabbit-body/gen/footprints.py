"""Custom footprints of the body board (rev B), written to lib/rabbit_body.pretty (the directory is rebuilt).

Pad positions come from the vendor land patterns (top view, KiCad frame: x right, y down):
- DRV8316 RGF0040E VQFN-40 5 x 7: SLVSF16B p.93;
- LM61495 RPH0016B VQFN-HR-16 4.5 x 3.5 (notched corner pads): SNVSBZ4A p.59, measured off the vector drawing;
- LM74800 DRR0012E WSON-12 3 x 3: SNOSDD8 p.41 (exposed pad left floating, p.3);
- Littelfuse NANO2 451 2410 fuse: 451/453 datasheet, "Recommended pad layout" (pads 1.96 x 3.15, gap 2.95);
- Raspberry Pi 4: mechanical drawing, holes 58 x 49, 3.5 from the edges.
"""
import shutil
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib" / "rabbit_body.pretty"
M3D = "${KIPRJMOD}/3d/"


def _f(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


class FP:
    def __init__(self, name, descr, attr="smd"):
        self.name, self.descr, self.attr = name, descr, attr
        self.items = []
        self.model = None

    def tht(self, num, x, y, size, drill, shape="circle", layers='"*.Cu" "*.Mask"'):
        sx, sy = (size, size) if not isinstance(size, tuple) else size
        self.items.append(f'  (pad "{num}" thru_hole {shape} (at {_f(x)} {_f(y)}) (size {_f(sx)} {_f(sy)}) '
                          f'(drill {_f(drill)}) (layers {layers}) (remove_unused_layers no))')

    def npth(self, x, y, d):
        self.items.append(f'  (pad "" np_thru_hole circle (at {_f(x)} {_f(y)}) (size {_f(d)} {_f(d)}) '
                          f'(drill {_f(d)}) (layers "*.Cu" "*.Mask"))')

    def smd(self, num, x, y, sx, sy, shape="roundrect", paste=True, paste_margin=None, mask=True):
        layers = '"F.Cu"' + (' "F.Paste"' if paste else "") + (' "F.Mask"' if mask else "")
        extra = f' (solder_paste_margin {_f(paste_margin)})' if paste_margin is not None else ""
        rr = " (roundrect_rratio 0.2)" if shape == "roundrect" else ""
        self.items.append(f'  (pad "{num}" smd {shape} (at {_f(x)} {_f(y)}) (size {_f(sx)} {_f(sy)}) '
                          f'(layers {layers}){rr}{extra})')

    def paste(self, x, y, sx, sy):
        self.items.append(f'  (pad "" smd rect (at {_f(x)} {_f(y)}) (size {_f(sx)} {_f(sy)}) (layers "F.Paste"))')

    def poly_pad(self, num, rects):
        """Custom pad = union of rectangles (x0, y0, x1, y1), anchored at the first rectangle's centre."""
        x0, y0, x1, y1 = rects[0]
        ax, ay = (x0 + x1) / 2, (y0 + y1) / 2
        a = min(x1 - x0, y1 - y0) * 0.5
        prims = []
        for r0x, r0y, r1x, r1y in rects:
            pts = [(r0x, r0y), (r1x, r0y), (r1x, r1y), (r0x, r1y)]
            prims.append("(gr_poly (pts " + " ".join(f"(xy {_f(px - ax)} {_f(py - ay)})" for px, py in pts) +
                         ") (width 0) (fill yes))")
        self.items.append(f'  (pad "{num}" smd custom (at {_f(ax)} {_f(ay)}) (size {_f(a)} {_f(a)}) '
                          f'(layers "F.Cu" "F.Paste" "F.Mask") (options (clearance outline) (anchor rect)) '
                          f'(primitives {" ".join(prims)}))')

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

    def pin1(self, x, y):
        self.circle("F.SilkS", x, y, 0.15, 0.1, True)

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
        (LIB / f"{self.name}.kicad_mod").write_text("\n".join(out) + "\n")


def drv8316():
    """TI RGF0040E, body 5 (x) x 7 (y). Pins 1-12 left (top to bottom), 13-20 bottom, 21-32 right (bottom to top),
    33-40 top (right to left); pads 0.6 x 0.25, pad centres at x +-2.4 (4.8 c-c) and y +-3.4 (6.8 c-c); EP 3.7 x 5.7 = pin 41."""
    f = FP("TI_RGF0040E_VQFN-40_5x7mm_P0.5mm_EP3.7x5.7mm", "TI DRV8316 RGF0040E VQFN-40 5x7 mm, 0.5 mm pitch, SLVSF16B p.93")
    for i in range(12):
        f.smd(str(1 + i), -2.4, -2.75 + 0.5 * i, 0.6, 0.25)
        f.smd(str(21 + i), 2.4, 2.75 - 0.5 * i, 0.6, 0.25)
    for i in range(8):
        f.smd(str(13 + i), -1.75 + 0.5 * i, 3.4, 0.25, 0.6)
        f.smd(str(33 + i), 1.75 - 0.5 * i, -3.4, 0.25, 0.6)
    f.smd("41", 0, 0, 3.7, 5.7, "rect", paste=False)
    for x in (-0.9, 0.9):
        for y in (-1.95, -0.65, 0.65, 1.95):
            f.paste(x, y, 1.3, 1.0)
    for x in (-1.25, 0.0, 1.25):
        for y in (-2.25, -1.125, 0.0, 1.125, 2.25):
            f.tht("41", x, y, 0.5, 0.3, layers='"*.Cu"')
    f.rect("F.Fab", -2.5, -3.5, 2.5, 3.5)
    f.rect("F.CrtYd", -2.95, -3.95, 2.95, 3.95, 0.05)
    f.pin1(-3.1, -3.6)
    f.set_model(M3D + "vqfn40_5x7.step")
    f.write(-4.4, 4.4)


def lm61495():
    """TI RPH0016B (VQFN-HR 4.5 x 3.5). Left: 1 PGND2, 2 VIN2, 3 RBOOT, 4 CBOOT, 5 BIAS, 6 VCC; bottom: 7 FB, 8 AGND,
    9 RT; right (bottom to top): 10 RESET, 11 SPSP, 12 SYNC/MODE, 13 EN, 14 VIN1, 15 PGND1; centre: 16 SW (SNVSBZ4A p.3-4).
    Geometry from the land pattern p.59 (drawing y up -> KiCad y down)."""
    f = FP("TI_RPH0016B_VQFN-HR-16_3.5x4.5mm", "TI LM61495 RPH0016B VQFN-HR-16, SNVSBZ4A p.59")
    def r(x0, y0, x1, y1):            # drawing coordinates (y up) -> KiCad rect
        return (x0, -y1, x1, -y0)
    for s, n_top, n_bot in ((-1, "1", "6"), (1, "15", "10")):
        lo, hi = sorted((s * 0.803, s * 1.954)); nlo, nhi = sorted((s * 0.803, s * 1.601))
        f.poly_pad(n_top, [r(lo, 1.353, hi, 2.104), r(nlo, 2.104, nhi, 2.451)])
        blo, bhi = sorted((s * 0.85, s * 1.954)); nblo, nbhi = sorted((s * 0.85, s * 1.601))
        f.poly_pad(n_bot, [r(blo, -2.098, bhi, -1.902), r(nblo, -2.451, nbhi, -2.098)])
    f.smd("2", -1.4165, -0.552, 1.075, 0.4)
    f.smd("14", 1.4165, -0.552, 1.075, 0.4)
    for n_l, n_r, y in (("3", "13", -0.525), ("4", "12", -1.025), ("5", "11", -1.525)):
        f.smd(n_l, -1.5405, -y, 0.827, 0.25)
        f.smd(n_r, 1.5405, -y, 0.827, 0.25)
    f.smd("16", 0, -0.963, 0.35, 2.977)
    f.smd("7", -0.5, 2.1155, 0.25, 0.671)
    f.smd("8", 0, 2.0405, 0.25, 0.821)
    f.smd("9", 0.5, 2.1155, 0.25, 0.671)
    f.rect("F.Fab", -1.75, -2.25, 1.75, 2.25)
    f.rect("F.CrtYd", -2.2, -2.7, 2.2, 2.7, 0.05)
    f.pin1(-2.35, -2.75)
    f.set_model(M3D + "vqfn16_3.5x4.5.step")
    f.write(-3.5, 3.5)


def lm74800():
    """TI DRR0012E WSON-12 3 x 3: pads 0.62 x 0.25 at x +-1.39 (2.78 c-c), pins 1-6 left top to bottom, 7-12 right bottom to top;
    EP 1.3 x 2.5 (RTN, must float: SNOSDD8 p.3)."""
    f = FP("TI_DRR0012E_WSON-12_3x3mm_P0.5mm_EP1.3x2.5mm", "TI LM74800 DRR0012E WSON-12, SNOSDD8 p.41")
    for i in range(6):
        f.smd(str(1 + i), -1.39, -1.25 + 0.5 * i, 0.62, 0.25)
        f.smd(str(7 + i), 1.39, 1.25 - 0.5 * i, 0.62, 0.25)
    f.smd("13", 0, 0, 1.3, 2.5, "rect", paste=False)
    for y in (-0.6, 0.6):
        f.paste(0, y, 1.0, 0.95)
    f.rect("F.Fab", -1.5, -1.5, 1.5, 1.5)
    f.rect("F.CrtYd", -1.95, -1.75, 1.95, 1.75, 0.05)
    f.pin1(-1.95, -1.9)
    f.set_model(M3D + "wson12_3x3.step")
    f.write(-2.6, 2.6)


def fuse_2410():
    f = FP("Fuse_Littelfuse_NANO2_451_2410", "Littelfuse NANO2 451 series 2410 fuse, recommended pads 1.96 x 3.15, gap 2.95")
    for num, x in (("1", -2.455), ("2", 2.455)):
        f.smd(num, x, 0, 1.96, 3.15, "rect")
    f.rect("F.Fab", -3.05, -1.25, 3.05, 1.25)
    f.rect("F.SilkS", -1.3, -1.7, 1.3, 1.7)
    f.rect("F.CrtYd", -3.7, -1.85, 3.7, 1.85, 0.05)
    f.set_model(M3D + "fuse_2410.step")
    f.write(-2.6, 2.6)


def shunt_2512():
    f = FP("R_Shunt_2512_Kelvin", "2512 current-sense resistor with split Kelvin pads: 1/2 current, 3/4 sense")
    for s, ci, si in ((-1, "1", "3"), (1, "2", "4")):
        f.smd(ci, s * 3.05, -0.45, 1.9, 2.5, "rect")
        f.smd(si, s * 3.05, 1.55, 1.9, 0.7, "rect")
    f.rect("F.Fab", -3.15, -1.6, 3.15, 1.6)
    f.rect("F.CrtYd", -4.25, -2.2, 4.25, 2.2)
    f.set_model("${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_2512_6332Metric.step")
    f.write(-2.6, 2.6)


def net_tie():
    """Star point GND_MOT -> GND: 3.5 mm copper bridge."""
    f = FP("NetTie_3.5mm", "Net tie, 2 pads, 3.5 mm wide copper bridge for the motor return star point")
    f.items.append('  (net_tie_pad_groups "1, 2")')
    f.smd("1", -2.0, 0, 3.5, 3.5, "circle", paste=False)
    f.smd("2", 2.0, 0, 3.5, 3.5, "circle", paste=False)
    f.items.append('  (fp_poly (pts (xy -2 -1.75) (xy 2 -1.75) (xy 2 1.75) (xy -2 1.75)) (stroke (width 0) (type solid)) '
                   '(fill yes) (layer "F.Cu"))')
    f.rect("F.CrtYd", -3.75, -1.85, 3.75, 1.85, 0.05)
    f.write(-2.8, 2.8)


def rpi4():
    f = FP("RaspberryPi4_Standoffs", "Raspberry Pi 4 on 4x M2.5 x 6 mm standoffs, component side up; origin = board centre")
    f.attr = "board_only exclude_from_pos_files exclude_from_bom"
    for x, y in ((3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)):
        f.npth(x - 42.5, 28.0 - y, 2.7)
        f.circle("F.Fab", x - 42.5, 28.0 - y, 3.0, 0.1)
    f.rect("F.Fab", -42.5, -28.0, 42.5, 28.0)
    f.rect("F.SilkS", -42.0, -27.2, 42.0, 27.2)
    f.rect("F.CrtYd", -42.75, -28.25, 45.25, 28.25)
    f.rect("F.Fab", 42.5 - 19.0, 28.0 - 53.75, 45.0, 28.0 - 37.75)
    f.rect("F.Fab", 42.5 - 17.0, 28.0 - 33.5, 44.5, 28.0 - 2.5)
    f.text("F.SilkS", "RASPBERRY PI 4", -8, 0, 2.5)
    f.text("F.SilkS", "USB / ETH", 34, 0, 1.2)
    f.set_model(M3D + "rpi4.step", z=6.0)
    f.write(-29.5, 29.5)


def main():
    if LIB.exists():
        shutil.rmtree(LIB)
    LIB.mkdir(parents=True)
    for fn in (drv8316, lm61495, lm74800, fuse_2410, shunt_2512, net_tie, rpi4):
        fn()
    print("footprints in", LIB)


if __name__ == "__main__":
    main()
