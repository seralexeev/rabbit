import asyncio
import json
import math
import time

import numpy as np
from lib.drive import CAMERA_WAKE_SUBJECT
from lib.geometry import camera_point
from lib.log import time_id
from lib.navmap import USE_GRID, ScanHistory, camera_frame, map_source, mark_known, scan_rays, warm_up
from lib.node import RabbitNode
from lib.exploration import MIN_CLUSTER_CELLS, next_view
from lib.planner import Pose2D, connected_components, distance_map_from, expand, frontier_mask
from lib.spatial_map import MAP_CHUNKS_SUBJECT, MAP_GRID_SNAPSHOT_SUBJECT, MAP_GRID_SUBJECT, MAP_SAVE_SUBJECT, MAP_SNAPSHOT_SUBJECT
from lib.trip import PARAMS, TERMINAL, rear_pose, theta_to_heading
from nats.aio.msg import Msg

EXPLORE_SUBJECT = "rabbit.nav.explore"
CANCEL_SUBJECT = "rabbit.nav.cancel"
PLANNER_GOAL_SUBJECT = "rabbit.planner.goal"
PLANNER_STATE_SUBJECT = "rabbit.planner.state"
POSE_SUBJECT = "rabbit.zed.pose"
OBSTACLE_SUBJECT = "rabbit.zed.obstacle"
STATE_SUBJECT = "rabbit.explore.state"
HEALTH_SUBJECT = "rabbit.health.zed"
MAP_EXTEND_SUBJECT = "rabbit.map.extend"


