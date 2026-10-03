"""BLDC rear drive in the widened chassis: fit checks, renders and the combined STEP.

    uv run --project ../../model python assembly.py              # checks + renders + drive-assembly.step
    uv run --project ../../model python assembly.py --no-render  # checks only

The chassis is model/chassis.step rebuilt by cad/brackets/assembly.py (3-deck stack, body PCB as deck 2),
with the kit's rear drive removed and the rear wheels moved out by WIDEN (owner: 142 mm between the
bracket inner faces). The motors are envelopes from the makers' drawings; the Faulhaber STEP from
data/cad/makers/ (not redistributable) is used when present. Results: renders/fit_report.json.
"""

import importlib.util
import json
import math
import sys

from build123d import Compound, Pos, export_step

import bracket
import coupling
from bracket import xcyl, zcyl
from geometry import (
    AXLE_Y,
    AXLE_Z,
    BEARING,
    BRACKET_FACE,
    BRACKETS,
    BRG1_IN,
    BRG1_OUT,
    BRG2_IN,
    BRG2_OUT,
    CIRCLIP,
    CX,
    FLANGE_SCREW_ANGLES,
    FLANGE_SCREW_R,
    FLOOR_Z,
    FOOT_BOTTOM,
    FOOT_HOLES,
    GEAR_FACE,
    HALF_GAP,
    HERE,
    MOTOR,
    MOTORS,
    PLATE_BOTTOM,
    PLATE_TOP,
    RENDERS,
    WIDEN,
    box,
    gap_between_motors,
    label_png,
    motor_length,
    motor_rear,
    render,
    to_chassis,
)

spec = importlib.util.spec_from_file_location("mounts_assembly", BRACKETS / "assembly.py")
mounts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mounts)

KIT_REAR_DRIVE = (
    "s015", "s091", "s007", "s130", "s000", "s049", "s063", "s128", "s055", "s058",
    "s104", "s110", "s114", "s124", "s121", "s033",
    "s030", "s031", "s076", "s107", "s008", "s029", "s069", "s133", "s018", "s071", "s103", "s127",
    "s012", "s019", "s032", "s035", "s037", "s048", "s067", "s092", "s093", "s105", "s117", "s131",
)
REAR_WHEELS = {"s027": +1, "s119": -1}
BOTTOM_PLATE = "s016"
REPORT = RENDERS / "fit_report.json"
COLOURS = {
    "bracket": "#8fa8c8",
    "motor_flange": "#c98f4f",
    "stub_axle": "#9e9e9e",
    "inner_spacer": "#555555",
    "oldham_hub": "#d32f2f",
    "oldham_disc": "#f2c94c",
    "bearing": "#e0e0e0",
    "circlip": "#333333",
    "motor": "#2b2b2b",
    "gearhead": "#6d6d6d",
    "screw": "#222222",
}


def motor_envelope(key):
    """Gearhead, motor and encoder as cylinders from the maker's drawing, plus pilot, shoulder and shaft."""
    m = MOTORS[key]
    x = GEAR_FACE
    gear_len = m["segments"][0][1]
    shapes = {"gearhead": xcyl(m["segments"][0][0], x - gear_len, x)}
    body = None
    x -= gear_len
    for d, length in m["segments"][1:]:
        c = xcyl(d, x - length, x)
        body = c if body is None else body + c
        x -= length
    if m["tab"]:
        t = m["tab"]
        rear = GEAR_FACE - motor_length(key)
        body += box(rear, rear + t["len"], -t["w"] / 2, t["w"] / 2, 0, t["r"])
    shapes["motor"] = body
    front = xcyl(m["pilot_d"], GEAR_FACE, GEAR_FACE + m["pilot_h"])
    front += xcyl(m["shoulder_d"], GEAR_FACE + m["pilot_h"], GEAR_FACE + m["pilot_h"] + m["shoulder_h"])
    front += xcyl(m["shaft_d"], GEAR_FACE, GEAR_FACE + m["shaft_len"])
    shapes["gearhead"] += front
    return shapes


def bearings():
    out = {}
    for name, (x0, x1) in {"bearing_1": (BRG1_IN, BRG1_OUT), "bearing_2": (BRG2_IN, BRG2_OUT)}.items():
        out[name] = xcyl(BEARING["D"], x0, x1) - xcyl(BEARING["d"], x0 - 1, x1 + 1)
    x1 = BRG1_IN
    x0 = x1 - CIRCLIP["s"]
    out["circlip"] = xcyl(CIRCLIP["lug_od"], x0, x1) - xcyl(CIRCLIP["groove_d"], x0 - 1, x1 + 1)
    return out


