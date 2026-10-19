"""Copper check for the high-current nets after routing (DRC does not see current): per net the narrowest track
segment per layer, segments below the class width (necks at pads excluded within NECK mm of a pad), the vias and
the number of vias per pad that drops into a plane. Capacity from IPC-2221 (external k = 0.048, internal 0.024,
dT 20 K) at the copper weights of the order: 2 oz outer, 1 oz inner.

Run with KiCad's Python: gen/power_check.py
"""
import math
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

BOARD = HERE.parent / "rabbit-body-c.kicad_pcb"
NECK = 1.5
OZ = {"F.Cu": 2.0, "B.Cu": 2.0}
CURRENT = {**{n: 14.0 for n in design.POWER_15A}, **{n: 10.0 for n in design.POWER_10A},
           "ML_OUT1": 4.1, "ML_OUT2": 4.1, "MR_OUT1": 4.1, "MR_OUT2": 4.1, "ARM_PWR": 5.7, "SW4": 8.0, "+5V_BUCK": 8.0}


def ampacity(width_mm, layer):
    oz = OZ.get(layer, 1.0)
    area_mil2 = (width_mm / 0.0254) * (oz * 1.378)
    k = 0.048 if layer in ("F.Cu", "B.Cu") else 0.024
    return k * 20 ** 0.44 * area_mil2 ** 0.725


def main():
    b = pcbnew.LoadBoard(str(BOARD))
    pads = {}
    for fp in b.GetFootprints():
        for p in fp.Pads():
            pads.setdefault(p.GetNetname(), []).append(p.GetPosition())
    worst = []
    for net, amps in sorted(CURRENT.items()):
        segs, vias = [], 0
        for t in b.GetTracks():
            if t.GetNetname() != net:
                continue
            if t.GetClass() == "PCB_VIA":
                vias += 1
                continue
            mid = (t.GetStart() + t.GetEnd()) / 2
            near_pad = any(math.hypot(pcbnew.ToMM(mid.x - q.x), pcbnew.ToMM(mid.y - q.y)) < NECK for q in pads.get(net, []))
            segs.append((pcbnew.ToMM(t.GetWidth()), b.GetLayerName(t.GetLayer()), near_pad, pcbnew.ToMM(t.GetLength())))
        body = [s for s in segs if not s[2]]
        if not body:
            print(f"{net:12} {amps:5.1f} A  no tracks (pours/planes only), vias {vias}")
            continue
        w, layer, _, _ = min(body, key=lambda s: ampacity(s[0], s[1]))
        cap = ampacity(w, layer)
        flag = "  <-- UNDERSIZED" if cap < amps else ""
        print(f"{net:12} {amps:5.1f} A  narrowest {w:.2f} mm on {layer} ({cap:.1f} A), {len(segs)} segments, "
              f"vias {vias}{flag}")
        if flag:
            worst.append(net)
    print("undersized (before pours):", worst or "none")


if __name__ == "__main__":
    main()
