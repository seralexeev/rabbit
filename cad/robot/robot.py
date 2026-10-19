"""The whole robot as one named assembly: the kit model plus our changes.

Changes to the kit so far:
- rear hubs get their Ø6 bore (the kit model's hub is solid apart from the set-screw hole).
- rear drive (default): the kit's Hiwonder JGB37-520R30-12, completed with its gearbox and output shaft,
  which the kit model leaves out. RABBIT_DRIVE=maxon puts the maxon ECX FLAT 22 L + GPX 22 UP + ENX 22 MILE
  on a 4 mm adapter plate in each bracket instead.
- third floor: a second copy of the kit's upper plate on the same 50 mm standoffs, so the decks are
  52 mm apart bottom to bottom (owner, 2026-10-10); the kit's top screws move up to deck 3.
- rear drive widened: motor brackets 142 mm apart instead of 120.6 (owner, M10 -> C16), so every rear
  drive part (motor, rear hub, rear wheel and their screws) moves 10.7 mm outward per side.

Use it through run.py (build, render, measure, check, export).
"""

import json
import os

from build123d import Box, Color, Compound, Cylinder, Pos, Rot, Vector, export_gltf, export_step

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "parts"))

import body_pcb  # noqa: E402
import jgb37  # noqa: E402
import maxon  # noqa: E402
import tof_mount  # noqa: E402
import zed  # noqa: E402
from chassis import CX, REAR_AXLE_Y, boxes, cache_dir, named  # noqa: E402
from mesh import OUT, shape_key  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
KIT_HALF_GAP = 60.30
HALF_GAP = 71.0
WIDEN = HALF_GAP - KIT_HALF_GAP

COLOURS = {
    "deck": "#c9a227", "wheel": "#2b2b2b", "hub": "#ff9800", "motor": "#1e88e5", "steering": "#43a047",
    "standoff": "#8e24aa", "fastener": "#9e9e9e", "other": "#e53935", "new": "#e91e63",
    "pcb": "#1b5e20", "module": "#00838f", "tof": "#f4511e",
}
PROXY_GROUPS = ("fastener", "wheel")

AXLE_Z = 44.457
BORE_Y = 83.156  # centre of the kit bracket's Ø15 hole, measured on motor_bracket_left
FLOOR_PITCH = 52.0
DECK2_BOTTOM = 79.12
STANDOFF_TOP_SCREWS_Z = 75.0
BRACKET_T = 3.0
DRIVE = os.environ.get("RABBIT_DRIVE", "kit")
DECK2 = os.environ.get("RABBIT_DECK2", "pcb")  # "pcb": the body board replaces the kit's deck 2 plate; "plate": kit plate
KIT_MOTOR_PARTS = ("motor_can_", "motor_encoder_", "motor_connector_")
DRIVES = {
    "maxon": {"label": "maxon ECX FLAT 22 L HT 18 V + GPX 22 UP 2-stage + ENX 22 MILE, modelled from the catalogue"},
}


def rear_drive(name, centre):
    """True for parts that ride with the rear motor brackets."""
    if name.startswith(("motor_", "wheel_rear", "wheel_hub_rear")):
        return True
    if not name.startswith("fastener"):
        return False
    x, y, z = centre
    return abs(y - REAR_AXLE_Y) < 25 and z > 29.2 and abs(x - CX) > 18


WHEEL_SOCKET_D = 14.0  # free bore of the tyre envelope: the 12 mm hex hub and the shaft sit inside


def proxy(lo, hi, bore=0.0):
    """A plain cylinder in a part's bounding box: screw threads (~1 MB each) and the tyre tread
    (~25 MB per wheel in STEP) make up most of the kit model."""
    size = dict(zip("XYZ", (h - l for l, h in zip(lo, hi))))
    a, b, c = sorted(size, key=size.get)
    axis, d = (a, size[c]) if size[c] - size[b] < size[b] - size[a] else (c, size[a])
    turn = {"X": Rot(0, 90, 0), "Y": Rot(90, 0, 0), "Z": Rot(0, 0, 0)}[axis]
    body = Cylinder(d / 2, size[axis])
    if bore:
        body -= Cylinder(bore / 2, size[axis] + 1)
    return Pos(Vector(*((l + h) / 2 for l, h in zip(lo, hi)))) * (turn * body)


