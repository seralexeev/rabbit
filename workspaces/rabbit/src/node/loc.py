import argparse
import asyncio
import csv
import json
import time
from collections import deque
from pathlib import Path

import numpy as np
from lib.geometry import matrix_to_quaternion
from lib.loc import (
    KEYFRAME_SUBJECT,
    LOC_HEALTH_SUBJECT,
    GROW,
    LOCALIZED,
    MAP_ODOM_SUBJECT,
    STOP,
    GrowthPolicy,
    Keyframe,
    LocalizationFilter,
    decode_keyframe,
    from_rtabmap,
    to_rtabmap,
)
from lib.node import RabbitNode
from lib.spatial_map import MAP_DIR
from nats.aio.msg import Msg
from rabbit_rtabmap import Localizer

DATABASE = MAP_DIR / "rtabmap.db"
MAP_ID_FILE = MAP_DIR / "rtabmap.id"

BASE_PARAMETERS = {
    "Mem/BinDataKept": "false",
    "Kp/MaxFeatures": "300",
    "Mem/InitWMWithAllNodes": "true",
    "Rtabmap/TimeThr": "0",
    "Rtabmap/MemoryThr": "0",
}
MAPPING_PARAMETERS = {"RGBD/LinearUpdate": "0.1", "RGBD/AngularUpdate": "0.1"}
LOCALIZATION_PARAMETERS = {"RGBD/LinearUpdate": "0", "RGBD/AngularUpdate": "0"}


