"""Rabbit 2.0 mounts on the chassis: fit checks, renders and the combined STEP.

Run from cad/brackets with the model/ uv project:
    uv run --project ../../model python assembly.py
The first run imports model/chassis.step (~1 min) and caches it under data/cad/chassis/.

Real robot vs model/chassis.step: the kit standoffs are 50 mm, the robot's are longer, so the
top plate is lifted by TOP_LIFT (top face 122 mm above the floor, from the ZED height). The ZED,
the battery and its V-mount plate are boxes (estimates, see README "Measure before printing").
"""

import json
import math
import sys

from build123d import (
    import_step,
    Axis,
    Compound,
    Polyline,
    Pos,
    export_step,
    revolve,
    make_face,
)

from common import (
    BATTERY_CENTER_Y,
    BATTERY_SIZE,
    BOTTOM_PLATE_TOP,
    CAM3_HFOV,
    CAM3_VFOV,
    CX,
    FRONT_WHEEL_Z,
    HERE,
    KINGPINS,
    KINGPIN_TO_WHEEL,
    PART_COLOURS,
    RENDERS,
    STEER_LOCK_CHECK,
    STEER_LOCK_DESIGN,
    TOF_HFOV,
    TOF_VFOV,
    TOP_LIFT,
    TOP_PLATE_TOP,
    VPLATE_SIZE,
    ZED_HFOV,
    ZED_SIZE,
    ZED_BACK_Y,
    VPLATE_Y,
    DECK2_BOTTOM,
    DECK3_BOTTOM,
    PCB_STEP,
    PCB_T,
    pcb_location,
    ZED_VFOV,
    box,
    cyl,
    frustum,
    h,
    label_png,
    load_chassis,
    plate_holes,
    render,
    wheel_envelope,
    z_at,
)
import bumper
import cable_clip
import cap_clamp
import pcb_edge_comb
import slot_grommet
import xt60_strain_relief
import zed_grommet
import lidar_mast
import power_button_panel
import rear_camera_mount
import tof_pair

TOP_SOLIDS_ABOVE = 75.0
KIT_STANDOFFS = ("s079", "s074", "s061", "s113")
STEERING_POSTS = ("s087", "s070")
STEERING_POST_SCREWS = ("s062", "s022", "s111", "s088")
FRONT_WHEELS = ("s044", "s116")
REAR_WHEELS = ("s119", "s027")
BOTTOM_PLATE, TOP_PLATE = "s016", "s132"
REPORT = HERE / "renders" / "fit_report.json"
STEP_MIN_VOLUME = 1000.0


def chassis():
    """The kit model rebuilt as the 3-deck stack: 45 mm brass columns deck 1 -> PCB -> deck 3,
    deck 3 lifted, the steering-bracket posts cut to 18 mm under the PCB."""
    raw = load_chassis()
    out = {}
    for name, s in raw.items():
        bb = s.bounding_box()
        if name in KIT_STANDOFFS:
            x, y = bb.center().X, bb.center().Y
            out[f"{name}_1_2"] = box(x - 3, x + 3, y - 3.45, y + 3.45, BOTTOM_PLATE_TOP, DECK2_BOTTOM)
            out[f"{name}_2_3"] = box(x - 3, x + 3, y - 3.45, y + 3.45, DECK2_BOTTOM + PCB_T, DECK3_BOTTOM)
        elif name in STEERING_POSTS:
            out[name] = box(bb.min.X, bb.max.X, bb.min.Y, bb.max.Y, bb.min.Z, DECK2_BOTTOM)
        elif name in STEERING_POST_SCREWS:
            continue
        elif bb.min.Z > TOP_SOLIDS_ABOVE:
            out[name] = Pos(0, 0, TOP_LIFT) * s
        else:
            out[name] = s
    return out


def pcb():
    """Deck 2: pcb/rabbit-body/rabbit-body.step (board + components) placed in the chassis frame."""
    loc = pcb_location()
    out = {}
    for i, s in enumerate(import_step(str(PCB_STEP)).solids()):
        bb = s.bounding_box()
        name = "pcb_board" if bb.size.X > 100 else f"pcb_{i:03d}"
        out[name] = loc * s
    return out