def kit_parts(light):
    kit = cache_dir().name
    box = boxes()
    out = {}
    for name, (solid, group, kit_id) in named().items():
        lo, hi = box[name]
        if removed(name, [(l + h) / 2 for l, h in zip(lo, hi)]):
            continue
        centre = [(l + h) / 2 for l, h in zip(lo, hi)]
        dx = 0.0
        if rear_drive(name, centre):
            dx = WIDEN if centre[0] > CX else -WIDEN
            solid = Pos(dx, 0, 0) * solid
            lo, hi = [lo[0] + dx, lo[1], lo[2]], [hi[0] + dx, hi[1], hi[2]]
        dz = 0.0
        if group == "fastener" and lo[2] > STANDOFF_TOP_SCREWS_Z and near_standoff(centre, box):
            dz = FLOOR_PITCH
            solid = Pos(0, 0, dz) * solid
            lo, hi = [lo[0], lo[1], lo[2] + dz], [hi[0], hi[1], hi[2] + dz]
        if name.startswith("wheel_hub_rear"):
            mid = [(l + h) / 2 for l, h in zip(lo, hi)]
            solid = solid - Pos(*mid) * (Rot(0, 90, 0) * Cylinder(HUB_BORE_D / 2, hi[0] - lo[0] + 1))
        if light and group in PROXY_GROUPS:
            shape = proxy(lo, hi, WHEEL_SOCKET_D if group == "wheel" else 0.0)
            key = shape_key(shape)
        else:
            shape, key = solid, f"{kit}|{kit_id}|{dx}|{dz}|bore2" if name.startswith("wheel_hub_rear") else f"{kit}|{kit_id}|{dx}|{dz}"
        out[name] = {"shape": shape, "group": group, "colour": COLOURS[group], "key": key, "kit": True, "box": (lo, hi)}
    for name, (solid, group, kit_id) in named().items():
        if name == "deck_2" or name.startswith("standoff_"):
            copy = "deck_3" if name == "deck_2" else f"{name}_upper"
            lo, hi = box[name]
            out[copy] = {"shape": Pos(0, 0, FLOOR_PITCH) * solid, "group": group, "colour": COLOURS[group],
                         "key": f"{kit}|{kit_id}|0|{FLOOR_PITCH}", "kit": True,
                         "box": ([lo[0], lo[1], lo[2] + FLOOR_PITCH], [hi[0], hi[1], hi[2] + FLOOR_PITCH])}
    return out


def near_standoff(centre, box, tol=4.0):
    for n, (lo, hi) in box.items():
        if n.startswith("standoff_") and abs(centre[0] - (lo[0] + hi[0]) / 2) < tol and abs(centre[1] - (lo[1] + hi[1]) / 2) < tol:
            return True
    return False


def maxon_drives():
    """Both maxon drives with their adapter plates and gearhead screws, in the chassis frame.
    Local frame of parts/maxon.py: origin on the gearhead flange face = the plate's inner face,
    +X outboard; the plate's outer face lies on the bracket's inner face (CX ± HALF_GAP)."""
    out = {}
    local = {**{k: v for k, v in maxon.drive().items()}, "plate": maxon.adapter_plate(),
             "plate_screws": maxon.gearhead_screw_heads()}
    for side, sign in (("left", 1), ("right", -1)):
        loc = Pos(CX + sign * (HALF_GAP - maxon.PLATE_T), BORE_Y, AXLE_Z) * (Rot(0, 0, 0) if sign > 0 else Rot(0, 0, 180))
        for k, shape in local.items():
            group = "fastener" if k == "plate_screws" else "new"
            out[f"maxon_{k}_{side}"] = (loc * shape, group)
    return out


def jgb37_gearboxes():
    """The kit motors' missing 30:1 gearboxes and output shafts (Hiwonder JGB37-520R30-12 drawing),
    face on each bracket's inner face, output on the bracket's Ø15 hole."""
    out = {}
    local = {"gearbox": jgb37.gearbox(), "shaft": jgb37.output_shaft()}
    for side, sign in (("left", 1), ("right", -1)):
        loc = Pos(CX + sign * HALF_GAP, BORE_Y, AXLE_Z) * (Rot(0, 0, 0) if sign > 0 else Rot(0, 0, 180))
        for k, shape in local.items():
            out[f"motor_{k}_{side}"] = (loc * shape, "motor")
    return out


