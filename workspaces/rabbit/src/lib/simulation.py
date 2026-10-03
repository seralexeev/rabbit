from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from lib.geometry import CAMERA_TO_REAR_AXLE, camera_point, curvature_for_steer
from lib.navmap import clear_unknown, mark_known
from lib.planner import FREE, OCCUPIED, UNKNOWN, CostMap, OccupancyGrid, build_costmap
from lib.safety import Footprint
from lib.trip import PARAMS

RES = 0.05
METRES_PER_SECOND_PER_DUTY = 0.464
STEER_LAG = 0.05
SPEED_LAG = 0.05
ACTUATION_DELAY = 0.06
POSE_LATENCY = 0.047
SCAN_LATENCY = 0.056
BLIND_RANGE = 0.3
SCAN_RANGE = 5.0
CAMERA_FOV_DEG = 87.0
DEPTH_RANGE = 5.0


def room_grid(width_m: float, height_m: float) -> OccupancyGrid:
    grid = OccupancyGrid.filled((0.0, 0.0), round(width_m / RES), round(height_m / RES), RES, FREE)
    grid.cells[[0, -1], :] = OCCUPIED
    grid.cells[:, [0, -1]] = OCCUPIED
    return grid


def block(grid: OccupancyGrid, x0: float, z0: float, x1: float, z1: float, value: int = OCCUPIED) -> None:
    grid.cells[round(z0 / RES) : round(z1 / RES), round(x0 / RES) : round(x1 / RES)] = value


def corridor_flat() -> OccupancyGrid:
    grid = room_grid(10.0, 7.0)
    for x0, x1 in ((0.0, 1.0), (1.8, 4.6), (5.4, 10.0)):
        block(grid, x0, 4.15, x1, 4.25)
    for x0, x1 in ((0.0, 1.4), (2.2, 4.2), (5.0, 7.3), (8.8, 10.0)):
        block(grid, x0, 2.95, x1, 3.05)
    block(grid, 4.95, 4.25, 5.05, 7.0)
    block(grid, 2.95, 0.0, 3.05, 2.95)
    block(grid, 6.95, 0.0, 7.05, 2.95)
    block(grid, 3.6, 0.3, 5.2, 1.9)
    block(grid, 6.5, 5.4, 8.0, 6.2)
    block(grid, 8.0, 1.0, 9.2, 1.6)
    block(grid, 0.3, 5.6, 1.2, 6.9)
    return grid


def open_plan() -> OccupancyGrid:
    grid = room_grid(9.0, 7.0)
    block(grid, 5.95, 0.0, 6.05, 3.0)
    block(grid, 5.95, 3.8, 6.05, 7.0)
    block(grid, 0.0, 5.45, 2.0, 5.55)
    block(grid, 3.0, 5.45, 5.95, 5.55)
    block(grid, 2.4, 2.6, 3.8, 3.2)
    block(grid, 0.6, 0.4, 2.6, 1.2)
    block(grid, 4.2, 4.2, 5.2, 4.9)
    block(grid, 7.0, 4.8, 8.9, 6.9)
    block(grid, 0.05, 2.0, 0.6, 4.6)
    return grid


class ScannedMap:
    def __init__(self, world: OccupancyGrid):
        self.world = world
        self.cells = np.full(world.cells.shape, UNKNOWN, dtype=np.int8)

    def observe(self, origin: np.ndarray, heading: float) -> None:
        angles = heading + np.radians(np.linspace(-0.5 * CAMERA_FOV_DEG, 0.5 * CAMERA_FOV_DEG, 4 * int(CAMERA_FOV_DEG) + 1))
        directions = np.stack([np.cos(angles), np.sin(angles)], axis=1)
        distances = np.arange(0.05, DEPTH_RANGE, 0.5 * RES)
        samples = origin + distances[None, :, None] * directions[:, None, :]
        iz, ix, inside = self.world.cell_index(samples.reshape(-1, 2))
        hit = (~inside | (self.world.cells[np.clip(iz, 0, self.world.height - 1), np.clip(ix, 0, self.world.width - 1)] == OCCUPIED)).reshape(len(angles), -1)
        first = np.where(hit.any(axis=1), hit.argmax(axis=1), len(distances) - 1)
        ends = origin + distances[first][:, None] * directions
        grid = OccupancyGrid(self.world.origin, self.world.resolution, self.world.width, self.world.height, self.cells)
        clear_unknown(grid, origin, ends)
        grid.mark_points(ends[hit.any(axis=1)], OCCUPIED)

    def ready(self) -> bool:
        return True

    def costmap(self, scans, trail: np.ndarray, robot: tuple[float, float, float] | None) -> CostMap:
        grid = OccupancyGrid(self.world.origin, self.world.resolution, self.world.width, self.world.height, self.cells.copy())
        mark_known(grid, trail, robot)
        return build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)

    def explored(self) -> float:
        free = self.world.cells == FREE
        return float((self.cells[free] == FREE).sum() / max(free.sum(), 1))



