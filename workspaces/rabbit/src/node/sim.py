import json
import math
import os
import time
import uuid
from collections import deque

import numpy as np
from lib.detector import OBJECTS_SUBJECT, DetectedObject, DetectedObjects
from lib.drive import DRIVE_SUBJECT, JOY_SUBJECT, CommandArbiter, slew
from lib.geometry import CAMERA_HEIGHT, CAMERA_TO_REAR_AXLE, GRAVITY, quaternion_to_matrix
from lib.node import RabbitNode
from lib.planner import OCCUPIED, UNKNOWN, OccupancyGrid, build_costmap
from lib.simulation import ACTUATION_DELAY, CAMERA_FOV_DEG, DEPTH_RANGE, METRES_PER_SECOND_PER_DUTY, POSE_LATENCY, SCAN_LATENCY, WORLDS, Robot, ScannedMap, body_free, scan_ranges
from lib.spatial_map import GRID_UNKNOWN, MAP_CHUNKS_SUBJECT, MAP_GRID_SNAPSHOT_SUBJECT, MAP_GRID_SUBJECT, MAP_RESET_SUBJECT, MAP_SNAPSHOT_SUBJECT, encode_chunk, encode_grid
from nats.aio.msg import Msg

POSE_SUBJECT = "rabbit.zed.pose"
OBSTACLE_SUBJECT = "rabbit.zed.obstacle"
IMU_SUBJECT = "rabbit.zed.imu"
HEALTH_SUBJECT = "rabbit.health.zed"
ROBOCLAW_SUBJECT = "rabbit.roboclaw"
MAP_EXTEND_SUBJECT = "rabbit.map.extend"
RESTART_SUBJECT = "rabbit.sim.restart"
SIM_STATE_SUBJECT = "rabbit.sim.state"
TELEMETRY_SUBJECT = "rabbit.telemetry"
STEERING_SUBJECT = "rabbit.steering"
INA_SUBJECT = "rabbit.ina"
BLOCK_CELLS = 8
WALL_HEIGHT = 1.2

STARTS = {"apartment": (1.0, 1.5, 90.0), "corridor": (1.5, 1.5, 0.0), "open-plan": (1.5, 4.0, 90.0)}
OBJECTS = {
    "apartment": [("refrigerator", 1.0, 5.5, 0.7, 1.8, 0.9)],
    "corridor": [("refrigerator", 0.75, 6.25, 0.9, 1.8, 1.3), ("sofa", 7.25, 5.8, 1.5, 0.8, 0.8)],
    "open-plan": [("kitchen island", 3.1, 2.9, 1.4, 0.9, 0.6), ("bed", 7.95, 5.85, 1.9, 0.5, 2.1)],
}


def heading_to_theta(heading_deg: float) -> float:
    h = math.radians(heading_deg)
    return math.atan2(-math.cos(h), math.sin(h))


def cell_quads(x0: float, z0: float, size: float, height: float) -> list[list[tuple[float, float, float]]]:
    x1, z1 = x0 + size, z0 + size
    if height <= 0:
        return [[(x0, 0.0, z0), (x1, 0.0, z0), (x1, 0.0, z1), (x0, 0.0, z1)]]
    return [
        [(x0, height, z0), (x1, height, z0), (x1, height, z1), (x0, height, z1)],
        [(x0, 0.0, z0), (x1, 0.0, z0), (x1, height, z0), (x0, height, z0)],
        [(x0, 0.0, z1), (x1, 0.0, z1), (x1, height, z1), (x0, height, z1)],
        [(x0, 0.0, z0), (x0, 0.0, z1), (x0, height, z1), (x0, height, z0)],
        [(x1, 0.0, z0), (x1, 0.0, z1), (x1, height, z1), (x1, height, z0)],
    ]


def block_mesh(cells: np.ndarray, heights: np.ndarray, origin: tuple[float, float], resolution: float) -> tuple[np.ndarray, np.ndarray]:
    quads = []
    for (iz, ix), value in np.ndenumerate(cells):
        if value != UNKNOWN:
            quads += cell_quads(origin[0] + ix * resolution, origin[1] + iz * resolution, resolution, float(heights[iz, ix]) if value == OCCUPIED else 0.0)
    vertices = np.array(quads, dtype=np.float64).reshape(-1, 3)
    base = np.arange(len(quads))[:, None] * 4
    triangles = np.concatenate([base + [0, 1, 2], base + [0, 2, 3]]).reshape(-1, 3)
    return vertices, triangles


