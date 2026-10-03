import json
import math
import time
from collections import deque

import numpy as np
from lib.drive import DRIVE_SUBJECT, JOY_SUBJECT, is_active, parse_joy
from lib.lidar import SCAN_SUBJECT as LIDAR_SUBJECT
from lib.lidar import decode_scan, point_times, points_xy
from lib.log import time_id
from lib.node import RabbitNode
from lib.geometry import (
    CAMERA_TO_REAR_AXLE,
    MAX_CURVATURE,
    curvature_for_steer,
    linear_acceleration,
    planar_pose,
    rear_axle_path,
    rear_axle_point,
    rigid_transform,
    steer_for_curvature,
)
from lib.safety import free_distance, scan_points
from nats.aio.msg import Msg

GOAL_SUBJECT = "rabbit.nav.goal"
MISSION_SUBJECT = "rabbit.nav.mission"
CANCEL_SUBJECT = "rabbit.nav.cancel"
STATE_SUBJECT = "rabbit.nav.state"
POSE_SUBJECT = "rabbit.zed.pose"
OBSTACLE_SUBJECT = "rabbit.zed.obstacle"
ROBOCLAW_SUBJECT = "rabbit.roboclaw"
IMU_SUBJECT = "rabbit.zed.imu"

class Node(RabbitNode):
    CONTROL_INTERVAL = 0.05
    STATE_INTERVAL = 0.1
    ARRIVE_DISTANCE = 0.15
    PATH_ARRIVE_DISTANCE = 0.05
    LOOKAHEAD = 1.0
    CRUISE_SPEED = 0.35
    MANEUVER_SPEED = 0.25
    MIN_SPEED = 0.2
    SAFETY_LOOKAHEAD = 1.0
    SAFETY_STOP = 0.15
    SAFETY_SLOW = 0.6
    SAFETY_RESUME = 0.25
    SEGMENT_END_MARGIN = 0.03
    REVERSE_LOOKAHEAD = 0.5
    REVERSE_STOP = 0.1
    MAX_DIRECTION_FLIPS = 12
    STEP_TIMEOUT = 90.0
    PATH_SECONDS_PER_METRE = 15.0
    PATH_SEARCH_AHEAD = 1.5
    OBSTACLE_MEMORY = 4.0
    BLIND_RANGE = 0.4
    BLIND_MEMORY_MAX = 30.0
    BLOCKED_ARRIVE = 0.12
    BLOCKED_TIMEOUT = 10.0
    SCAN_TIMEOUT = 0.5
    LIDAR_TIMEOUT = 0.3
    STALL_CURRENT = 1.8
    STALL_SPEED = 0.02
    STALL_TIME = 1.0
    STUCK_TIME = 2.5
    BUMP_ACCELERATION = 5.0
    BUMP_GRACE = 0.4
    BUMP_WINDOW = 0.05
    JUMP_DISTANCE = 0.25
    MAX_STEPS = 20
    MAX_MOVE = 3.0
    MAX_GOTO = 8.0
    MAX_TURN_DEG = 360.0
    MAX_PATH_POINTS = 2000
    JUMP_HEADING_DEG = 10.0
    MANEUVER_ENTER_DEG = 100.0
    MANEUVER_EXIT_DEG = 30.0
    MANEUVER_SEGMENT = 0.3
    POSE_TIMEOUT = 0.5
    PATH_STEP = 0.1
    TURN_TOLERANCE_DEG = 8.0
    PATH_LOOKAHEAD = 0.35
    GEAR_SWITCH_TOLERANCE = 0.05
    REVERSE_SPEED = 0.22
    MAX_MESSAGE_AGE = 0.3
    TRACKING_DISTANCE = 0.2
    LATERAL_GAIN = 1.0 / TRACKING_DISTANCE**2
    HEADING_GAIN = 2.0 / TRACKING_DISTANCE
    FEEDFORWARD_SPAN = 0.15
    STEER_RATE = 6.0
    TRACK_SECONDS = 1.0

    def __init__(self):
        super().__init__("nav")
        self.position: np.ndarray | None = None
        self.map_position: np.ndarray | None = None
        self.map_from_control: tuple[np.ndarray, np.ndarray] = (np.eye(2), np.zeros(2))
        self.control_frame = "map"
        self.odom_session: str | None = None
        self.forward: np.ndarray | None = None
        self.pose_at = 0.0
        self.track: deque[tuple[float, np.ndarray, np.ndarray]] = deque()
        self.remembered: deque[tuple[float, np.ndarray]] = deque()
        self.retained_since: float | None = None
        self.bump_window: deque[tuple[float, np.ndarray]] = deque()
        self.scan_at = 0.0
        self.lidar: tuple[float, np.ndarray] | None = None
        self.free = self.SAFETY_LOOKAHEAD
        self.ground_speed = 0.0
        self.blind = False
        self.direction_flips = 0
        self.step_started = 0.0
        self.step_timeout = self.STEP_TIMEOUT
        self.mission_source: str | None = None
        self.motor_current = 0.0
        self.stall_since: float | None = None
        self.stuck_since: float | None = None
        self.fault: str | None = None
        self.hold: str | None = None
        self.mission_id: str | None = None
        self.trip_id: str | None = None
        self.mission_started_at = 0.0
        self.control_at: float | None = None
        self.speed_changed_at = 0.0
        self.holding = False
        self.blocked_since: float | None = None
        self.goal: np.ndarray | None = None
        self.steps: deque[dict] = deque()
        self.step: dict | None = None
        self.step_index = 0
        self.steps_total = 0
        self.turn_remaining: float | None = None
        self.path: np.ndarray | None = None
        self.path_index = 0
        self.last_heading: float | None = None
        self.mode = "idle"
        self.maneuver_direction = 1
        self.segment_start: np.ndarray | None = None
        self.speed = 0.0
        self.steer = 0.0
        self.heading_error = 0.0
        self.distance = 0.0
        self.path_left = 0.0
        self.segment_left = math.inf
        self.steer_at = 0.0

    async def init(self):
        await self.subscribe(POSE_SUBJECT, self.on_pose)
        await self.subscribe(OBSTACLE_SUBJECT, self.on_obstacle)
        await self.subscribe(LIDAR_SUBJECT, self.on_lidar)
        await self.subscribe(ROBOCLAW_SUBJECT, self.on_roboclaw)
        await self.subscribe(IMU_SUBJECT, self.on_imu)
        await self.subscribe(JOY_SUBJECT, self.on_joy)
        await self.subscribe(GOAL_SUBJECT, self.on_goal)
        await self.subscribe(MISSION_SUBJECT, self.on_mission)
        await self.subscribe(CANCEL_SUBJECT, self.on_cancel)
        self.set_interval(self.control, self.CONTROL_INTERVAL, max_parallel=1)
        self.set_interval(self.publish_state, self.STATE_INTERVAL, max_parallel=1)

    def captured_at(self, message: dict, now: float) -> float:
        if "ts" not in message:
            return now
        age = (time.time_ns() - int(message["ts"])) * 1e-9
        return now - min(max(age, 0.0), self.MAX_MESSAGE_AGE)

    def pose_at_time(self, at: float) -> tuple[np.ndarray, np.ndarray]:
        assert self.track
        times = [t for t, _, _ in self.track]
        i = int(np.searchsorted(times, at))
        if i <= 0 or i >= len(self.track):
            _, position, forward = self.track[0 if i <= 0 else -1]
            return position, forward
        (t0, p0, f0), (t1, p1, f1) = self.track[i - 1], self.track[i]
        w = (at - t0) / max(t1 - t0, 1e-9)
        h0, h1 = math.atan2(f0[1], f0[0]), math.atan2(f1[1], f1[0])
        heading = h0 + w * ((h1 - h0 + math.pi) % (2 * math.pi) - math.pi)
        return p0 + w * (p1 - p0), np.array([math.cos(heading), math.sin(heading)])

    async def on_pose(self, msg: Msg):
        pose = json.loads(msg.data)
        map_position, map_forward = planar_pose(pose["translation"], pose["orientation"])
        odom = pose.get("odom")
        if odom is not None:
            position_new, forward_new = planar_pose(odom["translation"], odom["orientation"])
            if odom.get("session") != self.odom_session:
                previous = self.odom_session
                self.odom_session = odom.get("session")
                self.set_log_context(odom_session=self.odom_session)
                if previous is not None:
                    await self.odometry_restarted(previous)
        else:
            position_new, forward_new = map_position, map_forward
        now = time.monotonic()
        captured = self.captured_at(pose, now)
        if self.track and self.position is not None:
            last_at, last_position, last_forward = self.track[-1]
            if captured > last_at:
                step_speed = float(np.linalg.norm(position_new - last_position)) / (captured - last_at)
                self.ground_speed += 0.3 * (min(step_speed, 2.0) - self.ground_speed)
            if odom is None or self.control_frame != "odom":
                if self.reanchor(last_position, last_forward, position_new, forward_new):
                    self.track.clear()
        self.control_frame = "map" if odom is None else "odom"
        if self.track and captured <= self.track[-1][0]:
            captured = self.track[-1][0] + 1e-6
        self.track.append((captured, position_new, forward_new))
        while self.track and captured - self.track[0][0] > self.TRACK_SECONDS:
            self.track.popleft()
        self.map_position = map_position
        self.map_from_control = rigid_transform(position_new, forward_new, map_position, map_forward)
        self.position = position_new
        self.forward = forward_new
        self.pose_at = now

        heading = math.atan2(forward_new[1], forward_new[0])
        if self.turn_remaining is not None and self.last_heading is not None:
            delta = (heading - self.last_heading + math.pi) % (2 * math.pi) - math.pi
            self.turn_remaining -= math.degrees(delta)
        self.last_heading = heading

    async def odometry_restarted(self, previous: str):
        self.event(
            "nav.odometry_reset",
            "the camera started a new odometry session",
            severity="warning",
            message="The camera restarted its odometry, dropping the mission and the remembered obstacles",
            previous_session=previous,
            mode=self.mode,
        )
        self.position = None
        self.forward = None
        self.track.clear()
        self.last_heading = None
        self.remembered.clear()
        self.lidar = None
        self.retained_since = None
        await self.trip("odometry reset")

    def reanchor(self, position: np.ndarray, forward: np.ndarray, new_position: np.ndarray, new_forward: np.ndarray) -> bool:
        rotation = math.atan2(
            forward[0] * new_forward[1] - forward[1] * new_forward[0], forward @ new_forward
        )
        jump = float(np.linalg.norm(new_position - position))
        if jump < self.JUMP_DISTANCE and abs(math.degrees(rotation)) < self.JUMP_HEADING_DEG:
            return False
        self.event(
            "nav.pose_jump",
            "the map pose jumped, re-anchoring the mission",
            severity="warning",
            message=f"Pose jump {jump:.2f} m / {math.degrees(rotation):.1f} deg, re-anchoring the mission",
            jump_m=jump,
            rotation_deg=math.degrees(rotation),
            frame=self.control_frame,
            mode=self.mode,
        )
        cos, sin = math.cos(rotation), math.sin(rotation)
        rotate = np.array([[cos, sin], [-sin, cos]])

        def move(points) -> np.ndarray:
            return new_position + (np.asarray(points, dtype=float) - position) @ rotate

        self.remembered = deque((at, move(points)) for at, points in self.remembered)
        if self.lidar is not None:
            self.lidar = (self.lidar[0], move(self.lidar[1]))
        if self.goal is not None:
            self.goal = move(self.goal)
        if self.path is not None:
            self.path[:, :2] = move(self.path[:, :2])
            if self.path.shape[1] > 3:
                self.path[:, 3] += rotation
        if self.segment_start is not None:
            self.segment_start = move(self.segment_start)
        for step in self.steps:
            if step["type"] == "goto":
                step["x"], step["z"] = (float(v) for v in move([step["x"], step["z"]]))
            elif step["type"] == "path":
                points = np.array(step["points"], dtype=float)
                points[:, :2] = move(points[:, :2])
                step["points"] = points.tolist()
        if self.last_heading is not None:
            self.last_heading += rotation
        return True

    def rear_axle(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        assert self.position is not None and self.forward is not None
        right = np.array([-self.forward[1], self.forward[0]])
        return rear_axle_point(self.position, self.forward), self.forward, right

    def obstacles(self) -> np.ndarray:
        now = time.monotonic()
        cutoff = now - self.OBSTACLE_MEMORY
        unseen = []
        expired = False
        while self.remembered and self.remembered[0][0] < cutoff:
            expired = True
            _, points = self.remembered.popleft()
            if self.position is not None and self.forward is not None:
                sensor = rear_axle_point(self.position, self.forward) + CAMERA_TO_REAR_AXLE * self.forward
                unseen.append(points[np.linalg.norm(points - sensor, axis=1) < self.BLIND_RANGE])
        if expired:
            if unseen and sum(len(points) for points in unseen):
                self.retained_since = self.retained_since or now
                if now - self.retained_since <= self.BLIND_MEMORY_MAX:
                    self.remembered.append((now, np.concatenate(unseen)))
            else:
                self.retained_since = None
        seen = [points for _, points in self.remembered]
        if self.lidar is not None and now - self.lidar[0] <= self.LIDAR_TIMEOUT:
            seen.append(self.lidar[1])
        if not seen or self.position is None:
            return np.empty((0, 2))
        origin, forward, right = self.rear_axle()
        world = np.concatenate(seen) - origin
        return np.stack([world @ forward, world @ right], axis=1)

    async def on_obstacle(self, msg: Msg):
        message = json.loads(msg.data)
        scan = message.get("scan")
        if scan is None or self.position is None or not self.track:
            return
        self.blind = bool(scan.get("blind"))
        local = scan_points(scan)
        position, forward = self.pose_at_time(self.captured_at(message, time.monotonic()))
        right = np.array([-forward[1], forward[0]])
        origin = rear_axle_point(position, forward)
        world = origin + np.outer(local[:, 0], forward) + np.outer(local[:, 1], right)
        self.remembered.append((time.monotonic(), world))
        self.scan_at = time.monotonic()

    def poses_at(self, at: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        times = np.array([t for t, _, _ in self.track])
        positions = np.array([p for _, p, _ in self.track])
        headings = np.unwrap([math.atan2(f[1], f[0]) for _, _, f in self.track])
        heading = np.interp(at, times, headings)
        position = np.stack([np.interp(at, times, positions[:, 0]), np.interp(at, times, positions[:, 1])], axis=1)
        return position, np.stack([np.cos(heading), np.sin(heading)], axis=1)

    async def on_lidar(self, msg: Msg):
        if self.position is None or not self.track:
            return
        scan = decode_scan(msg.data)
        now = time.monotonic()
        ages = np.clip((time.time_ns() - point_times(scan)) * 1e-9, 0.0, self.MAX_MESSAGE_AGE)
        position, forward = self.poses_at(now - ages)
        right = np.stack([-forward[:, 1], forward[:, 0]], axis=1)
        local = points_xy(scan)
        origin = rear_axle_point(position, forward)
        self.lidar = (now, origin + local[:, :1] * forward - local[:, 1:] * right)

    async def on_roboclaw(self, msg: Msg):
        data = json.loads(msg.data)
        self.motor_current = max(abs(data["left"]["current"]), abs(data["right"]["current"]))
        moving_command = abs(self.speed) >= self.MIN_SPEED
        stalled = moving_command and self.motor_current > self.STALL_CURRENT and self.ground_speed < self.STALL_SPEED
        if not stalled:
            self.stall_since = None
        elif self.stall_since is None:
            self.stall_since = time.monotonic()
        elif time.monotonic() - self.stall_since > self.STALL_TIME:
            await self.trip("stall", motor_current_a=self.motor_current, ground_speed_mps=self.ground_speed, stall_s=time.monotonic() - self.stall_since, stall_current_a=self.STALL_CURRENT)
            return
        now = time.monotonic()
        stuck = (
            moving_command
            and self.ground_speed < self.STALL_SPEED
            and now - self.pose_at < self.POSE_TIMEOUT
            and now - self.speed_changed_at > self.BUMP_GRACE
        )
        if not stuck:
            self.stuck_since = None
        elif self.stuck_since is None:
            self.stuck_since = now
        elif now - self.stuck_since > self.STUCK_TIME:
            await self.trip("stuck", motor_current_a=self.motor_current, ground_speed_mps=self.ground_speed, stuck_s=now - self.stuck_since, reversing=self.speed < 0)

    async def on_imu(self, msg: Msg):
        imu = json.loads(msg.data)
        linear = linear_acceleration(imu["acceleration"], imu["orientation"])
        now = time.monotonic()
        self.bump_window.append((now, linear))
        while self.bump_window and now - self.bump_window[0][0] > self.BUMP_WINDOW:
            self.bump_window.popleft()
        mean = np.mean([sample for _, sample in self.bump_window], axis=0)
        steady = now - self.speed_changed_at > self.BUMP_GRACE
        if abs(self.speed) > 0 and steady and math.hypot(mean[0], mean[2]) > self.BUMP_ACCELERATION:
            await self.trip("collision", accel_mps2=math.hypot(mean[0], mean[2]), threshold_mps2=self.BUMP_ACCELERATION, samples=len(self.bump_window))

    async def on_joy(self, msg: Msg):
        if self.mode in ("idle", "arrived", "fault"):
            return
        if is_active(*parse_joy(json.loads(msg.data))):
            self.event("nav.manual_override", "gamepad input during a mission", severity="warning", message="Manual override, cancelling the mission", mode=self.mode)
            self.steps.clear()
            self.finish_step()
            self.mode = "idle"
            self.fault = "manual override"
            self.end_mission()

    async def trip(self, fault: str, **details):
        if self.mode in ("idle", "arrived", "fault"):
            return
        self.fault = fault
        context = {
            "fault": fault,
            "mode": self.mode,
            "step_type": None if self.step is None else self.step.get("type"),
            "step_index": self.step_index,
            "free_distance_m": self.free,
            "speed": self.speed,
            "steer": self.steer,
            "ground_speed_mps": self.ground_speed,
            "distance_to_goal_m": self.distance,
            "mission_s": time.monotonic() - self.mission_started_at,
        }
        self.event("nav.safety_stop", fault, severity="warning", message=f"Safety stop: {fault}", **{**context, **details})
        self.steps.clear()
        self.finish_step()
        self.mode = "fault"
        await self.command(0.0, 0.0)
        self.end_mission()

    async def on_goal(self, msg: Msg):
        goal = json.loads(msg.data)
        steps = [{"type": "goto", "x": goal["x"], "z": goal["z"]}]
        problem = self.validate_mission(steps)
        if problem is not None:
            self.event("nav.mission_rejected", problem, severity="error", message=f"Rejected goal: {problem}", source=goal.get("source"))
            self.fault = f"rejected: {problem}"
            return
        self.start_mission(steps, source=goal.get("source"))

    async def on_mission(self, msg: Msg):
        request = json.loads(msg.data)
        steps = request["steps"]
        problem = self.validate_mission(steps)
        if problem is not None:
            self.event(
                "nav.mission_rejected",
                problem,
                severity="error",
                message=f"Rejected mission: {problem}",
                source=request.get("source"),
                rejected_mission=request.get("id"),
                trip_id=request.get("trip_id"),
            )
            self.fault = f"rejected: {problem}"
            return
        self.start_mission(steps, request.get("id"), request.get("source"), request.get("trip_id"))

    def validate_mission(self, steps: list[dict]) -> str | None:
        if not 0 < len(steps) <= self.MAX_STEPS:
            return f"mission must have 1-{self.MAX_STEPS} steps"
        for step in steps:
            kind = step.get("type")
            if kind == "move" and math.hypot(float(step.get("forward", 0)), float(step.get("right", 0))) > self.MAX_MOVE:
                return f"move longer than {self.MAX_MOVE} m"
            if kind == "turn" and abs(float(step.get("degrees", 0))) > self.MAX_TURN_DEG:
                return f"turn larger than {self.MAX_TURN_DEG} deg"
            if kind == "goto" and self.map_position is not None:
                if math.hypot(float(step["x"]) - self.map_position[0], float(step["z"]) - self.map_position[1]) > self.MAX_GOTO:
                    return f"goto farther than {self.MAX_GOTO} m"
            if kind == "path" and not 0 < len(step.get("points", [])) <= self.MAX_PATH_POINTS:
                return f"path must have 1-{self.MAX_PATH_POINTS} points"
            if kind not in ("move", "turn", "goto", "path"):
                return f"unknown step type {kind}"
        return None

    async def on_cancel(self, msg: Msg):
        request = json.loads(msg.data or b"{}")
        if self.mode not in ("idle", "arrived", "fault"):
            source = request.get("source") or "unknown"
            self.event(
                "nav.mission_cancelled",
                f"cancelled by {source}",
                message="Mission cancelled",
                source=source,
                mode=self.mode,
                distance_to_goal_m=self.distance,
                mission_s=time.monotonic() - self.mission_started_at,
            )
        self.steps.clear()
        self.finish_step()
        self.mode = "idle"
        await self.command(0.0, 0.0)
        self.end_mission()

    def start_mission(self, steps: list[dict], mission_id: str | None = None, source: str | None = None, trip_id: str | None = None):
        replaced = self.mission_id if self.mode not in ("idle", "arrived", "fault") else None
        self.steps = deque(steps)
        self.mission_source = source
        self.steps_total = len(steps)
        self.step_index = 0
        self.finish_step()
        self.fault = None
        self.stall_since = None
        self.blocked_since = None
        self.holding = False
        self.mode = "driving"
        self.hold = None
        self.mission_id = mission_id or time_id()
        self.trip_id = trip_id
        self.mission_started_at = time.monotonic()
        self.set_log_context(mission_id=self.mission_id, trip_id=trip_id)
        self.event(
            "nav.mission_started",
            f"from {source or 'unknown'}",
            message=f"New mission with {len(steps)} steps",
            source=source,
            steps=len(steps),
            step_types=[step.get("type") for step in steps],
            path_points=sum(len(step.get("points", [])) for step in steps),
            replaced_mission=replaced,
        )

    def end_mission(self):
        self.hold = None
        self.set_log_context(mission_id=None, trip_id=None)

    def finish_step(self):
        self.step = None
        self.goal = None
        self.turn_remaining = None
        self.path = None
        self.path_left = 0.0
        self.segment_left = math.inf

    def begin_next_step(self) -> bool:
        if not self.steps:
            return False
        assert self.position is not None and self.forward is not None
        self.step = self.steps.popleft()
        self.step_index += 1
        self.step_started = time.monotonic()
        self.step_timeout = self.STEP_TIMEOUT
        self.direction_flips = 0
        right = np.array([-self.forward[1], self.forward[0]])
        kind = self.step["type"]
        if kind == "goto":
            self.goal = self.to_control(np.array([float(self.step["x"]), float(self.step["z"])]))
        elif kind == "move":
            self.goal = (
                self.position
                + float(self.step.get("forward", 0.0)) * self.forward
                + float(self.step.get("right", 0.0)) * right
            )
        elif kind == "path":
            self.path = np.array(self.step["points"], dtype=float)
            self.path[:, :2] = self.to_control(self.path[:, :2])
            if self.path.shape[1] > 3:
                rotation = self.map_from_control[0]
                self.path[:, 3] -= math.atan2(rotation[1, 0], rotation[0, 0])
            self.path_index = 0
            self.goal = self.path[-1, :2].copy()
            length = float(np.linalg.norm(np.diff(self.path[:, :2], axis=0), axis=1).sum())
            self.step_timeout = max(self.STEP_TIMEOUT, self.PATH_SECONDS_PER_METRE * length)
        elif kind == "turn":
            self.turn_remaining = float(self.step["degrees"])
            self.segment_start = self.position.copy()
            self.maneuver_direction = 1
        else:
            self.logger.error(f"Unknown mission step {self.step}")
            self.step = None
            return self.begin_next_step()
        self.mode = "maneuvering" if kind == "turn" else "driving"
        return True

    def govern(self, speed: float, steer: float) -> float:
        if speed == 0:
            return 0.0
        if time.monotonic() - self.scan_at > self.SCAN_TIMEOUT:
            self.free = 0.0
            return self.held("no fresh scan", scan_age_s=time.monotonic() - self.scan_at)
        if speed < 0:
            self.free = free_distance(self.obstacles(), curvature_for_steer(steer), self.REVERSE_LOOKAHEAD, direction=-1)
            return self.held("obstacle behind", stop_m=self.REVERSE_STOP) if self.free < self.REVERSE_STOP else self.released(speed)
        if self.blind:
            self.free = 0.0
            return self.held("blind")
        self.free = free_distance(self.obstacles(), curvature_for_steer(steer), self.SAFETY_LOOKAHEAD)
        stop = min(self.SAFETY_STOP, self.segment_left + self.SEGMENT_END_MARGIN)
        if self.free < stop:
            self.holding = True
        elif self.free >= stop + self.SAFETY_RESUME - self.SAFETY_STOP:
            self.holding = False
        if self.holding:
            return self.held("obstacle ahead", stop_m=stop)
        if self.free < self.SAFETY_SLOW:
            return self.released(min(speed, self.MIN_SPEED))
        return self.released(speed)

    def held(self, reason: str, **details) -> float:
        if reason != self.hold:
            self.event(
                "nav.hold",
                reason,
                every_s=2.0,
                message=f"Holding: {reason}",
                free_distance_m=self.free,
                steer=self.steer,
                mode=self.mode,
                distance_to_goal_m=self.distance,
                **details,
            )
        self.hold = reason
        return 0.0

    def released(self, speed: float) -> float:
        self.hold = None
        return speed

    async def command(self, speed: float, steer: float) -> bool:
        allowed = self.govern(speed, steer)
        if abs(allowed - self.speed) > 0.05:
            self.speed_changed_at = time.monotonic()
        self.speed = allowed
        self.steer = steer
        await self.publish_json(DRIVE_SUBJECT, {"speed": allowed, "steer": steer, "source": "nav"})
        return allowed == speed

    async def control(self):
        started = time.monotonic()
        if self.control_at is not None:
            self.observe("control_period_ms", (started - self.control_at) * 1000.0)
        self.control_at = started
        try:
            await self.control_step()
        except Exception as e:
            self.logger.exception("Navigation control failed")
            await self.trip("control error", error=repr(e))
        self.observe("control_ms", (time.monotonic() - started) * 1000.0)

    async def control_step(self):
        if self.mode in ("idle", "arrived", "fault"):
            return
        if self.step is not None and time.monotonic() - self.step_started > self.step_timeout:
            await self.trip("step timeout", step_s=time.monotonic() - self.step_started, step_timeout_s=self.step_timeout)
            return
        if self.position is None or self.forward is None or time.monotonic() - self.pose_at > self.POSE_TIMEOUT:
            if self.position is not None:
                self.held("no fresh pose", pose_age_s=time.monotonic() - self.pose_at)
            await self.command(0.0, 0.0)
            return
        if self.step is None and not self.begin_next_step():
            self.mode = "arrived"
            self.event(
                "nav.mission_arrived",
                "all steps done",
                message="Mission arrived",
                mission_s=time.monotonic() - self.mission_started_at,
                steps=self.steps_total,
                distance_to_goal_m=self.distance,
            )
            await self.command(0.0, 0.0)
            self.end_mission()
            return

        if self.turn_remaining is not None:
            self.heading_error = self.turn_remaining
            self.distance = 0.0
            if abs(self.turn_remaining) < self.TURN_TOLERANCE_DEG:
                self.finish_step()
                await self.command(0.0, 0.0)
                return
            self.mode = "maneuvering"
            await self.maneuver()
            return
        if self.path is not None:
            await self.follow_path()
            return
        assert self.goal is not None

        offset = self.goal - self.position
        self.distance = float(np.linalg.norm(offset))
        right = np.array([-self.forward[1], self.forward[0]])
        along = float(offset @ self.forward)
        across = float(offset @ right)
        self.heading_error = math.degrees(math.atan2(across, along))

        if self.distance < self.ARRIVE_DISTANCE:
            self.finish_step()
            await self.command(0.0, 0.0)
            return

        needs_turn = abs(self.heading_error) > self.MANEUVER_ENTER_DEG or (
            abs(self.heading_error) > 45.0 and self.distance < 2.0 / MAX_CURVATURE
        )
        if self.mode != "maneuvering" and needs_turn:
            self.mode = "maneuvering"
            self.maneuver_direction = 1
            self.segment_start = self.position.copy()
        if self.mode == "maneuvering" and abs(self.heading_error) < self.MANEUVER_EXIT_DEG:
            self.mode = "driving"

        if self.mode == "maneuvering":
            await self.maneuver()
            return

        lookahead = min(self.distance, self.LOOKAHEAD)
        curvature = 2.0 * math.sin(math.radians(self.heading_error)) / lookahead
        steer = steer_for_curvature(curvature)
        speed = max(self.MIN_SPEED, self.CRUISE_SPEED * (1.0 - min(abs(steer), 1.0) * 0.3))
        await self.drive(speed, steer)

    async def drive(self, speed: float, steer: float):
        allowed = await self.command(speed, steer)
        if allowed or self.speed != 0:
            self.mode = "driving"
            self.blocked_since = None
            return
        self.mode = "blocked"
        if not self.steps and max(self.distance, self.path_left) <= self.BLOCKED_ARRIVE:
            self.event(
                "nav.blocked_at_goal",
                "blocked within reach of the goal, counting it as arrived",
                message=f"Blocked {self.distance:.2f} m from the goal, counting it as arrived",
                distance_to_goal_m=self.distance,
                path_left_m=self.path_left,
                free_distance_m=self.free,
            )
            self.finish_step()
            self.blocked_since = None
            return
        if self.blocked_since is None:
            self.blocked_since = time.monotonic()
        elif time.monotonic() - self.blocked_since > self.BLOCKED_TIMEOUT:
            blocked_s = time.monotonic() - self.blocked_since
            self.blocked_since = None
            await self.trip("blocked", blocked_s=blocked_s, hold=self.hold)

    async def follow_path(self):
        assert self.path is not None and self.position is not None and self.forward is not None
        directions = self.path[:, 2]
        position, _, _ = self.rear_axle()
        points = self.rear_axle_points()
        direction = directions[self.path_index]
        switch = next((i for i in range(self.path_index, len(points)) if directions[i] != direction), len(points))
        segment_end = switch - 1
        motion = self.forward * direction
        end_offset = points[segment_end] - position
        end_distance = float(np.linalg.norm(end_offset))
        along_path = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
        segment_left = along_path[segment_end] - along_path[self.path_index]
        passed = segment_left < self.PATH_LOOKAHEAD and end_distance < self.PATH_LOOKAHEAD and float(end_offset @ motion) <= 0.0
        self.distance = float(np.linalg.norm(points[-1] - position))
        self.path_left = float(along_path[-1] - along_path[self.path_index])
        if switch == len(points) and segment_left < self.PATH_LOOKAHEAD and (self.distance < self.PATH_ARRIVE_DISTANCE or passed):
            self.finish_step()
            await self.command(0.0, 0.0)
            return
        window = points[self.path_index : segment_end + 1]
        along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(window, axis=0), axis=1))])
        window = window[: max(1, int(np.searchsorted(along, self.PATH_SEARCH_AHEAD, side="right")))]
        nearest = self.path_index + int(np.argmin(np.linalg.norm(window - position, axis=1)))
        self.path_index = nearest
        self.segment_left = float(along_path[segment_end] - along_path[nearest])
        if switch < len(points) and (end_distance < self.GEAR_SWITCH_TOLERANCE or passed):
            self.path_index = switch
            await self.command(0.0, 0.0)
            return

        first = max(nearest - 1, self.first_of_segment(directions, nearest))
        if segment_end > first:
            curvature = self.tracking_curvature(points[first : segment_end + 1], self.motion_headings(points, first, segment_end), position, motion)
            steer = self.rate_limited(steer_for_curvature(curvature * direction))
        else:
            steer = self.steer
        if direction > 0:
            await self.drive(max(self.MIN_SPEED, self.CRUISE_SPEED * (1.0 - min(abs(steer), 1.0) * 0.3)), steer)
        else:
            await self.drive(-self.REVERSE_SPEED, steer)

    def rear_axle_points(self) -> np.ndarray:
        assert self.path is not None and self.forward is not None
        if self.path.shape[1] > 3:
            return rear_axle_point(self.path[:, :2], np.stack([np.cos(self.path[:, 3]), np.sin(self.path[:, 3])], axis=1))
        return rear_axle_path(self.path[:, :2], self.path[:, 2], self.forward)

    @staticmethod
    def first_of_segment(directions: np.ndarray, index: int) -> int:
        start = index
        while start > 0 and directions[start - 1] == directions[index]:
            start -= 1
        return start

    def motion_headings(self, points: np.ndarray, first: int, last: int) -> np.ndarray:
        assert self.path is not None
        direction = self.path[first, 2]
        if self.path.shape[1] > 3:
            return self.path[first : last + 1, 3] + (math.pi if direction < 0 else 0.0)
        span = points[first : last + 1]
        ahead = np.diff(span, axis=0, append=span[-1:]) + np.diff(span, axis=0, prepend=span[:1])
        return np.arctan2(ahead[:, 1], ahead[:, 0])

    def tracking_curvature(self, points: np.ndarray, headings: np.ndarray, position: np.ndarray, motion: np.ndarray) -> float:
        steps = np.diff(points, axis=0)
        lengths = np.maximum(np.linalg.norm(steps, axis=1), 1e-9)
        tangents = steps / lengths[:, None]
        offsets = position - points[:-1]
        along = np.clip(np.einsum("ij,ij->i", offsets, tangents), 0.0, lengths)
        gaps = np.linalg.norm(points[:-1] + along[:, None] * tangents - position, axis=1)
        i = int(np.argmin(gaps))
        travelled = np.concatenate([[0.0], np.cumsum(lengths)])
        unwrapped = np.unwrap(headings)
        here = travelled[i] + along[i]
        path_heading = float(np.interp(here, travelled, unwrapped))
        lateral = float((position - points[i] - along[i] * tangents[i]) @ np.array([-math.sin(path_heading), math.cos(path_heading)]))
        heading_error = (math.atan2(motion[1], motion[0]) - path_heading + math.pi) % (2 * math.pi) - math.pi
        ahead = min(here + self.FEEDFORWARD_SPAN, travelled[-1])
        back = max(ahead - self.FEEDFORWARD_SPAN, 0.0)
        path_curvature = float(np.interp(ahead, travelled, unwrapped) - np.interp(back, travelled, unwrapped)) / max(ahead - back, 1e-6)
        self.heading_error = math.degrees(heading_error)
        sinc = 1.0 if abs(heading_error) < 1e-6 else math.sin(heading_error) / heading_error
        return (
            path_curvature * math.cos(heading_error) / max(1.0 - path_curvature * lateral, 0.2)
            - self.HEADING_GAIN * heading_error
            - self.LATERAL_GAIN * lateral * sinc
        )

    def rate_limited(self, steer: float) -> float:
        now = time.monotonic()
        step = self.STEER_RATE * min(max(now - self.steer_at, 0.0), 0.2)
        self.steer_at = now
        return float(np.clip(steer, self.steer - step, self.steer + step))

    async def maneuver(self):
        assert self.position is not None and self.segment_start is not None
        travelled = float(np.linalg.norm(self.position - self.segment_start))
        if travelled > self.MANEUVER_SEGMENT:
            await self.flip_direction()
            if self.mode == "fault":
                return

        turn = math.copysign(1.0, self.heading_error)
        allowed = await self.command(
            self.MANEUVER_SPEED * self.maneuver_direction, turn * self.maneuver_direction
        )
        if not allowed and self.speed == 0:
            await self.flip_direction()

    async def flip_direction(self):
        assert self.position is not None
        self.direction_flips += 1
        if self.direction_flips > self.MAX_DIRECTION_FLIPS:
            await self.trip("manoeuvre failed", direction_flips=self.direction_flips, turn_remaining_deg=self.turn_remaining)
            return
        self.maneuver_direction = -self.maneuver_direction
        self.segment_start = self.position.copy()

    def to_control(self, points: np.ndarray) -> np.ndarray:
        rotation, translation = self.map_from_control
        return (np.asarray(points, dtype=float) - translation) @ rotation

    def to_map(self, points: np.ndarray) -> np.ndarray:
        rotation, translation = self.map_from_control
        return np.asarray(points, dtype=float) @ rotation.T + translation

    def predicted_path(self) -> list[list[float]]:
        path = self.control_path()
        return self.to_map(np.array(path)).round(3).tolist() if path else []

    def control_path(self) -> list[list[float]]:
        if self.position is None or self.forward is None or self.goal is None:
            return []
        if self.path is not None:
            return self.path[self.path_index :, :2].round(3).tolist()
        if self.mode != "driving":
            return [self.position.round(3).tolist(), self.goal.round(3).tolist()]
        heading = math.atan2(self.forward[1], self.forward[0])
        curvature = curvature_for_steer(self.steer)
        point = self.position.copy()
        path = [point.round(3).tolist()]
        for _ in range(int(min(self.distance, 3.0) / self.PATH_STEP)):
            heading += curvature * self.PATH_STEP
            point = point + self.PATH_STEP * np.array([math.cos(heading), math.sin(heading)])
            path.append(point.round(3).tolist())
        return path

    async def publish_state(self):
        await self.publish_json(
            STATE_SUBJECT,
            {
                "mode": self.mode,
                "goal": None if self.goal is None else dict(zip(("x", "z"), (round(float(v), 3) for v in self.to_map(self.goal)))),
                "step": self.step,
                "step_index": self.step_index,
                "steps_total": self.steps_total,
                "queue": list(self.steps),
                "turn_remaining_deg": None if self.turn_remaining is None else round(self.turn_remaining, 1),
                "path": self.predicted_path(),
                "path_index": self.path_index if self.path is not None else None,
                "path_direction": int(self.path[self.path_index, 2]) if self.path is not None else None,
                "distance_to_goal": round(self.distance, 3),
                "heading_error_deg": round(self.heading_error, 1),
                "speed": round(self.speed, 3),
                "free_distance": round(self.free, 3),
                "fault": self.fault,
                "hold": self.hold,
                "mission_id": self.mission_id,
                "mission_source": self.mission_source,
                "trip_id": self.trip_id,
                "steer": round(self.steer, 3),
            },
        )

    async def close(self):
        await self.command(0.0, 0.0)


if __name__ == "__main__":
    Node().run_node()