def apartment(door_b_to_c: bool = True, door_a_to_c: bool = False):
    grid = room_grid(8.0, 6.0)
    block(grid, 3.95, 0.0, 4.05, 1.0)
    block(grid, 3.95, 1.8, 4.05, 3.0)
    block(grid, 0.0, 2.95, 0.4, 3.05)
    block(grid, 1.2, 2.95, 6.0, 3.05)
    block(grid, 6.8, 2.95, 8.0, 3.05)
    if not door_b_to_c:
        block(grid, 6.0, 2.95, 6.8, 3.05)
    if not door_a_to_c:
        block(grid, 0.4, 2.95, 1.2, 3.05)
    block(grid, 0.65, 5.05, 1.35, 5.95)
    return grid


WORLDS = {"apartment": lambda: apartment(door_a_to_c=True), "corridor": corridor_flat, "open-plan": open_plan}


@dataclass
class Robot:
    x: float
    z: float
    theta: float
    steer: float = 0.0
    speed: float = 0.0

    def camera(self) -> np.ndarray:
        return camera_point(np.array([self.x, self.z]), np.array([math.cos(self.theta), math.sin(self.theta)]))

    def orientation(self) -> list[float]:
        psi = math.atan2(-math.cos(self.theta), -math.sin(self.theta))
        return [0.0, math.sin(psi / 2), 0.0, math.cos(psi / 2)]

    def step(self, speed: float, steer: float, dt: float) -> None:
        self.steer += (steer - self.steer) * (1.0 - math.exp(-dt / STEER_LAG))
        self.speed += (speed - self.speed) * (1.0 - math.exp(-dt / SPEED_LAG))
        distance = self.speed * METRES_PER_SECOND_PER_DUTY * dt
        curvature = curvature_for_steer(self.steer)
        self.x += distance * math.cos(self.theta + 0.5 * distance * curvature)
        self.z += distance * math.sin(self.theta + 0.5 * distance * curvature)
        self.theta = (self.theta + distance * curvature + math.pi) % (2 * math.pi) - math.pi


def scan_ranges(world: OccupancyGrid, robot: Robot) -> dict:
    origin = np.array([robot.x, robot.z]) + CAMERA_TO_REAR_AXLE * np.array([math.cos(robot.theta), math.sin(robot.theta)])
    ranges: list[float | None] = []
    for i in range(48):
        angle = robot.theta + math.radians(-60.0 + (i + 0.5) * 2.5)
        direction = np.array([math.cos(angle), math.sin(angle)])
        distances = np.arange(0.05, SCAN_RANGE, 0.5 * RES)
        iz, ix, inside = world.cell_index(origin + distances[:, None] * direction)
        hit = ~inside | (world.cells[np.clip(iz, 0, world.height - 1), np.clip(ix, 0, world.width - 1)] == OCCUPIED)
        first = int(np.argmax(hit)) if hit.any() else -1
        distance = float(distances[first]) if first >= 0 else None
        ranges.append(None if distance is None or distance < BLIND_RANGE else round(distance, 3))
    return {"angle_min_deg": -60.0, "angle_step_deg": 2.5, "ranges": ranges, "blind": False}


def body_free(world: OccupancyGrid, robot: Robot) -> bool:
    footprint = Footprint()
    forward = np.array([math.cos(robot.theta), math.sin(robot.theta)])
    right = np.array([-forward[1], forward[0]])
    along, across = np.meshgrid(np.linspace(-footprint.rear, footprint.front, 12), np.linspace(-footprint.half_width, footprint.half_width, 6))
    body = np.array([robot.x, robot.z]) + np.outer(along.ravel(), forward) + np.outer(across.ravel(), right)
    iz, ix, inside = world.cell_index(body)
    return bool(inside.all() and not (world.cells[iz, ix] == OCCUPIED).any())
