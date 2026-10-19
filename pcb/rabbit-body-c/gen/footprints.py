"""Custom footprints of the body board (rev C), written to lib/rabbit_body.pretty (the directory is rebuilt).

Pad positions come from the vendor land patterns (top view, KiCad frame: x right, y down):
- LM61495 RPH0016B VQFN-HR-16 4.5 x 3.5 (notched corner pads): SNVSBZ4A p.59, measured off the vector drawing;
- LM74800 DRR0012E WSON-12 3 x 3: SNOSDD8 p.41 (exposed pad left floating, p.3);
- Littelfuse NANO2 451 2410 fuse: 451/453 datasheet, "Recommended pad layout" (pads 1.96 x 3.15, gap 2.95);
- Raspberry Pi 4: mechanical drawing, holes 58 x 49, 3.5 from the edges;
- DRV8243 RXY0014A VQFN-HR-14 3 x 4.5: SLVSG23E p.68 (data/pcb-revc/ics/drv8243.json);
- TPS259470L RPW0010A VQFN-HR-10 2 x 2: SLVSFC9C p.73 (tps259470l.json);
- TPS62826 DMQ0006A VSON-HR-6 1.5 x 1.5: SLVSEF9I p.33 (tps62826.json);
- TPS2121 RUX0012A VQFN-HR-12 2 x 2.5: SLVSEA3F p.39 (tps2121.json);
- SK9822-EC20 2 x 2 LED: Opsco SK9822-EC20 p.4-5 (sk9822.json).
The source tables give pads in a y-up frame (pin 1 top-left); yk() converts to KiCad's y-down frame.
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


def tps25982():
    """TPS25982 RGE0024M VQFN-24 4 x 4 with two exposed pads (SLVSEI3D fig. 5-1 p.5, land pattern p.56): pins 1-6
    left (top to bottom), 7-12 bottom, 13-18 right (bottom to top), 19-24 top (right to left), 0.24 x 0.575 at
    0.5 mm, pad centres 1.9125 from the centre; pad 25 = IN 2.7 x 1.45 at y -0.625, pad 26 = GND 2.7 x 0.85 at
    y +0.925 (KiCad y down)."""
    f = FP("TI_RGE0024M_VQFN-24_4x4mm_2EP", "TI TPS25982 RGE0024M VQFN-24 4x4 mm, P0.5, split exposed pad (IN / GND)")
    c, L, W = 1.9125, 0.575, 0.24
    for i in range(6):
        d = -1.25 + 0.5 * i
        f.smd(str(1 + i), -c, d, L, W)
        f.smd(str(7 + i), d, c, W, L)
        f.smd(str(13 + i), c, -d, L, W)
        f.smd(str(19 + i), -d, -c, W, L)
    f.smd("25", 0, -0.625, 2.7, 1.45, shape="rect", paste=False)
    f.smd("26", 0, 0.925, 2.7, 0.85, shape="rect", paste=False)
    for x in (-0.65, 0.65):   # ~74 % paste on both exposed pads (SLVSEI3D stencil p.57: ~78 %)
        f.paste(x, -0.625, 1.2, 1.2)
        f.paste(x, 0.925, 1.2, 0.7)
    f.box(-2.0, -2.0, 2.0, 2.0, crt=0.45, silk=False)
    f.pin1(-2.4, -1.9)
    f.write(-3.0, 3.0)


def dpy0002a():
    """TI DPY0002A X1SON-2 1.0 x 0.6 (TPD1E10B09DPY, land pattern SLLSEB0E p.19): pads 0.3 x 0.5 at +-0.35."""
    f = FP("TI_DPY0002A_X1SON-2", "TI DPY0002A X1SON-2 1.0 x 0.6 mm")
    for num, x in (("1", -0.35), ("2", 0.35)):
        f.smd(num, x, 0, 0.3, 0.5)
    f.box(-0.5, -0.3, 0.5, 0.3, crt=0.2, silk=False)
    f.write(-1.0, 1.0)


def tof_bracket():
    """ToF bracket (cad/robot/parts/tof_mount.py): two M2.5 holes 18 mm apart, 4.5 mm in from the board edge point
    (origin), sensor heading -y; B.CrtYd = the flange under the board (26 x 9), F.CrtYd = the screw heads."""
    f = FP("ToF_Bracket_M2.5", "ToF sensor bracket: 2x M2.5 + flange keep-out under the board; origin = edge point")
    f.attr = "board_only exclude_from_pos_files exclude_from_bom"
    for x in (-9.0, 9.0):
        f.npth(x, 4.5, 2.7)
        f.circle("F.CrtYd", x, 4.5, 2.75, 0.05)
        f.circle("F.SilkS", x, 4.5, 2.6, 0.12)
    f.rect("B.CrtYd", -13.25, -0.25, 13.25, 9.25, 0.05)
    f.rect("B.SilkS", -13.0, 0.0, 13.0, 9.0, 0.12)
    f.rect("B.Fab", -13.0, 0.0, 13.0, 9.0, 0.1)
    f.write(-1.5, 7.0)


def yk(y):
    return -y


def rect_pad(f, num, x0, x1, y0, y1, mask_margin=None, paste=True):
    """Rectangular pad from y-up extents (datasheet frame)."""
    f.smd(num, (x0 + x1) / 2, yk((y0 + y1) / 2), x1 - x0, y1 - y0, "roundrect" if min(x1 - x0, y1 - y0) < 0.6 else "rect",
          paste=paste)
    if mask_margin is not None:
        f.items[-1] = f.items[-1][:-1] + f" (solder_mask_margin {_f(mask_margin)}))"


def drv8243():
    """TI DRV8243-Q1 RXY0014A VQFN-HR-14, 3.0 x 4.5 mm (SLVSG23E p.66-69, data/pcb-revc/ics/drv8243.json).
    Signal pads 0.60 x 0.25 (side, pins 1-3 left, 10-8 right) and 0.25 x 0.60 (top, pins 14-11), NSMD.
    Power pads by copper extent (p.68): 4 VM bar, 5 OUT2 / 7 OUT1 below it, 6 GND bar at the bottom with 4 thermal vias
    0.3 mm (TI thermal model: vias at 1 mm pitch into the inner GND_MOT planes, p.63). The datasheet's mask is
    solder-mask defined on the power pads; here -0.05 mm mask margin approximates it [mask polygons unverified]."""
    f = FP("TI_RXY0014A_VQFN-HR-14_3x4.5mm", "TI DRV8243 RXY0014A VQFN-HR-14 3x4.5 mm, SLVSG23E p.68")
    for num, (x, y) in {"1": (-1.4, 1.625), "2": (-1.4, 1.125), "3": (-1.4, 0.625), "10": (1.4, 1.625), "9": (1.4, 1.125),
                        "8": (1.4, 0.625)}.items():
        f.smd(num, x, yk(y), 0.6, 0.25)
    for num, x in (("14", -0.75), ("13", -0.25), ("12", 0.25), ("11", 0.75)):
        f.smd(num, x, yk(2.15), 0.25, 0.6)
    rect_pad(f, "4", -1.75, 1.75, -0.2, 0.3, -0.05)
    rect_pad(f, "5", -1.75, -0.075, -0.9, -0.4, -0.05)
    rect_pad(f, "7", 0.075, 1.75, -0.9, -0.4, -0.05)
    rect_pad(f, "6", -1.75, 1.75, -2.5, -1.1, -0.05, paste=False)
    for x in (-1.2, -0.4, 0.4, 1.2):
        f.paste(x, yk(-1.8), 0.6, 1.0)
        f.tht("6", x, yk(-1.8), 0.6, 0.3, layers='"*.Cu"')
    f.rect("F.Fab", -1.5, -2.25, 1.5, 2.25)
    f.rect("F.CrtYd", -2.0, -2.75, 2.0, 2.75, 0.05)
    f.pin1(-1.95, -2.55)
    f.write(-3.4, 3.4)


def tps259470l():
    """TI TPS25947xL RPW0010A VQFN-HR-10, 2 x 2 mm (SLVSFC9C p.72-74, tps259470l.json): 5 IN and 6 OUT bars in the
    middle, 1 EN/UVLO, 2 OVLO, 3 AUXOFF, 4 FLT on the left (1 and 4 L-shaped), 10 ITIMER, 9 ILM, 8 GND, 7 DVDT on the right."""
    f = FP("TI_RPW0010A_VQFN-HR-10_2x2mm", "TI TPS259470L RPW0010A VQFN-HR-10 2x2 mm, SLVSFC9C p.73")
    def r(x0, x1, y0, y1):
        return (x0, yk(y1), x1, yk(y0))
    rect_pad(f, "5", -0.40, -0.10, -1.20, 1.20)
    rect_pad(f, "6", 0.10, 0.40, -1.20, 1.20)
    rect_pad(f, "2", -1.20, -0.60, 0.10, 0.35)
    rect_pad(f, "3", -1.20, -0.60, -0.35, -0.10)
    rect_pad(f, "9", 0.60, 1.20, 0.10, 0.35)
    rect_pad(f, "8", 0.60, 1.20, -0.35, -0.10)
    f.poly_pad("1", [r(-1.20, -0.60, 0.55, 0.85), r(-0.85, -0.60, 0.85, 1.20)])
    f.poly_pad("4", [r(-1.20, -0.60, -0.85, -0.55), r(-0.85, -0.60, -1.20, -0.85)])
    f.poly_pad("10", [r(0.60, 1.20, 0.55, 0.85), r(0.60, 0.85, 0.85, 1.20)])
    f.poly_pad("7", [r(0.60, 1.20, -0.85, -0.55), r(0.60, 0.85, -1.20, -0.85)])
    f.rect("F.Fab", -1.0, -1.0, 1.0, 1.0)
    f.rect("F.CrtYd", -1.45, -1.45, 1.45, 1.45, 0.05)
    f.pin1(-1.45, -1.6)
    f.write(-2.2, 2.2)


def tps62826():
    """TI TPS62826 DMQ0006A VSON-HR-6, 1.5 x 1.5 mm (SLVSEF9I p.32-33): 1 EN, 2 PG, 3 FB left (0.60 x 0.25);
    6 VIN, 5 SW, 4 GND right (mask 1.00 x 0.20, copper 0.05 larger, here 1.05 x 0.25) [drawing labels, not vector-measured]."""
    f = FP("TI_DMQ0006A_VSON-HR-6_1.5x1.5mm", "TI TPS62826 DMQ0006A VSON-HR-6 1.5x1.5 mm, SLVSEF9I p.33")
    for num, y in (("1", 0.5), ("2", 0.0), ("3", -0.5)):
        f.smd(num, -0.65, yk(y), 0.6, 0.25)
    for num, y in (("6", 0.5), ("5", 0.0), ("4", -0.5)):
        f.smd(num, 0.45, yk(y), 1.05, 0.25)
    f.rect("F.Fab", -0.75, -0.75, 0.75, 0.75)
    f.rect("F.CrtYd", -1.2, -1.0, 1.2, 1.0, 0.05)
    f.pin1(-1.2, -1.15)
    f.write(-1.8, 1.8)


def tps2121():
    """TI TPS2121 RUX0012A VQFN-HR-12, 2.0 x 2.5 mm (SLVSEA3F p.38-39, top view as drawn on p.39): signal pads
    0.20 x 0.60, top row 12-9, bottom row 3-6; power pads 1.05 x 0.40: 1 OUT, 8 OUT (upper), 2 IN2, 7 IN1 (lower)."""
    f = FP("TI_RUX0012A_VQFN-HR-12_2x2.5mm", "TI TPS2121 RUX0012A VQFN-HR-12 2x2.5 mm, SLVSEA3F p.39")
    for num, x in (("12", -0.75), ("11", -0.25), ("10", 0.25), ("9", 0.75)):
        f.smd(num, x, yk(1.15), 0.2, 0.6)
    for num, x in (("3", -0.75), ("4", -0.25), ("5", 0.25), ("6", 0.75)):
        f.smd(num, x, yk(-1.15), 0.2, 0.6)
    for num, x, y in (("1", -0.675, 0.35), ("8", 0.675, 0.35), ("2", -0.675, -0.35), ("7", 0.675, -0.35)):
        f.smd(num, x, yk(y), 1.05, 0.4)
    f.rect("F.Fab", -1.0, -1.25, 1.0, 1.25)
    f.rect("F.CrtYd", -1.45, -1.7, 1.45, 1.7, 0.05)
    f.pin1(-1.25, -1.75)
    f.write(-2.4, 2.4)


def sk9822():
    """Opsco SK9822-EC20, 2.0 x 2.0 x 0.65 mm (datasheet p.4-5, sk9822.json): pads 0.70 x 0.40 at x +-0.65,
    y -0.8 / 0 / +0.8; 1 SDO, 2 GND, 3 SDI (left, top to bottom), 4 CKI, 5 VDD, 6 CKO (right, bottom to top)
    [pad sizes from partly illegible drawing labels]."""
    f = FP("LED_SK9822-EC20_2x2mm", "Opsco SK9822-EC20 2020 RGB LED with clock, sk9822.json")
    for num, x, y in (("1", -0.65, -0.8), ("2", -0.65, 0.0), ("3", -0.65, 0.8), ("4", 0.65, 0.8), ("5", 0.65, 0.0),
                      ("6", 0.65, -0.8)):
        f.smd(num, x, y, 0.7, 0.4)
    f.rect("F.Fab", -1.0, -1.0, 1.0, 1.0)
    f.rect("F.CrtYd", -1.3, -1.3, 1.3, 1.3, 0.05)
    f.pin1(-1.25, -1.45)
    f.write(-2.0, 2.0)


def main():
    if LIB.exists():
        shutil.rmtree(LIB)
    LIB.mkdir(parents=True)
    for fn in (lm61495, lm74800, fuse_2410, shunt_2512, net_tie, rpi4, drv8243, tps259470l, tps62826, tps2121,
               sk9822, tof_bracket, tps25982, dpy0002a):
        fn()
    print("footprints in", LIB)


if __name__ == "__main__":
    main()
