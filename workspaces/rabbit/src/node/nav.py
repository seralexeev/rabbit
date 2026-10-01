import json
import math
import time
from collections import deque

import numpy as np
from lib.drive import DRIVE_SUBJECT, HEARTBEAT_SUBJECT, JOY_SUBJECT, is_active, parse_joy
from lib.log import time_id
from lib.node import RabbitNode
from lib.geometry import (
    MAX_CURVATURE,
    curvature_for_steer,
    linear_acceleration,
    rear_axle_path,
    rear_axle_point,
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
    CRUISE_SPEED = 0.25
    MANEUVER_SPEED = 0.25
    MIN_SPEED = 0.2
    SAFETY_LOOKAHEAD = 1.0
    SAFETY_STOP = 0.3
    SAFETY_SLOW = 0.6
    SAFETY_RESUME = 0.45
    REVERSE_LOOKAHEAD = 0.5
    REVERSE_STOP = 0.1
    MAX_DIRECTION_FLIPS = 12
    STEP_TIMEOUT = 90.0
    OBSTACLE_MEMORY = 4.0
    BLOCKED_TIMEOUT = 10.0
    SCAN_TIMEOUT = 0.5
    STALL_CURRENT = 1.8
    STALL_SPEED = 0.02
    STALL_TIME = 1.0
    BUMP_ACCELERATION = 5.0
    BUMP_GRACE = 0.4
    JUMP_DISTANCE = 0.25
    OPERATOR_TIMEOUT = 3.0
    MAX_STEPS = 20
    MAX_MOVE = 3.0
    MAX_GOTO = 8.0
    MAX_TURN_DEG = 360.0
    MAX_PATH_POINTS = 2000
    OPERATOR_PRESENCE = 60.0
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

    def __init__(self):
        super().__init__("nav")
        self.position: np.ndarray | None = None
        self.forward: np.ndarray | None = None
        self.pose_at = 0.0
        self.remembered: deque[tuple[float, np.ndarray]] = deque()
        self.scan_at = 0.0
        self.free = self.SAFETY_LOOKAHEAD
        self.ground_speed = 0.0
        self.blind = False
        self.direction_flips = 0
        self.step_started = 0.0
        self.imu_orientation: list[float] | None = None
        self.motor_current = 0.0
        self.stall_since: float | None = None
        self.fault: str | None = None
        self.mission_id: str | None = None
        self.speed_changed_at = 0.0
        self.holding = False
        self.blocked_since: float | None = None
        self.operator_at: float | None = None
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

    async def init(self):
        await self.subscribe(POSE_SUBJECT, self.on_pose)
        await self.subscribe(OBSTACLE_SUBJECT, self.on_obstacle)
        await self.subscribe(ROBOCLAW_SUBJECT, self.on_roboclaw)
        await self.subscribe(IMU_SUBJECT, self.on_imu)
        await self.subscribe(JOY_SUBJECT, self.on_joy)
        await self.subscribe(HEARTBEAT_SUBJECT, self.on_heartbeat)
        await self.subscribe(GOAL_SUBJECT, self.on_goal)
        await self.subscribe(MISSION_SUBJECT, self.on_mission)
        await self.subscribe(CANCEL_SUBJECT, self.on_cancel)
        self.set_interval(self.control, self.CONTROL_INTERVAL, max_parallel=1)
        self.set_interval(self.publish_state, self.STATE_INTERVAL, max_parallel=1)

    async def on_pose(self, msg: Msg):
        pose = json.loads(msg.data)
        x, y, z, w = pose["orientation"]
        forward = np.array([-2 * (x * z + y * w), -2 * (y * z - x * w), -(1 - 2 * (x * x + y * y))])
        flat = np.array([forward[0], forward[2]])
        forward_new = flat / np.linalg.norm(flat)
        position_new = np.array([pose["translation"][0], pose["translation"][2]])
        now = time.monotonic()
        if self.position is not None and self.forward is not None:
            if now > self.pose_at:
                step_speed = float(np.linalg.norm(position_new - self.position)) / (now - self.pose_at)
                self.ground_speed += 0.3 * (min(step_speed, 2.0) - self.ground_speed)
            self.reanchor(self.position, self.forward, position_new, forward_new)
        self.forward = forward_new
        self.position = position_new
        self.pose_at = now

        heading = math.atan2(self.forward[1], self.forward[0])
        if self.turn_remaining is not None and self.last_heading is not None:
            delta = (heading - self.last_heading + math.pi) % (2 * math.pi) - math.pi
            self.turn_remaining -= math.degrees(delta)
        self.last_heading = heading

    def reanchor(self, position: np.ndarray, forward: np.ndarray, new_position: np.ndarray, new_forward: np.ndarray):
        rotation = math.atan2(
            forward[0] * new_forward[1] - forward[1] * new_forward[0], forward @ new_forward
        )
        jump = float(np.linalg.norm(new_position - position))
        if jump < self.JUMP_DISTANCE and abs(math.degrees(rotation)) < self.JUMP_HEADING_DEG:
            return
        self.logger.warning(f"Pose jump {jump:.2f} m / {math.degrees(rotation):.1f} deg, re-anchoring the mission")
        cos, sin = math.cos(rotation), math.sin(rotation)
        rotate = np.array([[cos, sin], [-sin, cos]])

        def move(points) -> np.ndarray:
            return new_position + (np.asarray(points, dtype=float) - position) @ rotate

        self.remembered = deque((at, move(points)) for at, points in self.remembered)
        if self.goal is not None:
            self.goal = move(self.goal)
        if self.path is not None:
            self.path[:, :2] = move(self.path[:, :2])
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

    def rear_axle(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        assert self.position is not None and self.forward is not None
        right = np.array([-self.forward[1], self.forward[0]])
        return rear_axle_point(self.position, self.forward), self.forward, right

    def obstacles(self) -> np.ndarray:
        cutoff = time.monotonic() - self.OBSTACLE_MEMORY
        while self.remembered and self.remembered[0][0] < cutoff:
            self.remembered.popleft()
        if not self.remembered or self.position is None:
            return np.empty((0, 2))
        origin, forward, right = self.rear_axle()
        world = np.concatenate([points for _, points in self.remembered]) - origin
        return np.stack([world @ forward, world @ right], axis=1)

    async def on_obstacle(self, msg: Msg):
        scan = json.loads(msg.data).get("scan")
        if scan is None or self.position is None:
            return
        self.blind = bool(scan.get("blind"))
        local = scan_points(scan)
        origin, forward, right = self.rear_axle()
        world = origin + np.outer(local[:, 0], forward) + np.outer(local[:, 1], right)
        self.remembered.append((time.monotonic(), world))
        self.scan_at = time.monotonic()

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
            await self.trip("stall")

    async def on_imu(self, msg: Msg):
        imu = json.loads(msg.data)
        linear = linear_acceleration(imu["acceleration"], imu["orientation"])
        steady = time.monotonic() - self.speed_changed_at > self.BUMP_GRACE
        if abs(self.speed) > 0 and steady and math.hypot(linear[0], linear[2]) > self.BUMP_ACCELERATION:
            await self.trip("collision")

    async def on_joy(self, msg: Msg):
        if self.mode in ("idle", "arrived", "fault"):
            return
        if is_active(*parse_joy(json.loads(msg.data))):
            self.logger.warning("Manual override, cancelling the mission")
            self.steps.clear()
            self.finish_step()
            self.mode = "idle"
            self.fault = "manual override"
            self.end_mission()

    async def on_heartbeat(self, msg: Msg):
        self.operator_at = time.monotonic()

    def operator_lost(self) -> bool:
        if self.operator_at is None:
            return False
        silence = time.monotonic() - self.operator_at
        return self.OPERATOR_TIMEOUT < silence < self.OPERATOR_PRESENCE

    async def trip(self, fault: str):
        if self.mode in ("idle", "arrived", "fault"):
            return
        self.fault = fault
        self.logger.warning("Safety stop: %s", fault, extra={"fault": fault})
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
            self.logger.error(f"Rejected goal: {problem}")
            self.fault = f"rejected: {problem}"
            return
        self.start_mission(steps)

    async def on_mission(self, msg: Msg):
        request = json.loads(msg.data)
        steps = request["steps"]
        problem = self.validate_mission(steps)
        if problem is not None:
            self.logger.error(f"Rejected mission: {problem}")
            self.fault = f"rejected: {problem}"
            return
        self.start_mission(steps, request.get("id"))

    def validate_mission(self, steps: list[dict]) -> str | None:
        if not 0 < len(steps) <= self.MAX_STEPS:
            return f"mission must have 1-{self.MAX_STEPS} steps"
        for step in steps:
            kind = step.get("type")
            if kind == "move" and math.hypot(float(step.get("forward", 0)), float(step.get("right", 0))) > self.MAX_MOVE:
                return f"move longer than {self.MAX_MOVE} m"
            if kind == "turn" and abs(float(step.get("degrees", 0))) > self.MAX_TURN_DEG:
                return f"turn larger than {self.MAX_TURN_DEG} deg"
            if kind == "goto" and self.position is not None:
                if math.hypot(float(step["x"]) - self.position[0], float(step["z"]) - self.position[1]) > self.MAX_GOTO:
                    return f"goto farther than {self.MAX_GOTO} m"
            if kind == "path" and not 0 < len(step.get("points", [])) <= self.MAX_PATH_POINTS:
                return f"path must have 1-{self.MAX_PATH_POINTS} points"
            if kind not in ("move", "turn", "goto", "path"):
                return f"unknown step type {kind}"
        return None

    async def on_cancel(self, msg: Msg):
        if self.mode not in ("idle", "arrived", "fault"):
            self.logger.info("Mission cancelled")
        self.steps.clear()
        self.finish_step()
        self.mode = "idle"
        await self.command(0.0, 0.0)
        self.end_mission()

    def start_mission(self, steps: list[dict], mission_id: str | None = None):
        self.steps = deque(steps)
        self.steps_total = len(steps)
        self.step_index = 0
        self.finish_step()
        self.fault = None
        self.stall_since = None
        self.blocked_since = None
        self.holding = False
        self.mode = "driving"
        self.mission_id = mission_id or time_id()
        self.set_log_context(mission_id=self.mission_id)
        self.logger.info("New mission with %d steps", len(steps), extra={"step_types": [step.get("type") for step in steps]})

    def end_mission(self):
        self.set_log_context(mission_id=None)

    def finish_step(self):
        self.step = None
        self.goal = None
        self.turn_remaining = None
        self.path = None

    def begin_next_step(self) -> bool:
        if not self.steps:
            return False
        assert self.position is not None and self.forward is not None
        self.step = self.steps.popleft()
        self.step_index += 1
        self.step_started = time.monotonic()
        self.direction_flips = 0
        right = np.array([-self.forward[1], self.forward[0]])
        kind = self.step["type"]
        if kind == "goto":
            self.goal = np.array([float(self.step["x"]), float(self.step["z"])])
        elif kind == "move":
            self.goal = (
                self.position
                + float(self.step.get("forward", 0.0)) * self.forward
                + float(self.step.get("right", 0.0)) * right
            )
        elif kind == "path":
            self.path = np.array(self.step["points"], dtype=float)
            self.path_index = 0
            self.goal = self.path[-1, :2].copy()
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
            return 0.0
        if speed < 0:
            self.free = free_distance(self.obstacles(), curvature_for_steer(steer), self.REVERSE_LOOKAHEAD, direction=-1)
            return 0.0 if self.free < self.REVERSE_STOP else speed
        if self.blind:
            self.free = 0.0
            return 0.0
        self.free = free_distance(self.obstacles(), curvature_for_steer(steer), self.SAFETY_LOOKAHEAD)
        if self.free < self.SAFETY_STOP:
            self.holding = True
        elif self.free >= self.SAFETY_RESUME:
            self.holding = False
        if self.holding:
            return 0.0
        if self.free < self.SAFETY_SLOW:
            return min(speed, self.MIN_SPEED)
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
        try:
            await self.control_step()
        except Exception:
            self.logger.exception("Navigation control failed")
            await self.trip("control error")

    async def control_step(self):
        if self.mode in ("idle", "arrived", "fault"):
            return
        if self.step is not None and time.monotonic() - self.step_started > self.STEP_TIMEOUT:
            await self.trip("step timeout")
            return
        if self.operator_lost():
            await self.trip("operator link lost")
            return
        if self.position is None or self.forward is None or time.monotonic() - self.pose_at > self.POSE_TIMEOUT:
            await self.command(0.0, 0.0)
            return
        if self.step is None and not self.begin_next_step():
            self.mode = "arrived"
            self.logger.info("Mission arrived")
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
        if self.blocked_since is None:
            self.blocked_since = time.monotonic()
        elif time.monotonic() - self.blocked_since > self.BLOCKED_TIMEOUT:
            self.blocked_since = None
            await self.trip("blocked")

    async def follow_path(self):
        assert self.path is not None and self.position is not None and self.forward is not None
        directions = self.path[:, 2]
        position, _, _ = self.rear_axle()
        points = rear_axle_path(self.path[:, :2], directions, self.forward)
        direction = directions[self.path_index]
        switch = next((i for i in range(self.path_index, len(points)) if directions[i] != direction), len(points))
        segment_end = switch - 1
        motion = self.forward * direction
        end_offset = points[segment_end] - position
        end_distance = float(np.linalg.norm(end_offset))
        passed = end_distance < self.PATH_LOOKAHEAD and float(end_offset @ motion) <= 0.0
        self.distance = float(np.linalg.norm(points[-1] - position))
        if switch == len(points) and (self.distance < self.PATH_ARRIVE_DISTANCE or passed):
            self.finish_step()
            await self.command(0.0, 0.0)
            return
        window = points[self.path_index : segment_end + 1]
        nearest = self.path_index + int(np.argmin(np.linalg.norm(window - position, axis=1)))
        self.path_index = nearest
        if switch < len(points) and (end_distance < self.GEAR_SWITCH_TOLERANCE or passed):
            self.path_index = switch
            await self.command(0.0, 0.0)
            return

        ahead = np.linalg.norm(points[nearest : segment_end + 1] - position, axis=1)
        target_index = nearest + int(np.argmax(ahead >= self.PATH_LOOKAHEAD)) if (ahead >= self.PATH_LOOKAHEAD).any() else segment_end
        right = np.array([-motion[1], motion[0]])
        offset = points[target_index] - position
        lookahead = max(float(np.linalg.norm(offset)), 0.05)
        self.heading_error = math.degrees(math.atan2(float(offset @ right), float(offset @ motion)))
        curvature = 2.0 * math.sin(math.radians(self.heading_error)) / lookahead
        steer = steer_for_curvature(curvature * direction)
        if direction > 0:
            await self.drive(max(self.MIN_SPEED, self.CRUISE_SPEED * (1.0 - min(abs(steer), 1.0) * 0.3)), steer)
        else:
            await self.drive(-self.REVERSE_SPEED, steer)

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
            await self.trip("manoeuvre failed")
            return
        self.maneuver_direction = -self.maneuver_direction
        self.segment_start = self.position.copy()

    def predicted_path(self) -> list[list[float]]:
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
                "goal": None if self.goal is None else {"x": float(self.goal[0]), "z": float(self.goal[1])},
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
                "mission_id": self.mission_id,
                "steer": round(self.steer, 3),
            },
        )

    async def close(self):
        await self.command(0.0, 0.0)


if __name__ == "__main__":
    Node().run_node()
