from __future__ import annotations

import math

import numpy as np
from lib.geometry import CENTERLINE_OFFSET
from lib.planner import (
    FREE,
    OCCUPIED,
    UNKNOWN,
    CostMap,
    Footprint,
    OccupancyGrid,
    build_costmap,
    costmap_from_clearance,
    grid_from_mesh,
    with_obstacles,
)
from lib.spatial_map import GRID_UNKNOWN, decode_chunks, decode_grid
from lib.trip import PARAMS, Navigator, Target
from numba import njit

USE_GRID = True
FREE_RANGE_WITHOUT_HIT = 2.5
HIT_RANGE = 3.0
BLIND_RANGE = 0.4


def forward_of(orientation: list[float]) -> np.ndarray:
    x, y, z, w = orientation
    forward = np.array([-2 * (x * z + y * w), -(1 - 2 * (x * x + y * y))])
    return forward / np.linalg.norm(forward)


def camera_frame(pose: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    forward = forward_of(pose["orientation"])
    right = np.array([-forward[1], forward[0]])
    origin = np.array([pose["translation"][0], pose["translation"][2]]) + CENTERLINE_OFFSET * right
    return origin, forward, right


def scan_rays(scan: dict, origin: np.ndarray, forward: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hits = np.array([r is not None and r < FREE_RANGE_WITHOUT_HIT for r in scan["ranges"]])
    ranges = np.array([FREE_RANGE_WITHOUT_HIT if r is None else min(r, FREE_RANGE_WITHOUT_HIT) for r in scan["ranges"]])
    angles = np.radians(scan["angle_min_deg"] + (np.arange(len(ranges)) + 0.5) * scan["angle_step_deg"])
    along, across = ranges * np.cos(angles), ranges * np.sin(angles)
    return origin + np.outer(along, forward) + np.outer(across, right), hits


@njit(cache=True)
def _clear_rays(cells: np.ndarray, ox: float, oz: float, resolution: float, origins: np.ndarray, ends: np.ndarray) -> None:
    height, width = cells.shape
    step = 0.5 * resolution
    for i in range(len(ends)):
        sx, sz = origins[i, 0], origins[i, 1]
        dx, dz = ends[i, 0] - sx, ends[i, 1] - sz
        length = math.hypot(dx, dz)
        reach = length - resolution
        if reach <= 0:
            continue
        count = int(math.ceil(reach / step))
        for j in range(count):
            t = j * step / length
            ix = int(math.floor((sx + t * dx - ox) / resolution))
            iz = int(math.floor((sz + t * dz - oz) / resolution))
            if 0 <= ix < width and 0 <= iz < height and cells[iz, ix] == -1:
                cells[iz, ix] = 0


def clear_unknown(grid: OccupancyGrid, origins: np.ndarray, ends: np.ndarray) -> None:
    origins = np.ascontiguousarray(np.broadcast_to(np.asarray(origins, dtype=np.float64).reshape(-1, 2), np.shape(ends)))
    _clear_rays(grid.cells, float(grid.origin[0]), float(grid.origin[1]), float(grid.resolution), origins, np.ascontiguousarray(ends, dtype=np.float64))


def body_cells(x: float, z: float, theta: float) -> np.ndarray:
    along = np.arange(-0.1, 0.3, 0.025)
    across = np.arange(-0.12, 0.125, 0.025)
    a, c = np.meshgrid(along, across)
    forward = np.array([math.cos(theta), math.sin(theta)])
    right = np.array([-forward[1], forward[0]])
    return np.array([x, z]) + np.outer(a.ravel(), forward) + np.outer(c.ravel(), right)


class ScanHistory:
    MIN_MOVE = 0.05
    MIN_TURN = math.radians(3.0)
    MAX_SCANS = 2000
    RECENT_HITS = 50

    def __init__(self):
        self.scans: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []

    def clear(self):
        self.scans = []

    def add(self, origin: np.ndarray, forward: np.ndarray, ends: np.ndarray, hits: np.ndarray) -> None:
        if self.scans:
            last_origin, last_ends, _ = self.scans[-1]
            last_heading = math.atan2(*(last_ends[len(last_ends) // 2] - last_origin)[::-1])
            heading = math.atan2(forward[1], forward[0])
            moved = np.linalg.norm(origin - last_origin) >= self.MIN_MOVE
            turned = abs((heading - last_heading + math.pi) % (2 * math.pi) - math.pi) >= self.MIN_TURN
            if not (moved or turned):
                return
        self.scans.append((origin, ends, hits))
        del self.scans[: -self.MAX_SCANS]

    def points(self) -> np.ndarray:
        if not self.scans:
            return np.empty((0, 2))
        return np.concatenate([np.vstack([origin, ends]) for origin, ends, _ in self.scans])

    def apply(self, grid: OccupancyGrid) -> None:
        if not self.scans:
            return
        origins = np.concatenate([np.broadcast_to(origin, ends.shape) for origin, ends, _ in self.scans])
        ends = np.concatenate([ends for _, ends, _ in self.scans])
        clear_unknown(grid, origins, ends)
        for _, ends, hits in self.scans[-self.RECENT_HITS :]:
            grid.mark_points(ends[hits], OCCUPIED)


class ObstacleMemory:
    CELL = 0.05

    def __init__(self, memory_s: float = 6.0):
        self.memory_s = memory_s
        self.hits = np.empty((0, 2))
        self.times = np.empty(0)

    def clear(self):
        self.hits = np.empty((0, 2))
        self.times = np.empty(0)

    def expire(self, now: float) -> None:
        fresh = now - self.times <= self.memory_s
        self.hits, self.times = self.hits[fresh], self.times[fresh]

    def add(self, now: float, origin: np.ndarray, ends: np.ndarray, hits: np.ndarray) -> None:
        self.expire(now)
        if len(self.hits):
            rays = ends - origin
            reach = np.linalg.norm(rays, axis=1)
            ray_bearing = np.arctan2(rays[:, 1], rays[:, 0])
            offset = self.hits - origin
            distance = np.linalg.norm(offset, axis=1)
            gap = np.abs((np.arctan2(offset[:, 1], offset[:, 0])[:, None] - ray_bearing[None, :] + np.pi) % (2 * np.pi) - np.pi)
            nearest = gap.argmin(axis=1)
            passed = (gap[np.arange(len(gap)), nearest] < math.radians(2.0)) & (distance < reach[nearest] - 0.1) & (distance > BLIND_RANGE)
            self.hits, self.times = self.hits[~passed], self.times[~passed]
        close = hits & (np.linalg.norm(ends - origin, axis=1) <= HIT_RANGE)
        if not close.any():
            return
        points = np.vstack([self.hits, ends[close]])
        times = np.concatenate([self.times, np.full(int(close.sum()), now)])
        cells = np.floor(points / self.CELL).astype(np.int64)
        newest_first = np.argsort(-times, kind="stable")
        _, keep = np.unique(cells[newest_first], axis=0, return_index=True)
        chosen = newest_first[keep]
        self.hits, self.times = points[chosen], times[chosen]

    def points(self, now: float) -> np.ndarray:
        self.expire(now)
        return self.hits.copy()


class MeshMap:
    kind = "mesh"

    def __init__(self, footprint: Footprint, proximity_band: float):
        self.footprint = footprint
        self.proximity_band = proximity_band
        self.session: str | None = None
        self.chunks: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.version = 0

    def reset(self, session: str | None):
        self.session = session
        self.chunks = {}
        self.version += 1

    def apply(self, session: str | None, payload: bytes, snapshot: bool = False) -> bool:
        changed = session != self.session
        if changed or snapshot:
            self.reset(session)
        self.chunks.update(decode_chunks(payload))
        self.version += 1
        return changed

    def ready(self) -> bool:
        return bool(self.chunks)

    def occupancy(self, extra_points: np.ndarray) -> OccupancyGrid | None:
        chunks = [chunk for chunk in self.chunks.values() if len(chunk[0])]
        if not chunks:
            return None
        offsets = np.cumsum([0] + [len(v) for v, _ in chunks])[:-1]
        vertices = np.concatenate([v for v, _ in chunks] + [np.column_stack([extra_points[:, 0], np.full(len(extra_points), 1.0), extra_points[:, 1]])])
        triangles = np.concatenate([t + offset for (_, t), offset in zip(chunks, offsets)])
        return grid_from_mesh(vertices, triangles)

    def costmap(self, scans: ScanHistory, trail: np.ndarray, robot: tuple[float, float, float] | None) -> CostMap | None:
        grid = self.occupancy(np.vstack([scans.points(), trail.reshape(-1, 2)]))
        if grid is None:
            return None
        scans.apply(grid)
        mark_known(grid, trail, robot)
        return build_costmap(grid, self.footprint, False, self.proximity_band)


class ClearanceGridMap:
    kind = "grid"

    def __init__(self, footprint: Footprint):
        self.footprint = footprint
        self.session: str | None = None
        self.grid: tuple[tuple[float, float], float, np.ndarray] | None = None
        self.version = 0

    def apply(self, session: str | None, payload: bytes, snapshot: bool = False) -> bool:
        changed = session != self.session
        self.session = session
        self.grid = decode_grid(payload)
        self.version += 1
        return changed

    def ready(self) -> bool:
        return self.grid is not None

    def costmap(self, scans: ScanHistory, trail: np.ndarray, robot: tuple[float, float, float] | None) -> CostMap | None:
        if self.grid is None:
            return None
        origin, resolution, clearance = self.grid
        costmap = costmap_from_clearance(origin, resolution, clearance.copy(), self.footprint, GRID_UNKNOWN)
        mark_known(costmap.grid, trail, robot)
        return costmap


def mark_known(grid: OccupancyGrid, trail: np.ndarray, robot: tuple[float, float, float] | None) -> None:
    points = [trail.reshape(-1, 2)]
    if robot is not None:
        points.append(body_cells(*robot))
    iz, ix, inside = grid.cell_index(np.vstack(points))
    iz, ix = iz[inside], ix[inside]
    unknown = grid.cells[iz, ix] == UNKNOWN
    grid.cells[iz[unknown], ix[unknown]] = FREE
    if robot is not None:
        iz, ix, inside = grid.cell_index(body_cells(*robot))
        grid.cells[iz[inside], ix[inside]] = FREE


def map_source() -> MeshMap | ClearanceGridMap:
    return ClearanceGridMap(PARAMS.footprint) if USE_GRID else MeshMap(PARAMS.footprint, PARAMS.proximity_band)


def warm_up() -> None:
    grid = OccupancyGrid.filled((0.0, 0.0), 60, 40, 0.05, FREE)
    grid.cells[[0, -1], :] = OCCUPIED
    grid.cells[:, [0, -1]] = OCCUPIED
    grid.cells[10:30, 30] = OCCUPIED
    scans = ScanHistory()
    scans.add(np.array([0.5, 1.0]), np.array([1.0, 0.0]), np.array([[2.0, 1.0], [1.5, 1.5]]), np.array([True, False]))
    scans.apply(grid)
    costmap = with_obstacles(build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band), np.array([[2.2, 0.5]]), PARAMS.proximity_band)
    clearance = np.where(grid.cells == OCCUPIED, 0, 500).astype(np.int16)
    costmap_from_clearance(grid.origin, grid.resolution, clearance, PARAMS.footprint, GRID_UNKNOWN)
    for target in (Target("point", 2.6, 1.4), Target("point", 2.6, 0.6, 0.0), Target("object", 2.6, 1.0, size=0.2), Target("point", 9.0, 1.0)):
        navigator = Navigator()
        navigator.on_map(costmap, np.empty((0, 2)))
        navigator.on_pose(np.array([0.6, 1.0]), 0.0, 0.0)
        navigator.request("warm-up", "warm-up", target, 0.0)
        job = navigator.tick(0.0)
        if job is not None:
            job.run()
