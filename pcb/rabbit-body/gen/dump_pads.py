"""Print pad positions (board frame) of the given references: dump_pads.py U2 F1 ..."""
import sys
from pathlib import Path
import pcbnew
b = pcbnew.LoadBoard(str(Path(__file__).resolve().parents[1] / "rabbit-body.kicad_pcb"))
for fp in b.GetFootprints():
    if fp.GetReference() in sys.argv[1:]:
        rows = []
        for p in fp.Pads():
            x = pcbnew.ToMM(p.GetPosition().x) - 150; y = 150 - pcbnew.ToMM(p.GetPosition().y)
            rows.append(f"{p.GetNumber() or '-'}:{p.GetNetname() or '.'}@({x:.2f},{y:.2f})")
        print(fp.GetReference(), " ".join(rows))
