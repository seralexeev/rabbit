"""Extract the deck outline from the chassis STEP into the board frame.

Run with the model/ uv venv: model/.venv/bin/python pcb/rabbit-body/gen/extract_outline.py
Board frame: origin at the plate bounding-box centre, +X = robot right, +Y = robot front, mm, top view.
Writes gen/outline.json (segments + mounting holes) and kit_plate.dxf (the whole kit plate, decks 1 and 3);
the board outline.dxf with all its holes is written by fab.py.
"""
import json
import math
from pathlib import Path

import ezdxf
from build123d import Axis, GeomType, import_step

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
STEP = ROOT / "model" / "chassis.step"

PLATE_Z_TOP = 81.12  # top chassis plate (solid 132): 120.5 x 269.9 x 2 mm


def to_board(x, y, cx, cy):
    return (round(-(x - cx), 4), round(-(y - cy), 4))


def segment(edge, cx, cy):
    a = edge.start_point(); b = edge.end_point(); m = edge.position_at(0.5)
    p0, pm, p1 = (to_board(v.X, v.Y, cx, cy) for v in (a, m, b))
    if edge.geom_type == GeomType.LINE:
        return {"type": "line", "start": p0, "end": p1}
    pts = [to_board(edge.position_at(t / 8).X, edge.position_at(t / 8).Y, cx, cy) for t in range(9)]
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    L = math.hypot(x1 - x0, y1 - y0)
    dev = max(abs((x1 - x0) * (y0 - py) - (x0 - px) * (y1 - y0)) / L for px, py in pts) if L > 1e-6 else 1
    if dev < 0.01:
        return {"type": "line", "start": p0, "end": p1}
    return {"type": "arc", "start": p0, "mid": pm, "end": p1}


def main():
    shape = import_step(str(STEP))
    plate = next(s for s in shape.solids()
                 if abs(s.bounding_box().max.Z - PLATE_Z_TOP) < 0.05 and s.bounding_box().size.X > 100)
    bb = plate.bounding_box()
    cx, cy = (bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2
    top = plate.faces().sort_by(Axis.Z)[-1]
    segs = [segment(e, cx, cy) for e in top.outer_wire().edges()]
    holes = []
    for w in top.inner_wires():
        wb = w.bounding_box()
        if len(w.edges()) <= 2 and abs(wb.size.X - wb.size.Y) < 0.05:
            hx, hy = to_board((wb.min.X + wb.max.X) / 2, (wb.min.Y + wb.max.Y) / 2, cx, cy)
            holes.append({"x": hx, "y": hy, "d": round(wb.size.X, 2)})
    # the deck keeps only the holes of the inter-deck standoffs: 4 corner standoffs (50 mm in the kit,
    # M4 clearance 4.3) and the 2 front shoulder standoffs of the steering bracket (M3, 3.2)
    keep = [h for h in holes if (abs(abs(h["x"]) - 38.09) < 0.1 and h["d"] > 4.2)
            or (abs(abs(h["x"]) - 55.26) < 0.2 and abs(h["y"] - 84.95) < 0.3)]
    out = {"frame": "origin = top plate bbox centre; +X robot right; +Y robot front; mm; top view",
           "model_centre": [round(cx, 3), round(cy, 3)], "size": [round(bb.size.X, 3), round(bb.size.Y, 3)],
           "segments": segs, "mounting_holes": sorted(keep, key=lambda h: (h["y"], h["x"])),
           "all_kit_holes": holes}
    (HERE / "outline.json").write_text(json.dumps(out, indent=1))


    # the full kit plate (decks 1 and 3) with every hole and slot, same frame
    kit = ezdxf.new("R2010", setup=True)
    kit.units = ezdxf.units.MM
    ms = kit.modelspace()
    for wire, layer in [(top.outer_wire(), "OUTLINE")] + [(w, "HOLES") for w in top.inner_wires()]:
        pts = []
        for e in wire.edges():
            n = 2 if e.geom_type == GeomType.LINE else 16
            pts += [to_board(e.position_at(t / n).X, e.position_at(t / n).Y, cx, cy) for t in range(n)]
        ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
    kit.saveas(HERE.parent / "kit_plate.dxf")
    print(len(segs), "segments,", len(keep), "mounting holes, size", out["size"])


if __name__ == "__main__":
    main()
