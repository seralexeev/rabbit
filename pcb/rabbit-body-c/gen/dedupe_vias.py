"""Merge same-net vias whose holes sit closer than JLC's 0.25 mm hole-to-hole (deeproute fanout leaves pairs 0.1 mm
apart): keep the locked or larger one, move the track ends of the other onto it, delete it.
Run with KiCad's Python: gen/dedupe_vias.py [board]"""
import math
import sys
from pathlib import Path

import pcbnew

BOARD = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "rabbit-body-c.kicad_pcb"
GAP = pcbnew.FromMM(0.25)

b = pcbnew.LoadBoard(str(BOARD))
vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
vias.sort(key=lambda v: (not v.IsLocked(), -v.GetDrill()))
tracks = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
kept, gone = [], []
for v in vias:
    p = v.GetPosition()
    host = next((k for k in kept if k.GetNetCode() == v.GetNetCode() and
                 math.hypot(k.GetPosition().x - p.x, k.GetPosition().y - p.y) < (k.GetDrill() + v.GetDrill()) / 2 + GAP), None)
    if host is None:
        kept.append(v)
        continue
    for t in tracks:
        for get, put in ((t.GetStart, t.SetStart), (t.GetEnd, t.SetEnd)):
            if get() == p and t.GetNetCode() == v.GetNetCode():
                put(host.GetPosition())
    gone.append(v)
for v in gone:
    b.Remove(v)
for t in tracks:
    if t.GetStart() == t.GetEnd():
        b.Remove(t)
b.Save(str(BOARD))
print(f"dedupe_vias: merged {len(gone)} vias")
