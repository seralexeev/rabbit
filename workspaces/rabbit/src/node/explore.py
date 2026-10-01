import asyncio
import json
import math
import time

import numpy as np
from lib.log import time_id
from lib.node import RabbitNode
from lib.planner import (
    FREE,
    OCCUPIED,
    UNKNOWN,
    PlannerParams,
    Pose2D,
    build_costmap,
    distance_map_from,
    find_frontiers,
    grid_from_mesh,
    plan_hybrid_astar,
    rank_frontiers,
    smooth,
)
from lib.geometry import CAMERA_TO_REAR_AXLE, CENTERLINE_OFFSET
from lib.spatial_map import MAP_CHUNKS_SUBJECT, MAP_SAVE_SUBJECT, MAP_SNAPSHOT_SUBJECT, decode_chunks
from nats.aio.msg import Msg

EXPLORE_SUBJECT = "rabbit.nav.explore"
CANCEL_SUBJECT = "rabbit.nav.cancel"
MISSION_SUBJECT = "rabbit.nav.mission"
NAV_STATE_SUBJECT = "rabbit.nav.state"
POSE_SUBJECT = "rabbit.zed.pose"
OBSTACLE_SUBJECT = "rabbit.zed.obstacle"
STATE_SUBJECT = "rabbit.explore.state"

FREE_RANGE_WITHOUT_HIT = 2.5
PLANNER = PlannerParams(reverse_penalty=6.0, gear_switch_penalty=2.0, time_limit=3.0)


def rear_axle_pose(translation: list[float], orientation: list[float]) -> Pose2D:
    x, y, z, w = orientation
    forward = np.array([-2 * (x * z + y * w), -(1 - 2 * (x * x + y * y))])
    forward /= np.linalg.norm(forward)
    right = np.array([-forward[1], forward[0]])
    camera = np.array([translation[0], translation[2]])
    rear = camera + CENTERLINE_OFFSET * right - CAMERA_TO_REAR_AXLE * forward
    return Pose2D(float(rear[0]), float(rear[1]), math.atan2(forward[1], forward[0]))


def camera_points(path) -> list[list[float]]:
    points = []
    for waypoint in path.waypoints:
        cos, sin = math.cos(waypoint.theta), math.sin(waypoint.theta)
        points.append(
            [
                round(waypoint.x + CAMERA_TO_REAR_AXLE * cos + CENTERLINE_OFFSET * sin, 3),
                round(waypoint.z + CAMERA_TO_REAR_AXLE * sin - CENTERLINE_OFFSET * cos, 3),
                int(waypoint.direction),
            ]
        )
    return points