def envelopes():
    zed = box(CX - ZED_SIZE[0] / 2, CX + ZED_SIZE[0] / 2, ZED_BACK_Y - ZED_SIZE[1], ZED_BACK_Y, TOP_PLATE_TOP, TOP_PLATE_TOP + ZED_SIZE[2])
    vx, vy, vz = VPLATE_SIZE
    vplate = box(CX - vx / 2, CX + vx / 2, VPLATE_Y[0], VPLATE_Y[1], TOP_PLATE_TOP, TOP_PLATE_TOP + vz)
    bx, by, bz = BATTERY_SIZE
    battery = box(
        CX - bx / 2, CX + bx / 2, BATTERY_CENTER_Y - by / 2, BATTERY_CENTER_Y + by / 2, TOP_PLATE_TOP + vz, TOP_PLATE_TOP + vz + bz
    )
    return {"zed_envelope": zed, "vmount_plate_envelope": vplate, "battery_envelope": battery}


def parts():
    """name -> (printed shape installed, colour key)."""
    out = {}
    for end in ("front", "rear"):
        p, _ = bumper.build(end)
        out[f"bumper_{end}"] = (bumper.installed(end, p), "bumper")
        out[f"tof_pair_{end}"] = (bumper.tof_location(end) * tof_pair.build(), "tof")
    out["lidar_mast"] = (lidar_mast.installed(lidar_mast.build()), "mast")
    out["power_button_panel"] = (power_button_panel.installed(power_button_panel.build()), "button")
    out["rear_camera_mount"] = (rear_camera_mount.installed(rear_camera_mount.build()), "camera")
    for end in ("front", "rear"):
        out[f"pcb_comb_{end}"] = (pcb_edge_comb.installed(end, pcb_edge_comb.build(end)), "deck")
    out["xt60_strain_relief"] = (xt60_strain_relief.installed(xt60_strain_relief.build()), "deck")
    out["cap_clamp"] = (cap_clamp.installed(cap_clamp.build()), "deck")
    out["zed_grommet"] = (zed_grommet.installed(zed_grommet.build()), "clip")
    for i in range(2):
        out[f"slot_grommet_{i}"] = (slot_grommet.installed(slot_grommet.build(), i), "clip")
    return out


def hardware():
    out = {}
    for end in ("front", "rear"):
        out[f"tof_boards_{end}"] = bumper.tof_location(end) * tof_pair.boards()
        for i, s in enumerate(bumper.switches(end)):
            out[f"d2f_{end}_{i}"] = s
    out["rplidar_c1"] = lidar_mast.installed(lidar_mast.lidar_solid())
    out["power_button"] = power_button_panel.installed(power_button_panel.button_solid())
    out["camera_module_3_wide"] = rear_camera_mount.installed(rear_camera_mount.camera_solid())
    return out


def bbox_overlap(a, b, margin=0.0):
    A, B = a.bounding_box(), b.bounding_box()
    return (
        A.min.X - margin <= B.max.X
        and B.min.X - margin <= A.max.X
        and A.min.Y - margin <= B.max.Y
        and B.min.Y - margin <= A.max.Y
        and A.min.Z - margin <= B.max.Z
        and B.min.Z - margin <= A.max.Z
    )


def overlap_volume(a, b):
    if not bbox_overlap(a, b):
        return 0.0
    try:
        return (a & b).volume
    except Exception:
        return float("nan")


def interference(parts_, hardware_, chassis_, env):
    """Volume of every overlap between a printed part (with its hardware) and anything else."""
    others = {**chassis_, **env}
    rows = []
    allowed = {
        ("tof_pair_front", "tof_boards_front"),
        ("tof_pair_rear", "tof_boards_rear"),
    }
    items = {**{k: v[0] for k, v in parts_.items()}, **hardware_}
    names = list(items)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if (a, b) in allowed or (b, a) in allowed:
                continue
            v = overlap_volume(items[a], items[b])
            if v > 0.5 or math.isnan(v):
                rows.append((a, b, round(v, 2)))
        for b, s in others.items():
            v = overlap_volume(items[a], s)
            if v > 0.5 or math.isnan(v):
                rows.append((a, b, round(v, 2)))
    return rows


def min_distance(a, b):
    try:
        return a.distance_to(b)
    except Exception:
        return float("nan")