class Node(RabbitNode):
    STATE_INTERVAL = 0.5
    TRIP_POLL = 0.2
    TRIP_TIMEOUT = 300.0
    TRIP_ACCEPT_TIMEOUT = 5.0
    FAILED_FRONTIER_RADIUS = 0.6
    MAX_FAILURES = 5
    CAMERA_RESTART_TIMEOUT = 90.0
    SNAPSHOT_TIMEOUT = 30.0
    POSE_GAP = 0.5
    POSE_STEADY = 2.0
    WAKE_EVERY = 10.0
    WAKE_SECONDS = 30.0
    MAX_REFUSALS = 10
    REFUSAL_WAIT = 2.0
    UNSETTLED_MEMORY = ("INITIALIZING", "SEARCHING")

    def __init__(self):
        super().__init__("explore")
        self.exploration_id: str | None = None
        self.trip_id: str | None = None
        self.map = map_source()
        self.scans = ScanHistory()
        self.pose: dict | None = None
        self.pose_at = 0.0
        self.pose_since = 0.0
        self.planner: dict = {}
        self.task: asyncio.Task | None = None
        self.phase = "idle"
        self.started_at: float | None = None
        self.limits: dict = {}
        self.travelled = 0.0
        self.frontiers = 0
        self.last_view: Pose2D | None = None
        self.target: dict | None = None
        self.failed: list[tuple[float, float]] = []
        self.message: str | None = None
        self.planning_ms: float | None = None
        self.blocked: list[tuple[float, float]] = []
        self.visited: list[tuple[float, float]] = []
        self.health: dict = {}

    async def init(self):
        await asyncio.to_thread(warm_up)
        await self.subscribe(MAP_GRID_SUBJECT if USE_GRID else MAP_CHUNKS_SUBJECT, self.on_map)
        await self.subscribe(POSE_SUBJECT, self.on_pose)
        await self.subscribe(OBSTACLE_SUBJECT, self.on_obstacle)
        await self.subscribe(PLANNER_STATE_SUBJECT, self.on_planner)
        await self.subscribe(HEALTH_SUBJECT, self.on_health)
        await self.subscribe(EXPLORE_SUBJECT, self.on_explore)
        await self.subscribe(CANCEL_SUBJECT, self.on_cancel)
        self.set_interval(self.publish_state, self.STATE_INTERVAL, max_parallel=1)

    def apply_map(self, msg: Msg, snapshot: bool = False):
        session = msg.headers.get("session") if msg.headers else None
        if self.map.apply(session, msg.data, snapshot):
            self.scans.clear()
            self.set_log_context(map_session=session)

    async def on_map(self, msg: Msg):
        self.apply_map(msg)

    async def on_pose(self, msg: Msg):
        pose = json.loads(msg.data)
        if self.pose is not None and self.phase == "driving":
            a, b = self.pose["translation"], pose["translation"]
            step = math.hypot(b[0] - a[0], b[2] - a[2])
            if step < 0.25:
                self.travelled += step
        now = time.monotonic()
        if now - self.pose_at > self.POSE_GAP:
            self.pose_since = now
        self.pose = pose
        self.pose_at = now

    async def on_obstacle(self, msg: Msg):
        scan = json.loads(msg.data).get("scan")
        if scan is None or self.pose is None:
            return
        origin, forward, right = camera_frame(self.pose)
        self.scans.add(origin, forward, *scan_rays(scan, origin, forward, right))

    async def on_planner(self, msg: Msg):
        self.planner = json.loads(msg.data)

    async def on_health(self, msg: Msg):
        self.health = json.loads(msg.data)

    def relocalized(self) -> bool:
        return not self.health.get("relocalizing", False) and self.health.get("spatial_memory_status") not in self.UNSETTLED_MEMORY

    async def start_mapping(self):
        if "map_mode" not in self.health or self.health.get("map_mode") == "mapping":
            return
        self.message = "asking the camera to map new places"
        session = self.health.get("map_session")
        reply = json.loads(
            (await self.nc.request(MAP_EXTEND_SUBJECT, json.dumps({"ts": time.time_ns(), "source": "explore"}).encode(), timeout=5)).data
        )
        self.event("explore.map_extend", str(reply.get("reason")), accepted=reply.get("accepted"), restarting=reply.get("restarting"))
        if not reply.get("accepted"):
            self.logger.info(f"The camera stays in localization mode ({reply.get('reason')}); exploring without extending its area memory")
            self.message = None
            return
        if reply.get("restarting"):
            self.message = "waiting for the camera to restart in mapping mode"
            deadline = time.monotonic() + self.CAMERA_RESTART_TIMEOUT
            while not (self.health.get("map_session") != session and self.health.get("map_mode") == "mapping" and self.relocalized()):
                if time.monotonic() > deadline:
                    raise RuntimeError(f"the camera did not come back mapping and relocalized within {self.CAMERA_RESTART_TIMEOUT:.0f} s")
                await asyncio.sleep(0.5)
        self.message = None

    async def fetch_snapshot(self):
        subject = MAP_GRID_SNAPSHOT_SUBJECT if USE_GRID else MAP_SNAPSHOT_SUBJECT
        deadline = time.monotonic() + self.SNAPSHOT_TIMEOUT
        while True:
            try:
                snapshot = await self.nc.request(subject, b"", timeout=10)
                if snapshot.data:
                    self.apply_map(snapshot, snapshot=True)
                    return
            except Exception:
                if time.monotonic() > deadline:
                    raise
            if time.monotonic() > deadline:
                raise RuntimeError("no map from the camera")
            await asyncio.sleep(1.0)

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
        self.event("explore.started", f"requested by {request.get('source', 'unknown')}", message="Exploration started", source=request.get("source"), **self.limits)
        self.travelled = 0.0
        self.failed = []
        self.last_view = None
        self.blocked = []
        self.visited = []
        self.message = None
        self.task = asyncio.create_task(self.explore())

    async def on_cancel(self, msg: Msg):
        source = json.loads(msg.data or b"{}").get("source")
        if source in ("explore", "planner"):
            return
        if self.task is not None and not self.task.done():
            await self.stop("cancelled")

    async def stop(self, reason: str):
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.phase = "idle"
            self.message = reason
            self.event("explore.stopped", reason, message=f"Exploration stopped: {reason}", travelled_m=self.travelled, failed_frontiers=len(self.failed))
            self.set_log_context(exploration_id=None)

    async def explore(self):
        try:
            self.phase = "planning"
            await self.start_mapping()
            await self.fetch_snapshot()
            failures = 0
            refusals = 0
            while True:
                limit = self.limit_reached()
                if limit is not None:
                    await self.finish("done", limit)
                    return
                self.phase = "planning"
                await self.wait_for_pose()
                plan = await asyncio.to_thread(self.plan_next)
                if plan is None:
                    await self.finish("done", "nothing left worth looking at")
                    return
                frontier, viewpoint = plan
                self.event(
                    "explore.goal_chosen",
                    "a turn on the spot" if frontier == (viewpoint.x, viewpoint.z) else "best view of unknown space per cost",
                    frontier_x=frontier[0],
                    frontier_z=frontier[1],
                    view_x=viewpoint.x,
                    view_z=viewpoint.z,
                    view_heading_deg=theta_to_heading(viewpoint.theta),
                    gain_cells=None if self.target is None else self.target.get("cells"),
                    cost=None if self.target is None else self.target.get("cost"),
                    frontiers=self.frontiers,
                    failed_frontiers=len(self.failed),
                    planning_ms=self.planning_ms,
                    travelled_m=self.travelled,
                )
                self.phase = "driving"
                outcome = await self.run_trip(viewpoint)
                self.event("explore.trip_outcome", outcome, severity="info" if outcome in ("arrived", "limit") else "warning", frontier_x=frontier[0], frontier_z=frontier[1], trip_id=self.trip_id)
                if outcome.startswith("rejected"):
                    refusals += 1
                    if refusals >= self.MAX_REFUSALS:
                        await self.finish("failed", f"the planner keeps refusing trips: {outcome}")
                        return
                    self.logger.info(f"Trip refused, retrying: {outcome}")
                    await asyncio.sleep(self.REFUSAL_WAIT)
                    continue
                refusals = 0
                if outcome == "limit":
                    continue
                if outcome == "cancelled":
                    await self.finish("idle", "the trip was cancelled outside exploration")
                    return
                if outcome == "arrived":
                    failures = 0
                    self.arrived_at(frontier)
                    continue
                if outcome == "unreachable":
                    self.failed.append(frontier)
                    self.event("explore.frontier_abandoned", "unreachable", message=f"Frontier at {frontier} is unreachable", frontier_x=frontier[0], frontier_z=frontier[1])
                    continue
                failures += 1
                if outcome == "blocked":
                    self.blocked.append(frontier)
                repeats = sum(math.dist(frontier, other) <= self.FAILED_FRONTIER_RADIUS for other in self.blocked)
                if outcome != "blocked" or repeats >= 2:
                    self.failed.append(frontier)
                    self.event("explore.frontier_abandoned", outcome if outcome != "blocked" else "blocked twice", frontier_x=frontier[0], frontier_z=frontier[1])
                self.logger.warning(f"Frontier at {frontier} failed: {outcome}")
                if failures >= self.MAX_FAILURES:
                    await self.finish("failed", f"{failures} frontiers failed, last: {outcome}")
                    return
        except asyncio.CancelledError:
            if self.phase == "driving":
                await self.cancel_trip()
            raise
        except Exception as e:
            self.logger.exception("Exploration crashed")
            await self.finish("failed", f"error: {e}")

    async def wait_for_pose(self):
        deadline = time.monotonic() + self.CAMERA_RESTART_TIMEOUT
        woken = -math.inf
        while time.monotonic() - self.pose_at > self.POSE_GAP or time.monotonic() - self.pose_since < self.POSE_STEADY or not self.relocalized():
            if time.monotonic() > deadline:
                raise RuntimeError("no pose from the camera")
            if time.monotonic() - woken > self.WAKE_EVERY:
                woken = time.monotonic()
                await self.publish_json(CAMERA_WAKE_SUBJECT, {"seconds": self.WAKE_SECONDS, "source": "explore"})
            self.message = "waiting for the camera pose" if self.relocalized() else "waiting for the camera to relocalize"
            await asyncio.sleep(0.5)
        self.message = None

    def arrived_at(self, frontier: tuple[float, float]):
        self.visited.append(frontier)
        if sum(math.dist(frontier, other) <= self.FAILED_FRONTIER_RADIUS for other in self.visited) >= 2:
            self.failed.append(frontier)
            self.event("explore.frontier_abandoned", "visited twice", frontier_x=frontier[0], frontier_z=frontier[1])

    def limit_reached(self) -> str | None:
        assert self.started_at is not None
        if time.monotonic() - self.started_at > self.limits["max_duration_s"]:
            return "time limit reached"
        if self.travelled > self.limits["max_distance_m"]:
            return "distance limit reached"
        return None

    def plan_next(self) -> tuple[tuple[float, float], Pose2D] | None:
        pose = self.pose
        if pose is None or not self.map.ready():
            raise RuntimeError("No pose or map yet")
        started = time.monotonic()
        forward = camera_frame(pose)[1]
        start = rear_pose(np.array([pose["translation"][0], pose["translation"][2]]), math.atan2(forward[1], forward[0]))
        costmap = self.map.costmap(self.scans, np.empty((0, 2)), (start.x, start.z, start.theta))
        if costmap is None:
            raise RuntimeError("No map yet")
        costmap = expand(costmap, np.array([[start.x, start.z]]), 1.0, PARAMS.proximity_band)
        mark_known(costmap.grid, np.empty((0, 2)), (start.x, start.z, start.theta))
        self.frontiers = sum(len(cells) >= MIN_CLUSTER_CELLS for cells in connected_components(frontier_mask(costmap.grid)))
        view = next_view(costmap, start, distance_map_from(costmap, (start.x, start.z), PARAMS.unknown_cost), self.failed, self.last_view)
        self.planning_ms = round((time.monotonic() - started) * 1000.0)
        if view is None:
            return None
        self.last_view = view.pose
        self.target = {"x": view.pose.x, "z": view.pose.z, "theta": view.pose.theta, "cells": round(view.gain / costmap.grid.resolution**2), "cost": round(view.cost, 2), "path_length": None}
        return view.frontier, view.pose

    async def run_trip(self, viewpoint: Pose2D) -> str:
        trip_id = f"explore-{time_id()}"
        self.trip_id = trip_id
        forward = np.array([math.cos(viewpoint.theta), math.sin(viewpoint.theta)])
        x, z = camera_point(np.array([viewpoint.x, viewpoint.z]), forward)
        request = {
            "id": trip_id, "source": "explore", "x": round(float(x), 3), "z": round(float(z), 3), "heading_deg": round(theta_to_heading(viewpoint.theta), 1), "tolerance": 0.3,
            "exploration_id": self.exploration_id,
        }
        try:
            reply = json.loads((await self.nc.request(PLANNER_GOAL_SUBJECT, json.dumps(request).encode(), timeout=self.TRIP_ACCEPT_TIMEOUT)).data)
        except Exception as e:
            return f"rejected: planner unavailable ({e!r})"
        if not reply.get("ok"):
            return f"rejected: {reply.get('error')}"
        deadline = time.monotonic() + self.TRIP_TIMEOUT
        adopted_by = time.monotonic() + self.TRIP_ACCEPT_TIMEOUT
        while time.monotonic() < deadline:
            if self.limit_reached() is not None:
                await self.cancel_trip()
                return "limit"
            state = self.planner
            if state.get("trip_id") == trip_id:
                if self.target is not None and state.get("path_length_m") is not None:
                    self.target["path_length"] = state["path_length_m"]
                phase = state.get("phase")
                if phase in TERMINAL:
                    return self.outcome(phase, str(state.get("message") or ""))
            elif time.monotonic() > adopted_by:
                return "cancelled"
            await asyncio.sleep(self.TRIP_POLL)
        await self.cancel_trip()
        return "timeout"

    @staticmethod
    def outcome(phase: str, message: str) -> str:
        if phase == "arrived":
            return "arrived"
        if phase == "cancelled":
            return "cancelled"
        if message.startswith("cannot reach"):
            return "unreachable"
        if message.startswith(("route blocked", "stuck")):
            return "blocked"
        return f"failed: {message}"

    async def cancel_trip(self):
        await self.publish_json(CANCEL_SUBJECT, {"source": "explore"})

    async def finish(self, phase: str, message: str):
        self.phase = phase
        self.message = message
        self.target = None
        self.event(
            "explore.finished",
            message,
            severity="warning" if phase == "failed" else "info",
            message=f"Exploration {phase}: {message}",
            outcome=phase,
            travelled_m=self.travelled,
            elapsed_s=None if self.started_at is None else time.monotonic() - self.started_at,
            failed_frontiers=len(self.failed),
            visited=len(self.visited),
        )
        self.set_log_context(exploration_id=None)
        if self.travelled > 0.5:
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
                "map_chunks": len(getattr(self.map, "chunks", {})),
            },
        )

    async def close(self):
        await self.stop("shutdown")


if __name__ == "__main__":
    Node().run_node()
