"""Custom footprints of the ToF carrier, written to lib/rabbit_tof.pretty (the directory is rebuilt).

ST VL53L8CX optical LGA-16, 6.4 x 3.0 x 1.75 mm (data/datasheets/st/vl53l8cx-DS14161-rev12.pdf):
- land pattern: DS p.37 fig. 33 "Recommended solder pattern (view through top of module)": 14 pads 0.500 x 0.515 at
  0.750 pitch, rows 1.315 from the centre line to the outer pad edge (0.200 from the thermal pad), thermal pad B4
  2.316 x 1.200, side pads B1/B7 0.535 x 0.500 on the centre line with their outer edge 0.435 beyond the outer row pad
  (centre at x +-2.6675); A1 carries ST's pin 1 tab: the pad is 0.600 wide (instead of 0.500) over the 0.200 nearest
  the thermal pad, the extra 0.100 on its outer (+x) side (fig. 33 dimensions 0.500 / 0.600 / 0.200), so the pattern is
  no longer 180 deg symmetric and a rotated placement shows in the JLC overlay;
- pin map: DS p.6 fig. 4 (bottom view) mirrored to the top view: A row at the bottom with A1 on the right, C row at the
  top with C1 on the right, B1 right, B7 left;
- thermal pad (review round 2, T-2): 4 vias 0.3/0.5 in one row on the centre line, tented on the back (no bottom pad,
  no bottom mask opening), front paste split into 4 windows 1.108 x 0.32 clear of the vias (51 % of the pad). AN5897 p.4
  fig. 3 shows 8 vias with a full paste rectangle and the bottom open; 8 vias of JLC's 2-layer minimum (0.3 drill, 0.5
  copper) cover the whole 2.316 x 1.200 pad and leave no room for paste windows, so 4 are used;
- assembly marks: F.Fab outline chamfered at A1 (bottom right) with the 2D-code square of the cap at C7 (top left,
  DS p.35: the code marks C7, not pin 1); silk dot next to A1 outside the projected exclusion cones;
- optical centres: DS p.31 fig. 26 and p.33 fig. 29: Rx (SPAD, "optical centre") 1.48 from the left package edge and
  0.10 below the package centre line (towards the A row), Tx (VCSEL) 4.00 to its right; exclusion cones 57.6 deg square,
  0.90 at the module top (z = 0) and 4.20 at z = 3.00. They start at the module top (1.75 above the board), so only
  parts taller than the module near it could enter them. F.Fab carries the apertures, Cmts.User the cone sections at
  z = 3 mm.
"""
import shutil
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib" / "rabbit_tof.pretty"
M3D = "${KIPRJMOD}/3d/"


