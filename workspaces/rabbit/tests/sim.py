import asyncio
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path as FsPath
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(FsPath(__file__).resolve().parents[1] / "src"))

from lib.geometry import CAMERA_TO_REAR_AXLE, CAMERA_HEIGHT
from lib.geometry import camera_point as camera_of_rear
from lib.navmap import ObstacleMemory, scan_rays
from lib.planner import CostMap, OccupancyGrid, build_costmap
from lib.simulation import (
    ACTUATION_DELAY,
    POSE_LATENCY,
    SCAN_LATENCY,
    Robot,
    ScannedMap,
    apartment,
    block,
    body_free,
    corridor_flat,
    open_plan,
    room_grid,
    scan_ranges,
)
from lib.trip import PARAMS, Navigator, Target, theta_to_heading
from node import explore as explore_module
from node import nav as nav_module

DT = 0.05
SUBSTEPS = 5
SCAN_EVERY = 3
STATE_EVERY = 2
TICK_EVERY = 5


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def time_ns(self) -> int:
        return int(self.now * 1e9)


@dataclass
class Event:
    at: float
    action: object
    done: bool = False


@dataclass
class Sim:
    world: OccupancyGrid
    known: OccupancyGrid
    robot: Robot
    events: list[Event] = field(default_factory=list)
    clock: Clock = field(default_factory=Clock)
    trajectory: list[tuple[float, float, float]] = field(default_factory=list)
    messages: list[tuple[float, str, dict]] = field(default_factory=list)
    states: list[dict] = field(default_factory=list)
    odom: bool = False
    map_error: Callable[[float], tuple[float, float]] | None = None
    latency: bool = True

    def __post_init__(self):
        self.history: list[tuple[float, float, float, float]] = []
        self.commands: list[tuple[float, float, float]] = []
        self.nav = nav_module.Node()
        self.navigator = Navigator()
        self.memory = ObstacleMemory()
        self.costmap: CostMap = build_costmap(self.known, PARAMS.footprint, False, PARAMS.proximity_band)
        self.nav_state: dict = {}
        self.mapper: ScannedMap | None = None

        async def capture(subject: str, payload: dict):
            if subject == nav_module.STATE_SUBJECT:
                self.nav_state = json.loads(json.dumps(payload))

        self.nav.publish_json = capture

    def set_known(self, known: OccupancyGrid) -> None:
        self.known = known
        self.costmap = build_costmap(known, PARAMS.footprint, False, PARAMS.proximity_band)

    def past(self, ago: float) -> Robot:
        if not self.latency or not self.history:
            return self.robot
        at = self.clock.now - ago
        times = [t for t, *_ in self.history]
        i = int(np.searchsorted(times, at))
        if i <= 0:
            _, x, z, theta = self.history[0]
        elif i >= len(self.history):
            return self.robot
        else:
            (t0, x0, z0, h0), (t1, x1, z1, h1) = self.history[i - 1], self.history[i]
            w = (at - t0) / max(t1 - t0, 1e-9)
            x, z, theta = x0 + w * (x1 - x0), z0 + w * (z1 - z0), h0 + w * ((h1 - h0 + math.pi) % (2 * math.pi) - math.pi)
        return Robot(x, z, theta)

    def advance(self, dt: float) -> None:
        self.commands.append((self.clock.now, self.nav.speed, self.nav.steer))
        for k in range(SUBSTEPS):
            at = self.clock.now + k * dt / SUBSTEPS
            speed, steer = self.nav.speed, self.nav.steer
            if self.latency:
                due = [c for c in self.commands if c[0] <= at - ACTUATION_DELAY + 1e-9]
                speed, steer = (due[-1][1], due[-1][2]) if due else (0.0, 0.0)
            self.robot.step(speed, steer, dt / SUBSTEPS)
            self.history.append((at + dt / SUBSTEPS, self.robot.x, self.robot.z, self.robot.theta))
        del self.commands[:-10]
        del self.history[:-60]

    def scan(self) -> dict:
        return {"ts": int((self.clock.now - (SCAN_LATENCY if self.latency else 0.0)) * 1e9), "scan": scan_ranges(self.world, self.past(SCAN_LATENCY))}

    def body_clearance(self) -> float:
        return 1.0 if body_free(self.world, self.robot) else 0.0

    async def feed(self, step: int) -> None:
        seen = self.past(POSE_LATENCY)
        camera = seen.camera()
        error = self.map_error(self.clock.now - 1000.0) if self.map_error is not None else (0.0, 0.0)
        pose = {"ts": int((self.clock.now - (POSE_LATENCY if self.latency else 0.0)) * 1e9), "translation": [float(camera[0]) + error[0], CAMERA_HEIGHT, float(camera[1]) + error[1]], "orientation": seen.orientation()}
        if self.odom:
            pose["odom"] = {"translation": [float(camera[0]), CAMERA_HEIGHT, float(camera[1])], "orientation": seen.orientation()}
        await self.nav.on_pose(SimpleNamespace(data=json.dumps(pose).encode()))
        self.navigator.on_pose(camera, seen.theta, self.clock.now)
        if step % SCAN_EVERY == 0:
            scan = self.scan()
            await self.nav.on_obstacle(SimpleNamespace(data=json.dumps(scan).encode()))
            scanned = self.past(SCAN_LATENCY)
            forward = np.array([math.cos(scanned.theta), math.sin(scanned.theta)])
            right = np.array([-forward[1], forward[0]])
            origin = np.array([scanned.x, scanned.z]) + CAMERA_TO_REAR_AXLE * forward
            ends, hits = scan_rays(scan["scan"], origin, forward, right)
            self.memory.add(self.clock.now, origin, ends, hits)
            if self.mapper is not None:
                self.mapper.observe(origin, scanned.theta)

    def deliver(self, subject: str, payload: dict) -> None:
        self.messages.append((self.clock.now, subject, payload))
        if subject == nav_module.MISSION_SUBJECT:
            asyncio.get_event_loop().run_until_complete(self.nav.on_mission(SimpleNamespace(data=json.dumps(payload).encode())))
        elif subject == nav_module.CANCEL_SUBJECT:
            asyncio.get_event_loop().run_until_complete(self.nav.on_cancel(SimpleNamespace(data=json.dumps(payload).encode())))

    def run(self, target: Target, seconds: float, trip_id: str = "trip") -> dict:
        nav_module.time = self.clock
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.feed(0))
            loop.run_until_complete(self.nav.publish_state())
            self.navigator.on_nav(self.nav_state)
            self.navigator.on_map(self.costmap, self.memory.points(self.clock.now))
            self.navigator.request(trip_id, "sim", target, self.clock.now)
            steps = int(seconds / DT)
            for step in range(steps):
                for event in self.events:
                    if not event.done and self.clock.now - 1000.0 >= event.at:
                        event.done = True
                        event.action(self)
                loop.run_until_complete(self.feed(step))
                loop.run_until_complete(self.nav.control_step())
                if step % STATE_EVERY == 0:
                    loop.run_until_complete(self.nav.publish_state())
                    self.navigator.on_nav(self.nav_state)
                if step % TICK_EVERY == 0:
                    if self.mapper is not None and step % (4 * TICK_EVERY) == 0:
                        robot = (self.robot.x, self.robot.z, self.robot.theta)
                        self.costmap = self.mapper.costmap(None, self.navigator.trail_points(), robot)
                    self.navigator.on_map(self.costmap, self.memory.points(self.clock.now))
                    job = self.navigator.tick(self.clock.now)
                    for message in self.navigator.drain():
                        self.deliver(*message)
                    if job is not None:
                        self.navigator.on_plan(job.run(), job.trip_id, self.clock.now)
                        for message in self.navigator.drain():
                            self.deliver(*message)
                    state = self.navigator.state(self.clock.now)
                    self.states.append(state)
                    if state["phase"] in ("arrived", "failed", "cancelled"):
                        break
                self.advance(DT)
                self.trajectory.append((self.robot.x, self.robot.z, self.body_clearance()))
                self.clock.now += DT
            return self.navigator.state(self.clock.now)
        finally:
            nav_module.time = __import__("time")
            loop.close()
            asyncio.set_event_loop(None)

    def run_mission(self, steps: list[dict], seconds: float) -> list[tuple[float, float, float, str]]:
        nav_module.time = self.clock
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        timeline = []
        try:
            loop.run_until_complete(self.feed(0))
            loop.run_until_complete(self.nav.on_mission(SimpleNamespace(data=json.dumps({"id": "m", "steps": steps}).encode())))
            for step in range(int(seconds / DT)):
                loop.run_until_complete(self.feed(step))
                loop.run_until_complete(self.nav.control_step())
                self.advance(DT)
                self.trajectory.append((self.robot.x, self.robot.z, self.body_clearance()))
                timeline.append((self.clock.now - 1000.0, self.robot.x, self.robot.z, self.nav.mode))
                self.clock.now += DT
            return timeline
        finally:
            nav_module.time = __import__("time")
            loop.close()
            asyncio.set_event_loop(None)

    def explore(self, seconds: float, trip_seconds: float = 120.0) -> list[str]:
        self.mapper = self.mapper or ScannedMap(self.world)
        nav_module.time = self.clock
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.feed(0))
        finally:
            nav_module.time = __import__("time")
            loop.close()
            asyncio.set_event_loop(None)
        self.costmap = self.mapper.costmap(None, np.empty((0, 2)), (self.robot.x, self.robot.z, self.robot.theta))
        node = explore_module.Node()
        node.map = self.mapper
        outcomes = []
        began = self.clock.now
        while self.clock.now - began < seconds:
            camera = self.robot.camera()
            node.pose = {"translation": [float(camera[0]), CAMERA_HEIGHT, float(camera[1])], "orientation": self.robot.orientation()}
            plan = node.plan_next()
            if plan is None:
                outcomes.append("nothing left worth looking at")
                break
            frontier, viewpoint = plan
            forward = np.array([np.cos(viewpoint.theta), np.sin(viewpoint.theta)])
            x, z = camera_of_rear(np.array([viewpoint.x, viewpoint.z]), forward)
            target = Target("point", float(x), float(z), theta_to_heading(viewpoint.theta), tolerance=0.3)
            state = self.run(target, trip_seconds, f"explore-{len(outcomes)}")
            outcome = node.outcome(state["phase"], str(state.get("message") or ""))
            outcomes.append(outcome)
            if outcome == "arrived":
                node.arrived_at(frontier)
            else:
                node.failed.append(frontier)
        return outcomes

    def collided(self) -> bool:
        return any(clear <= 0.0 for _, _, clear in self.trajectory)
