"""Locked copper laid before the autorouter (gen/make.sh runs it after build_board.py): the links the router cannot
make or made badly on the rev C routes (data/pcb-route/routed-8L-C2, see docs/log/2026-10-10-body-pcb-rev-c.md).

- DRV8243 VM bars (pad 4, 3.5 x 0.5 mm) into the In5 MOT_BUS pour: 3-4 vias d0.45/0.2 inside each bar (via-in-pad;
  the router cannot place those and left both VM pads unconnected).
- TPS16630 U5/U7 IN pins 1-3 (3.5 / 3.8 A) from the In4 VBUS plane: 4 x d0.8/0.4 vias and a 2 mm B.Cu feed per device
  (the router fed them through one 0.8 mm track and 0.1 mm necks past the NC pin 4); own vias for pin 6 (P_IN) and the
  OVP resistors R82 / R182.
- J50 USB-C: the A6/B6 USB_DP pair needs the second diagonal of the USB-C "X" (A7/B7 take the F.Cu diagonal).
Coordinates are in the board frame (mm, +X right, +Y front) and follow the footprint positions in gen/design.py +
gen/placement.json; every item is checked for 0.15 mm clearance against the placed pads with KiCad's shape collision.

Run with KiCad's Python: gen/preroute.py [board]
"""
import sys
from pathlib import Path

import pcbnew

PRJ = Path(__file__).resolve().parents[1]
BOARD = Path(sys.argv[1]) if len(sys.argv) > 1 else PRJ / "rabbit-body-c.kicad_pcb"
OX = OY = 150.0
CLR = 0.15

VM_VIAS = {"MOT_BUS": [(x, -82.95) for x in (-22.0, -21.3, -19.7, 26.3, 25.5, 24.7, 24.0)]}
VBUS_VIAS = [(-48.1, -37.0), (-47.3, -37.0), (-48.1, -36.2), (-47.3, -36.2),
             (-48.3, -60.0), (-46.6, -60.0), (-48.3, -59.2), (-46.6, -59.2)]
VBUS_FEEDS = [((-47.14, -36.2), (-47.14, -40.5)), ((-47.14, -59.2), (-47.14, -63.5))]
VBUS_SMALL = [(-46.5, -43.3), (-46.4, -66.3), (-44.6, -45.35), (-44.7, -68.2)]
USB_DP = [("F.Cu", (23.75, -149.67), (23.75, -148.7)), ("In2.Cu", (23.75, -148.7), (24.46, -150.53)),
          ("F.Cu", (24.46, -150.53), (24.25, -150.74)), ("F.Cu", (24.25, -150.74), (24.25, -151.33))]
USB_DP_VIAS = [(23.75, -148.7), (24.46, -150.53)]


def kp(X, Y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(OX + X), pcbnew.FromMM(OY - Y))


def bx(v):
    return pcbnew.ToMM(v.x) - OX, OY - pcbnew.ToMM(v.y)


class Pre:
    def __init__(self, b):
        self.b = b
        self.pads = [(fp.GetReference() + "." + p.GetNumber(), p) for fp in b.GetFootprints() for p in fp.Pads()]
        self.added = 0

    def check(self, item, layers, net):
        for lname in layers:
            lid = self.b.GetLayerID(lname)
            cs = item.GetEffectiveShape()
            bb = cs.BBox(); bb.Inflate(pcbnew.FromMM(CLR + 0.05))
            for descr, p in self.pads:
                if p.GetNetname() == net or not p.IsOnLayer(lid):
                    continue
                s = p.GetEffectiveShape(lid)
                if s.BBox().Intersects(bb) and s.Collide(cs, pcbnew.FromMM(CLR)):
                    raise SystemExit(f"preroute: {net} item at {bx(item.GetPosition())} hits {descr} on {lname}")

    def via(self, net, at, d=0.45, drill=0.2):
        for t in self.b.GetTracks():
            if t.GetClass() == "PCB_VIA" and t.GetNetname() == net and bx(t.GetPosition()) == at:
                return
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(kp(*at)); v.SetDrill(pcbnew.FromMM(drill)); v.SetWidth(pcbnew.FromMM(d))
        v.SetNet(self.b.FindNet(net)); v.SetLocked(True)
        self.check(v, ("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"), net)
        self.b.Add(v); self.added += 1

    def track(self, net, layer, a, c, w):
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(kp(*a)); t.SetEnd(kp(*c)); t.SetWidth(pcbnew.FromMM(w)); t.SetLayer(self.b.GetLayerID(layer))
        t.SetNet(self.b.FindNet(net)); t.SetLocked(True)
        self.check(t, (layer,), net)
        self.b.Add(t); self.added += 1


def apply(b):
    p = Pre(b)
    for net, pts in VM_VIAS.items():
        for at in pts:
            p.via(net, at)
    for at in VBUS_VIAS:
        p.via("VBUS", at, 0.8, 0.4)
    for a, c in VBUS_FEEDS:
        p.track("VBUS", "B.Cu", a, c, 2.0)
    for at in VBUS_SMALL:
        p.via("VBUS", at)
    for layer, a, c in USB_DP:
        p.track("USB_DP", layer, a, c, 0.15)
    for at in USB_DP_VIAS:
        p.via("USB_DP", at)
    return p.added


def main():
    b = pcbnew.LoadBoard(str(BOARD))
    n = apply(b)
    b.BuildConnectivity()
    pcbnew.SaveBoard(str(BOARD), b)
    print("preroute: added", n, "locked items")


if __name__ == "__main__":
    main()
