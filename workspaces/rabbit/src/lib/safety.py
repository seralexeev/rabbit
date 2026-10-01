from dataclasses import dataclass

import numpy as np
from lib.geometry import CAMERA_TO_REAR_AXLE


@dataclass(frozen=True, slots=True)
class Footprint:
    front: float = 0.2245
    rear: float = 0.07
    half_width: float = 0.10
    margin: float = 0.04


def scan_points(scan: dict) -> np.ndarray:
    ranges = np.array([np.nan if r is None else r for r in scan["ranges"]], dtype=float)
    angles = np.radians(scan["angle_min_deg"] + (np.arange(len(ranges)) + 0.5) * scan["angle_step_deg"])
    valid = np.isfinite(ranges)
    along = ranges[valid] * np.cos(angles[valid]) + CAMERA_TO_REAR_AXLE
    across = ranges[valid] * np.sin(angles[valid])
    return np.stack([along, across], axis=1)


def bin_scan(along: np.ndarray, across: np.ndarray, half_fov_deg: float, bins: int, min_points: int) -> np.ndarray:
    angles = np.degrees(np.arctan2(across, along))
    ranges = np.hypot(along, across)
    index = np.floor((angles + half_fov_deg) / (2 * half_fov_deg / bins)).astype(int)
    valid = (index >= 0) & (index < bins)
    index, ranges = index[valid], ranges[valid]
    order = np.lexsort((ranges, index))
    index, ranges = index[order], ranges[order]
    if len(ranges) == 0:
        return np.full(bins, np.inf)
    counts = np.bincount(index, minlength=bins)
    kth = np.minimum(np.searchsorted(index, np.arange(bins)) + min_points - 1, len(ranges) - 1)
    return np.where(counts >= min_points, ranges[kth], np.inf)


def heights_above_floor(
    offset_xz: np.ndarray,
    y: np.ndarray,
    band: float = 0.08,
    inlier: float = 0.02,
    max_slope: float = 0.15,
    min_points: int = 200,
) -> np.ndarray:
    candidates = np.abs(y) < band
    if candidates.sum() < min_points:
        return y
    design = np.column_stack([offset_xz[:, 0], offset_xz[:, 1], np.ones(len(y))])
    for _ in range(2):
        plane, *_ = np.linalg.lstsq(design[candidates], y[candidates], rcond=None)
        residual = y - _plane_height(offset_xz, plane)
        candidates = np.abs(residual) < inlier
        if candidates.sum() < min_points:
            return y
    if np.abs(plane[:2]).max() > max_slope or abs(plane[2]) > band:
        return y
    return y - _plane_height(offset_xz, plane)


def _plane_height(offset_xz: np.ndarray, plane: np.ndarray) -> np.ndarray:
    return plane[0] * offset_xz[:, 0] + plane[1] * offset_xz[:, 1] + plane[2]


def sweep_poses(curvature: float, distances: np.ndarray) -> np.ndarray:
    heading = curvature * distances
    if abs(curvature) < 1e-6:
        return np.stack([distances, np.zeros_like(distances), heading], axis=1)
    return np.stack([np.sin(heading) / curvature, (1 - np.cos(heading)) / curvature, heading], axis=1)


def free_distance(
    points: np.ndarray,
    curvature: float,
    lookahead: float,
    direction: int = 1,
    footprint: Footprint = Footprint(),
    step: float = 0.02,
) -> float:
    if len(points) == 0:
        return lookahead
    distances = np.arange(0.0, lookahead + step, step)
    poses = sweep_poses(curvature, direction * distances)
    dx = points[None, :, 0] - poses[:, None, 0]
    dy = points[None, :, 1] - poses[:, None, 1]
    cos, sin = np.cos(poses[:, 2])[:, None], np.sin(poses[:, 2])[:, None]
    along = dx * cos + dy * sin
    across = -dx * sin + dy * cos
    margin = footprint.margin
    inside = (
        (along <= footprint.front + margin)
        & (along >= -footprint.rear - margin)
        & (np.abs(across) <= footprint.half_width + margin)
    ).any(axis=1)
    hit = np.flatnonzero(inside)
    return float(distances[hit[0]]) if len(hit) else lookahead
