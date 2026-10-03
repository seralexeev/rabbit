"""Remove vias and track stubs that DRC reports as dangling (unused INA4235 fan-out vias), widen sub-0.1 mm\nnecks left by the autorouter. Reads fab/drc.json."""
import json
from pathlib import Path

import pcbnew

PRJ = Path(__file__).resolve().parents[1]
d = json.loads((PRJ / "fab" / "drc.json").read_text())
spots = []
for v in d["violations"]:
    if v["type"] in ("via_dangling", "track_dangling"):
        for i in v["items"]:
            spots.append((v["type"], round(i["pos"]["x"], 3), round(i["pos"]["y"], 3)))
b = pcbnew.LoadBoard(str(PRJ / "rabbit-body.kicad_pcb"))
n = 0
tracks = list(b.GetTracks())
for t in tracks:   # Freerouting sometimes necks a segment below the 0.1 mm minimum at a pad
    if t.GetClass() == "PCB_TRACK" and t.GetWidth() < pcbnew.FromMM(0.1):
        t.SetWidth(pcbnew.FromMM(0.12)); n += 1
for t in tracks:
    for kind, x, y in spots:
        p = t.GetPosition() if kind == "via_dangling" else t.GetStart()
        if kind == "via_dangling" and t.GetClass() == "PCB_VIA" and abs(pcbnew.ToMM(p.x) - x) < 0.01 and abs(pcbnew.ToMM(p.y) - y) < 0.01:
            b.Remove(t); n += 1; break
        if kind == "track_dangling" and t.GetClass() == "PCB_TRACK":
            pts = [t.GetStart(), t.GetEnd(), t.GetPosition()]
            if any(abs(pcbnew.ToMM(q.x) - x) < 0.01 and abs(pcbnew.ToMM(q.y) - y) < 0.01 for q in pts):
                b.Remove(t); n += 1; break
pcbnew.SaveBoard(str(PRJ / "rabbit-body.kicad_pcb"), b)
print("removed", n)
