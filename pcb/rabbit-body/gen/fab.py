"""Fabrication outputs for JLCPCB into fab/ (rev B): Gerbers + drill (zip), JLC BOM + CPL (SMT and THT assembly:
JLC solders every part with an LCSC number), full BOM with JLC stock and price (fab/stock.json from gen/stock.py),
outline DXF with all holes, board STEP.

Run with KiCad's Python: gen/fab.py
"""
import csv
import json
import math
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
PRJ = HERE.parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

KC = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
PCB = PRJ / "rabbit-body.kicad_pcb"
FAB = PRJ / "fab"
LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,Edge.Cuts"


def run(*args):
    subprocess.run([KC, *args], check=True, capture_output=True)


def sync_fields():
    """Copy value and LCSC / MPN / BOM fields from design.py into the routed board (no re-route needed)."""
    b = pcbnew.LoadBoard(str(PCB))
    by_ref = {p["ref"]: p for p in design.PARTS}
    for fp in b.GetFootprints():
        p = by_ref.get(fp.GetReference())
        if not p:
            continue
        fp.SetValue(p["value"])
        for key, val in (("LCSC", p["lcsc"]), ("MPN", p["mpn"]), ("BOM", p["bom"])):
            if val:
                fp.SetField(key, val)
                f = fp.GetField(key)
                f.SetVisible(False)
                f.SetLayer(pcbnew.F_Fab)
    pcbnew.SaveBoard(str(PCB), b)
    txt = PCB.read_text()
    PCB.write_text(txt.replace('(paper "A4")', '(paper "A3" portrait)', 1))


def gerbers():
    g = FAB / "gerber"
    if g.exists():
        shutil.rmtree(g)
    g.mkdir(parents=True)
    run("pcb", "export", "gerbers", "--layers", LAYERS, "--subtract-soldermask", "--use-drill-file-origin",
        "-o", str(g) + "/", str(PCB))
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th", "--generate-map",
        "--map-format", "pdf", "--drill-origin", "absolute", "-o", str(g) + "/", str(PCB))
    z = FAB / f"rabbit-body-rev{design.REV}-gerbers.zip"
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
        key = (p["value"], p["fp"].split(":")[1], p["lcsc"] or "", p["mpn"], p["bom"])
        full[key].append(p["ref"])
        if p["bom"] in ("smt", "tht"):
            jlc[(p["value"], p["fp"].split(":")[1], p["lcsc"])].append(p["ref"])
    stock_file = FAB / "stock.json"
    stock = json.loads(stock_file.read_text()) if stock_file.exists() else {"date": "", "parts": {}}
    rev = design.REV
    with open(FAB / f"rabbit-body-rev{rev}-bom-jlc.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (val, fp, lcsc), refs in sorted(jlc.items()):
            w.writerow([val, ",".join(sorted(refs, key=natural)), fp, lcsc])
    with open(FAB / f"rabbit-body-rev{rev}-bom-full.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Qty", "Designator", "Value", "Footprint", "LCSC", "MPN / description", "Assembly",
                    f"JLC stock {stock['date']}", "JLC library", "Unit price USD"])
        for (val, fp, lcsc, mpn, kind), refs in sorted(full.items(), key=lambda kv: (kv[0][4], kv[0][0])):
            how = {"smt": "JLCPCB SMT", "tht": "JLCPCB THT", "hand": "hand-solder",
                   "module": "owner's module, on standoffs"}[kind]
            s = stock["parts"].get(lcsc) or {}
            w.writerow([len(refs), ",".join(sorted(refs, key=natural)), val, fp, lcsc, mpn, how, s.get("stock", ""),
                        s.get("type", ""), s.get("price", "")])
    return jlc


