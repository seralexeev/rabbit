from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from lib.geometry import camera_point
from lib.planner import FREE, OCCUPIED, UNKNOWN, CostMap, Pose2D, connected_components, footprint_centers, frontier_mask, pose_clearance, wrap_angle

CAMERA_FOV = math.radians(87.0)
DEPTH_RANGE = 5.0
RAY_STEP = math.radians(3.0)
STANDOFFS = (0.8, 1.5, 2.5)
BEARINGS = 12
MIN_CLUSTER_CELLS = 6
MIN_GAIN = 1.0
LOCAL_REACH = 3.5
LEAVE_FACTOR = 2.0
MIN_FAR_GAIN = 2.0
UNKNOWN_DEPTH = 1.5
TURN_COST = 0.5
TRIP_COST = 0.8
NEARBY = 1.5
NEARBY_BONUS = 1.25
SAME_VIEW = 0.5
SAME_VIEW_HEADING = math.radians(45.0)


@dataclass(frozen=True)
class View:
    pose: Pose2D
    frontier: tuple[float, float]
    gain: float
    cost: float

    @property
    def score(self) -> float:
        return self.gain / self.cost


def visible_unknown(costmap: CostMap, cameras: np.ndarray, headings: np.ndarray) -> np.ndarray:
    grid = costmap.grid
    rays = np.arange(-0.5 * CAMERA_FOV, 0.5 * CAMERA_FOV + 1e-9, RAY_STEP)
    angles = headings[:, None] + rays[None, :]
    directions = np.stack([np.cos(angles), np.sin(angles)], axis=-1)
    step = 0.5 * grid.resolution
    distances = np.arange(0.5 * step, DEPTH_RANGE, step)
    samples = cameras[:, None, None, :] + distances[None, None, :, None] * directions[:, :, None, :]
    iz, ix, inside = grid.cell_index(samples.reshape(-1, 2))
    cells = np.where(inside, grid.cells[np.clip(iz, 0, grid.height - 1), np.clip(ix, 0, grid.width - 1)], UNKNOWN).reshape(samples.shape[:3])
    hidden = np.maximum.accumulate(cells == OCCUPIED, axis=2)
    unknown = (cells == UNKNOWN) & ~hidden
    unknown &= np.cumsum(unknown, axis=2) * step <= UNKNOWN_DEPTH
    return (unknown * distances[None, None, :]).sum(axis=(1, 2)) * step * RAY_STEP


def standing_room(costmap: CostMap, poses: np.ndarray) -> np.ndarray:
    grid = costmap.grid
    probes = np.concatenate([poses[:, None, :2], footprint_centers(poses, costmap.footprint)], axis=1).reshape(-1, 2)
    iz, ix, inside = grid.cell_index(probes)
    known = (inside & (grid.cells[np.clip(iz, 0, grid.height - 1), np.clip(ix, 0, grid.width - 1)] == FREE)).reshape(len(poses), -1).all(axis=1)
    return known & (pose_clearance(costmap, poses) >= 0.05)


def candidate_views(costmap: CostMap, start: Pose2D, failed: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    grid = costmap.grid
    poses, frontiers = [], []
    angles = np.linspace(0.0, 2.0 * math.pi, BEARINGS, endpoint=False)
    for cells in connected_components(frontier_mask(grid)):
        if len(cells) < MIN_CLUSTER_CELLS:
            continue
        centroid = np.asarray(grid.origin) + (cells[:, ::-1].mean(axis=0) + 0.5) * grid.resolution
        if any(math.dist(centroid, spot) <= SAME_VIEW for spot in failed):
            continue
        for standoff in STANDOFFS:
            cameras = centroid + standoff * np.stack([np.cos(angles), np.sin(angles)], axis=1)
            facing = np.arctan2(centroid[1] - cameras[:, 1], centroid[0] - cameras[:, 0])
            rear = cameras - camera_point(np.zeros((len(cameras), 2)), np.stack([np.cos(facing), np.sin(facing)], axis=1))
            poses.append(np.column_stack([rear, facing]))
            frontiers.append(np.repeat(centroid[None, :], len(cameras), axis=0))
    if all(math.dist((start.x, start.z), spot) > SAME_VIEW for spot in failed):
        turns = start.theta + np.array([0.5 * math.pi, math.pi, -0.5 * math.pi])
        poses.append(np.column_stack([np.full(3, start.x), np.full(3, start.z), turns]))
        frontiers.append(np.full((3, 2), np.nan))
    if not poses:
        return np.empty((0, 3)), np.empty((0, 2))
    return np.vstack(poses), np.vstack(frontiers)


def next_view(costmap: CostMap, start: Pose2D, reach: np.ndarray, failed: list[tuple[float, float]], previous: Pose2D | None = None) -> View | None:
    poses, frontiers = candidate_views(costmap, start, failed)
    grid = costmap.grid
    iz, ix, inside = grid.cell_index(poses[:, :2])
    travel = np.where(inside, reach[np.clip(iz, 0, grid.height - 1), np.clip(ix, 0, grid.width - 1)], np.inf)
    in_place = np.isnan(frontiers[:, 0])
    usable = np.isfinite(travel) & (in_place | standing_room(costmap, poses))
    if not usable.any():
        return None
    poses, frontiers, travel = poses[usable], frontiers[usable], travel[usable]
    cameras = camera_point(poses[:, :2], np.stack([np.cos(poses[:, 2]), np.sin(poses[:, 2])], axis=1))
    gain = visible_unknown(costmap, cameras, poses[:, 2])
    arriving = np.where(travel > 0.3, np.arctan2(poses[:, 1] - start.z, poses[:, 0] - start.x), start.theta)
    turn = np.abs((poses[:, 2] - arriving + math.pi) % (2 * math.pi) - math.pi)
    cost = TRIP_COST + travel + TURN_COST * turn
    score = gain / cost
    if previous is not None:
        score = np.where(np.hypot(poses[:, 0] - previous.x, poses[:, 1] - previous.z) <= NEARBY, NEARBY_BONUS * score, score)
    near = travel <= LOCAL_REACH
    worth = gain >= np.where(near, MIN_GAIN, MIN_FAR_GAIN)
    local = worth & near
    if local.any():
        score = np.where(local, score, gain / (cost + LEAVE_FACTOR * travel))
    score = np.where(worth, score, -np.inf)
    best = int(np.argmax(score))
    if not math.isfinite(score[best]):
        return None
    x, z, theta = poses[best]
    frontier = (float(start.x), float(start.z)) if np.isnan(frontiers[best, 0]) else (float(frontiers[best, 0]), float(frontiers[best, 1]))
    return View(Pose2D(float(x), float(z), float(wrap_angle(theta))), frontier, float(gain[best]), float(cost[best]))