def _f(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


class FP:
    def __init__(self, name, descr, attr="smd"):
        self.name, self.descr, self.attr = name, descr, attr
        self.items = []
        self.model = None

    def smd(self, num, x, y, sx, sy, shape="roundrect", layers=('F.Cu', 'F.Paste', 'F.Mask'), rr=0.15):
        ls = " ".join(f'"{lay}"' for lay in layers)
        r = f" (roundrect_rratio {rr})" if shape == "roundrect" else ""
        self.items.append(f'  (pad "{num}" smd {shape} (at {_f(x)} {_f(y)}) (size {_f(sx)} {_f(sy)}) (layers {ls}){r})')

    def via(self, num, x, y, d, drill):
        self.items.append(f'  (pad "{num}" thru_hole circle (at {_f(x)} {_f(y)}) (size {_f(d)} {_f(d)}) '
                          f'(drill {_f(drill)}) (layers "*.Cu") (remove_unused_layers no) (zone_connect 2))')

    def rect(self, layer, x0, y0, x1, y1, w=None, fill=False):
        w = w or {"F.CrtYd": 0.05, "F.SilkS": 0.12}.get(layer, 0.1)
        self.items.append(f'  (fp_rect (start {_f(x0)} {_f(y0)}) (end {_f(x1)} {_f(y1)}) '
                          f'(stroke (width {w}) (type solid)) (fill {"yes" if fill else "no"}) (layer "{layer}"))')

    def circle(self, layer, x, y, r, w=0.1, fill=False):
        self.items.append(f'  (fp_circle (center {_f(x)} {_f(y)}) (end {_f(x + r)} {_f(y)}) '
                          f'(stroke (width {w}) (type solid)) (fill {"yes" if fill else "no"}) (layer "{layer}"))')

    def poly(self, layer, pts, w=0.1):
        xy = " ".join(f"(xy {_f(x)} {_f(y)})" for x, y in pts)
        self.items.append(f'  (fp_poly (pts {xy}) (stroke (width {w}) (type solid)) (fill no) (layer "{layer}"))')

    def text(self, layer, s, x, y, size=0.5):
        self.items.append(f'  (fp_text user "{s}" (at {_f(x)} {_f(y)}) (layer "{layer}") '
                          f'(effects (font (size {size} {size}) (thickness {size * 0.15:.3f}))))')

    def write(self, ref_y=0.0, val_y=0.0):
        out = [f'(footprint "{self.name}"', '  (version 20241229)', '  (generator "rabbit_tof_gen")',
               '  (layer "F.Cu")', f'  (descr "{self.descr}")', f'  (attr {self.attr})',
               f'  (property "Reference" "REF**" (at 0 {_f(ref_y)} 0) (layer "F.SilkS") '
               f'(effects (font (size 0.8 0.8) (thickness 0.12))))',
               f'  (property "Value" "{self.name}" (at 0 {_f(val_y)} 0) (layer "F.Fab") '
               f'(effects (font (size 0.5 0.5) (thickness 0.08))))']
        out += self.items
        if self.model:
            out.append(f'  (model "{self.model}" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))')
        out.append(")")
        (LIB / f"{self.name}.kicad_mod").write_text("\n".join(out) + "\n")


PITCH = 0.75
ROW_Y = 1.315 - 0.515 / 2           # 1.0575: pad row centre from the centre line
SIDE_X = 2.5 + 0.435 - 0.535 / 2    # 2.6675: B1/B7 centre
TP_W, TP_H = 2.316, 1.200
VIAS_X = (-0.90, -0.30, 0.30, 0.90)  # 4 thermal vias on the centre line: 0.3 drill, 0.5 copper, 0.6 pitch
PASTE_X0, PASTE_Y0 = 0.05, 0.28      # paste windows: |x| >= 0.05, |y| >= 0.28 (via copper ends at |y| 0.25)
RX = (-1.72, 0.10)
TX = (2.28, 0.10)


def a1_with_tab(f, x, y):
    """A1 (bottom-right) with ST's pin 1 tab: 0.1 wide on the +x side over the 0.2 nearest the thermal pad."""
    w, h = 0.500, 0.515
    tab = (w / 2, -h / 2, w / 2 + 0.100, -h / 2 + 0.200)
    prim = (f"(gr_poly (pts (xy {_f(tab[0] - 0.01)} {_f(tab[1])}) (xy {_f(tab[2])} {_f(tab[1])}) "
            f"(xy {_f(tab[2])} {_f(tab[3])}) (xy {_f(tab[0] - 0.01)} {_f(tab[3])})) (width 0) (fill yes))")
    f.items.append(f'  (pad "A1" smd custom (at {_f(x)} {_f(y)}) (size {_f(w)} {_f(h)}) '
                   f'(layers "F.Cu" "F.Paste" "F.Mask") (options (clearance outline) (anchor rect)) '
                   f'(primitives {prim}))')


def vl53l8cx():
    f = FP("ST_VL53L8CX_LGA-16_6.4x3.0mm",
           "ST VL53L8CX optical LGA-16 6.4x3.0x1.75 mm, DS14161 Rev 12 p.37 fig. 33 (pads), p.31 fig. 26 (optics), "
           "AN5897 fig. 3 (thermal vias)")
    for i in range(7):
        x = 2.25 - PITCH * i                    # column 1 on the right (top view)
        if i == 0:
            a1_with_tab(f, x, ROW_Y)
        else:
            f.smd(f"A{i + 1}", x, ROW_Y, 0.500, 0.515)
        f.smd(f"C{i + 1}", x, -ROW_Y, 0.500, 0.515)
    f.smd("B1", SIDE_X, 0, 0.535, 0.500)
    f.smd("B7", -SIDE_X, 0, 0.535, 0.500)
    f.smd("B4", 0, 0, TP_W, TP_H, shape="rect", layers=("F.Cu", "F.Mask"))
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx = sx * (PASTE_X0 + TP_W / 2) / 2
            cy = sy * (PASTE_Y0 + TP_H / 2) / 2
            f.smd("", cx, cy, TP_W / 2 - PASTE_X0, TP_H / 2 - PASTE_Y0, shape="rect", layers=("F.Paste",))
    for x in VIAS_X:
        f.via("B4", x, 0.0, 0.5, 0.3)
    f.poly("F.Fab", [(-3.2, -1.515), (3.2, -1.515), (3.2, 1.115), (2.8, 1.515), (-3.2, 1.515)])
    f.rect("F.Fab", -3.1, -1.415, -2.55, -0.865, 0.05, fill=True)   # 2D code on the cap = C7 corner (DS p.35)
    f.text("F.Fab", "A1", 2.6, 1.0, 0.35)
    f.circle("F.Fab", RX[0], RX[1], 0.255)
    f.rect("F.Fab", TX[0] - 0.35, TX[1] - 0.35, TX[0] + 0.35, TX[1] + 0.35)
    f.text("F.Fab", "Rx", RX[0], RX[1] - 0.8, 0.4)
    f.text("F.Fab", "Tx", TX[0], TX[1] - 0.8, 0.4)
    for cx, cy in (RX, TX):
        f.rect("Cmts.User", cx - 2.1, cy - 2.1, cx + 2.1, cy + 2.1, 0.05)
        f.rect("Cmts.User", cx - 0.45, cy - 0.45, cx + 0.45, cy + 0.45, 0.05)
    f.rect("F.CrtYd", -3.45, -1.75, 3.45, 1.75)
    f.circle("F.SilkS", 3.48, 2.5, 0.15, 0.1, fill=True)   # A1 side, below the Tx cone projection (y > 2.2)
    f.model = M3D + "vl53l8cx.step"
    f.write(-2.4, 2.4)


def main():
    if LIB.exists():
        shutil.rmtree(LIB)
    LIB.mkdir(parents=True)
    vl53l8cx()
    print("footprints in", LIB)


if __name__ == "__main__":
    main()
