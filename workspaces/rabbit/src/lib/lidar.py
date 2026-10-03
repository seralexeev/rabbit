from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Callable

import numpy as np

SCAN_SUBJECT = "rabbit.lidar.scan"
HEALTH_SUBJECT = "rabbit.health.lidar"
HEADER = struct.Struct("<qqIHHffff")
POINT = np.dtype([("distance_mm", "<u2"), ("angle_q6", "<u2")])
ANGLE_SCALE = 64.0
MAX_RANGE_M = 12.0
SECTORS = 12


@dataclass(frozen=True, slots=True)
class Mount:
    x: float = 0.1597
    y: float = 0.0
    z: float = 0.23
    yaw_deg: float = 180.0


def mount_from_env() -> Mount:
    text = os.environ.get("LIDAR_MOUNT")
    return Mount(*(float(v) for v in text.split(","))) if text else Mount()


def mask_from_env() -> list[tuple[float, float]]:
    sectors = []
    for item in (os.environ.get("LIDAR_MASK") or "").replace(" ", "").split(","):
        if item:
            start, end = item.split(":")
            sectors.append((float(start), float(end)))
    return sectors


@dataclass(frozen=True, slots=True)
class Scan:
    ts_start: int
    ts_end: int
    seq: int
    mount: Mount
    distance_mm: np.ndarray
    angle_deg: np.ndarray

    def __len__(self) -> int:
        return len(self.distance_mm)


def encode_scan(ts_start: int, ts_end: int, seq: int, mount: Mount, distance_mm, angle_q6) -> bytes:
    points = np.empty(len(distance_mm), dtype=POINT)
    points["distance_mm"] = np.clip(np.asarray(distance_mm), 0, 65535)
    points["angle_q6"] = np.asarray(angle_q6) % int(360 * ANGLE_SCALE)
    header = HEADER.pack(ts_start, ts_end, seq & 0xFFFFFFFF, len(points), 0, mount.x, mount.y, mount.z, mount.yaw_deg)
    return header + points.tobytes()


def decode_scan(data: bytes) -> Scan:
    ts_start, ts_end, seq, count, _, x, y, z, yaw = HEADER.unpack_from(data)
    points = np.frombuffer(data, dtype=POINT, count=count, offset=HEADER.size)
    mount = Mount(*(round(value, 4) for value in (x, y, z, yaw)))
    return Scan(ts_start, ts_end, seq, mount, points["distance_mm"].astype(float), points["angle_q6"] / ANGLE_SCALE)


def masked(angle_deg: np.ndarray, sectors: list[tuple[float, float]]) -> np.ndarray:
    hidden = np.zeros(len(angle_deg), dtype=bool)
    for start, end in sectors:
        span = (end - start) % 360.0
        hidden |= (angle_deg - start) % 360.0 <= span
    return hidden


def points_xy(scan: Scan) -> np.ndarray:
    ranges = scan.distance_mm / 1000.0
    theta = np.radians(scan.mount.yaw_deg - scan.angle_deg)
    return np.stack([scan.mount.x + ranges * np.cos(theta), scan.mount.y + ranges * np.sin(theta)], axis=1)


def point_times(scan: Scan) -> np.ndarray:
    if len(scan) < 2:
        return np.full(len(scan), scan.ts_end, dtype=np.int64)
    swept = np.concatenate([[0.0], np.cumsum(np.diff(scan.angle_deg) % 360.0)])
    fraction = swept / swept[-1] if swept[-1] > 0 else np.linspace(0.0, 1.0, len(scan))
    return scan.ts_start + np.round(fraction * (scan.ts_end - scan.ts_start)).astype(np.int64)


Pose = tuple[np.ndarray, np.ndarray, np.ndarray]


def deskew(scan: Scan, poses_at: Callable[[np.ndarray], Pose]) -> np.ndarray:
    local = points_xy(scan)
    x, y, heading = poses_at(point_times(scan))
    cos, sin = np.cos(heading), np.sin(heading)
    return np.stack([x + local[:, 0] * cos - local[:, 1] * sin, y + local[:, 0] * sin + local[:, 1] * cos], axis=1)


def sector_minimums(scan: Scan, sectors: int = SECTORS) -> list[float | None]:
    xy = points_xy(scan)
    bearing = np.degrees(np.arctan2(xy[:, 1], xy[:, 0])) % 360.0
    index = np.floor(bearing / (360.0 / sectors)).astype(int) % sectors
    ranges = np.hypot(xy[:, 0], xy[:, 1])
    nearest: list[float | None] = []
    for sector in range(sectors):
        inside = ranges[index == sector]
        nearest.append(round(float(inside.min()), 3) if len(inside) else None)
    return nearest


def scan_period_s(scan: Scan) -> float:
    return max(scan.ts_end - scan.ts_start, 0) * 1e-9


def to_safety_frame(points: np.ndarray) -> np.ndarray:
    return np.stack([points[:, 0], -points[:, 1]], axis=1) if len(points) else np.empty((0, 2))
