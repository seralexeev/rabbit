"""Build pcb/rabbit-body/rabbit-body.kicad_pcb from design.py and routing.py.

Run with KiCad's bundled Python (pcbnew):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 gen/build_board.py [--no-route]
Board frame -> KiCad page: x = 150 + X, y = 150 - Y.
"""
import json
import math
import re
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
PRJ = HERE.parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

OX, OY = 150.0, 150.0
KFP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/"
LIBS = {"rabbit_body": str(PRJ / "lib" / "rabbit_body.pretty")}
BOARD_FILE = PRJ / "rabbit-body.kicad_pcb"
# library footprints whose 3D model is missing from the KiCad 10 library
MODEL_SUBST = {
    "${KICAD10_3DMODEL_DIR}/Connector_AMASS.3dshapes/AMASS_XT30PW-F_1x02_P2.50mm_Horizontal.step": "${KIPRJMOD}/3d/xt30pw_f.step",
    "${KICAD10_3DMODEL_DIR}/Package_TO_SOT_SMD.3dshapes/SOT-223-6.step": "${KICAD10_3DMODEL_DIR}/Package_TO_SOT_SMD.3dshapes/SOT-223.step",
}


def mm(v):
    return pcbnew.FromMM(v)


def kp(X, Y):
    return pcbnew.VECTOR2I(mm(OX + X), mm(OY - Y))


def board_xy(v):
    return pcbnew.ToMM(v.x) - OX, OY - pcbnew.ToMM(v.y)


