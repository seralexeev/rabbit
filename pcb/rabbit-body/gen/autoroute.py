"""Autoroute the signal nets with Freerouting and merge the result into the board.

1. export a DSN without the GND fills of F.Cu / In2.Cu / B.Cu (In1 is the GND plane, typed `power`) and with the
   power pours given to Freerouting as their filled copper instead of their outlines: KiCad exports a zone as a
   plane by its outline, which swallows the pads of other nets inside it, and Freerouting then never reaches them.
   A plane on a signal layer is no obstacle to Freerouting, so each pour also gets a keepout 0.35 mm inside its
   copper (own-net tracks can still reach the rim);
2. run Freerouting (CLI, headless), or fastroute (its Rust port) with ROUTER=fastroute;
3. import the SES into the full board, refill the zones and save.
Run with KiCad's Python: gen/autoroute.py [passes]
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pcbnew

PRJ = Path(__file__).resolve().parents[1]
ROOT = PRJ.parents[1]
BOARD = PRJ / "rabbit-body.kicad_pcb"
WORK = ROOT / "data" / "pcb-route"
JAR = ROOT / "data" / "tools" / "freerouting-2.4.1.jar"
JAVA = "/opt/homebrew/opt/openjdk/bin/java"
FASTROUTE = os.environ.get("FASTROUTE", str(ROOT / "data" / "tools" / "fastroute" / "fastroute-0.1.7-macos-arm64" / "fastroute"))


def filled_planes(b):
    out = []
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetZoneName().startswith("GND_FILL"):
            continue
        for layer in z.GetLayerSet().Seq():
            name = b.GetLayerName(layer)
            if name == "In1.Cu":
                continue
            polys = z.GetFilledPolysList(layer)
            core = pcbnew.SHAPE_POLY_SET(polys)
            core.Deflate(pcbnew.FromMM(0.35), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, pcbnew.FromMM(0.02))
            core.Fracture()
            for kind, ps in ((f"plane {z.GetNetname()}", polys), ('keepout ""', core)):
                for i in range(ps.OutlineCount()):
                    ol = ps.Outline(i)
                    pts = [ol.CPoint(k) for k in range(ol.PointCount())]
                    pts.append(pts[0])
                    xy = " ".join(f"{p.x / 1000:.1f} {-p.y / 1000:.1f}" for p in pts)
                    out.append(f"    ({kind} (polygon {name} 0 {xy}))\n")
    return "".join(out)


PLANE = re.compile(r"    \(plane \S+ \(polygon (?:F|B|In2)\.Cu [^()]*\)\)\n")


def main():
    passes = sys.argv[1] if len(sys.argv) > 1 else "40"
    WORK.mkdir(parents=True, exist_ok=True)
    b = pcbnew.LoadBoard(str(BOARD))
    planes = filled_planes(b)
    for z in list(b.Zones()):                    # after filled_planes(): Zones() breaks after a Remove()
        if z.GetZoneName().startswith("GND_FILL"):
            b.Remove(z)
    dsn = WORK / "board.dsn"
    ses = WORK / "board.ses"
    if not pcbnew.ExportSpecctraDSN(b, str(dsn)):
        raise SystemExit("DSN export failed")
    txt = dsn.read_text()
    at = PLANE.search(txt).start()
    txt = txt[:at] + planes + PLANE.sub("", txt[at:])
    txt = re.sub(r"\(layer In1\.Cu\s*\(type signal\)", "(layer In1.Cu\n      (type power)", txt, count=1)
    dsn.write_text(txt)
    if ses.exists():
        ses.unlink()
    t = time.time()
    if os.environ.get("ROUTER", "freerouting") == "fastroute":
        cmd = [FASTROUTE, "-de", str(dsn), "-do", str(ses), "-mp", passes, "--report", str(WORK / "fastroute.json"),
               "--router.copper_to_edge_clearance_um=350"]
    else:
        cmd = [JAVA, "-jar", str(JAR), "-de", str(dsn), "-do", str(ses), "-mp", passes, "-mt", "1"]
    print(" ".join(cmd), flush=True)
    log = WORK / "freerouting.log"
    with open(log, "w") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    print(f"freerouting {time.time() - t:.0f} s", flush=True)
    if not ses.exists():
        raise SystemExit(f"no SES, see {log}")
    subprocess.run([sys.executable, str(Path(__file__).with_name("import_ses.py")), str(ses)], check=True)
    subprocess.run([str(Path(__file__).with_name("fill.sh"))], check=True)


if __name__ == "__main__":
    main()
