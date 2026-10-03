"""Netlist sanity checks in place of ERC (the netlist is code, not a schematic):
every net has at least two pins, every IC/module power pin is on a net, and the board matches design.py."""
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

pins = defaultdict(list)
for p in design.PARTS:
    for pad, net in p["pins"].items():
        pins[net].append(f'{p["ref"]}.{pad}')
bad = {n: v for n, v in pins.items() if len(v) < 2}
print(f"{len(design.PARTS)} parts, {len(pins)} nets")
for n, v in sorted(bad.items()):
    print("single-pin net:", n, v)
must = {"U3": ["A4", "B4"], "U7": ["1", "2", "3", "5"], "U8": ["14", "28", "26", "27"], "U9": ["2", "13", "15", "16"],
        "U2": ["VIN", "VOUT", "GND"], "U4": ["VIN", "VOUT", "GND"], "U5": ["VIN", "VOUT", "GND", "EN"],
        "U6": ["VIN", "VOUT", "GND"]}
by = {p["ref"]: p for p in design.PARTS}
for ref, need in must.items():
    miss = [x for x in need if x not in by[ref]["pins"]]
    if miss:
        print("unconnected power/bus pin:", ref, miss)
if "--board" in sys.argv:
    import pcbnew
    b = pcbnew.LoadBoard(str(HERE.parent / "rabbit-body.kicad_pcb"))
    diff = 0
    for fp in b.GetFootprints():
        p = by.get(fp.GetReference())
        for pad in fp.Pads():
            want = p["pins"].get(pad.GetNumber(), "") if p else ""
            if pad.GetNetname() != want:
                print("board/design mismatch", fp.GetReference(), pad.GetNumber(), pad.GetNetname(), want)
                diff += 1
    print("board matches design.py" if not diff else f"{diff} mismatches")
sys.exit(1 if bad else 0)