class Builder:
    def __init__(self):
        self.board = pcbnew.NewBoard(str(BOARD_FILE))
        self.b = self.board
        self.b.SetCopperLayerCount(4)
        self.nets = {}
        self.fps = {}

    # ------------------------------------------------------------ setup
    def rules(self):
        ds = self.b.GetDesignSettings()
        ds.m_MinClearance = mm(0.1)
        ds.m_TrackMinWidth = mm(0.1)
        ds.m_ViasMinSize = mm(0.45)
        ds.m_MinThroughDrill = mm(0.2)
        ds.m_ViasMinAnnularWidth = mm(0.13)
        ds.m_HoleClearance = mm(0.25)
        ds.m_HoleToHoleMin = mm(0.25)
        ds.m_CopperEdgeClearance = mm(0.3)
        ds.m_SilkClearance = mm(0.0)
        ds.m_MinSilkTextHeight = mm(0.8)
        ds.m_MinSilkTextThickness = mm(0.15)
        ds.m_MinResolvedSpokes = 1
        ns = ds.m_NetSettings
        default = ns.GetDefaultNetclass()
        default.SetClearance(mm(0.15))
        default.SetTrackWidth(mm(0.15))
        default.SetViaDiameter(mm(0.6))
        default.SetViaDrill(mm(0.3))
        for name, width, clr, via, drill, nets in (
                ("PWR_HI", 2.0, 0.3, 1.0, 0.5, design.POWER_HI),
                ("PWR_MID", 1.0, 0.2, 0.8, 0.4, design.POWER_MID),
                ("PWR_LO", 0.4, 0.15, 0.6, 0.3, design.POWER_LO + ["GND"])):
            nc = pcbnew.NETCLASS(name)
            nc.SetClearance(mm(clr)); nc.SetTrackWidth(mm(width)); nc.SetViaDiameter(mm(via)); nc.SetViaDrill(mm(drill))
            ns.SetNetclass(name, nc)
            for n in nets:
                ns.SetNetclassPatternAssignment(n, name)
        ns.RecomputeEffectiveNetclasses()

    def outline(self):
        data = json.loads((HERE / "outline.json").read_text())
        for s in data["segments"]:
            sh = pcbnew.PCB_SHAPE(self.b)
            sh.SetLayer(pcbnew.Edge_Cuts)
            sh.SetWidth(mm(0.1))
            if s["type"] == "line":
                sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
                sh.SetStart(kp(*s["start"])); sh.SetEnd(kp(*s["end"]))
            else:
                sh.SetShape(pcbnew.SHAPE_T_ARC)
                sh.SetArcGeometry(kp(*s["start"]), kp(*s["mid"]), kp(*s["end"]))
            self.b.Add(sh)
        for poly in getattr(design, "CUTOUTS", []):
            for a, c in zip(poly, poly[1:] + poly[:1]):
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

    # ------------------------------------------------------------ parts
    def place(self):
        for p in design.PARTS:
            lib, name = p["fp"].split(":")
            path = LIBS.get(lib, KFP + lib + ".pretty")
            fp = pcbnew.FootprintLoad(path, name)
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
            for pad in fp.Pads():
                n = p["pins"].get(pad.GetNumber())
                if n:
                    pad.SetNet(self.net(n))
            attrs = fp.GetAttributes()
            if p["bom"] in ("none", "module"):
                attrs |= pcbnew.FP_EXCLUDE_FROM_POS_FILES
            if p["bom"] == "none":
                attrs |= pcbnew.FP_EXCLUDE_FROM_BOM
            fp.SetAttributes(attrs)
            ref = fp.Reference()
            ref.SetTextSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
            ref.SetTextThickness(mm(0.15))
            if re.match(r"^(H|TP|NT|MOD|R|C|D|Q)\d", p["ref"]) or p["ref"] in ("U1", "J23", "J24", "J25"):
                ref.SetVisible(False)
            self.b.Add(fp)
            self.fps[p["ref"]] = fp

    def labels(self):
        for p in design.PARTS:
            if not p.get("label"):
                continue
            fp = self.fps[p["ref"]]
            bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox() if fp.GetCourtyard(pcbnew.F_CrtYd).OutlineCount() else fp.GetBoundingBox()
            cx = pcbnew.ToMM((bb.GetLeft() + bb.GetRight()) / 2) - OX
            top = OY - pcbnew.ToMM(bb.GetTop())
            bot = OY - pcbnew.ToMM(bb.GetBottom())
            dx, dy, side = design.LABEL_POS.get(p["ref"], (0.0, 0.0, "top")) if hasattr(design, "LABEL_POS") else (0, 0, "top")
            if side == "right":
                right = pcbnew.ToMM(bb.GetRight()) - OX
                lbl = p["label"] if p["label"].startswith(p["ref"]) else f'{p["ref"]} {p["label"]}'
                self.text(lbl, right + 1.0 + dx, (top + bot) / 2 + dy, 1.0, rot=90)
                fp.Reference().SetVisible(False)
                continue
            y = (top + 1.0) if side == "top" else (bot - 1.0)
            lbl = p["label"] if (p["label"].startswith(p["ref"]) or p["ref"].startswith("TP")) else f'{p["ref"]} {p["label"]}'
            self.text(lbl, cx + dx, y + dy, 1.0)
            fp.Reference().SetVisible(False)
        for txt, x, y, size, side in getattr(design, "SILK", []):
            self.text(txt, x, y, size, pcbnew.F_SilkS if side == "F" else pcbnew.B_SilkS)

    def text(self, s, X, Y, size=1.0, layer=pcbnew.F_SilkS, rot=0):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetPosition(kp(X, Y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(max(0.15, size * 0.15)))
        t.SetTextAngleDegrees(rot)
        if layer == pcbnew.B_SilkS:
            t.SetMirrored(True)
        self.b.Add(t)

    # ------------------------------------------------------------ copper
    def track(self, net, pts, width, layer=pcbnew.F_Cu):
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

    def zone(self, net, layer, poly, priority=0, clearance=0.3, min_w=0.25, thermal=False, name=None):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(layer)
        if net:
            z.SetNet(self.net(net))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in poly:
            ol.Append(mm(OX + x), mm(OY - y))
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(min_w))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL if thermal else pcbnew.ZONE_CONNECTION_FULL)
        z.SetThermalReliefGap(mm(0.4))
        z.SetThermalReliefSpokeWidth(mm(0.6))
        if name:
            z.SetZoneName(name)
        self.b.Add(z)
        return z

    def keepout(self, poly, layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"), tracks=True, vias=True, pours=True,
                footprints=False):
        z = pcbnew.ZONE(self.b)
        z.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(self.b.GetLayerID(l))
        z.SetLayerSet(ls)
        z.SetDoNotAllowTracks(tracks); z.SetDoNotAllowVias(vias); z.SetDoNotAllowZoneFills(pours)
        z.SetDoNotAllowPads(False); z.SetDoNotAllowFootprints(footprints)
        ol = z.Outline(); ol.NewOutline()
        for x, y in poly:
            ol.Append(mm(OX + x), mm(OY - y))
        self.b.Add(z)

    def pad_xy(self, ref, num):
        for pad in self.fps[ref].Pads():
            if pad.GetNumber() == str(num):
                return board_xy(pad.GetPosition())
        raise KeyError(f"{ref}.{num}")

    def fill(self):
        filler = pcbnew.ZONE_FILLER(self.b)
        filler.Fill(self.b.Zones())

    def save(self):
        self.b.BuildConnectivity()
        pcbnew.SaveBoard(str(BOARD_FILE), self.b)
        txt = BOARD_FILE.read_text()
        txt = txt.replace('(paper "A4")', '(paper "A3" portrait)', 1)
        for a, c in MODEL_SUBST.items():
            txt = txt.replace(a, c)
        BOARD_FILE.write_text(txt)


def circle(x, y, r, n=24):
    return [(x + r * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def main():
    bl = Builder()
    bl.rules()
    bl.outline()
    bl.place()
    bl.labels()
    if "--no-route" not in sys.argv:
        import routing
        routing.apply(bl)
    bl.fill()
    bl.save()
    print("saved", BOARD_FILE, "parts", len(design.PARTS), "nets", len(bl.nets))


if __name__ == "__main__":
    main()
