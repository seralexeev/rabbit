"""Import a Freerouting session into rabbit-body.kicad_pcb: import_ses.py board.ses"""
import sys
from pathlib import Path

import pcbnew

BOARD = Path(__file__).resolve().parents[1] / "rabbit-body.kicad_pcb"
b = pcbnew.LoadBoard(str(BOARD))
if not pcbnew.ImportSpecctraSES(b, sys.argv[1]):
    raise SystemExit("SES import failed")
seen = set()
for t in list(b.GetTracks()):   # the session repeats the fixed hand tracks and vias already on the board
    key = (t.GetClass(), t.GetNetCode(), t.GetLayer(), t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y,
           t.GetWidth(pcbnew.F_Cu) if t.GetClass() == "PCB_VIA" else t.GetWidth())
    if key in seen:
        b.Remove(t)
    else:
        seen.add(key)
pcbnew.SaveBoard(str(BOARD), b)
print("imported", sys.argv[1])