class Session:
    """RTAB-Map over one process lifetime: localization against the database; growing the map (incremental, the
    first new node anchored to the last matched one) while localized among new views; mapping when there is no map
    yet (the first session defines the map frame) or when relocalization failed for long enough (a new session in
    the same database, merged into the map by RTAB-Map's inter-session loop closures)."""

    ANCHOR_VARIANCE = 1e-3

    NEW_SESSION_S = 60.0
    NEW_SESSION_M = 2.0

    def __init__(self, database: Path, now: float, log=print, parameters: dict | None = None):
        self.log = log
        database.parent.mkdir(parents=True, exist_ok=True)
        fresh = not database.exists()
        self.localizer = Localizer(
            str(database), {**BASE_PARAMETERS, **(parameters or {}), **(MAPPING_PARAMETERS if fresh else LOCALIZATION_PARAMETERS)}, fresh
        )
        self.mode = "mapping" if self.localizer.last_old_id == 0 else "localization"
        if self.mode == "mapping" and not fresh:
            self.localizer.set_mode(True, MAPPING_PARAMETERS)
        self.filter = LocalizationFilter()
        if self.mode == "mapping":
            self.filter.lost_s = float("inf")
            self.filter.seed(now, np.eye(4))
        self.started = now
        self.travel_since_start = 0.0
        self.last_position: np.ndarray | None = None
        self.frames = 0
        self.process_ms: deque[float] = deque(maxlen=50)
        self.last_result: dict = {}
        self.last_match_ts = 0
        self.odom_session: str | None = None
        self.growth = GrowthPolicy()
        self.growth_from_id = 0
        self.anchor: tuple[int, np.ndarray] | None = None
        self.last_matched_id = 0
        self.grown_nodes = 0
        self.lost_s = self.filter.lost_s
        self.log(f"RTAB-Map {self.mode} on {database} ({self.localizer.nodes} nodes)")

    def restart(self, now: float, reason: str):
        """A new odom session (rabbit-zed restarted): odom starts over, so any map<-odom is void."""
        if self.localizer.nodes == 0:
            self.filter = LocalizationFilter(lost_s=float("inf"))
            self.filter.seed(now, np.eye(4))
        else:
            if self.mode not in ("localization", "mapping"):
                self.localizer.set_mode(False, LOCALIZATION_PARAMETERS)
                self.mode = "localization"
            self.localizer.trigger_new_map()
            self.filter = LocalizationFilter()
        self.lost_s = self.filter.lost_s
        self.growth = GrowthPolicy()
        self.anchor = None
        self.started = now
        self.travel_since_start = 0.0
        self.last_position = None
        self.log(f"{reason}: relocalizing ({self.mode}, {self.localizer.nodes} nodes)")

    def process(self, frame: Keyframe, now: float) -> bool:
        if self.odom_session is not None and frame.session != self.odom_session:
            self.restart(now, f"Odometry session changed from {self.odom_session} to {frame.session}")
        self.odom_session = frame.session
        result = self.localizer.process(frame.rgb, frame.depth, to_rtabmap(frame.odom), frame.ts / 1e9, *frame.intrinsics)
        self.frames += 1
        self.process_ms.append(result["process_ms"])
        self.last_result = result
        position = frame.odom[:3, 3]
        if self.last_position is not None:
            self.travel_since_start += float(np.linalg.norm(position - self.last_position))
        self.last_position = position
        matched = (
            result["matched_id"] > 0
            and (self.mode != "new session" or result["matched_previous_session"])
            and (self.mode != "growing" or result["matched_id"] <= self.growth_from_id)
        )
        candidate = from_rtabmap(result["map_correction"]) if matched else None
        before = self.filter.status
        changed = self.filter.update(now, position, candidate, result["loop_id"] > 0)
        if candidate is not None:
            self.last_match_ts = frame.ts
        if self.filter.status != before:
            self.log(f"Localization {before} -> {self.filter.status} ({self.mode}, match {result['matched_id']}, {result['inliers']} inliers)")
        if self.mode in ("localization", "growing"):
            self._grow(result, frame, now, candidate is not None)
        if (
            self.mode == "localization"
            and self.filter.map_from_odom is None
            and now - self.started > self.NEW_SESSION_S
            and self.travel_since_start > self.NEW_SESSION_M
        ):
            self.localizer.set_mode(True, MAPPING_PARAMETERS)
            self.localizer.trigger_new_map()
            self.mode = "new session"
            self.log(f"Not localized after {now - self.started:.0f} s and {self.travel_since_start:.1f} m: mapping a new session")
        return changed

    def _grow(self, result: dict, frame: Keyframe, now: float, matched: bool):
        if self.mode == "growing" and self.anchor is not None and result["added"]:
            anchor_id, anchor_pose = self.anchor
            self.anchor = None
            self.growth_from_id = result["id"] - 1
            node_pose = to_rtabmap(self.filter.map_from_odom @ frame.odom)
            linked = self.localizer.add_link(anchor_id, result["id"], np.linalg.inv(anchor_pose) @ node_pose, self.ANCHOR_VARIANCE)
            self.log(f"Growing the map from node {result['id']}, anchored to node {anchor_id}: {'linked' if linked else 'LINK FAILED'}")
        if self.mode == "growing" and result["added"]:
            self.grown_nodes += 1
        known = matched and (self.mode == "localization" or 0 < result["matched_id"] <= self.growth_from_id)
        if known and self.mode == "localization":
            self.last_matched_id = result["matched_id"]
        action = self.growth.update(now, self.filter, known)
        if action == GROW:
            anchor_pose = self.localizer.node_pose(self.last_matched_id) if self.last_matched_id else None
            if anchor_pose is None:
                self.growth.growing = False
                return
            self.anchor = (self.last_matched_id, np.asarray(anchor_pose))
            self.lost_s, self.filter.lost_s = self.filter.lost_s, float("inf")
            self.localizer.set_mode(True, MAPPING_PARAMETERS)
            self.mode = "growing"
            self.log(f"New views {self.filter.travel_m:.1f} m after the last fix: growing the map")
        elif action == STOP:
            self.filter.lost_s = self.lost_s
            self.localizer.set_mode(False, LOCALIZATION_PARAMETERS)
            self.mode = "localization"
            self.log(f"Back to localization ({self.filter.status}), {self.grown_nodes} nodes grown so far")

    def map_odom(self, ts: int, map_id: str) -> dict:
        m = self.filter.map_from_odom
        return {
            "keyframe_ts": ts or None,
            "status": self.filter.status,
            "transform": None if m is None else [round(float(v), 6) for v in m.reshape(16)],
            "translation": None if m is None else [round(float(v), 4) for v in m[:3, 3]],
            "orientation": None if m is None else [round(float(v), 6) for v in matrix_to_quaternion(m[:3, :3])],
            "map_id": map_id,
            "odom_session": self.odom_session,
            "mode": self.mode,
            "matches": self.filter.matches,
            "corrections": self.filter.corrections,
            "pending": len(self.filter.pending),
            "last_match_ts": self.last_match_ts or None,
            "grown_nodes": self.grown_nodes,
        }

    def close(self):
        self.localizer.close(save=self.mode != "localization" or self.grown_nodes > 0)


def rss_mb(field: str = "VmRSS") -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(f"{field}:"):
            return int(line.split()[1]) / 1024
    return 0.0


