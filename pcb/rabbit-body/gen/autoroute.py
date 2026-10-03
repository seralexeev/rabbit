"""Autoroute the signal nets with Freerouting and merge the result into the board.

1. export a DSN without the GND fills of F.Cu / In2.Cu / B.Cu (In1 is the GND plane, typed `power`);
2. run Freerouting (CLI, headless);
3. import the SES into the full board, refill the zones and save.
Run with KiCad's Python: gen/autoroute.py [passes]
"""
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


def main():
    passes = sys.argv[1] if len(sys.argv) > 1 else "40"
    WORK.mkdir(parents=True, exist_ok=True)
    b = pcbnew.LoadBoard(str(BOARD))
    for z in list(b.Zones()):
        if z.GetZoneName().startswith("GND_FILL"):
            b.Remove(z)
    dsn = WORK / "board.dsn"
    ses = WORK / "board.ses"
    if not pcbnew.ExportSpecctraDSN(b, str(dsn)):
        raise SystemExit("DSN export failed")
    txt = dsn.read_text()
    txt = re.sub(r"\(layer In1\.Cu\s*\(type signal\)", "(layer In1.Cu\n      (type power)", txt, count=1)
    dsn.write_text(txt)
    if ses.exists():
        ses.unlink()
    t = time.time()
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