def fasteners(key=MOTOR):
    out = {}
    sc = MOTORS[key]["screws"]
    for i in range(sc["n"]):
        a = math.radians(sc["start_deg"] + i * 360 / sc["n"])
        y, z = sc["pcd"] / 2 * math.cos(a), sc["pcd"] / 2 * math.sin(a)
        head = xcyl(sc["head_d"], BRACKET_FACE, BRACKET_FACE + sc["head_h"], y, z)
        out[f"gearhead_screw_{i}"] = head + xcyl(float(sc["thread"][1:]) * 0.9, GEAR_FACE - 3.0, BRACKET_FACE, y, z)
    for i, (hx, hy) in enumerate(FOOT_HOLES):
        head = zcyl(7.0, PLATE_TOP, PLATE_TOP + 2.2, hx, hy)
        shank = zcyl(4.0, FOOT_BOTTOM - 4.0, PLATE_TOP, hx, hy)
        nut = zcyl(7.9, FOOT_BOTTOM - 5.0, FOOT_BOTTOM, hx, hy) - zcyl(4.0, FOOT_BOTTOM - 6, FOOT_BOTTOM + 1, hx, hy)
        out[f"m4_foot_{i}"] = head + shank + nut
    for i, deg in enumerate(FLANGE_SCREW_ANGLES):
        y, z = FLANGE_SCREW_R * math.cos(math.radians(deg)), FLANGE_SCREW_R * math.sin(math.radians(deg))
        head = xcyl(5.5, GEAR_FACE - 3.0, GEAR_FACE, y, z)
        shank = xcyl(3.0, GEAR_FACE, BRACKET_FACE + 7.0, y, z)
        out[f"m3_flange_{i}"] = head + shank
    return out


def drive_side(key=MOTOR):
    """Every drive part of one side in the local frame: name -> (shape, colour key)."""
    out = {"bracket": (bracket.bracket(), "bracket"), "motor_flange": (bracket.motor_flange(key), "motor_flange")}
    for name, p in coupling.parts(key).items():
        out[name] = (p, name)
    for name, p in bearings().items():
        out[name] = (p, "circlip" if name == "circlip" else "bearing")
    for name, p in fasteners(key).items():
        out[name] = (p, "screw")
    for name, p in motor_envelope(key).items():
        out[name] = (p, name)
    return out


def chassis_widened():
    raw = mounts.chassis()
    out = {}
    for name, s in raw.items():
        if name in KIT_REAR_DRIVE:
            continue
        if name in REAR_WHEELS:
            out[name] = Pos(REAR_WHEELS[name] * WIDEN, 0, 0) * s
        else:
            out[name] = s
    return out


_BOXES = {}


def bounds(shape):
    key = id(shape)
    if key not in _BOXES:
        _BOXES[key] = (shape, shape.bounding_box())
    return _BOXES[key][1]


def bbox_overlap(a, b, margin=0.0):
    A, B = bounds(a), bounds(b)
    return all(lo_a - margin <= hi_b and lo_b - margin <= hi_a for lo_a, hi_a, lo_b, hi_b in zip(A.min, A.max, B.min, B.max))


def overlap_volume(a, b):
    if not bbox_overlap(a, b):
        return 0.0
    try:
        return (a & b).volume
    except Exception:
        return float("nan")


def min_gap(a, b, margin=30.0):
    if not bbox_overlap(a, b, margin):
        return None
    try:
        return round(a.distance_to(b), 2)
    except Exception:
        return None


ALLOWED = {
    frozenset(p)
    for p in (
        ("bracket", "bearing_1"), ("bracket", "bearing_2"), ("stub_axle", "bearing_1"), ("stub_axle", "bearing_2"),
        ("stub_axle", "circlip"), ("stub_axle", "inner_spacer"), ("oldham_hub", "gearhead"), ("motor_flange", "gearhead"),
        ("bracket", "motor_flange"), ("m3_flange_0", "bracket"), ("m3_flange_1", "bracket"), ("m3_flange_2", "bracket"),
        ("m3_flange_0", "motor_flange"), ("m3_flange_1", "motor_flange"), ("m3_flange_2", "motor_flange"),
        ("m4_foot_0", "bracket"), ("m4_foot_1", "bracket"), ("gearhead", "motor"),
    )
} | {frozenset((f"gearhead_screw_{i}", o)) for i in range(6) for o in ("gearhead", "motor_flange")}
ALLOWED_CHASSIS = {("m4_foot_0", BOTTOM_PLATE), ("m4_foot_1", BOTTOM_PLATE)}