class Node(RabbitNode):
    HEALTH_S = 1.0

    def __init__(self):
        super().__init__("rabbit-loc")
        self.session: Session | None = None
        self.map_id = ""
        self.latest: Keyframe | None = None
        self.ready = asyncio.Event()
        self.received = 0
        self.dropped = 0
        self.last_ts = 0

    async def init(self):
        self.session = await asyncio.to_thread(Session, DATABASE, time.monotonic(), self.logger.info)
        if not MAP_ID_FILE.exists():
            MAP_ID_FILE.write_text(str(time.time_ns()))
        self.map_id = MAP_ID_FILE.read_text().strip()
        await self.subscribe(KEYFRAME_SUBJECT, self.on_keyframe)
        await self.async_task(self.process)
        self.set_interval(self.publish_health, self.HEALTH_S, max_parallel=1)

    async def on_keyframe(self, msg: Msg):
        self.received += 1
        if self.latest is not None:
            self.dropped += 1
        self.latest = decode_keyframe(msg.data, msg.headers or {})
        self.ready.set()

    async def process(self):
        await self.ready.wait()
        self.ready.clear()
        frame, self.latest = self.latest, None
        if frame is None:
            return
        await asyncio.to_thread(self.session.process, frame, time.monotonic())
        self.last_ts = frame.ts
        await self.publish_json(MAP_ODOM_SUBJECT, self.session.map_odom(frame.ts, self.map_id))

    async def publish_health(self):
        s = self.session
        await self.publish_json(MAP_ODOM_SUBJECT, s.map_odom(self.last_ts, self.map_id))
        await self.publish_json(
            LOC_HEALTH_SUBJECT,
            {
                "status": s.filter.status,
                "mode": s.mode,
                "map_id": self.map_id,
                "received": self.received,
                "dropped": self.dropped,
                "processed": s.frames,
                "process_ms": round(s.process_ms[-1], 1) if s.process_ms else None,
                "process_ms_p50": round(float(np.median(s.process_ms)), 1) if s.process_ms else None,
                "wm_size": s.last_result.get("wm_size"),
                "nodes": s.localizer.nodes,
                "inliers": s.last_result.get("inliers"),
                "matches": s.filter.matches,
                "corrections": s.filter.corrections,
                "rss_mb": round(rss_mb(), 1),
                "rss_anon_mb": round(rss_mb("RssAnon"), 1),
                "db_mb": round(DATABASE.stat().st_size / 2**20, 1) if DATABASE.exists() else 0.0,
            },
        )

    async def close(self):
        if self.session is not None:
            await asyncio.to_thread(self.session.close)


IMAGE_TO_Y_UP = np.diag([1.0, -1.0, -1.0, 1.0])


def replay(dump: Path, database: Path, out: Path, rate: float, decimation: int, parameters: dict):
    """Feeds a bench dump (workspaces/bench zed_dump layout, IMAGE-frame TUM odometry) through the same session."""
    meta = json.loads((dump / "meta.json").read_text())
    odom = np.loadtxt(dump / "zed_vio.txt", ndmin=2)
    session = Session(database, 0.0, parameters={"Mem/ImagePreDecimation": str(decimation), **parameters})
    rows = [r for r in csv.DictReader(open(dump / "frames.csv")) if r["rgb"] and r["depth"]]
    t0 = int(rows[0]["t_ns"])
    last = -1e18
    with open(out, "w") as f:
        f.write("t_s,status,mode,matched_id,loop_id,inliers,process_ms,x,y,z\n")
        for r in rows:
            t = int(r["t_ns"])
            if t - last < 1e9 / rate:
                continue
            i = int(np.argmin(np.abs(odom[:, 0] * 1e9 - t)))
            if abs(odom[i, 0] * 1e9 - t) > 2e7:
                continue
            last = t
            pose = np.eye(4)
            x, y, z, qx, qy, qz, qw = odom[i, 1:]
            pose[:3, :3] = [
                [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
            ]
            pose[:3, 3] = [x, y, z]
            frame = Keyframe(
                ts=t,
                session="replay",
                odom=IMAGE_TO_Y_UP @ pose @ IMAGE_TO_Y_UP,
                intrinsics=(meta["fx"], meta["fy"], meta["cx"], meta["cy"]),
                rgb=(dump / r["rgb"]).read_bytes(),
                depth=(dump / r["depth"]).read_bytes(),
            )
            session.process(frame, (t - t0) / 1e9)
            res = session.last_result
            m = session.filter.map_from_odom
            p = (m @ frame.odom)[:3, 3] if m is not None else [float("nan")] * 3
            f.write(
                f"{(t - t0) / 1e9:.2f},{session.filter.status},{session.mode},{res['matched_id']},{res['loop_id']},"
                f"{res['inliers']},{res['process_ms']:.1f},{p[0]:.3f},{p[1]:.3f},{p[2]:.3f}\n"
            )
    print(json.dumps({"frames": session.frames, "status": session.filter.status, "mode": session.mode, "matches": session.filter.matches,
                      "corrections": session.filter.corrections, "nodes": session.localizer.nodes,
                      "process_ms_p50": round(float(np.median(session.process_ms)), 1), "rss_mb": round(rss_mb(), 1),
                      "rss_anon_mb": round(rss_mb("RssAnon"), 1)}))
    session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", type=Path, help="bench dump directory to replay instead of running the node")
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--out", type=Path, default=Path("loc_replay.csv"))
    parser.add_argument("--rate", type=float, default=2.0)
    parser.add_argument("--param", action="append", default=[], help="extra RTAB-Map parameter Key=Value")
    parser.add_argument("--decimation", type=int, default=2, help="the bench dumps are 1280x720; the robot sends 640x360")
    args = parser.parse_args()
    if args.replay:
        replay(args.replay, args.db, args.out, args.rate, args.decimation, dict(p.split("=", 1) for p in args.param))
    else:
        Node().run_node()
