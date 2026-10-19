"""Remove vias and track stubs that DRC reports as dangling and widen sub-0.13 mm necks left by the autorouter.
Reads fab/drc.json."""
import json
from pathlib import Path

import pcbnew

PRJ = Path(__file__).resolve().parents[1]
d = json.loads((PRJ / "fab" / "drc.json").read_text())
spots = [(v["type"], round(i["pos"]["x"], 3), round(i["pos"]["y"], 3))
         for v in d["violations"] if v["type"] in ("via_dangling", "track_dangling") for i in v["items"]]
b = pcbnew.LoadBoard(str(PRJ / "rabbit-tof.kicad_pcb"))
n = 0
tracks = list(b.GetTracks())
for t in tracks:
    if t.GetClass() == "PCB_TRACK" and t.GetWidth() < pcbnew.FromMM(0.13):
        t.SetWidth(pcbnew.FromMM(0.15)); n += 1
for t in tracks:
    for kind, x, y in spots:
        near = lambda q: abs(pcbnew.ToMM(q.x) - x) < 0.01 and abs(pcbnew.ToMM(q.y) - y) < 0.01  # noqa: E731
        if kind == "via_dangling" and t.GetClass() == "PCB_VIA" and near(t.GetPosition()):
            b.Remove(t); n += 1; break
        if kind == "track_dangling" and t.GetClass() == "PCB_TRACK" and (near(t.GetStart()) or near(t.GetEnd())):
            b.Remove(t); n += 1; break
pcbnew.SaveBoard(str(PRJ / "rabbit-tof.kicad_pcb"), b)
print("cleaned", n)
