"""JLCPCB cost estimate for N assembled boards (run with KiCad's Python after gen/stock.py): gen/cost.py [boards] [pcbs]

Rates (JLCPCB assembly price page, as quoted in docs/reports/2026-10-03-body-pcb-review.md §5): Standard PCBA set-up
US$25.56 per order, stencil ~US$7, extended part US$3 per unique part per order, SMT joint US$0.0017, THT (hand by
JLC) US$0.0164 per joint + US$3.58 per order. Part prices: JLC catalogue unit price at 1-9 pcs (fab/stock.json).
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

boards = int(sys.argv[1]) if len(sys.argv) > 1 else 2
pcbs = int(sys.argv[2]) if len(sys.argv) > 2 else 5
stock = json.loads((HERE.parent / "fab" / "stock.json").read_text())["parts"]
b = pcbnew.LoadBoard(str(HERE.parent / "rabbit-body.kicad_pcb"))
pads = {fp.GetReference(): sum(1 for p in fp.Pads() if p.GetNumber()) for fp in b.GetFootprints()}

smt_joints = tht_joints = 0
parts_cost = 0.0
ext = set()
qty = Counter()
for p in design.PARTS:
    if p["bom"] not in ("smt", "tht") or not p["lcsc"]:
        continue
    qty[p["lcsc"]] += 1
    if p["bom"] == "smt":
        smt_joints += pads.get(p["ref"], 2)
    else:
        tht_joints += pads.get(p["ref"], 2)
for code, n in qty.items():
    s = stock.get(code) or {}
    parts_cost += (s.get("price") or 0) * n
    if s.get("type") != "base":
        ext.add(code)

setup = 25.56 + 7.0 + 3.0 * len(ext) + 3.58
per_board = smt_joints * 0.0017 + tht_joints * 0.0164 + parts_cost
print(f"BOM lines {len(qty)}, extended {len(ext)}, basic {len(qty) - len(ext)}")
print(f"per board: {smt_joints} SMT joints, {tht_joints} THT joints, parts US${parts_cost:.2f}")
print(f"assembly set-up + extended-part fees per order: US${setup:.2f}")
print(f"{boards} assembled boards: US${setup + boards * per_board:.2f} (+ {pcbs} bare 4-layer PCBs ~US$60-90, "
      f"DHL to Australia ~US$25-35)")