def steering_sweep(parts_, hardware_):
    """Smallest gap between the steered front tyres (+-lock) and the front parts, bar at rest and pushed."""
    _, moving = bumper.build("front")
    pushed = bumper.installed("front", Pos(0, bumper.TRAVEL, 0) * moving)
    targets = {
        "bumper_front": parts_["bumper_front"][0],
        "bumper_front_bar_pushed": pushed,
        "tof_pair_front": parts_["tof_pair_front"][0],
        "d2f_front": hardware_["d2f_front_0"] + hardware_["d2f_front_1"],
    }
    wheel_centres = [
        (KINGPINS[0][0] + KINGPIN_TO_WHEEL, KINGPINS[0][1], FRONT_WHEEL_Z),
        (KINGPINS[1][0] - KINGPIN_TO_WHEEL, KINGPINS[1][1], FRONT_WHEEL_Z),
    ]
    result = {}
    for limit in (STEER_LOCK_DESIGN, STEER_LOCK_CHECK):
        worst = {k: (float("inf"), None) for k in targets}
        angle = -limit
        while angle <= limit + 1e-6:
            for centre, pivot in zip(wheel_centres, KINGPINS):
                w = wheel_envelope(centre, angle, pivot)
                for k, t in targets.items():
                    d = min_distance(w, t)
                    if d < worst[k][0]:
                        worst[k] = (d, angle)
            angle += 2.5
        result[f"+-{limit:.0f}deg"] = {k: {"min_gap_mm": round(v[0], 2), "at_deg": v[1]} for k, v in worst.items()}
    reach = []
    for angle in (STEER_LOCK_DESIGN, STEER_LOCK_CHECK):
        best = 0.0
        for a in (-angle, angle):
            w = wheel_envelope((KINGPINS[0][0] + KINGPIN_TO_WHEEL, KINGPINS[0][1], FRONT_WHEEL_Z), a, KINGPINS[0])
            best = min(best, w.bounding_box().min.Y)
        reach.append({"lock_deg": angle, "tyre_front_y": round(best, 2)})
    result["tyre_forward_reach"] = reach
    return result


def screw_alignment(chassis_):
    holes = {"bottom": plate_holes(chassis_[BOTTOM_PLATE]), "top": plate_holes(chassis_[TOP_PLATE])}
    screws = []
    for end in ("front", "rear"):
        for x, y in bumper.screw_points(end):
            screws.append((f"bumper_{end}", "bottom", x, y, 3.0))
    for x, y in lidar_mast.M3_SCREWS:
        screws.append(("lidar_mast", "top", x, y, 3.0))
    for x, y in lidar_mast.M25_SCREWS:
        screws.append(("lidar_mast", "top", x, y, 2.5))
    for x, y in rear_camera_mount.SCREWS:
        screws.append(("rear_camera_mount", "top", x, y, 3.0))
    rows = []
    for part, plate, x, y, d in screws:
        hit = None
        for hx, hy, sx, sy in holes[plate]:
            if abs(x - hx) <= sx / 2 - d / 2 + 0.05 and abs(y - hy) <= sy / 2 - d / 2 + 0.05:
                hit = (round(hx, 2), round(hy, 2), round(sx, 2), round(sy, 2))
                break
        rows.append({"part": part, "plate": plate, "screw": [round(x, 2), round(y, 2)], "M": d, "hole": hit})
    return rows


def tof_frustums():
    out = {}
    for end in ("front", "rear"):
        loc = bumper.tof_location(end)
        turn = bumper.ENDS[end]["turn"]
        for i, (origin, yaw, pitch) in enumerate(tof_pair.sensors()):
            o = (loc * Pos(*origin)).position
            out[f"tof_{end}_{'a' if i == 0 else 'b'}"] = (o, yaw + turn, pitch)
    return out


def lidar_band(r_min=31.0, r_max=500.0, half=3.0, tilt_deg=1.5):
    """Region the C1 beam can occupy: plane +- (beam half-height + r * tan(tilt))."""
    t = math.tan(math.radians(tilt_deg))
    pts = [(r_min, -half - r_min * t), (r_max, -half - r_max * t), (r_max, half + r_max * t), (r_min, half + r_min * t)]
    face = make_face(Polyline(*[(x, 0, z) for x, z in pts], close=True))
    band = revolve(face, Axis.Z, 360)
    lx, ly = lidar_mast.LIDAR_XY
    return Pos(lx, ly, z_at(lidar_mast.LIDAR_PLANE_H)) * band


