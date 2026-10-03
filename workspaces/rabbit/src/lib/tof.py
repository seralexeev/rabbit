from __future__ import annotations

import math
import os
from dataclasses import dataclass, replace

import numpy as np

TOF_SUBJECT = "rabbit.tof"
HEALTH_SUBJECT = "rabbit.health.tof"
RESOLUTION = 8
FOV_DEG = 45.0
ZONE_DEG = FOV_DEG / RESOLUTION
VALID_STATUS = frozenset({5, 9})
NO_TARGET = 255
MIN_RANGE_M = 0.02
MAX_RANGE_M = 4.0
FLOOR_MARGIN_M = 0.03
MAX_HEIGHT_M = 0.26


@dataclass(frozen=True, slots=True)
class Mount:
    name: str
    bus: int
    x: float
    y: float
    z: float
    yaw_deg: float
    pitch_deg: float
    roll_deg: float = 90.0


MOUNTS = {
    "FL": Mount("FL", 3, 0.2246, 0.019, 0.0578, 22.0, 15.0),
    "FR": Mount("FR", 4, 0.2246, -0.019, 0.0578, -22.0, 15.0),
    "RL": Mount("RL", 5, -0.0514, 0.019, 0.0578, 158.0, 15.0),
    "RR": Mount("RR", 6, -0.0514, -0.019, 0.0578, -158.0, 15.0),
}


def mounts_from_env() -> dict[str, Mount]:
    names = [name for name in (os.environ.get("TOF_SENSORS", "FL,FR,RL,RR") or "").replace(" ", "").split(",") if name]
    roll = float(os.environ.get("TOF_ROLL_DEG", "90"))
    return {name: replace(MOUNTS[name], roll_deg=roll) for name in names}


def zone_directions(flip_rows: bool = False, flip_cols: bool = False) -> np.ndarray:
    index = np.arange(RESOLUTION * RESOLUTION)
    row, col = index // RESOLUTION, index % RESOLUTION
    if flip_rows:
        row = RESOLUTION - 1 - row
    if flip_cols:
        col = RESOLUTION - 1 - col
    elevation = np.radians((RESOLUTION / 2 - 0.5 - row) * ZONE_DEG)
    azimuth = np.radians((RESOLUTION / 2 - 0.5 - col) * ZONE_DEG)
    return np.stack([np.cos(elevation) * np.cos(azimuth), np.cos(elevation) * np.sin(azimuth), np.sin(elevation)], axis=1)


ZONES = zone_directions(os.environ.get("TOF_FLIP_ROWS") == "1", os.environ.get("TOF_FLIP_COLS") == "1")
PERPENDICULAR = os.environ.get("TOF_DISTANCE", "perpendicular") == "perpendicular"


def rotation(mount: Mount) -> np.ndarray:
    roll, pitch, yaw = (math.radians(v) for v in (mount.roll_deg, mount.pitch_deg, mount.yaw_deg))
    spin = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(roll), -math.sin(roll)], [0.0, math.sin(roll), math.cos(roll)]])
    tilt = np.array([[math.cos(pitch), 0.0, -math.sin(pitch)], [0.0, 1.0, 0.0], [math.sin(pitch), 0.0, math.cos(pitch)]])
    turn = np.array([[math.cos(yaw), -math.sin(yaw), 0.0], [math.sin(yaw), math.cos(yaw), 0.0], [0.0, 0.0, 1.0]])
    return turn @ tilt @ spin


def base_directions(mount: Mount) -> np.ndarray:
    return ZONES @ rotation(mount).T


def zone_points(mount: Mount, distance_mm: np.ndarray) -> np.ndarray:
    ranges = np.asarray(distance_mm, dtype=float) / 1000.0
    if PERPENDICULAR:
        ranges = ranges / ZONES[:, 0]
    return np.array([mount.x, mount.y, mount.z]) + ranges[:, None] * base_directions(mount)


@dataclass(frozen=True, slots=True)
class Classified:
    points: np.ndarray
    valid: int
    floor: int
    overhead: int
    nearest_m: float | None


def classify(mount: Mount, distance_mm, status) -> Classified:
    distance_mm, status = np.asarray(distance_mm, dtype=float), np.asarray(status)
    points = zone_points(mount, distance_mm)
    ranges = np.linalg.norm(points - np.array([mount.x, mount.y, mount.z]), axis=1)
    valid = np.isin(status, list(VALID_STATUS)) & (ranges >= MIN_RANGE_M) & (ranges <= MAX_RANGE_M)
    floor = valid & (points[:, 2] < FLOOR_MARGIN_M)
    overhead = valid & (points[:, 2] > MAX_HEIGHT_M)
    obstacle = valid & ~floor & ~overhead
    nearest = float(np.hypot(points[obstacle, 0] - mount.x, points[obstacle, 1] - mount.y).min()) if obstacle.any() else None
    return Classified(points[obstacle], int(valid.sum()), int(floor.sum()), int(overhead.sum()), nearest)


def frame_message(mount: Mount, seq: int, ts: int, distance_mm, status) -> dict:
    found = classify(mount, distance_mm, status)
    return {
        "ts": ts,
        "sensor": mount.name,
        "seq": seq,
        "distance_mm": [int(v) for v in distance_mm],
        "status": [int(v) for v in status],
        "points": np.round(found.points, 3).tolist(),
        "nearest_m": None if found.nearest_m is None else round(found.nearest_m, 3),
        "valid": found.valid,
        "floor": found.floor,
        "overhead": found.overhead,
    }