def checks(key, chassis_, env, mounts_parts):
    """Interference of the drive (both sides) with the chassis, the PCB, the printed mounts and itself."""
    sides = {s: {n: to_chassis(p, s) for n, (p, _) in drive_side(key).items()} for s in (1, -1)}
    rows = []
    others = {**chassis_, **env, **{k: v[0] for k, v in mounts_parts.items()}}
    for s, parts in sides.items():
        names = list(parts)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if frozenset((a, b)) in ALLOWED:
                    continue
                v = overlap_volume(parts[a], parts[b])
                if v > 0.05 or math.isnan(v):
                    rows.append({"side": s, "a": a, "b": b, "mm3": round(v, 2)})
            for b, o in others.items():
                if (a, b) in ALLOWED_CHASSIS:
                    continue
                v = overlap_volume(parts[a], o)
                if v > 0.05 or math.isnan(v):
                    rows.append({"side": s, "a": a, "b": b, "mm3": round(v, 2)})
    left, right = sides[1], sides[-1]
    motor_l = left["motor"] + left["gearhead"]
    motor_r = right["motor"] + right["gearhead"]
    pcb_parts = {k: v for k, v in env.items() if k.startswith("pcb_")}
    deck1 = chassis_[BOTTOM_PLATE]
    gaps = {
        "motor_to_motor_mm": round(gap_between_motors(key), 2),
        "motor_to_deck1_mm": min_gap(motor_l, deck1),
        "bracket_to_deck1_edge_mm": min_gap(left["bracket"], deck1),
        "motor_flange_to_deck1_mm": min_gap(left["motor_flange"], deck1),
        "bracket_top_to_pcb_mm": min((g for k, v in pcb_parts.items() if (g := min_gap(left["bracket"], v, 15)) is not None), default=None),
        "motor_to_pcb_mm": min((g for k, v in pcb_parts.items() if (g := min_gap(motor_l, v, 15)) is not None), default=None),
        "bracket_to_wheel_mm": min_gap(left["bracket"], chassis_["s027"]),
        "lowest_point_above_floor_mm": round(min(p.bounding_box().min.Z for p in left.values()) - FLOOR_Z, 2),
    }
    return rows, gaps


def screw_check(chassis_):
    from common import plate_holes

    holes = plate_holes(chassis_[BOTTOM_PLATE])
    out = []
    for side in (1, -1):
        for hx, hy in FOOT_HOLES:
            x = CX + side * (HALF_GAP + hx)
            y = AXLE_Y + hy
            hit = next(((round(a, 2), round(b, 2), round(sx, 2)) for a, b, sx, sy in holes if abs(x - a) < 0.3 and abs(y - b) < 1.2), None)
            out.append({"side": side, "screw": [round(x, 2), round(y, 2)], "plate_hole": hit})
    return out


def loads():
    """Wheel load cases on the stub axle, bearing reactions and the Faulhaber/maxon shaft rating for comparison."""
    mass, rear_share, g = 4.5, 0.55, 9.81
    static = mass * g * rear_share / 2
    centre = (8.80 + 37.98) / 2
    b2 = (BRG2_IN + BRG2_OUT) / 2
    b1 = (BRG1_IN + BRG1_OUT) / 2
    span = b2 - b1
    a = centre - b2
    out = {"static_wheel_load_N": round(static, 1), "wheel_centre_from_outer_bearing_mm": round(a, 1), "bearing_span_mm": round(span, 1)}
    for name, fz, fy in (("static", static, 0.0), ("cornering_0.7g", static, 0.7 * static), ("bump_3g_plus_cornering", 3 * static, 0.7 * static), ("bump_5g", 5 * static, 0.7 * static)):
        moment = fz * a + fy * 37.5
        r1 = moment / span
        r2 = fz + r1
        out[name] = {"radial_N": round(fz, 1), "lateral_N": round(fy, 1), "outer_bearing_N": round(r2, 0), "inner_bearing_N": round(r1, 0),
                     "static_safety_s0": round(BEARING["C0_kN"] * 1000 / r2, 2)}
    return out


