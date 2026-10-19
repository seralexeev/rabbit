"""Field of view of the ToF sensors hung under deck 2: casts the VL53L8CX's 8 x 8 zones (45 x 45 deg) from each
sensor pose against the assembly mesh (data/cad/robot/robot.glb, `run.py build` first) and reports what each
zone hits: a robot part (blocked), the floor (with the distance) or nothing within range.

    uv run --project model python cad/robot/tof_fov.py            # the poses in TOF_POSES (pcb/rabbit-body-c/gen/tof.json)
    uv run --project model python cad/robot/tof_fov.py --scan     # every 4 mm of the board edge, sensor facing out

Board frame (pcb/rabbit-body-c): +X robot right, +Y front. Chassis frame: x = 2.482 - X, y = -3.427 - Y, z up.
The front wheels are also tested steered by +-STEER deg about their kingpins.
"""

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import trimesh

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "parts"))
import tof_mount  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
GLB = REPO / "data" / "cad" / "robot" / "robot.glb"
OUTLINE = REPO / "pcb" / "rabbit-body-c" / "gen" / "outline.json"
POSES = REPO / "pcb" / "rabbit-body-c" / "gen" / "tof.json"
FOV = 45.0
ZONES = 8
SUB = 3
RANGE = 1500.0
DECK2_BOTTOM = 79.12
FLOOR_Z = 5.7
STEER = 30.0
KINGPINS = {"wheel_front_left": (57.74, -88.39), "wheel_front_right": (-52.78, -88.39)}


def to_chassis(X, Y):
    return 2.482 - X, -3.427 - Y


def load_scene():
    scene = trimesh.load(GLB)
    meshes, names = [], []
    for node in scene.graph.nodes_geometry:
        tf, geom = scene.graph[node]
        part = re.sub(r"_[0-9a-f]{6}$", "", node)
        if part.startswith(("body_pcb", "raspberry_pi")):
            continue
        m = scene.geometry[geom].copy()
        m.apply_transform(tf)
        meshes.append(m)
        names.append(part)
        if part in KINGPINS:
            kx, ky = KINGPINS[part]
            for a in (-STEER, STEER):
                r = trimesh.transformations.rotation_matrix(math.radians(a), (0, 0, 1), (kx, ky, 0))
                meshes.append(m.copy().apply_transform(r))
                names.append(f"{part}_steered")
    return meshes, names


def soup(meshes):
    """All triangles as (a, edge1, edge2) arrays and the index of the mesh each came from."""
    tri = np.vstack([m.triangles for m in meshes])
    owner = np.concatenate([np.full(len(m.faces), i) for i, m in enumerate(meshes)])
    return (tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), owner


def first_hits(tris, origin, dirs):
    """Moller-Trumbore: distance to and index of the nearest triangle per ray (inf, -1 if none)."""
    a, e1, e2 = tris
    t_best = np.full(len(dirs), np.inf)
    i_best = np.full(len(dirs), -1)
    s = origin - a
    for k in range(0, len(dirs), 64):
        d = dirs[k:k + 64, None, :]
        p = np.cross(d, e2)
        det = np.einsum("rtj,tj->rt", p, e1)
        ok = np.abs(det) > 1e-9
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        u = np.einsum("rtj,tj->rt", p, s) * inv
        q = np.cross(s, e1)
        v = (dirs[k:k + 64] @ q.T) * inv
        t = np.einsum("tj,tj->t", e2, q)[None] * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0.5)
        t = np.where(hit, t, np.inf)
        j = t.argmin(axis=1)
        tb = t[np.arange(len(j)), j]
        t_best[k:k + 64] = tb
        i_best[k:k + 64] = np.where(np.isfinite(tb), j, -1)
    return t_best, i_best


def zone_rays(yaw, tilt):
    """Unit directions (ZONES*SUB)^2 in the chassis frame; yaw = board-frame heading (0 = front, 90 = right)."""
    n = ZONES * SUB
    a = (np.arange(n) + 0.5) / n * FOV - FOV / 2
    h, v = np.meshgrid(a, a)
    h, v = np.radians(h.ravel()), np.radians(v.ravel() - tilt)
    yb = math.radians(yaw)
    fwd = np.array([-math.sin(yb), -math.cos(yb), 0.0])
    side = np.array([-math.cos(yb), math.sin(yb), 0.0])
    d = (np.cos(v) * np.cos(h))[:, None] * fwd + (np.cos(v) * np.sin(h))[:, None] * side + np.sin(v)[:, None] * [0, 0, 1]
    return d, h, v