def natural(ref):
    import re
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def cpl(jlc):
    tmp = FAB / "pos-all.csv"
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "front", "--use-drill-file-origin",
        "-o", str(tmp), str(PCB))
    smt_refs = {r for refs in jlc.values() for r in refs}
    rows = list(csv.DictReader(open(tmp)))
    with open(FAB / f"rabbit-body-rev{design.REV}-cpl-jlc.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in rows:
            if r["Ref"] in smt_refs:
                w.writerow([r["Ref"], f'{float(r["PosX"]):.3f}mm', f'{float(r["PosY"]):.3f}mm', "Top",
                            f'{float(r["Rot"]):.1f}'])
    tmp.unlink()
    missing = smt_refs - {r["Ref"] for r in rows}
    if missing:
        raise SystemExit(f"CPL misses {sorted(missing)}")


def _arc(start, mid, end):
    (ax, ay), (bx, by), (cx, cy) = start, mid, end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
    uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a0, am, a1 = (math.degrees(math.atan2(y - uy, x - ux)) % 360 for x, y in (start, mid, end))
    if (am - a0) % 360 > (a1 - a0) % 360:   # clockwise from start to end: swap to keep DXF arcs CCW
        a0, a1 = a1, a0
    return ux, uy, r, a0, a1


def outline_dxf():
    """R12 DXF in the board frame (mm): layer OUTLINE = edge + cut-outs, HOLES = every drilled
    mechanical hole >= 2 mm (deck standoffs, Pi, RoboClaw, module mounting holes)."""
    ents = []
    data = json.loads((HERE / "outline.json").read_text())
    for sgm in data["segments"]:
        if sgm["type"] == "line":
            ents.append(("LINE", "OUTLINE", sgm["start"], sgm["end"]))
        else:
            ents.append(("ARC", "OUTLINE", *_arc(sgm["start"], sgm["mid"], sgm["end"])))
    for poly in getattr(design, "CUTOUTS", []):
        for a, c in zip(poly, poly[1:] + poly[:1]):
            ents.append(("LINE", "OUTLINE", a, c))
    b = pcbnew.LoadBoard(str(PCB))
    holes = []
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            d = pcbnew.ToMM(pad.GetDrillSize().x)
            if d >= 2.0 and pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                x = pcbnew.ToMM(pad.GetPosition().x) - 150
                y = 150 - pcbnew.ToMM(pad.GetPosition().y)
                holes.append((fp.GetReference(), round(x, 3), round(y, 3), round(d, 2)))
                ents.append(("CIRCLE", "HOLES", (x, y), d / 2))
    out = ["0", "SECTION", "2", "ENTITIES"]
    for e in ents:
        if e[0] == "LINE":
            (x0, y0), (x1, y1) = e[2], e[3]
            out += ["0", "LINE", "8", e[1], "10", f"{x0:.4f}", "20", f"{y0:.4f}", "11", f"{x1:.4f}", "21", f"{y1:.4f}"]
        elif e[0] == "ARC":
            _, lay, ux, uy, r, a0, a1 = e
            out += ["0", "ARC", "8", lay, "10", f"{ux:.4f}", "20", f"{uy:.4f}", "40", f"{r:.4f}", "50", f"{a0:.4f}",
                    "51", f"{a1:.4f}"]
        else:
            (x, y), r = e[2], e[3]
            out += ["0", "CIRCLE", "8", e[1], "10", f"{x:.4f}", "20", f"{y:.4f}", "40", f"{r:.4f}"]
    out += ["0", "ENDSEC", "0", "EOF"]
    (PRJ / "outline.dxf").write_text("\n".join(out) + "\n")
    (FAB / "holes.json").write_text(json.dumps(holes, indent=1))
    return holes


def main():
    FAB.mkdir(exist_ok=True)
    sync_fields()
    z = gerbers()
    for old in ("rabbit-body-gerbers.zip", "rabbit-body-bom-jlc.csv", "rabbit-body-cpl-jlc.csv", "rabbit-body-bom-full.csv"):
        (FAB / old).unlink(missing_ok=True)             # rev A names (rev A stays in git)
    smt = boms()
    cpl(smt)
    print("outline.dxf holes:", len(outline_dxf()))
    run("pcb", "export", "step", "--force", "--subst-models", "--user-origin", "150x150mm",
        "-o", str(PRJ / "rabbit-body.step"), str(PCB))
    print("gerbers:", z)
    print("JLC BOM lines:", len(smt), "placements:", sum(len(v) for v in smt.values()))


if __name__ == "__main__":
    main()
