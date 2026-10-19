"""Autoroute every net with Freerouting and merge the result into the board.

The GND pours (F and B) are removed from the exported DSN: KiCad exports a zone as a plane by its outline, which would
swallow the pads of other nets. Freerouting routes GND like any other net; the pours are refilled afterwards.
Run with KiCad's Python: gen/autoroute.py [passes]
"""
import subprocess
import sys
import time
from pathlib import Path

import pcbnew

PRJ = Path(__file__).resolve().parents[1]
ROOT = PRJ.parents[1]
BOARD = PRJ / "rabbit-tof.kicad_pcb"
WORK = ROOT / "data" / "pcb-route-tof"
JAR = ROOT / "data" / "tools" / "freerouting-2.4.1.jar"
JAVA = "/opt/homebrew/opt/openjdk/bin/java"


def main():
    passes = sys.argv[1] if len(sys.argv) > 1 else "30"
    WORK.mkdir(parents=True, exist_ok=True)
    b = pcbnew.LoadBoard(str(BOARD))
    for z in list(b.Zones()):
        b.Remove(z)
    dsn, ses = WORK / "board.dsn", WORK / "board.ses"
    if not pcbnew.ExportSpecctraDSN(b, str(dsn)):
        raise SystemExit("DSN export failed")
    if ses.exists():
        ses.unlink()
    t = time.time()
    cmd = [JAVA, "-jar", str(JAR), "-de", str(dsn), "-do", str(ses), "-mp", passes, "-mt", "1"]
    print(" ".join(cmd), flush=True)
    with open(WORK / "freerouting.log", "w") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    print(f"freerouting {time.time() - t:.0f} s", flush=True)
    if not ses.exists():
        raise SystemExit(f"no SES, see {WORK / 'freerouting.log'}")
    subprocess.run([sys.executable, str(Path(__file__).with_name("import_ses.py")), str(ses)], check=True)


if __name__ == "__main__":
    main()