def evaluate(tris, owner, names, X, Y, z, yaw, tilt):
    x, y = to_chassis(X, Y)
    origin = np.array([x, y, z])
    dirs, _, _ = zone_rays(yaw, tilt)
    near = np.linalg.norm(tris[0] - origin, axis=1) < RANGE
    sub = tuple(e[near] for e in tris)
    t, idx = first_hits(sub, origin, dirs)
    floor_t = np.where(dirs[:, 2] < 0, (z - FLOOR_Z) / np.maximum(-dirs[:, 2], 1e-9), np.inf)
    blocked = np.isfinite(t) & (t < floor_t)
    hit_parts = {}
    for i in np.flatnonzero(blocked):
        part = names[owner[near][idx[i]]]
        hit_parts[part] = hit_parts.get(part, 0) + 1
    floor = np.hypot(*(dirs[~blocked & np.isfinite(floor_t)][:, :2] * floor_t[~blocked & np.isfinite(floor_t)][:, None]).T)
    n = ZONES * SUB
    zones = blocked.reshape(ZONES, SUB, ZONES, SUB).mean(axis=(1, 3)) > 0.5
    return dict(blocked_pct=round(float(100 * blocked.mean()), 1), zones_blocked=int(zones.sum()),
                parts={k: round(100 * c / n / n, 1) for k, c in sorted(hit_parts.items(), key=lambda kv: -kv[1])},
                floor_near_mm=round(float(floor.min())) if len(floor) else None)


def edge_points(step=4.0):
    o = json.loads(OUTLINE.read_text())
    out = []
    for s in o["segments"]:
        if s["type"] != "line":
            continue
        a, b = np.array(s["start"]), np.array(s["end"])
        L = np.linalg.norm(b - a)
        t = (b - a) / L
        nrm = np.array([t[1], -t[0]])
        mid = (a + b) / 2
        if np.dot(nrm, mid) < 0:
            nrm = -nrm
        yaw = math.degrees(math.atan2(nrm[0], nrm[1]))
        for k in range(int(L // step) + 1):
            p = a + t * min(k * step, L)
            out.append((round(p[0], 1), round(p[1], 1), round(yaw, 1)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--z", type=float, default=None, help="sensor centre height (chassis z)")
    ap.add_argument("--tilt", type=float, default=None, help="deg below horizontal")
    args = ap.parse_args()
    meshes, names = load_scene()
    tris, owner = soup(meshes)
    poses = json.loads(POSES.read_text()) if POSES.exists() else {"z": 68.0, "tilt": 10.0, "sensors": []}
    z = args.z if args.z is not None else poses["z"]
    tilt = args.tilt if args.tilt is not None else poses["tilt"]
    if args.scan:
        for X, Y, yaw in edge_points():
            r = evaluate(tris, owner, names, X, Y, z, yaw, tilt)
            print(f"X {X:7.1f} Y {Y:7.1f} yaw {yaw:6.1f}  blocked {r['blocked_pct']:5.1f}%  "
                  f"{', '.join(f'{k} {v}' for k, v in list(r['parts'].items())[:3])}")
        return
    out_y, _ = tof_mount.sensor_centre()
    for s in poses["sensors"]:
        a = math.radians(s["yaw"])
        X, Y = s["X"] + out_y * math.sin(a), s["Y"] + out_y * math.cos(a)
        r = evaluate(tris, owner, names, X, Y, z, s["yaw"], tilt)
        print(f"{s['name']:10} X {s['X']:6.1f} Y {s['Y']:6.1f} yaw {s['yaw']:6.1f}: blocked {r['blocked_pct']}% "
              f"({r['zones_blocked']}/64 zones), floor from {r['floor_near_mm']} mm  {r['parts']}")


if __name__ == "__main__":
    main()
