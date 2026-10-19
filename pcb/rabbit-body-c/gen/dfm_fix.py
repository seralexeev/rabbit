"""Post-route DFM fixes for JLC (review round 3, data/pcb-revc/review/round3-dfm.md), on the routed board:
- the ZED cutout is not plated: no copper fill of any net within 0.5 mm of it, on all eight layers (M1);
- the 0.30 mm thermal holes in the exposed pads of U5/U7 (TPS16630) and U11/U12 (DRV8243) become board vias of the
  pad's net, so the order's "epoxy filled and capped" applies to them (M2);
- the USB-C locating pegs of J50/J53 (0.58 x 1.0 mm) become plated slots: JLC's non-plated slots start at 1.0 mm (M3);
- GND fills on In2 and In3 balance the inner copper of the 2.0 mm deck (4 % vs 90 % on the planes) (M5);
- silkscreen: XT30 polarity marks beside their pins, board title off J63's pads.

Idempotent. Run after gen/power_fix.py, then gen/fill.sh:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 gen/dfm_fix.py [board]
"""
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixups as F  # noqa: E402
import routing as R  # noqa: E402

ALL = ("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu")


def layerset(B, names):
    ls = pcbnew.LSET()
    for n in names:
        ls.AddLayer(B.layer(n))
    return ls


def cutout_keepout(B):
    for z in B.b.Zones():
        if z.GetIsRuleArea() and z.GetZoneName() == "cutout_keepout":
            z.SetLayerSet(layerset(B, ALL))
            z.SetDoNotAllowZoneFills(True)
            B.log.append("cutout_keepout: all layers, no fills")


def thermal_vias(B):
    n = 0
    for ref in ("U5", "U7", "U11", "U12"):
        fp = B.b.FindFootprintByReference(ref)
        for p in list(fp.Pads()):
            if p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH or pcbnew.ToMM(p.GetDrillSize().x) > 0.35:
                continue
            net = p.GetNetname()
            v = pcbnew.PCB_VIA(B.b)
            v.SetPosition(p.GetPosition())
            v.SetDrill(pcbnew.FromMM(0.3))
            v.SetWidth(pcbnew.FromMM(0.5))
            v.SetNet(B.b.FindNet(net))
            B.b.Add(v)
            fp.Remove(p)
            B.removed.append(p)
            n += 1
    B.log.append(f"thermal holes -> vias: {n}")


def plated_pegs(B):
    for ref in ("J50", "J53"):
        fp = B.b.FindFootprintByReference(ref)
        for p in fp.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH and p.GetDrillShape() == pcbnew.PAD_DRILL_SHAPE_OBLONG:
                d = p.GetDrillSize()
                p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
                ls = pcbnew.LSET.AllCuMask()
                ls.AddLayer(pcbnew.F_Mask)
                ls.AddLayer(pcbnew.B_Mask)
                p.SetLayerSet(ls)
                p.SetShape(pcbnew.PAD_SHAPE_OVAL)
                p.SetSize(pcbnew.VECTOR2I(d.x + pcbnew.FromMM(0.36), d.y + pcbnew.FromMM(0.36)))
                p.SetNet(B.b.FindNet("GND"))
                B.log.append(f"{ref} peg -> plated slot, GND")


def inner_gnd(B):
    for lname in ("In2.Cu", "In3.Cu"):
        name = f"GND_FILL_{lname[:3]}"
        if any(z.GetZoneName() == name for z in B.b.Zones()):
            continue
        z = pcbnew.ZONE(B.b)
        z.SetLayer(B.layer(lname))
        z.SetNet(B.b.FindNet("GND"))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in R.BOARD_POLY:
            ol.Append(F.kp(x, y))
        z.SetAssignedPriority(0)
        z.SetLocalClearance(pcbnew.FromMM(0.3))
        z.SetMinThickness(pcbnew.FromMM(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(pcbnew.FromMM(0.4))
        z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.6))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetZoneName(name)
        B.b.Add(z)
        B.log.append(f"{name}")


def silk(B):
    """J20's '+' and J21's '-' printed on top of each other at (-65, -39): put each polarity mark beside its own pin;
    the board title lines crossed J63's pads."""
    for ref in ("J20", "J21"):
        fp = B.b.FindFootprintByReference(ref)
        pins = {p.GetNumber(): F.bx(p.GetPosition()) for p in fp.Pads()}
        for t in fp.GraphicalItems():
            if t.GetClass() == "PCB_TEXT" and t.GetText() in ("+", "-"):
                y = pins["2" if t.GetText() == "+" else "1"][1]
                t.SetPosition(F.kp(-61.2, y))
    for d in B.b.GetDrawings():
        if d.GetClass() == "PCB_TEXT" and d.GetText().startswith(("RABBIT 2.0 BODY", "8L 2.0 mm")):
            x, y = F.bx(d.GetPosition())
            d.SetPosition(F.kp(x, -118.0 if d.GetText().startswith("RABBIT") else -121.0))
    B.log.append("silk: XT30 polarity marks, board title")


def main():
    B = F.Board(F.BOARD)
    cutout_keepout(B)
    thermal_vias(B)
    plated_pegs(B)
    inner_gnd(B)
    silk(B)
    B.save(F.BOARD)
    print("\n".join(B.log))


if __name__ == "__main__":
    main()