def view_checks(parts_, hardware_, chassis_, env):
    everything = {**{k: v[0] for k, v in parts_.items()}, **hardware_, **chassis_, **env}
    report = {}
    for name, (o, yaw, pitch) in tof_frustums().items():
        f = frustum((o.X, o.Y, o.Z), yaw, pitch, TOF_HFOV, TOF_VFOV, 600.0)
        f -= Pos(o.X, o.Y, o.Z) * cyl(8.0, 8.0, centered=True)
        hits = {k: round(v, 1) for k, s in everything.items() if (v := overlap_volume(f, s)) > 0.5}
        lower = math.radians(TOF_VFOV / 2 - pitch)
        report[name] = {
            "height_above_floor_mm": round(h(o.Z), 1),
            "yaw_deg": round(yaw, 1),
            "pitch_up_deg": pitch,
            "floor_first_seen_mm": round(h(o.Z) / math.tan(lower), 0) if lower > 0 else None,
            "obstructions": hits,
        }
    band = lidar_band()
    hits = {k: round(v, 1) for k, s in everything.items() if k not in ("rplidar_c1",) and (v := overlap_volume(band, s)) > 0.5}
    tallest = sorted(
        ((round(h(s.bounding_box().max.Z), 1), k) for k, s in everything.items() if k not in ("rplidar_c1", "lidar_mast")), reverse=True
    )[:5]
    report["lidar"] = {
        "scan_plane_above_floor_mm": lidar_mast.LIDAR_PLANE_H,
        "lidar_base_above_floor_mm": round(lidar_mast.BASE_H, 1),
        "robot_top_above_floor_mm": round(lidar_mast.BASE_H + 41.3, 1),
        "band": "plane +- (3 mm + r tan 1.5 deg), r 31-500 mm",
        "obstructions": hits,
        "tallest_other_items_mm": tallest,
    }
    zed_front = (CX, ZED_BACK_Y - ZED_SIZE[1] - 0.5, TOP_PLATE_TOP + ZED_SIZE[2] / 2)
    for pitch in (0.0, -10.0):
        f = frustum(zed_front, 0.0, pitch, ZED_HFOV, ZED_VFOV, 1500.0)
        hits = {k: round(v, 1) for k, s in everything.items() if k != "zed_envelope" and (v := overlap_volume(f, s)) > 0.5}
        report[f"zed_pitch_{pitch:+.0f}"] = {"obstructions": hits}
    o, yaw, pitch = rear_camera_mount.lens_pose()
    o = (o[0], o[1], o[2] + TOP_PLATE_TOP)
    f = frustum(o, yaw, pitch, CAM3_HFOV, CAM3_VFOV, 1000.0)
    f -= Pos(*o) * cyl(10.0, 10.0, centered=True)
    hits = {k: round(v, 1) for k, s in everything.items() if k not in ("camera_module_3_wide",) and (v := overlap_volume(f, s)) > 0.5}
    report["rear_camera"] = {
        "lens_above_floor_mm": round(h(o[2]), 1),
        "pitch_down_deg": -pitch,
        "floor_first_seen_behind_lens_mm": round(h(o[2]) / math.tan(math.radians(CAM3_VFOV / 2 - pitch)), 0),
        "obstructions": hits,
    }
    return report


def footprint():
    front = bumper.installed("front", bumper.moving_part()[1]).bounding_box().min.Y
    rear = bumper.installed("rear", bumper.moving_part()[1]).bounding_box().max.Y
    from common import REAR_AXLE_Y

    return {
        "front_from_rear_axle_m": round((REAR_AXLE_Y - front) / 1000, 4),
        "rear_from_rear_axle_m": round((rear - REAR_AXLE_Y) / 1000, 4),
        "half_width_m": round(bumper.BAR_HALF_W / 1000, 4),
        "was": {"front": 0.2245, "rear": 0.07, "half_width": 0.10},
    }


def simplified_chassis(chassis_):
    """Chassis for the combined STEP: tyres as envelopes, fasteners (modelled threads, ~1 MB each) left out."""
    out = {}
    for name, s in chassis_.items():
        if name in FRONT_WHEELS + REAR_WHEELS:
            c = s.bounding_box().center()
            out[name] = wheel_envelope((c.X, c.Y, c.Z))
        elif s.volume >= STEP_MIN_VOLUME or name in KIT_STANDOFFS:
            out[name] = s
    return out