def world_from_map(path: str) -> OccupancyGrid:
    data = np.load(path)
    clearance = data["clearance"]
    cells = np.where(clearance > 0, 0, OCCUPIED).astype(np.int8)
    return OccupancyGrid(tuple(data["origin"]), float(data["res"]), clearance.shape[1], clearance.shape[0], cells)


class Node(RabbitNode):
    PHYSICS = 0.01
    POSE_RATE = 30.0
    SCAN_RATE = 15.0
    COMMAND_TIMEOUT = 0.4
    ACCEL = 1.5
    DECEL = 5.0
    STALL_CURRENT = 1.0
    CURRENT_PER_DUTY = 1.2

    def __init__(self):
        super().__init__("sim")
        self.world_name = os.environ.get("SIM_WORLD", "apartment")
        if self.world_name.endswith(".npz"):
            self.world = world_from_map(self.world_name)
            self.objects = []
        else:
            self.world = WORLDS[self.world_name]()
            self.objects = OBJECTS.get(self.world_name, [])
        x, z, heading = (float(v) for v in os.environ.get("SIM_START", ",".join(map(str, STARTS.get(self.world_name, (1.0, 1.0, 90.0))))).split(","))
        self.robot = Robot(x, z, heading_to_theta(heading))
        self.mapper = ScannedMap(self.world)
        if os.environ.get("SIM_KNOWN_MAP") == "1":
            self.mapper.cells = self.world.cells.copy()
        self.arbiter = CommandArbiter()
        self.owner = "none"
        self.target = (0.0, 0.0)
        self.command_at = -math.inf
        self.duty = 0.0
        self.commands: deque[tuple[float, float, float]] = deque(maxlen=100)
        self.history: deque[tuple[float, float, float, float]] = deque(maxlen=200)
        self.stepped_at = time.monotonic()
        self.contact = False
        self.contacts = 0
        self.session = uuid.uuid4().hex[:12]
        self.map_id = f"sim-{os.path.basename(self.world_name)}"
        self.grid_payload: bytes | None = None
        self.frame = 0
        self.heights = self.object_heights()
        self.chunks: dict[tuple[int, int], tuple[int, bytes, bytes]] = {}
        self.chunk_bytes = 0

    async def init(self):
        self.set_log_context(odom_session=self.session, map_session=self.session, map_id=self.map_id)
        await self.subscribe(DRIVE_SUBJECT, self.on_command)
        await self.subscribe(JOY_SUBJECT, self.on_command)
        await self.subscribe(MAP_GRID_SNAPSHOT_SUBJECT, self.on_snapshot)
        await self.subscribe(MAP_EXTEND_SUBJECT, self.on_extend)
        await self.subscribe(RESTART_SUBJECT, self.on_restart)
        await self.subscribe(SIM_STATE_SUBJECT, self.on_state)
        await self.subscribe(MAP_SNAPSHOT_SUBJECT, self.on_mesh_snapshot)
        await self.subscribe(MAP_RESET_SUBJECT, self.on_reset)
        self.set_interval(self.publish_chunks, 1.0, max_parallel=1)
        self.set_interval(self.publish_telemetry, 1.0, max_parallel=1)
        self.set_interval(self.publish_steering, 0.1, max_parallel=1)
        self.set_interval(self.physics, self.PHYSICS, max_parallel=1)
        self.set_interval(self.publish_pose, 1.0 / self.POSE_RATE, max_parallel=1)
        self.set_interval(self.publish_scan, 1.0 / self.SCAN_RATE, max_parallel=1)
        self.set_interval(self.publish_grid, 1.0, max_parallel=1)
        self.set_interval(self.publish_health, 1.0, max_parallel=1)
        self.set_interval(self.publish_imu, 0.05, max_parallel=1)
        self.set_interval(self.publish_objects, 0.5, max_parallel=1)
        self.set_interval(self.publish_roboclaw, 0.1, max_parallel=1)
        self.logger.info(f"Simulating {self.world_name} from ({self.robot.x:.2f}, {self.robot.z:.2f})")

    async def on_command(self, msg: Msg):
        resolved = self.arbiter.resolve(msg)
        if self.arbiter.owner() != self.owner:
            self.event("drive.owner_changed", f"{self.owner} -> {self.arbiter.owner()}", previous=self.owner, owner=self.arbiter.owner(), subject=msg.subject)
            self.owner = self.arbiter.owner()
        if resolved is not None:
            self.target = resolved
            self.command_at = time.monotonic()

    async def physics(self):
        now = time.monotonic()
        dt = min(max(now - self.stepped_at, 0.0), 0.05)
        self.stepped_at = now
        if now - self.command_at > self.COMMAND_TIMEOUT and self.target != (0.0, 0.0):
            self.event("motors.command_timeout", "no drive command, stopping the motors", severity="warning", every_s=1.0, command_age_s=now - self.command_at, timeout_s=self.COMMAND_TIMEOUT, owner=self.owner)
            self.target = (0.0, 0.0)
        speed, steer = self.target if now - self.command_at <= self.COMMAND_TIMEOUT else (0.0, 0.0)
        self.duty = slew(self.duty, speed, dt, self.ACCEL, self.DECEL)
        self.commands.append((now, self.duty, steer))
        due = next((c for c in reversed(self.commands) if c[0] <= now - ACTUATION_DELAY), (now, 0.0, 0.0))
        before = (self.robot.x, self.robot.z, self.robot.theta)
        self.robot.step(due[1], due[2], dt)
        self.contact = not body_free(self.world, self.robot)
        if self.contact:
            self.robot.x, self.robot.z, self.robot.theta = before
            self.contacts += 1
            self.event("sim.contact", "the simulated body touched a wall", severity="warning", every_s=2.0, x=self.robot.x, z=self.robot.z, duty=self.duty, contacts=self.contacts)
        self.history.append((now, self.robot.x, self.robot.z, self.robot.theta))

    def past(self, ago: float) -> Robot:
        at = time.monotonic() - ago
        for t, x, z, theta in reversed(self.history):
            if t <= at:
                return Robot(x, z, theta)
        return Robot(self.robot.x, self.robot.z, self.robot.theta)

    @staticmethod
    def stamp(ago: float) -> int:
        return time.time_ns() - int(ago * 1e9)

    async def publish_pose(self):
        seen = self.past(POSE_LATENCY)
        camera = seen.camera()
        translation = [round(float(camera[0]), 4), CAMERA_HEIGHT, round(float(camera[1]), 4)]
        orientation = seen.orientation()
        qx, qy, qz, qw = orientation
        speed = self.robot.speed * METRES_PER_SECOND_PER_DUTY
        ts = self.stamp(POSE_LATENCY)
        await self.publish_json(
            POSE_SUBJECT,
            {
                "ts": ts,
                "timestamp": ts,
                "frame_number": self.frame,
                "translation": translation,
                "orientation": orientation,
                "euler_deg": [0.0, round(math.degrees(math.atan2(2 * (qw * qy + qx * qz), 1 - 2 * (qx * qx + qy * qy))), 3), 0.0],
                "velocity": [round(speed * math.cos(seen.theta), 4), 0.0, round(speed * math.sin(seen.theta), 4)],
                "angular_velocity": [0.0, 0.0, 0.0],
                "position_std": [0.001, 0.001, 0.001],
                "confidence": 100,
                "odom": {"translation": translation, "orientation": orientation, "session": self.session},
            },
        )

    async def publish_scan(self):
        seen = self.past(SCAN_LATENCY)
        await self.publish_json(OBSTACLE_SUBJECT, {"ts": self.stamp(SCAN_LATENCY), "nearest": None, "ahead": None, "scan": {**scan_ranges(self.world, seen), "blind_fraction": 0.0}})
        forward = np.array([math.cos(seen.theta), math.sin(seen.theta)])
        self.mapper.observe(np.array([seen.x, seen.z]) + CAMERA_TO_REAR_AXLE * forward, seen.theta)

    async def publish_grid(self):
        grid = OccupancyGrid(self.world.origin, self.world.resolution, self.world.width, self.world.height, self.mapper.cells.copy())
        distance = build_costmap(grid).distance
        clearance = np.where(grid.cells == UNKNOWN, GRID_UNKNOWN, np.where(grid.cells == OCCUPIED, 0, np.round(distance * 1000.0))).astype(np.int16)
        self.grid_payload = encode_grid(self.world.origin, self.world.resolution, clearance)
        await self.publish(MAP_GRID_SUBJECT, self.grid_payload, headers=self.map_headers())

    def map_headers(self) -> dict[str, str]:
        return {"session": self.session, "map": self.map_id, "format": "grid"}

    async def on_snapshot(self, msg: Msg):
        if msg.reply and self.grid_payload is not None:
            await self.publish(msg.reply, self.grid_payload, headers=self.map_headers())

    async def on_extend(self, msg: Msg):
        if msg.reply:
            await self.publish(msg.reply, json.dumps({"accepted": False, "reason": "the simulator always maps"}).encode())

    def object_heights(self) -> np.ndarray:
        heights = np.where(self.world.cells == OCCUPIED, WALL_HEIGHT, 0.0)
        for _, x, z, width, height, length in self.objects:
            iz, ix, _ = self.world.cell_index(np.array([[x - width / 2, z - length / 2], [x + width / 2, z + length / 2]]))
            area = heights[max(iz[0], 0) : iz[1] + 1, max(ix[0], 0) : ix[1] + 1]
            area[area > 0] = height
        return heights

    def mesh_headers(self) -> dict[str, str]:
        return {"session": self.session, "map": self.map_id, "format": "mesh"}

    async def publish_chunks(self):
        cells = self.mapper.cells
        changed = []
        for bz in range(0, cells.shape[0], BLOCK_CELLS):
            for bx in range(0, cells.shape[1], BLOCK_CELLS):
                part = cells[bz : bz + BLOCK_CELLS, bx : bx + BLOCK_CELLS]
                if (part == UNKNOWN).all():
                    continue
                key = (bz, bx)
                signature = part.tobytes()
                index, previous, _ = self.chunks.get(key, (len(self.chunks) + 1, b"", b""))
                if signature == previous:
                    continue
                origin = (self.world.origin[0] + bx * self.world.resolution, self.world.origin[1] + bz * self.world.resolution)
                vertices, triangles = block_mesh(part, self.heights[bz : bz + BLOCK_CELLS, bx : bx + BLOCK_CELLS], origin, self.world.resolution)
                encoded = encode_chunk(index, vertices, triangles)
                self.chunks[key] = (index, signature, encoded)
                changed.append(encoded)
        self.chunk_bytes = sum(len(encoded) for *_, encoded in self.chunks.values())
        if changed:
            await self.publish(MAP_CHUNKS_SUBJECT, b"".join(changed), headers=self.mesh_headers())

    async def on_mesh_snapshot(self, msg: Msg):
        if msg.reply:
            await self.publish(msg.reply, b"".join(encoded for *_, encoded in self.chunks.values()), headers=self.mesh_headers())

    async def on_reset(self, msg: Msg):
        tombstones = b"".join(encode_chunk(index, np.empty((0, 3)), np.empty((0, 3))) for index, *_ in self.chunks.values())
        self.chunks.clear()
        self.mapper.cells[:] = UNKNOWN
        self.session = uuid.uuid4().hex[:12]
        self.set_log_context(odom_session=self.session, map_session=self.session)
        self.event("map.reset", f"requested by {json.loads(msg.data or b'{}').get('source', 'unknown')}", severity="warning", message=f"Simulated map reset, session {self.session}", map_session=self.session, map_id=self.map_id)
        if tombstones:
            await self.publish(MAP_CHUNKS_SUBJECT, tombstones, headers=self.mesh_headers())

    async def on_restart(self, msg: Msg):
        previous, self.session = self.session, uuid.uuid4().hex[:12]
        self.chunks.clear()
        self.set_log_context(odom_session=self.session, map_session=self.session)
        self.event(
            "camera.restart",
            "simulated camera restart",
            severity="warning",
            message=f"Simulated camera restart, odometry session {self.session}",
            previous_session=previous,
            odom_session=self.session,
            map_id=self.map_id,
            archive_map=False,
        )
        if msg.reply:
            await self.publish(msg.reply, json.dumps({"session": self.session}).encode())

    async def on_state(self, msg: Msg):
        if msg.reply:
            camera = self.robot.camera()
            state = {
                "x": self.robot.x, "z": self.robot.z, "theta": self.robot.theta, "camera": [float(camera[0]), float(camera[1])],
                "coverage": self.mapper.explored(), "contacts": self.contacts, "session": self.session,
            }
            await self.publish(msg.reply, json.dumps(state).encode())

    async def publish_health(self):
        moving = abs(self.robot.speed) > 0.01
        await self.publish_json(
            HEALTH_SUBJECT,
            {
                "ts": time.time_ns(), "simulated": True, "frame_number": self.frame, "camera_fps": self.POSE_RATE, "current_fps": self.POSE_RATE,
                "last_capture_duration_ms": 12.0, "last_pose_state": "OK", "pose_messages": self.frame, "pose_drop_count": 0, "frames_dropped": 0, "preview_skipped": 0,
                "held_poses": 0, "implausible_poses": 0, "tracking_state": "OK", "odometry_status": "OK", "spatial_memory_status": "OK",
                "tracking_fusion_status": "VISUAL_INERTIAL", "camera_moving_state": "MOVING" if moving else "STATIC",
                "low_image_quality": False, "low_lighting": False, "low_depth_reliability": False, "low_motion_sensors_reliability": False,
                "exposure": 40, "gain": 20, "whitebalance_temperature": 4600, "temperature": {"imu": 38.0, "barometer": 37.0, "onboard_left": 41.0, "onboard_right": 41.0},
                "mapping_state": "OK", "map_mode": "mapping", "relocalizing": False, "idle": not moving, "map_id": self.map_id, "map_session": self.session,
                "map_chunks": len(self.chunks), "map_points": int((self.mapper.cells != UNKNOWN).sum()), "map_bytes": self.chunk_bytes,
            },
        )

    async def publish_telemetry(self):
        load = 20.0 + 30.0 * min(abs(self.duty) / 0.35, 1.0)
        await self.publish_json(
            TELEMETRY_SUBJECT,
            {
                "simulated": True, "cpu": [load] * 6, "cpu_freq_mhz": [1728] * 6, "gpu": 35.0, "gpu_freq_mhz": 1020,
                "ram": {"used": 4.0e9, "total": 7.4e9, "shared": 1.2e9}, "swap": {"used": 0, "total": 3.7e9},
                "temp": {"cpu": 50.0, "gpu": 49.0, "soc0": 48.0, "soc1": 48.0, "soc2": 47.0, "tj": 51.0},
                "power": 12000, "input_mv": 11900, "input_ma": 1000, "rails_mw": {"VDD_CPU_GPU_CV": 4000, "VDD_SOC": 2500},
                "disk": {"used": 60, "total": 230}, "uptime": f"{int(time.monotonic() - self.node_started_at)}s", "fan": 40, "fan_rpm": 3000, "containers": [],
                "boot_id": self.boot_id,
                "wifi": {
                    "connected": True, "ssid": "SIM", "frequency_mhz": 5180, "signal_dbm": -50, "rx_bitrate_mbps": 400.0, "tx_bitrate_mbps": 400.0,
                    "gateway_rtt_ms": 2.0, "tx_errors": 0, "rx_errors": 0, "tx_dropped": 0, "rx_dropped": 0,
                },
            },
        )

    async def publish_steering(self):
        await self.publish_json(STEERING_SUBJECT, {"angle": round(self.robot.steer, 3), "pulse_us": round(1532 + 532 * self.robot.steer), "errors": 0, "simulated": True})

    async def publish_imu(self):
        orientation = self.robot.orientation()
        gravity = quaternion_to_matrix(orientation).T @ np.array([0.0, GRAVITY, 0.0])
        await self.publish_json(IMU_SUBJECT, {"ts": time.time_ns(), "acceleration": gravity.round(4).tolist(), "orientation": orientation, "angular_velocity": [0.0, 0.0, 0.0]})

    async def publish_objects(self):
        seen = self.past(POSE_LATENCY)
        camera = seen.camera()
        visible = []
        for index, (label, x, z, width, height, length) in enumerate(self.objects):
            offset = np.array([x, z]) - camera
            bearing = abs((math.atan2(offset[1], offset[0]) - seen.theta + math.pi) % (2 * math.pi) - math.pi)
            if np.linalg.norm(offset) <= DEPTH_RANGE and bearing <= math.radians(0.5 * CAMERA_FOV_DEG):
                corners = [[x + sx * width / 2, sy * height, z + sz * length / 2] for sx in (-1, 1) for sy in (0, 1) for sz in (-1, 1)]
                visible.append(DetectedObject(id=index + 1, label=label, confidence=90.0, position=[x, height / 2, z], dimensions=[width, height, length], corners=corners, box=[], moving=False))
        self.frame += 1
        await self.publish(OBJECTS_SUBJECT, DetectedObjects(ts=self.stamp(POSE_LATENCY), frame_number=self.frame, objects=visible).model_dump_json().encode())

    async def publish_roboclaw(self):
        current = self.STALL_CURRENT if self.contact else self.CURRENT_PER_DUTY * abs(self.duty)
        side = {"command": round(self.duty, 3), "pwm": round(self.duty, 3), "current": round(current, 3), "speed": 0, "encoder": 0}
        await self.publish_json(ROBOCLAW_SUBJECT, {"left": side, "right": side, "supply_voltage": 11.9, "duty_max": 1.0, "temperature": 30.0, "status": 0, "errors": 0, "simulated": True})
        battery_current = 0.9 + 2 * current * 12.0 / 15.6
        voltage = round(15.8 - 0.08 * battery_current, 3)
        channels = [
            {"ch": 1, "name": "battery", "voltage": voltage, "current": round(battery_current, 3), "power": round(voltage * battery_current, 3), "clipped": False},
            {"ch": 2, "name": "rail_6v", "voltage": 6.0, "current": 0.1, "power": 0.6, "clipped": False},
        ]
        await self.publish_json(INA_SUBJECT, {"channels": channels, "battery_charge_pct": 80.0, "errors": 0, "simulated": True})


if __name__ == "__main__":
    Node().run_node()