def renders(key, chassis_, env, mounts_parts):
    items = []
    for name, s in chassis_.items():
        bb = s.bounding_box()
        colour = "#3a3a3a" if (bb.size.Z < 2.5 and bb.size.Y > 100) else "#1c1c1c" if name in REAR_WHEELS or name in mounts.FRONT_WHEELS else "#b8b8b8"
        items.append((s, colour))
    for name, s in env.items():
        items.append((s, "#1b5e20" if name == "pcb_board" else "#d7d7d7" if name.startswith("pcb_") else "#9e9e9e"))
    for s, c in mounts_parts.values():
        items.append((s, "#c9a227"))
    drive = []
    for side in (1, -1):
        for name, (p, ck) in drive_side(key).items():
            drive.append((to_chassis(p, side), COLOURS[ck]))
    RENDERS.mkdir(parents=True, exist_ok=True)
    paths = []
    rear_focus = (CX - 120, CX + 120, AXLE_Y - 70, AXLE_Y + 60, FLOOR_Z, 125)
    paths += render(items + drive, RENDERS / f"assembly_{key}", views=("iso", "top", "rear"), zoom=1.15)
    no_top = [(s, c) for s, c in items if s.bounding_box().min.Z < 70]
    paths += render(no_top + drive, RENDERS / f"rear_{key}", views=("iso_rear", "top", "rear"), focus=rear_focus, zoom=1.3)
    cut = box(-500, 500, AXLE_Y, 500, -500, 500)
    tyres = [(Pos(CX + side * HALF_GAP, AXLE_Y, AXLE_Z) * xcyl(74.9, side * 8.80 if side > 0 else -37.98, side * 37.98 if side > 0 else -8.80)
              - Pos(CX + side * HALF_GAP, AXLE_Y, AXLE_Z) * xcyl(54.0, -60, 60), "#1c1c1c") for side in (1, -1)]
    section = [(s & cut, c) for s, c in [(s, c) for s, c in no_top if s not in [chassis_[k] for k in REAR_WHEELS]] + tyres + drive
               if s.bounding_box().max.Y > AXLE_Y and s.bounding_box().min.Y < AXLE_Y]
    paths += render(section, RENDERS / f"section_{key}", views=("front",), focus=(CX - 120, CX + 120, AXLE_Y - 1, AXLE_Y + 1, FLOOR_Z, 80), zoom=1.25, edges=False)
    local = [(p, COLOURS[ck]) for p, ck in drive_side(key).values()]
    paths += render(local, RENDERS / f"drive_{key}", views=("iso", "iso_rear"), zoom=1.1, edges=True)
    lcut = box(-500, 500, 0, 500, -500, 500)
    paths += render([(p & lcut, c) for p, c in local], RENDERS / f"drive_section_{key}", views=("front",), zoom=1.1, edges=True)
    return paths


def export_assembly(key, chassis_, env):
    children = []
    for side in (1, -1):
        for name, (p, _) in drive_side(key).items():
            s = to_chassis(p, side)
            s.label = f"{'left' if side > 0 else 'right'}_{name}"
            children.append(s)
    deck = chassis_[BOTTOM_PLATE]
    deck.label = "deck1"
    children.append(deck)
    for side in (1, -1):
        tyre = to_chassis(xcyl(74.9, 8.80, 37.98) - xcyl(54.0, 0.0, 40.0), side)
        tyre.label = f"{'left' if side > 0 else 'right'}_rear_tyre_envelope"
        children.append(tyre)
    export_step(Compound(children=children, label="rabbit-bldc-drive"), str(HERE / "drive-assembly.step"))


def main():
    chassis_ = chassis_widened()
    env = {**mounts.pcb(), **mounts.envelopes()}
    mounts_parts = mounts.parts()
    report = {"widen_per_side_mm": round(WIDEN, 2), "screws": screw_check(chassis_), "loads": loads(), "motors": {}}
    for key in MOTORS:
        rows, gaps = checks(key, chassis_, env, mounts_parts)
        report["motors"][key] = {
            "label": MOTORS[key]["label"],
            "length_behind_flange_mm": round(motor_length(key), 1),
            "rear_end_from_centreline_mm": round(HALF_GAP + motor_rear(key), 1),
            "gaps": gaps,
            "interference": rows,
        }
    RENDERS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if "--no-render" not in sys.argv:
        for key in MOTORS:
            for p in renders(key, chassis_, env, mounts_parts):
                print(p)
        export_assembly(MOTOR, chassis_, env)


if __name__ == "__main__":
    main()