def new_parts():
    """Our own parts, {name: (shape, group)}. Add designs here as they come."""
    out = {}
    if DRIVE == "maxon":
        out.update(maxon_drives())
    else:
        out.update(jgb37_gearboxes())
    if DECK2 == "pcb":
        loc = body_pcb.to_chassis(DECK2_BOTTOM)
        out["body_pcb"] = (loc * body_pcb.board(), "pcb")
        out["raspberry_pi"] = (loc * body_pcb.raspberry_pi(), "module")
        poses = json.loads((REPO / "pcb" / "rabbit-body-c" / "gen" / "tof.json").read_text())
        # ZED 2i on 5 mm M3 standoffs on top of deck 2, centred, front face on the board's front edge (owner, 2026-10-11)
        front_y = max(seg_y for seg in json.loads(body_pcb.OUTLINE.read_text())["segments"]
                      for seg_y in (seg["start"][1], seg["end"][1]))
        at = loc * Pos(0, front_y - zed.DEPTH / 2, body_pcb.THICKNESS)
        out["zed_2i"] = (at * Pos(0, 0, zed.STANDOFF_H) * zed.camera(), "module")
        out["zed_standoffs"] = (at * zed.standoffs(), "standoff")
        bracket, carrier = tof_mount.bracket(), tof_mount.carrier()
        for p in poses["sensors"]:
            at = loc * tof_mount.placement(p["X"], p["Y"], p["yaw"])
            out[f"tof_bracket_{p['name']}"] = (at * bracket, "tof")
            out[f"tof_carrier_{p['name']}"] = (at * carrier, "tof")
    return out


ALLOWED_CONTACTS = {
    ("motor_gearbox_left", "motor_can_left"): "the motor's front pilot sits in the gearbox",
    ("motor_gearbox_right", "motor_can_right"): "the motor's front pilot sits in the gearbox",
    ("motor_shaft_left", "fastener_p114"): "hub M4 set screw on the shaft flat",
    ("motor_shaft_right", "fastener_p113"): "hub M4 set screw on the shaft flat",
    ("motor_shaft_left", "wheel_hub_rear_left"): "kit model: the hub sits 0.04 mm above the bracket bore centre",
    ("motor_shaft_right", "wheel_hub_rear_right"): "kit model: the hub sits 0.04 mm above the bracket bore centre",
    ("maxon_gearhead_left", "wheel_hub_rear_left"): "kit model: the hub sits 0.04 mm above the bracket bore centre (2.4 mm3 crescent)",
    ("maxon_gearhead_right", "wheel_hub_rear_right"): "kit model: the hub sits 0.04 mm above the bracket bore centre (2.4 mm3 crescent)",
    ("maxon_gearhead_left", "fastener_p114"): "hub M4 set screw on the shaft flat (maxon flat 5.5 vs kit 5.4)",
    ("maxon_gearhead_right", "fastener_p113"): "hub M4 set screw on the shaft flat (maxon flat 5.5 vs kit 5.4)",
}
HUB_BORE_D = 6.0


def removed(name, centre):
    """Kit parts that a design replaces: deck 2 when the body board takes its place; with the maxon drive,
    the kit motor and the two bracket screws under the axle (their holes sit 1 mm from the pilot bore)."""
    if name == "deck_2" and DECK2 == "pcb":
        return True
    if DRIVE not in DRIVES:
        return False
    if name.startswith(KIT_MOTOR_PARTS):
        return True
    x, y, z = centre
    return name.startswith("fastener") and abs(y - REAR_AXLE_Y) < 12 and AXLE_Z - 12 < z < AXLE_Z and 55 < abs(x - CX) < 75


def build(light=True):
    """{name: {"shape", "group", "colour", "key"}} in the chassis frame."""
    parts = kit_parts(light)
    for name, (shape, group) in new_parts().items():
        b = shape.bounding_box()
        parts[name] = {"shape": shape, "group": group, "colour": COLOURS.get(group, COLOURS["new"]), "key": shape_key(shape),
                       "box": ([b.min.X, b.min.Y, b.min.Z], [b.max.X, b.max.Y, b.max.Z])}
    return parts


def export_exact():
    """data/cad/robot/robot.step and robot_exact.glb with every thread and tread (slow, ~2 min)."""
    children = []
    for name, p in build(light=False).items():
        s = p["shape"]
        s.label, s.color = name, Color(p["colour"])
        children.append(s)
    a = Compound(children=children, label="rabbit")
    export_step(a, str(OUT / "robot.step"))
    export_gltf(a, str(OUT / "robot_exact.glb"), binary=True, linear_deflection=0.2, angular_deflection=0.4)
    return OUT / "robot.step"
