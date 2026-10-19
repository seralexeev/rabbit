"""Hiwonder Ackermann kit (model/chassis.step) as named parts.

The STEP holds 134 solids labelled "Part_1".."Part_134" by the kit's CAD. Those labels are the stable
ids; classify() gives each one a meaningful name from its size, volume and place, so assemblies and
agents can say "deck_1" or "wheel_rear_left" instead of "Part_28".
Frame: model/chassis.step, mm; forward is -Y, the robot's left is +X, up is +Z.
"""

import hashlib
import json
import sys
from pathlib import Path

import build123d
from build123d import export_brep, import_brep, import_step

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CHASSIS_STEP = REPO / "model" / "chassis.step"
CACHE_ROOT = REPO / "data" / "cad" / "kit"
MANIFEST = HERE / "chassis_parts.json"

CX = 2.48
FRONT_AXLE_Y = -88.4
REAR_AXLE_Y = 83.15
WHEEL_VOLUME = 21_990
FASTENER_VOLUME = 130


def cache_dir():
    digest = hashlib.sha256(CHASSIS_STEP.read_bytes()).hexdigest()[:12]
    return CACHE_ROOT / f"{digest}-b123d-{build123d.__version__}"


def raw_solids():
    """{"Part_28": solid, ...} keyed by the STEP labels. The import (~1 min) is cached as BREP under
    data/cad/kit/<step hash>-<build123d version>/, so a new STEP or library rebuilds it."""
    cache = cache_dir()
    order = cache / "order.json"
    if not order.exists():
        cache.mkdir(parents=True, exist_ok=True)
        labels = []
        for child in import_step(str(CHASSIS_STEP)).children:
            export_brep(child, str(cache / f"{child.label}.brep"))
            labels.append(child.label)
        order.write_text(json.dumps(labels))
    return {label: import_brep(str(cache / f"{label}.brep")) for label in json.loads(order.read_text())}


def side(x):
    return "left" if x > CX else "right"


def end(y):
    return "front" if y < 0 else "rear"


def classify(sid, solid):
    """(name, group) for one kit solid."""
    bb = solid.bounding_box()
    c, s, v = bb.center(), bb.size, solid.volume
    dims = sorted((s.X, s.Y, s.Z))
    if s.Z < 2.5 and s.Y > 200:
        return ("deck_1" if c.Z < 50 else "deck_2"), "deck"
    if abs(v - WHEEL_VOLUME) < 50:
        return f"wheel_{end(c.Y)}_{side(c.X)}", "wheel"
    rear = abs(c.Y - REAR_AXLE_Y) < 12
    if rear and dims[1] > 32 and dims[0] > 25 and v > 15_000:
        return f"motor_can_{side(c.X)}", "motor"
    if rear and abs(s.X - 12.4) < 0.5:
        return f"motor_encoder_cap_{side(c.X)}", "motor"
    if rear and abs(s.X - 1.6) < 0.2:
        return f"motor_encoder_pcb_{side(c.X)}", "motor"
    if rear and abs(s.X - 21.9) < 0.5 and s.Z > 40:
        return f"motor_bracket_{side(c.X)}", "motor"
    if abs(s.X - 18) < 0.5 and abs(s.Z - 12) < 0.5 and dims[1] > 13:
        return f"wheel_hub_{end(c.Y)}_{side(c.X)}", "hub"
    if abs(s.X - 21.2) < 0.5 and abs(s.Y - 9) < 0.5:
        return f"front_stub_axle_{side(c.X)}", "hub"
    if abs(s.X - 4) < 0.3 and abs(s.Y - 10) < 0.3 and abs(s.Z - 10) < 0.3:
        return f"wheel_bearing_{sid}", "hub"
    if rear and abs(s.Z - 16) < 0.5 and dims[0] < 6:
        return f"motor_connector_{side(c.X)}", "motor"
    if abs(s.Z - 50) < 0.5 and dims[0] < 7:
        return f"standoff_{end(c.Y)}_{side(c.X)}", "standoff"
    if abs(s.Z - 23) < 0.5 and dims[0] < 7:
        return f"steering_post_{side(c.X)}", "steering"
    if v > 10_000 and abs(c.Y + 99.8) < 2:
        return "servo", "steering"
    if v > 4_000 and c.Y < -60:
        return f"steering_{sid}", "steering"
    if c.Y < -55 and v > FASTENER_VOLUME:
        return f"steering_{sid}", "steering"
    if v <= FASTENER_VOLUME:
        return f"fastener_{sid}", "fastener"
    return f"part_{sid}", "other"


def classified():
    """{name: (solid, group, kit_id)} from the geometric rules (slow: ~25 s, volumes of threaded screws)."""
    out = {}
    for sid, solid in raw_solids().items():
        name, group = classify(sid, solid)
        name = name.replace("_Part_", "_p")
        if name in out:
            name = f"{name}_{sid}"
        out[name] = (solid, group, sid)
    return out


def boxes():
    """{name: (min xyz, max xyz)} of the kit parts as committed in chassis_parts.json (exact boxes are slow on threads)."""
    return {r["name"]: (r["min"], r["max"]) for r in json.loads(MANIFEST.read_text())}


def named():
    """{name: (solid, group, kit_id)} from the committed map chassis_parts.json (<1 s)."""
    raw = raw_solids()
    return {r["name"]: (raw[r["kit_id"]], r["group"], r["kit_id"]) for r in json.loads(MANIFEST.read_text())}


def write_manifest(parts):
    rows = []
    for name, (solid, group, sid) in sorted(parts.items()):
        bb = solid.bounding_box()
        rows.append({
            "name": name,
            "group": group,
            "kit_id": sid,
            "volume_mm3": round(solid.volume, 1),
            "min": [round(v, 2) for v in (bb.min.X, bb.min.Y, bb.min.Z)],
            "max": [round(v, 2) for v in (bb.max.X, bb.max.Y, bb.max.Z)],
        })
    MANIFEST.write_text(json.dumps(rows, indent=1) + "\n")
    return rows


if __name__ == "__main__":
    rows = write_manifest(classified())
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r["name"])
    for g, names in sorted(groups.items()):
        shown = [n for n in names if not n.startswith("fastener")][:12]
        print(f"{g:9} {len(names):3}  {' '.join(shown)}", file=sys.stderr)