def camera_frame(pose: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x, y, z, w = pose["orientation"]
    forward = np.array([-2 * (x * z + y * w), -(1 - 2 * (x * x + y * y))])
    forward /= np.linalg.norm(forward)
    right = np.array([-forward[1], forward[0]])
    origin = np.array([pose["translation"][0], pose["translation"][2]]) + CENTERLINE_OFFSET * right
    return origin, forward, right


def scan_rays(scan: dict, origin: np.ndarray, forward: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hits = np.array([r is not None and r < FREE_RANGE_WITHOUT_HIT for r in scan["ranges"]])
    ranges = np.array([FREE_RANGE_WITHOUT_HIT if r is None else min(r, FREE_RANGE_WITHOUT_HIT) for r in scan["ranges"]])
    angles = np.radians(scan["angle_min_deg"] + (np.arange(len(ranges)) + 0.5) * scan["angle_step_deg"])
    along, across = ranges * np.cos(angles), ranges * np.sin(angles)
    return origin + np.outer(along, forward) + np.outer(across, right), hits


def clear_unknown(grid, origin: np.ndarray, ends: np.ndarray) -> None:
    step = 0.5 * grid.resolution
    for end in ends:
        span = end - origin
        length = float(np.linalg.norm(span))
        if length <= grid.resolution:
            continue
        samples = origin + (np.arange(0.0, length - grid.resolution, step) / length)[:, None] * span
        iz, ix, inside = grid.cell_index(samples)
        iz, ix = iz[inside], ix[inside]
        unknown = grid.cells[iz, ix] == UNKNOWN
        grid.cells[iz[unknown], ix[unknown]] = FREE


class Node(RabbitNode):
    STATE_INTERVAL = 0.5
    MISSION_POLL = 0.2
    MISSION_TIMEOUT = 120.0
    FAILED_FRONTIER_RADIUS = 0.6
    MAX_FAILURES = 5
    CANDIDATES = 3
    SCAN_MIN_MOVE = 0.05
    SCAN_MIN_TURN = math.radians(3.0)
    MAX_SCANS = 2000
    RECENT_HITS = 50
    BLOCKED_REPLAN = 3.0

    def __init__(self):
        super().__init__("explore")
        self.session: str | None = None
        self.exploration_id: str | None = None
        self.chunks: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.pose: dict | None = None
        self.nav: dict = {}
        self.task: asyncio.Task | None = None
        self.phase = "idle"
        self.started_at: float | None = None
        self.limits: dict = {}
        self.travelled = 0.0
        self.frontiers = 0
        self.target: dict | None = None
        self.failed: list[tuple[float, float]] = []
        self.message: str | None = None
        self.planning_ms: float | None = None
        self.scans: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        self.cancelling = False
        self.attempts: dict[tuple[float, float], int] = {}

    async def init(self):
        await self.subscribe(MAP_CHUNKS_SUBJECT, self.on_chunks)
        await self.subscribe(POSE_SUBJECT, self.on_pose)
        await self.subscribe(OBSTACLE_SUBJECT, self.on_obstacle)
        await self.subscribe(NAV_STATE_SUBJECT, self.on_nav)
        await self.subscribe(EXPLORE_SUBJECT, self.on_explore)
        await self.subscribe(CANCEL_SUBJECT, self.on_cancel)
        self.set_interval(self.publish_state, self.STATE_INTERVAL, max_parallel=1)

    def apply_chunks(self, session: str | None, payload: bytes):
        if session != self.session:
            if self.session is not None:
                self.scans = []
            self.session = session
            self.set_log_context(map_session=session)
            self.chunks = {}
        self.chunks.update(decode_chunks(payload))

    async def on_chunks(self, msg: Msg):
        self.apply_chunks(msg.headers.get("session") if msg.headers else None, msg.data)

    async def on_pose(self, msg: Msg):
        pose = json.loads(msg.data)
        if self.pose is not None and self.phase == "driving":
            a, b = self.pose["translation"], pose["translation"]
            step = math.hypot(b[0] - a[0], b[2] - a[2])
            if step < 0.25:
                self.travelled += step
        self.pose = pose

    async def on_obstacle(self, msg: Msg):
        scan = json.loads(msg.data).get("scan")
        if scan is None or self.pose is None:
            return
        origin, forward, right = camera_frame(self.pose)
        if self.scans:
            last_origin, last_ends, _ = self.scans[-1]
            last_heading = np.arctan2(*(last_ends[len(last_ends) // 2] - last_origin)[::-1])
            heading = math.atan2(forward[1], forward[0])
            moved = np.linalg.norm(origin - last_origin) >= self.SCAN_MIN_MOVE
            turned = abs((heading - last_heading + math.pi) % (2 * math.pi) - math.pi) >= self.SCAN_MIN_TURN
            if not (moved or turned):
                return
        self.scans.append((origin, *scan_rays(scan, origin, forward, right)))
        del self.scans[: -self.MAX_SCANS]

    async def on_nav(self, msg: Msg):
        self.nav = json.loads(msg.data)

    async def on_explore(self, msg: Msg):
        request = json.loads(msg.data or b"{}")
        await self.stop("restarted")
        self.limits = {
            "max_duration_s": float(request.get("max_duration_s", 300.0)),
            "max_distance_m": float(request.get("max_distance_m", 20.0)),
        }
        self.started_at = time.monotonic()
        self.exploration_id = time_id()
        self.set_log_context(exploration_id=self.exploration_id)
        self.logger.info("Exploration started", extra=self.limits)
        self.travelled = 0.0
        self.failed = []
        self.attempts = {}
        self.message = None
        self.task = asyncio.create_task(self.explore())

    async def on_cancel(self, msg: Msg):
        if self.cancelling:
            self.cancelling = False
            return
        if self.task is not None and not self.task.done():
            await self.stop("cancelled")

    async def stop(self, reason: str):
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.phase = "idle"
            self.message = reason
            self.logger.info("Exploration stopped: %s", reason)
            self.set_log_context(exploration_id=None)

    async def explore(self):
        try:
            snapshot = await self.nc.request(MAP_SNAPSHOT_SUBJECT, b"", timeout=10)
            self.apply_chunks(snapshot.headers.get("session") if snapshot.headers else None, snapshot.data)
            failures = 0
            while True:
                limit = self.limit_reached()
                if limit is not None:
                    await self.finish("done", limit)
                    return
                self.phase = "planning"
                plan = await asyncio.to_thread(self.plan_next)
                if plan is None:
                    await self.finish("done", "no reachable frontiers left")
                    return
                frontier, points = plan
                self.phase = "driving"
                outcome = await self.run_mission([{"type": "path", "points": points}])
                if outcome == "limit":
                    continue
                if outcome != "arrived":
                    failures += 1
                    self.attempts[frontier] = self.attempts.get(frontier, 0) + 1
                    if outcome != "blocked" or self.attempts[frontier] >= 2:
                        self.failed.append(frontier)
                    self.logger.warning(f"Frontier at {frontier} failed: {outcome}")
                    if failures >= self.MAX_FAILURES:
                        await self.finish("failed", f"{failures} frontiers failed, last: {outcome}")
                        return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.exception("Exploration crashed")
            await self.finish("failed", f"error: {e}")

    def robot_cells(self, pose: Pose2D) -> np.ndarray:
        along = np.arange(-0.1, 0.3, 0.025)
        across = np.arange(-0.12, 0.125, 0.025)
        a, c = np.meshgrid(along, across)
        forward = np.array([math.cos(pose.theta), math.sin(pose.theta)])
        right = np.array([-forward[1], forward[0]])
        return np.array([pose.x, pose.z]) + np.outer(a.ravel(), forward) + np.outer(c.ravel(), right)

    def limit_reached(self) -> str | None:
        assert self.started_at is not None
        if time.monotonic() - self.started_at > self.limits["max_duration_s"]:
            return "time limit reached"
        if self.travelled > self.limits["max_distance_m"]:
            return "distance limit reached"
        return None

    def plan_next(self) -> tuple[tuple[float, float], list[list[float]]] | None:
        if self.pose is None or not self.chunks:
            raise RuntimeError("No pose or map yet")
        started = time.monotonic()
        offsets = np.cumsum([0] + [len(v) for v, _ in self.chunks.values()])[:-1]
        scans = list(self.scans)
        ray_points = np.concatenate([np.vstack([origin, ends]) for origin, ends, _ in scans]) if scans else np.empty((0, 2))
        vertices = np.concatenate(
            [v for v, _ in self.chunks.values()] + [np.column_stack([ray_points[:, 0], np.full(len(ray_points), 1.0), ray_points[:, 1]])]
        )
        triangles = np.concatenate([t + offset for (_, t), offset in zip(self.chunks.values(), offsets)])
        grid = grid_from_mesh(vertices, triangles)
        for origin, ends, hits in scans:
            clear_unknown(grid, origin, ends)
        for _, ends, hits in scans[-self.RECENT_HITS :]:
            grid.mark_points(ends[hits], OCCUPIED)
        robot_cells = self.robot_cells(rear_axle_pose(self.pose["translation"], self.pose["orientation"]))
        iz, ix, inside = grid.cell_index(robot_cells)
        grid.cells[iz[inside], ix[inside]] = FREE
        costmap = build_costmap(grid, PLANNER.footprint, PLANNER.unknown_blocked, PLANNER.proximity_band)
        start = rear_axle_pose(self.pose["translation"], self.pose["orientation"])
        frontiers = [
            frontier
            for frontier in find_frontiers(costmap)
            if all(math.dist(frontier.centroid, failed) > self.FAILED_FRONTIER_RADIUS for failed in self.failed)
        ]
        self.frontiers = len(frontiers)
        ranked = rank_frontiers(frontiers, start, grid, distance_map_from(costmap, (start.x, start.z), PLANNER.unknown_cost))
        for frontier in ranked[: self.CANDIDATES]:
            path = plan_hybrid_astar(grid, start, frontier.viewpoint, PLANNER)
            if path is None:
                self.failed.append(frontier.centroid)
                continue
            self.target = {
                "x": frontier.viewpoint.x,
                "z": frontier.viewpoint.z,
                "theta": frontier.viewpoint.theta,
                "cells": frontier.cells,
                "path_length": round(path.length, 2),
                "reverse_length": round(path.reverse_length, 2),
            }
            self.planning_ms = round((time.monotonic() - started) * 1000.0)
            return frontier.centroid, camera_points(smooth(path, costmap))
        self.planning_ms = round((time.monotonic() - started) * 1000.0)
        return None

    async def run_mission(self, steps: list[dict]) -> str:
        await self.publish_json(MISSION_SUBJECT, {"steps": steps, "source": "explore"})
        await asyncio.sleep(1.0)
        deadline = time.monotonic() + self.MISSION_TIMEOUT
        blocked_since: float | None = None
        while time.monotonic() < deadline:
            if self.limit_reached() is not None:
                await self.cancel_mission()
                return "limit"
            mode = self.nav.get("mode")
            if mode == "blocked":
                blocked_since = blocked_since or time.monotonic()
                if time.monotonic() - blocked_since > self.BLOCKED_REPLAN:
                    await self.cancel_mission()
                    return "blocked"
            else:
                blocked_since = None
            if mode == "arrived":
                return "arrived"
            if mode == "fault":
                return f"fault: {self.nav.get('fault')}"
            if mode == "idle":
                return "cancelled"
            await asyncio.sleep(self.MISSION_POLL)
        await self.cancel_mission()
        return "timeout"

    async def cancel_mission(self):
        self.cancelling = True
        await self.publish_json(CANCEL_SUBJECT, {"source": "explore"})

    async def finish(self, phase: str, message: str):
        self.phase = phase
        self.message = message
        self.target = None
        self.logger.info(f"Exploration {phase}: {message}")
        self.set_log_context(exploration_id=None)
        await self.publish_json(MAP_SAVE_SUBJECT, {"source": "explore"})

    async def publish_state(self):
        await self.publish_json(
            STATE_SUBJECT,
            {
                "phase": self.phase,
                "exploration_id": self.exploration_id,
                "message": self.message,
                "elapsed_s": None if self.started_at is None else round(time.monotonic() - self.started_at, 1),
                "travelled_m": round(self.travelled, 2),
                "limits": self.limits,
                "frontiers": self.frontiers,
                "failed_frontiers": len(self.failed),
                "target": self.target,
                "planning_ms": self.planning_ms,
                "map_chunks": len(self.chunks),
            },
        )

    async def close(self):
        await self.stop("shutdown")


if __name__ == "__main__":
    Node().run_node()
