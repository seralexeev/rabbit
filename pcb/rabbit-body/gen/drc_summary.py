"""Run kicad-cli DRC and summarise violations: drc_summary.py [--all]"""
import collections
import json
import subprocess
import sys
from pathlib import Path

PRJ = Path(__file__).resolve().parents[1]
KC = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
out = PRJ / "fab" / "drc.json"
out.parent.mkdir(exist_ok=True)
subprocess.run([KC, "pcb", "drc", "--format", "json", "--severity-all", "--refill-zones", "--save-board", "--units",
                "mm", "-o", str(out), str(PRJ / "rabbit-body.kicad_pcb")], capture_output=True)
d = json.loads(out.read_text())
c = collections.Counter()
for v in d.get("violations", []):
    c[(v["severity"], v["type"])] += 1
print("violations:", sum(c.values()), dict(c))
print("unconnected:", len(d.get("unconnected_items", [])))
print("courtyard/parity:", len(d.get("schematic_parity", [])))
show = sys.argv[1:] and sys.argv[1] or ""
for v in d.get("violations", []):
    if show == "--all" or (show and v["type"] == show):
        print(v["type"], "|", v["description"], "|", "; ".join(i["description"] + " @ (%.2f, %.2f)" % (i["pos"]["x"] - 150, 150 - i["pos"]["y"]) for i in v["items"]))
