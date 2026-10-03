"""Netlist checks in place of ERC (the netlist is code, not a schematic):
- every net has at least two pins;
- every IC power, ground and bus pin is on a net;
- star ground: no part touches both GND and GND_MOT except the net tie NT1;
- I2C1 addresses are unique (INA226 straps decoded per SBOS547C table 6-2);
- with --board: the routed board matches design.py pin for pin."""
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

errors = 0


def err(*a):
    global errors
    errors += 1
    print("ERROR:", *a)


pins = defaultdict(list)
for p in design.PARTS:
    for pad, net in p["pins"].items():
        pins[net].append(f'{p["ref"]}.{pad}')
print(f"{len(design.PARTS)} parts, {len(pins)} nets")
for n, v in sorted(pins.items()):
    if len(v) < 2:
        err("single-pin net:", n, v)

by = {p["ref"]: p for p in design.PARTS}
must = {"U1": ["1", "15", "16", "27", "28", "29", "31", "32", "47", "48", "63", "64", "7", "49", "50", "34", "55"],
        "U4": ["1", "2", "5", "6", "7", "8", "13", "14", "15", "16"], "U6": ["1", "2", "5", "6", "7", "8", "13", "14", "15", "16"],
        "U5": ["1", "6", "9", "13", "18", "21"],
        "U7": ["1", "2", "3", "5"], "U8": ["14", "28", "26", "27"], "U9": ["2", "13", "15", "16"],
        "U10": ["1", "2", "6", "7", "8", "9", "10", "11", "12"], "U15": ["1", "2", "3", "5"], "U16": ["1", "2", "3", "4", "5"],
        "U17": ["1", "2", "3", "4", "8"], "U18": ["1", "2", "3"]}
for ref in ("U11", "U12"):
    must[ref] = ["2", "4", "9", "10", "11", "12", "15", "18", "21", "22", "23", "25", "26", "41"] + [str(i) for i in range(27, 41)]
for ref in ("U19", "U20", "U21", "U22"):
    must[ref] = [str(i) for i in range(1, 11)]
for ref, need in must.items():
    miss = [x for x in need if x not in by[ref]["pins"]]
    if miss:
        err("unconnected power/bus pin:", ref, miss)
for ref in ("U11", "U12"):
    vm = [k for k, v in by[ref]["pins"].items() if v == "MOT_BUS"]
    if sorted(vm) != ["10", "11", "9"]:
        err(ref, "VM pins", vm)

for p in design.PARTS:
    s = set(p["pins"].values())
    if {"GND", "GND_MOT"} <= s and p["ref"] != "NT1":
        err("star ground broken by", p["ref"], p["pins"])
mot = sorted(p["ref"] for p in design.PARTS if "GND_MOT" in p["pins"].values())
print("on GND_MOT:", " ".join(mot))

strap = {"GND": 0, "+3V3_PI": 1, "I2C1_SDA": 2, "I2C1_SCL": 3}
addr = {"U8": [0x40, 0x70], "U9": [0x68]}
for p in design.PARTS:
    if p["value"] == "INA226":
        addr[p["ref"]] = [0x40 | strap[p["pins"]["1"]] << 2 | strap[p["pins"]["2"]]]
seen = defaultdict(list)
for ref, aa in addr.items():
    for a in aa:
        seen[a].append(ref)
for a, refs in sorted(seen.items()):
    print(f"I2C1 0x{a:02x}: {' '.join(refs)}")
    if len(refs) > 1:
        err("I2C address clash", hex(a), refs)

if "--board" in sys.argv:
    import pcbnew
    b = pcbnew.LoadBoard(str(HERE.parent / "rabbit-body.kicad_pcb"))
    diff = 0
    for fp in b.GetFootprints():
        p = by.get(fp.GetReference())
        for pad in fp.Pads():
            if not pad.GetNumber():
                continue
            want = p["pins"].get(pad.GetNumber(), "") if p else ""
            if pad.GetNetname() != want:
                print("board/design mismatch", fp.GetReference(), pad.GetNumber(), pad.GetNetname(), want)
                diff += 1
    print("board matches design.py" if not diff else f"{diff} mismatches")
    errors += diff
print("netlist OK" if not errors else f"{errors} errors")
sys.exit(1 if errors else 0)
