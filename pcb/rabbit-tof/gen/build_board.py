"""Build pcb/rabbit-tof/rabbit-tof.kicad_pcb from design.py (placement, outline, silk, GND pours; no tracks).

Run with KiCad's bundled Python (pcbnew):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 gen/build_board.py
Board frame -> KiCad page: x = 100 + X, y = 100 - Y (front view). Routing: gen/autoroute.py (Freerouting).
"""
import math
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
PRJ = HERE.parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

OX, OY = 100.0, 100.0
KFP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/"
LIBS = {"rabbit_tof": str(PRJ / "lib" / "rabbit_tof.pretty")}
BOARD_FILE = PRJ / "rabbit-tof.kicad_pcb"


def mm(v):
    return pcbnew.FromMM(v)


def kp(X, Y):
    return pcbnew.VECTOR2I(mm(OX + X), mm(OY - Y))


def board_xy(v):
    return pcbnew.ToMM(v.x) - OX, OY - pcbnew.ToMM(v.y)


def outline_pts(inset=0.0, n=8):
    """Rounded rectangle (board frame), counter-clockwise, arcs as n segments."""
    w, h, r = design.W / 2 - inset, design.H / 2 - inset, max(design.CORNER_R - inset, 0.05)
    pts = []
    for cx, cy, a0 in ((w - r, h - r, 0), (-w + r, h - r, 90), (-w + r, -h + r, 180), (w - r, -h + r, 270)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


class Builder:
    def __init__(self):
        self.b = pcbnew.NewBoard(str(BOARD_FILE))
        self.b.SetCopperLayerCount(2)
        self.nets = {}
        self.fps = {}

    def rules(self):
        """JLCPCB 2-layer standard process: 0.127 mm track / space, 0.3 mm drill, 0.5 mm via; used here with margin."""
        ds = self.b.GetDesignSettings()
        ds.m_MinClearance = mm(0.13)
        ds.m_TrackMinWidth = mm(0.13)
        ds.m_ViasMinSize = mm(0.5)
        ds.m_MinThroughDrill = mm(0.3)
        ds.m_ViasMinAnnularWidth = mm(0.1)
        ds.m_HoleClearance = mm(0.2)
        ds.m_HoleToHoleMin = mm(0.25)
        ds.m_CopperEdgeClearance = mm(0.3)
        ds.m_SilkClearance = mm(0.0)
        ds.m_MinSilkTextHeight = mm(0.6)
        ds.m_MinSilkTextThickness = mm(0.1)
        ds.m_MinResolvedSpokes = 1
        ds.SetAuxOrigin(kp(-design.W / 2, -design.H / 2))   # fab files: origin at the bottom-left board corner
        ns = ds.m_NetSettings
        ns.ClearNetclassPatternAssignments()
        ns.ClearNetclasses()
        default = ns.GetDefaultNetclass()
        default.SetClearance(mm(0.15))
        default.SetTrackWidth(mm(0.15))
        default.SetViaDiameter(mm(0.6))
        default.SetViaDrill(mm(0.3))
        nc = pcbnew.NETCLASS("PWR")
        nc.SetClearance(mm(0.15)); nc.SetTrackWidth(mm(0.3)); nc.SetViaDiameter(mm(0.6)); nc.SetViaDrill(mm(0.3))
        ns.SetNetclass("PWR", nc)
        for n in design.POWER:
            ns.SetNetclassPatternAssignment(n, "PWR")
        ns.RecomputeEffectiveNetclasses()

    def outline(self):
        pts = outline_pts()
        for a, c in zip(pts, pts[1:] + pts[:1]):
            sh = pcbnew.PCB_SHAPE(self.b)
            sh.SetLayer(pcbnew.Edge_Cuts); sh.SetWidth(mm(0.1)); sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
            sh.SetStart(kp(*a)); sh.SetEnd(kp(*c))
            self.b.Add(sh)

    def net(self, name):
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    def place(self):
        for p in design.PARTS:
            lib, name = p["fp"].split(":")
            fp = pcbnew.FootprintLoad(LIBS.get(lib, KFP + lib + ".pretty"), name)
            if fp is None:
                raise RuntimeError(f"footprint not found: {p['fp']}")
            fp.SetFPID(pcbnew.LIB_ID(lib, name))
            fp.SetReference(p["ref"])
            fp.SetValue(p["value"])
            for key, val in (("LCSC", p["lcsc"]), ("MPN", p["mpn"]), ("BOM", p["bom"])):
                if val:
                    fp.SetField(key, val)
                    f = fp.GetField(key)
                    f.SetVisible(False)
                    f.SetLayer(pcbnew.F_Fab)
            fp.SetPosition(kp(*p["at"]))
            fp.SetOrientationDegrees(p["rot"])
            self.b.Add(fp)
            if p["side"] == "B":
                fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
            for pad in fp.Pads():
                n = p["pins"].get(pad.GetNumber())
                if n:
                    pad.SetNet(self.net(n))
            attrs = fp.GetAttributes()
            if p["bom"] == "none":
                attrs |= pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_EXCLUDE_FROM_BOM
            fp.SetAttributes(attrs)
            fp.Reference().SetVisible(False)   # 22 x 18 mm: references live on F.Fab / the README, not on the silk
            self.fps[p["ref"]] = fp

    def text(self, s, X, Y, size=1.0, layer=pcbnew.F_SilkS, rot=0, thick=None):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetPosition(kp(X, Y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(thick or max(0.1, size * 0.15)))
        t.SetTextAngleDegrees(rot)
        if layer == pcbnew.B_SilkS:
            t.SetMirrored(True)
        self.b.Add(t)
        return t

    def silk(self):
        for s, x, y, size, side in design.SILK:
            self.text(s, x, y, size, pcbnew.F_SilkS if side == "F" else pcbnew.B_SilkS)
        # port pinout on the back, above each GH contact (seen from the back: pin 1 on the right), triangle at pin 1
        names = {"1": "GND", "2": "3V3", "3": "SDA", "4": "SCL", "5": "INT", "6": "LPn"}
        for num, name in names.items():
            x, y = self.pad_xy("J1", num)
            self.text(f"{num} {name}", x, y + 3.25, 0.6, pcbnew.B_SilkS, rot=90, thick=0.1)
        x1, y1 = self.pad_xy("J1", "1")
        tri = pcbnew.PCB_SHAPE(self.b)
        tri.SetShape(pcbnew.SHAPE_T_POLY); tri.SetLayer(pcbnew.B_SilkS); tri.SetFilled(True); tri.SetWidth(mm(0.05))
        tri.SetPolyPoints([kp(x1 - 0.3, y1 + 1.6), kp(x1 + 0.3, y1 + 1.6), kp(x1, y1 + 1.15)])
        self.b.Add(tri)

    def zone(self, net, layer, poly, priority=0, clearance=0.2, min_w=0.2, name=None):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(layer)
        z.SetNet(self.net(net))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in poly:
            ol.Append(mm(OX + x), mm(OY - y))
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(min_w))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.25))
        z.SetThermalReliefSpokeWidth(mm(0.3))
        if name:
            z.SetZoneName(name)
        self.b.Add(z)
        return z

    def pad_xy(self, ref, num):
        for pad in self.fps[ref].Pads():
            if pad.GetNumber() == str(num):
                return board_xy(pad.GetPosition())
        raise KeyError(f"{ref}.{num}")

    def track(self, net, pts, width, layer):
        pts = [self.pad_xy(*q.split(".")) if isinstance(q, str) else q for q in pts]
        for a, c in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(kp(*a)); t.SetEnd(kp(*c)); t.SetWidth(mm(width)); t.SetLayer(layer)
            t.SetNet(self.net(net))
            t.SetLocked(True)
            self.b.Add(t)

    def via(self, net, at, d=0.6, drill=0.3):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(kp(*at)); v.SetDrill(mm(drill)); v.SetWidth(mm(d))
        v.SetNet(self.net(net))
        v.SetLocked(True)
        self.b.Add(v)

    def title(self):
        tb = self.b.GetTitleBlock()
        tb.SetTitle("Rabbit ToF carrier (VL53L8CX)")
        tb.SetRevision(design.REV)
        tb.SetDate("2026-10-10")
        tb.SetCompany("github.com/seralexeev/rabbit")
        tb.SetComment(0, "Generated by pcb/rabbit-tof/gen (design.py); see pcb/rabbit-tof/README.md")

    def save(self):
        self.b.BuildConnectivity()
        pcbnew.SaveBoard(str(BOARD_FILE), self.b)


def main():
    bl = Builder()
    bl.rules()
    bl.title()
    bl.outline()
    bl.place()
    bl.silk()
    for net, layer, pts, w in design.ROUTES:
        bl.track(net, pts, w, bl.b.GetLayerID(layer))
    for net, xy in design.ROUTE_VIAS:
        bl.via(net, xy)
    for xy in design.STITCH:
        bl.via("GND", xy)
    poly = outline_pts(inset=0.0)
    bl.zone("GND", pcbnew.F_Cu, poly, name="GND_F")
    bl.zone("GND", pcbnew.B_Cu, poly, name="GND_B")
    bl.save()
    print("saved", BOARD_FILE, "parts", len(design.PARTS), "nets", len(bl.nets))


if __name__ == "__main__":
    main()