def export_assembly(parts_, hardware_, chassis_, env):
    children = []
    for name, s in simplified_chassis(chassis_).items():
        s.label = f"chassis_{name}"
        children.append(s)
    for name, s in env.items():
        s.label = name
        children.append(s)
    for name, (s, _) in parts_.items():
        s.label = name
        children.append(s)
    for name, s in hardware_.items():
        s.label = name
        children.append(s)
    asm = Compound(children=children, label="rabbit-2.0-mounts")
    export_step(asm, str(HERE / "rabbit-2.0-mounts.step"))


def renders(parts_, hardware_, chassis_, env):
    items = []
    for name, s in chassis_.items():
        bb = s.bounding_box()
        colour = "#3a3a3a" if (bb.size.Z < 2.5 and bb.size.Y > 100) else "#1c1c1c" if name in FRONT_WHEELS + REAR_WHEELS else "#b8b8b8"
        items.append((s, colour))
    for name, s in env.items():
        colour = "#1b5e20" if name == "pcb_board" else "#d7d7d7" if name.startswith("pcb_") else PART_COLOURS["envelope"]
        items.append((s, colour))
    for s, key in parts_.values():
        items.append((s, PART_COLOURS[key]))
    for s in hardware_.values():
        items.append((s, PART_COLOURS["hardware"]))
    legend = [
        "orange: ToF pairs (VL53L8CX)   blue: bumpers (D2F-01L)   green: lidar mast (RPLIDAR C1)",
        "red: power button pod   purple: rear camera mount   yellow: PCB edge combs, XT60 strain relief, C1 collar",
        "dark green: body PCB (deck 2)   grey boxes: ZED 2i, battery, V-mount plate (estimates)",
    ]
    paths = render(items, RENDERS / "assembly", views=("iso", "iso_rear", "top", "side", "front", "rear"), size=(1600, 1200))
    for p in paths:
        label_png(p, f"Rabbit 2.0 mounts on the chassis ({p.stem.split('_', 1)[1]})", legend)

    lower = [(s, c) for s, c in items if s.bounding_box().max.Z < DECK3_BOTTOM + 0.5 or s.bounding_box().min.Z < DECK3_BOTTOM - 5]
    lower = [(s, c) for s, c in lower if s.bounding_box().min.Z < DECK3_BOTTOM - 0.5]
    for p in render(lower, RENDERS / "deck2", views=("iso", "top", "side"), size=(1600, 1200)):
        label_png(p, f"Deck 2: body PCB and its mounts, deck 3 removed ({p.stem.split('_', 1)[1]})", legend)

    front_focus = (CX - 120, CX + 120, -175, -40, 0, 110)
    p = render(items, RENDERS / "detail_front", views=("iso",), focus=front_focus, zoom=1.0)[0]
    label_png(p, "Front: bumper, switches, ToF pair, steered-wheel clearance", ["bar travel 3.5 mm to the hard stops"])
    rear_focus = (CX - 120, CX + 120, 90, 165, 0, 200)
    p = render(items, RENDERS / "detail_rear", views=("iso_rear",), focus=rear_focus, zoom=1.0)[0]
    label_png(p, "Rear: bumper, ToF pair, camera mount", [])
    mast_focus = (CX - 70, CX + 70, -120, 0, TOP_PLATE_TOP - 10, z_at(240))
    p = render(items, RENDERS / "detail_mast", views=("iso",), focus=mast_focus, zoom=1.0)[0]
    label_png(p, "Lidar mast with the power button pod", [f"scan plane {lidar_mast.LIDAR_PLANE_H:.0f} mm above the floor"])

    fov = list(items)
    for name, (o, yaw, pitch) in tof_frustums().items():
        fov.append((frustum((o.X, o.Y, o.Z), yaw, pitch, TOF_HFOV, TOF_VFOV, 400.0), "#ffb74d"))
    fov.append((lidar_band(r_max=350.0, half=0.5, tilt_deg=0.0), "#ef5350"))
    o, yaw, pitch = rear_camera_mount.lens_pose()
    fov.append((frustum((o[0], o[1], o[2] + TOP_PLATE_TOP), yaw, pitch, CAM3_HFOV, CAM3_VFOV, 250.0), "#ce93d8"))
    paths = render(fov, RENDERS / "fields_of_view", views=("iso", "side", "top"), size=(1600, 1200), zoom=1.0)
    for p in paths:
        label_png(
            p,
            f"Fields of view ({p.stem.split('_')[-1]})",
            [
                "orange: ToF 45 x 45 deg to 0.4 m   red: lidar scan plane to 0.35 m   violet: rear camera to 0.25 m",
            ],
        )


