import json
import math
import sys
import time
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[2]
OFFLINE = REPO_ROOT / "data/offline"
OUT = OFFLINE / "replay"
REPO = REPO_ROOT / "workspaces/rabbit"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(ROOT))

from lib.geometry import plausible_position
from lib.planner import FREE, OCCUPIED, UNKNOWN, OccupancyGrid, costmap_from_clearance
from lib.trip import Navigator, Target, heading_to_theta, rear_pose
from nvgrid import nvblox_grid
from sim import Robot, Sim

DAYS = {
    "20261002": (
        OFFLINE / "export",
        [
            ("1790936125704990612", "2026-10-02 10:15:25", "2026-10-02 11:02:05", OFFLINE / "map/archive/room.20261002-110202.nvblx"),
            ("1790938925834011195", "2026-10-02 11:02:05", "2026-10-02 12:32:34", OFFLINE / "map/archive/room.20261002-123231.nvblx"),
            ("1790944354724387108", "2026-10-02 12:32:34", "2026-10-02 22:00:20", OFFLINE / "map/room.nvblx"),
        ],
    ),
    "20261003": (
        OFFLINE / "export-20261003",
        [
            ("1790982649088725664", "2026-10-02 23:10:49", "2026-10-03 01:05:18", OFFLINE / "map-20261003/archive/room.20261003-010518.nvblx"),
            ("1790989521206501780", "2026-10-03 01:05:21", "2026-10-03 01:06:27", OFFLINE / "map-20261003/archive/room.20261003-010627.nvblx"),
            ("1790989590371236502", "2026-10-03 01:06:30", "2026-10-03 01:29:40", OFFLINE / "map-20261003/archive/room.20261003-012940.nvblx"),
            ("1790990983468729356", "2026-10-03 01:29:43", "2026-10-03 01:49:22", OFFLINE / "map-20261003/archive/room.20261003-014922.nvblx"),
            ("1790992165631649174", "2026-10-03 01:49:25", "2026-10-03 01:58:09", OFFLINE / "map-20261003/archive/room.20261003-015809.nvblx"),
        ],
    ),
}
DAY = "20261002"


def grid_for(path: Path):
    cache = OUT / (path.stem + ".npz")
    if not cache.exists():
        origin, res, clearance = nvblox_grid(str(path))
        np.savez_compressed(cache, origin=np.array(origin), res=res, clearance=clearance)
    data = np.load(cache)
    return tuple(data["origin"]), float(data["res"]), data["clearance"]


def export_dir() -> Path:
    return DAYS[DAY][0]


def map_at(ts: str):
    for map_id, created, retired, path in DAYS[DAY][1]:
        if created <= ts < retired:
            return map_id, path
    return None


def trips(db):
    return db.sql(
        """
        select trip_id, min(ts) t0, max(ts) t1, arg_max(phase, ts) last_phase, arg_max(message, ts) msg,
               max(replans) replans, max(recoveries) recoveries, any_value(target_kind) kind, any_value(target_label) lbl,
               any_value(target_x) tx, any_value(target_z) tz, bool_or(preview) preview, max(path_length_m) length, max(plan_ms) plan_ms
        from 'planner_state.parquet' where target_x is not null group by trip_id order by t0
        """
    ).fetchall()


def target_of(db, trip_id: str, kind: str, label: str | None, tx: float, tz: float) -> Target:
    heading, tolerance = None, 0.25
    try:
        row = db.sql(f"select payload from 'command_events.parquet' where subject = 'rabbit.planner.goal' and payload like '%\"{trip_id}\"%' limit 1").fetchone()
    except duckdb.Error:
        row = None
    if row is not None:
        request = json.loads(row[0])
        heading, tolerance = request.get("heading_deg"), float(request.get("tolerance", 0.25))
    if kind == "object":
        return Target("object", float(tx), float(tz), label=label or None, size=0.6)
    return Target("point", float(tx), float(tz), heading, label or None, 0.0, tolerance)


def start_pose(db, t0):
    rows = db.sql(
        f"select x, y, z, qx, qy, qz, qw from 'pose.parquet' where ts <= '{t0}'::timestamptz and ts > '{t0}'::timestamptz - interval 5 second order by ts desc limit 50"
    ).fetchall()
    for x, y, z, qx, qy, qz, qw in rows:
        if plausible_position([x, y, z], 0.0):
            fx, fz = -2 * (qx * qz + qy * qw), -(1 - 2 * (qx * qx + qy * qy))
            return np.array([x, z]), math.atan2(fz, fx)
    return None


def world_from(clearance: np.ndarray, origin, res) -> OccupancyGrid:
    cells = np.where(clearance == -1, UNKNOWN, np.where(clearance == 0, OCCUPIED, FREE)).astype(np.int8)
    return OccupancyGrid(origin, res, clearance.shape[1], clearance.shape[0], cells)


def replay(only: str | None = None, seconds: float = 150.0):
    db = duckdb.connect()
    db.execute("set TimeZone = 'UTC'")
    db.execute(f"set file_search_path = '{export_dir()}'")
    results = []
    for trip_id, t0, t1, phase, msg, replans, recoveries, kind, label, tx, tz, preview, length, plan_ms in trips(db):
        if only and only not in trip_id:
            continue
        found = map_at(str(t0)[:19])
        start = start_pose(db, t0)
        if found is None or start is None:
            results.append((trip_id, "skipped", "no map or pose"))
            continue
        origin, res, clearance = grid_for(found[1])
        camera, theta = start
        target = target_of(db, trip_id, kind, label, tx, tz)
        rear = rear_pose(camera, theta)
        world = world_from(clearance, origin, res)
        sim = Sim(world, world, Robot(rear.x, rear.z, rear.theta))
        sim.costmap = costmap_from_clearance(origin, res, clearance)
        began = time.monotonic()
        if preview:
            navigator = Navigator()
            navigator.on_map(sim.costmap, np.empty((0, 2)))
            navigator.on_pose(camera, theta, 0.0)
            navigator.request(trip_id, "replay", target, 0.0, preview=True)
            job = navigator.tick(0.0)
            result = job.run()
            state = {"phase": "planned" if result.path else "failed", "message": result.message, "path_length_m": None if result.path is None else round(result.path.length, 2), "plan_ms": round(result.milliseconds, 1), "replans": 0, "recoveries": 0, "events": []}
        else:
            state = sim.run(target, seconds, trip_id)
        final = sim.robot.camera()
        results.append(
            (
                trip_id, str(t0)[11:19], kind, label, "preview" if preview else "drive",
                f"real: {phase} ({msg}) rp={replans} rc={recoveries} len={length} plan={plan_ms}",
                f"sim: {state['phase']} ({state['message']}) rp={state['replans']} rc={state['recoveries']} len={state.get('path_length_m')} plan={state.get('plan_ms')} collided={sim.collided()} to_target={np.hypot(*(final - [tx, tz])):.2f} wall={time.monotonic() - began:.1f}s",
                state.get("events", [])[-6:],
            )
        )
    return results


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] in DAYS:
        DAY = args.pop(0)
    for row in replay(args[0] if args else None):
        print(" | ".join(str(v) for v in row[:6]))
        print("    ", row[6] if len(row) > 6 else "")
        if len(row) > 7:
            for event in row[7]:
                print("       -", event)
