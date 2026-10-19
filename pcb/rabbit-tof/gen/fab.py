"""Fabrication outputs for JLCPCB into fab/: Gerbers + drill (zip), JLC BOM + CPL (every part with an LCSC number,
both sides), full BOM with the JLC stock of fab/stock.json (gen/stock.py), and the board STEP (origin = board centre,
the board frame of design.py) for the CAD bracket check.

Run with KiCad's Python: gen/fab.py
"""
import csv
import json
import re
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRJ = HERE.parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

KC = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
PCB = PRJ / "rabbit-tof.kicad_pcb"
FAB = PRJ / "fab"
NAME = f"rabbit-tof-rev{design.REV}"
LAYERS = "F.Cu,B.Cu,F.Mask,B.Mask,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,Edge.Cuts"


def run(*args):
    subprocess.run([KC, *args], check=True, capture_output=True)


def natural(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def gerbers():
    g = FAB / "gerber"
    if g.exists():
        shutil.rmtree(g)
    g.mkdir(parents=True)
    run("pcb", "export", "gerbers", "--layers", LAYERS, "--subtract-soldermask", "--use-drill-file-origin",
        "-o", str(g) + "/", str(PCB))
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th", "--generate-map",
        "--map-format", "pdf", "--drill-origin", "plot", "-o", str(g) + "/", str(PCB))
    z = FAB / f"{NAME}-gerbers.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(g.iterdir()):
            if f.suffix != ".pdf":
                zf.write(f, f.name)
    return z


def boms():
    jlc = defaultdict(list)
    full = defaultdict(list)
    for p in design.PARTS:
        if p["bom"] == "none":
            continue
        full[(p["value"], p["fp"].split(":")[1], p["lcsc"], p["mpn"])].append(p["ref"])
        jlc[(p["value"], p["fp"].split(":")[1], p["lcsc"])].append(p["ref"])
    stock_file = FAB / "stock.json"
    stock = json.loads(stock_file.read_text()) if stock_file.exists() else {"date": "", "parts": {}}
    with open(FAB / f"{NAME}-bom-jlc.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (val, fp, lcsc), refs in sorted(jlc.items(), key=lambda kv: natural(sorted(kv[1], key=natural)[0])):
            w.writerow([val, ",".join(sorted(refs, key=natural)), fp, lcsc])
    with open(FAB / f"{NAME}-bom-full.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Qty", "Designator", "Value", "Footprint", "LCSC", "MPN / description", "Side",
                    f"JLC stock {stock['date']}", "JLC library", "Unit price USD"])
        for (val, fp, lcsc, mpn), refs in sorted(full.items(), key=lambda kv: natural(sorted(kv[1], key=natural)[0])):
            s = stock["parts"].get(lcsc) or {}
            side = "Bottom" if any(p["side"] == "B" for p in design.PARTS if p["ref"] in refs) else "Top"
            w.writerow([len(refs), ",".join(sorted(refs, key=natural)), val, fp, lcsc, mpn, side, s.get("stock", ""),
                        s.get("type", ""), s.get("price", "")])
    return jlc


def cpl(jlc):
    tmp = FAB / "pos-all.csv"
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "--use-drill-file-origin",
        "-o", str(tmp), str(PCB))
    refs = {r for rs in jlc.values() for r in rs}
    rows = list(csv.DictReader(open(tmp)))
    with open(FAB / f"{NAME}-cpl-jlc.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in sorted(rows, key=lambda r: natural(r["Ref"])):
            if r["Ref"] in refs:
                w.writerow([r["Ref"], f'{float(r["PosX"]):.3f}mm', f'{float(r["PosY"]):.3f}mm',
                            "Bottom" if r.get("Side", "top").lower().startswith("b") else "Top",
                            f'{float(r["Rot"]) % 360:.1f}'])
    tmp.unlink()
    missing = refs - {r["Ref"] for r in rows}
    if missing:
        raise SystemExit(f"CPL misses {sorted(missing)}")


def main():
    FAB.mkdir(exist_ok=True)
    z = gerbers()
    jlc = boms()
    cpl(jlc)
    run("pcb", "export", "step", "--force", "--subst-models", "--include-tracks", "--include-zones",
        "--user-origin", "100x100mm", "-o", str(FAB / f"{NAME}.step"), str(PCB))
    print("gerbers:", z)
    print("JLC BOM lines:", len(jlc), "placements:", sum(len(v) for v in jlc.values()))


if __name__ == "__main__":
    main()