def part_renders(parts_, hardware_):
    singles = {
        "tof_pair": (tof_pair.build(), [(tof_pair.boards(), "#2e7d32")]),
        "bumper_front": (bumper.build("front")[0], [(bumper.switch_body(1) + bumper.switch_body(-1), "#222222")]),
        "bumper_rear": (bumper.build("rear")[0], [(bumper.switch_body(1) + bumper.switch_body(-1), "#222222")]),
        "lidar_mast": (lidar_mast.build(), []),
        "power_button_panel": (power_button_panel.build(), []),
        "rear_camera_mount": (rear_camera_mount.build(), [(rear_camera_mount.camera_solid(), "#2e7d32")]),
        "cable_clip": (cable_clip.build(), []),
        "pcb_comb_front": (pcb_edge_comb.build("front"), []),
        "pcb_comb_rear": (pcb_edge_comb.build("rear"), []),
        "xt60_strain_relief": (xt60_strain_relief.build(), []),
        "cap_clamp": (cap_clamp.build(), []),
        "zed_grommet": (zed_grommet.build(), []),
        "slot_grommet": (slot_grommet.build(), []),
    }
    colours = {
        "tof_pair": "tof",
        "bumper_front": "bumper",
        "bumper_rear": "bumper",
        "lidar_mast": "mast",
        "power_button_panel": "button",
        "rear_camera_mount": "camera",
        "cable_clip": "clip",
        "pcb_comb_front": "deck",
        "pcb_comb_rear": "deck",
        "xt60_strain_relief": "deck",
        "cap_clamp": "deck",
        "zed_grommet": "clip",
        "slot_grommet": "clip",
    }
    for name, (shape, extra) in singles.items():
        items = [(shape, PART_COLOURS[colours[name]])] + extra
        for p in render(items, RENDERS / f"part_{name}", views=("iso", "iso_rear"), size=(1200, 900), edges=False):
            label_png(p, name.replace("_", " "), [])


def pcb_clearance(parts_, hardware_, deck2):
    """Smallest gap from each part near deck 2 to the board and its parts (pins included)."""
    names = [k for k in parts_ if k.startswith(("tof_pair", "bumper", "pcb_comb", "xt60", "cap_clamp"))]
    items = {**{k: parts_[k][0] for k in names}, **{k: v for k, v in hardware_.items() if k.startswith(("tof_boards", "d2f"))}}
    out = {}
    for k, a in items.items():
        near = [s for s in deck2.values() if bbox_overlap(a, s, margin=15.0)]
        out[k] = round(min((min_distance(a, s) for s in near), default=float("inf")), 2)
    return out


def main():
    chassis_ = chassis()
    deck2 = pcb()
    env = {**envelopes(), **deck2}
    parts_ = parts()
    hardware_ = hardware()
    if "--step-only" in sys.argv:
        export_assembly(parts_, hardware_, chassis_, env)
        return
    report = {
        "top_lift_mm": round(TOP_LIFT, 2),
        "top_plate_top_above_floor_mm": round(h(TOP_PLATE_TOP), 1),
        "pcb_bottom_above_floor_mm": round(h(DECK2_BOTTOM), 1),
        "footprint": footprint(),
        "screws": screw_alignment(chassis_),
        "interference_mm3": interference(parts_, hardware_, chassis_, env),
        "steering": steering_sweep(parts_, hardware_),
        "views": view_checks(parts_, hardware_, chassis_, env),
        "pcb_gap_mm": pcb_clearance(parts_, hardware_, deck2),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str))
    if "--no-render" not in sys.argv:
        renders(parts_, hardware_, chassis_, env)
        part_renders(parts_, hardware_)
    if "--no-step" not in sys.argv:
        export_assembly(parts_, hardware_, chassis_, env)


if __name__ == "__main__":
    main()
