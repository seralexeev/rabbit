"""Import a Freerouting session into rabbit-body.kicad_pcb: import_ses.py board.ses"""
import sys
from pathlib import Path

import pcbnew

BOARD = Path(__file__).resolve().parents[1] / "rabbit-body.kicad_pcb"
b = pcbnew.LoadBoard(str(BOARD))
if not pcbnew.ImportSpecctraSES(b, sys.argv[1]):
    raise SystemExit("SES import failed")
pcbnew.SaveBoard(str(BOARD), b)
print("imported", sys.argv[1])
