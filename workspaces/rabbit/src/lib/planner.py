from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field, replace

import numpy as np
from lib.geometry import MAX_CURVATURE, camera_point, curvature_for_steer
from numba import njit, objmode

FREE = 0
OCCUPIED = 1
UNKNOWN = -1

MIN_TURN_RADIUS = 1.0 / MAX_CURVATURE

_SQRT2 = math.sqrt(2.0)
_NEIGHBOURS = ((0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0), (1, 1, _SQRT2), (1, -1, _SQRT2), (-1, 1, _SQRT2), (-1, -1, _SQRT2))
_DZ = np.array([n[0] for n in _NEIGHBOURS], dtype=np.int64)
_DX = np.array([n[1] for n in _NEIGHBOURS], dtype=np.int64)
_STEP = np.array([n[2] for n in _NEIGHBOURS], dtype=np.float64)


@dataclass
class OccupancyGrid:
    origin: tuple[float, float]
    resolution: float
    width: int
    height: int
    cells: np.ndarray

    @classmethod
    def filled(
        cls, origin: tuple[float, float], width: int, height: int, resolution: float = 0.05, value: int = UNKNOWN
    ) -> OccupancyGrid:
        return cls(origin, resolution, width, height, np.full((height, width), value, dtype=np.int8))

    def cell_index(self, points_xz: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        points = np.asarray(points_xz, dtype=np.float64).reshape(-1, 2)
        ix = np.floor((points[:, 0] - self.origin[0]) / self.resolution).astype(np.intp)
        iz = np.floor((points[:, 1] - self.origin[1]) / self.resolution).astype(np.intp)
        inside = (ix >= 0) & (ix < self.width) & (iz >= 0) & (iz < self.height)
        return iz, ix, inside

    def cell_center(self, iz: int, ix: int) -> tuple[float, float]:
        return (self.origin[0] + (ix + 0.5) * self.resolution, self.origin[1] + (iz + 0.5) * self.resolution)

    def mark_points(self, points_xz: np.ndarray, value: int = OCCUPIED) -> None:
        iz, ix, inside = self.cell_index(points_xz)
        self.cells[iz[inside], ix[inside]] = value


@dataclass(frozen=True)
class Pose2D:
    x: float
    z: float
    theta: float


@dataclass(frozen=True)
class Footprint:
    rear_overhang: float = 0.07
    front_overhang: float = 0.2245
    width: float = 0.20
    margin: float = 0.02

    @property
    def radius(self) -> float:
        return 0.5 * self.width + self.margin

    @property
    def circle_offsets(self) -> tuple[float, float, float]:
        length = self.front_overhang + self.rear_overhang
        center = 0.5 * (self.front_overhang - self.rear_overhang)
        return (center - length / 3.0, center, center + length / 3.0)


@dataclass(frozen=True)
class PlannerParams:
    min_turn_radius: float = MIN_TURN_RADIUS
    step: float = 0.15
    heading_bins: int = 72
    key_cells: int = 2
    steer_fractions: tuple[float, ...] = (-1.0, -0.5, 0.0, 0.5, 1.0)
    reverse_penalty: float = 3.0
    gear_switch_penalty: float = 1.0
    steer_change_penalty: float = 0.05
    unknown_cost: float = 1.0
    unknown_blocked: bool = False
    proximity_band: float = 0.35
    proximity_weight: float = 3.0
    goal_tolerance: float = 0.12
    heading_tolerance: float = math.radians(15.0)
    heuristic_weight: float = 1.5
    heuristic_slack: float = 3.0
    shot_interval: int = 8
    shot_distance: float = 4.0
    shot_slack: float = 1.1
    goal_offset: float = 0.0
    escape_radius: float = 0.5
    untraversed_reverse_penalty: float = 0.0
    max_expansions: int = 300_000
    time_limit: float = 1.5
    footprint: Footprint = field(default_factory=Footprint)


@dataclass(frozen=True)
class CostMap:
    grid: OccupancyGrid
    distance: np.ndarray
    footprint: Footprint

    @property
    def collision_radius(self) -> float:
        return self.footprint.radius + (0.5 + 0.5 * _SQRT2) * self.grid.resolution


@dataclass(frozen=True)
class Waypoint:
    x: float
    z: float
    theta: float
    direction: int


@dataclass(frozen=True)
class Path:
    waypoints: list[Waypoint]
    length: float
    reverse_length: float
    gear_switches: int
    cost: float

    def poses(self) -> np.ndarray:
        return np.array([(w.x, w.z, w.theta) for w in self.waypoints], dtype=np.float64).reshape(-1, 3)

    def directions(self) -> np.ndarray:
        return np.array([w.direction for w in self.waypoints], dtype=np.int64)


@dataclass(frozen=True)
class Segment:
    direction: int
    points: np.ndarray


@dataclass(frozen=True)
class SearchStats:
    expansions: int
    heuristic_ms: float
    search_ms: float
    reason: str


def wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _barycentric_weights(divisions: int) -> np.ndarray:
    i, j = np.meshgrid(np.arange(divisions + 1), np.arange(divisions + 1), indexing="ij")
    keep = i + j <= divisions
    a = i[keep] / divisions
    b = j[keep] / divisions
    return np.stack([1.0 - a - b, a, b], axis=1).astype(np.float32)


def sample_triangles(corners: np.ndarray, spacing: float, max_divisions: int = 512) -> np.ndarray:
    if len(corners) == 0:
        return np.empty((0, 3), dtype=np.float32)
    edges = np.linalg.norm(corners - np.roll(corners, 1, axis=1), axis=2).max(axis=1)
    divisions = np.clip(np.ceil(edges / spacing), 1, max_divisions).astype(np.intp)
    samples = []
    for count in np.unique(divisions):
        group = corners[divisions == count].astype(np.float32)
        weights = _barycentric_weights(int(count))
        chunk = max(1, 2_000_000 // len(weights))
        for begin in range(0, len(group), chunk):
            samples.append(np.einsum("mk,tkd->tmd", weights, group[begin : begin + chunk]).reshape(-1, 3))
    return np.concatenate(samples)


def grid_from_mesh(
    vertices: np.ndarray,
    triangles: np.ndarray,
    resolution: float = 0.05,
    obstacle_band: tuple[float, float] = (0.04, 0.45),
    floor_band: tuple[float, float] = (-0.05, 0.04),
    margin: float = 0.5,
    floor_normal_min: float = 0.8,
) -> OccupancyGrid:
    vertices = np.asarray(vertices, dtype=np.float64)[:, :3]
    corners = vertices[np.asarray(triangles, dtype=np.intp)]
    low = vertices[:, [0, 2]].min(axis=0) - margin
    high = vertices[:, [0, 2]].max(axis=0) + margin
    width, height = np.ceil((high - low) / resolution).astype(int)
    grid = OccupancyGrid.filled((float(low[0]), float(low[1])), int(width), int(height), resolution)
    spacing = 0.5 * resolution

    heights = corners[:, :, 1]
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    norms = np.linalg.norm(normals, axis=1)
    upright = np.abs(normals[:, 1]) > floor_normal_min * np.maximum(norms, 1e-12)
    floor = upright & (heights.min(axis=1) >= floor_band[0]) & (heights.max(axis=1) <= floor_band[1])
    grid.mark_points(sample_triangles(corners[floor], spacing)[:, [0, 2]], FREE)

    crossing = (heights.max(axis=1) >= obstacle_band[0]) & (heights.min(axis=1) <= obstacle_band[1])
    samples = sample_triangles(corners[crossing], spacing)
    in_band = (samples[:, 1] >= obstacle_band[0]) & (samples[:, 1] <= obstacle_band[1])
    grid.mark_points(samples[in_band][:, [0, 2]], OCCUPIED)
    return grid


@njit(cache=True, nogil=True)
def _stamp(distance: np.ndarray, sources_z: np.ndarray, sources_x: np.ndarray, offsets: np.ndarray) -> None:
    height, width = distance.shape
    for i in range(len(sources_z)):
        sz, sx = sources_z[i], sources_x[i]
        for k in range(len(offsets)):
            z = sz + int(offsets[k, 0])
            x = sx + int(offsets[k, 1])
            if 0 <= z < height and 0 <= x < width and offsets[k, 2] < distance[z, x]:
                distance[z, x] = offsets[k, 2]


def _disk(radius_m: float, resolution: float) -> np.ndarray:
    reach = int(math.ceil(radius_m / resolution))
    dz, dx = np.mgrid[-reach : reach + 1, -reach : reach + 1]
    offset = np.hypot(dz, dx) * resolution
    keep = offset < radius_m
    return np.column_stack([dz[keep], dx[keep], offset[keep]]).astype(np.float64)


def inflate(grid: OccupancyGrid, radius_m: float, unknown_blocked: bool = False) -> np.ndarray:
    blocked = grid.cells == OCCUPIED
    if unknown_blocked:
        blocked |= grid.cells == UNKNOWN
    distance = np.full(blocked.shape, radius_m, dtype=np.float32)
    sources = np.argwhere(blocked)
    _stamp(distance, sources[:, 0].astype(np.int64), sources[:, 1].astype(np.int64), _disk(radius_m, grid.resolution))
    return distance


def _reach(footprint: Footprint, resolution: float, proximity_band: float) -> float:
    return footprint.radius + (0.5 + 0.5 * _SQRT2) * resolution + proximity_band + 2.0 * resolution


def build_costmap(
    grid: OccupancyGrid, footprint: Footprint = Footprint(), unknown_blocked: bool = False, proximity_band: float = 0.25
) -> CostMap:
    return CostMap(grid, inflate(grid, _reach(footprint, grid.resolution, proximity_band), unknown_blocked), footprint)


def costmap_from_clearance(
    origin: tuple[float, float], resolution: float, clearance_mm: np.ndarray, footprint: Footprint = Footprint(), unknown: int = -1
) -> CostMap:
    clearance_mm = np.asarray(clearance_mm)
    height, width = clearance_mm.shape
    cells = np.where(clearance_mm == unknown, UNKNOWN, np.where(clearance_mm <= 0, OCCUPIED, FREE)).astype(np.int8)
    distance = np.where(clearance_mm == unknown, np.float32(32.767), clearance_mm.astype(np.float32) / 1000.0).astype(np.float32)
    return CostMap(OccupancyGrid((float(origin[0]), float(origin[1])), float(resolution), width, height, cells), distance, footprint)


def with_obstacles(costmap: CostMap, points_xz: np.ndarray, proximity_band: float = 0.25) -> CostMap:
    points = np.asarray(points_xz, dtype=np.float64).reshape(-1, 2)
    iz, ix, inside = costmap.grid.cell_index(points)
    if not inside.any():
        return costmap
    cells = costmap.grid.cells.copy()
    cells[iz[inside], ix[inside]] = OCCUPIED
    distance = costmap.distance.copy()
    reach = _reach(costmap.footprint, costmap.grid.resolution, proximity_band)
    _stamp(distance, iz[inside].astype(np.int64), ix[inside].astype(np.int64), _disk(reach, costmap.grid.resolution))
    return CostMap(replace(costmap.grid, cells=cells), distance, costmap.footprint)


def expand(costmap: CostMap, points_xz: np.ndarray, margin: float = 1.5, proximity_band: float = 0.35) -> CostMap:
    grid = costmap.grid
    points = np.asarray(points_xz, dtype=np.float64).reshape(-1, 2)
    if len(points) == 0:
        return costmap
    res = grid.resolution
    before = np.ceil((np.asarray(grid.origin) - (points.min(axis=0) - margin)) / res).clip(0).astype(int)
    after = np.ceil(((points.max(axis=0) + margin) - (np.asarray(grid.origin) + res * np.array([grid.width, grid.height]))) / res).clip(0).astype(int)
    if not before.any() and not after.any():
        return costmap
    pad = ((int(before[1]), int(after[1])), (int(before[0]), int(after[0])))
    reach = _reach(costmap.footprint, res, proximity_band)
    cells = np.pad(grid.cells, pad, constant_values=UNKNOWN)
    distance = np.pad(costmap.distance, pad, constant_values=np.float32(max(reach, float(costmap.distance.max(initial=reach)))))
    border = int(math.ceil(reach / res))
    edge = np.zeros(grid.cells.shape, dtype=bool)
    edge[:border, :] = edge[-border:, :] = True
    edge[:, :border] = edge[:, -border:] = True
    sources = np.argwhere(edge & (grid.cells == OCCUPIED)) + np.array([pad[0][0], pad[1][0]])
    _stamp(distance, sources[:, 0].astype(np.int64), sources[:, 1].astype(np.int64), _disk(reach, res))
    origin = (grid.origin[0] - before[0] * res, grid.origin[1] - before[1] * res)
    return CostMap(OccupancyGrid(origin, res, cells.shape[1], cells.shape[0], cells), distance, costmap.footprint)


def crop(costmap: CostMap, low_xz: tuple[float, float], high_xz: tuple[float, float]) -> CostMap:
    grid = costmap.grid
    iz, ix, _ = grid.cell_index(np.array([low_xz, high_xz]))
    z0, z1 = int(np.clip(min(iz), 0, grid.height)), int(np.clip(max(iz) + 1, 0, grid.height))
    x0, x1 = int(np.clip(min(ix), 0, grid.width)), int(np.clip(max(ix) + 1, 0, grid.width))
    origin = (grid.origin[0] + x0 * grid.resolution, grid.origin[1] + z0 * grid.resolution)
    cells = grid.cells[z0:z1, x0:x1]
    return CostMap(OccupancyGrid(origin, grid.resolution, x1 - x0, z1 - z0, cells), costmap.distance[z0:z1, x0:x1], costmap.footprint)


def swept_cells(grid: OccupancyGrid, poses: np.ndarray, footprint: Footprint, spacing: float = 0.025) -> np.ndarray:
    poses = np.asarray(poses, dtype=np.float64).reshape(-1, 3)
    along, across = np.meshgrid(
        np.arange(-footprint.rear_overhang, footprint.front_overhang + 1e-9, spacing), np.arange(-0.5 * footprint.width, 0.5 * footprint.width + 1e-9, spacing)
    )
    along, across = along.ravel(), across.ravel()
    cos, sin = np.cos(poses[:, 2])[:, None], np.sin(poses[:, 2])[:, None]
    points = np.stack([poses[:, :1] + cos * along - sin * across, poses[:, 1:2] + sin * along + cos * across], axis=2).reshape(-1, 2)
    mask = np.zeros(grid.cells.shape, dtype=bool)
    iz, ix, inside = grid.cell_index(points)
    mask[iz[inside], ix[inside]] = True
    return mask


def footprint_centers(poses: np.ndarray, footprint: Footprint) -> np.ndarray:
    poses = np.asarray(poses, dtype=np.float64).reshape(-1, 3)
    offsets = np.asarray(footprint.circle_offsets)
    heading = np.stack([np.cos(poses[:, 2]), np.sin(poses[:, 2])], axis=1)
    return poses[:, None, :2] + offsets[None, :, None] * heading[:, None, :]


def pose_clearance(costmap: CostMap, poses: np.ndarray) -> np.ndarray:
    centers = footprint_centers(poses, costmap.footprint)
    iz, ix, inside = costmap.grid.cell_index(centers.reshape(-1, 2))
    distance = np.where(inside, costmap.distance[np.clip(iz, 0, costmap.grid.height - 1), np.clip(ix, 0, costmap.grid.width - 1)], -np.inf)
    return (distance - costmap.collision_radius).reshape(centers.shape[:2]).min(axis=1)


def is_path_blocked(grid_or_costmap: OccupancyGrid | CostMap, path: Path, from_index: int = 0) -> bool:
    costmap = grid_or_costmap if isinstance(grid_or_costmap, CostMap) else build_costmap(grid_or_costmap)
    poses = path.poses()[from_index:]
    return bool(len(poses)) and bool((pose_clearance(costmap, poses) < 0).any())


@njit(cache=True, nogil=True)
def _dijkstra(cell_cost: np.ndarray, seed: int, resolution: float, stop: int, slack: float, dz: np.ndarray, dx: np.ndarray, steps: np.ndarray) -> np.ndarray:
    height, width = cell_cost.shape
    flat = cell_cost.ravel()
    cost = np.full(height * width, np.inf)
    cost[seed] = 0.0
    heap = [(0.0, seed)]
    limit = np.inf
    while len(heap) > 0:
        current, cell = heapq.heappop(heap)
        if current > cost[cell]:
            continue
        if current > limit:
            break
        if cell == stop:
            limit = current * 1.25 + slack
        z = cell // width
        x = cell - z * width
        here = flat[cell]
        for k in range(8):
            nz = z + dz[k]
            nx = x + dx[k]
            if nz < 0 or nz >= height or nx < 0 or nx >= width:
                continue
            neighbour = nz * width + nx
            weight = flat[neighbour]
            if weight == np.inf:
                continue
            candidate = current + steps[k] * resolution * 0.5 * (here + weight)
            if candidate < cost[neighbour]:
                cost[neighbour] = candidate
                heapq.heappush(heap, (candidate, neighbour))
    return cost.reshape(height, width)


def holonomic_distance(cell_cost: np.ndarray, seed_cell: tuple[int, int], resolution: float, stop_cell: tuple[int, int] | None = None, slack: float = 0.0) -> np.ndarray:
    height, width = cell_cost.shape
    seed = seed_cell[0] * width + seed_cell[1]
    stop = -1 if stop_cell is None else stop_cell[0] * width + stop_cell[1]
    return _dijkstra(np.ascontiguousarray(cell_cost, dtype=np.float64), seed, float(resolution), stop, float(slack), _DZ, _DX, _STEP)


def distance_map_from(costmap: CostMap, origin_xz: tuple[float, float], unknown_cost: float = 0.0) -> np.ndarray:
    grid = costmap.grid
    iz, ix, inside = grid.cell_index(np.asarray(origin_xz))
    if not inside[0]:
        return np.full((grid.height, grid.width), np.inf)
    nearest_offset = min(abs(o) for o in costmap.footprint.circle_offsets)
    passable = costmap.distance >= costmap.collision_radius - nearest_offset - 1.5 * grid.resolution
    cell_cost = np.where(passable, 1.0 + unknown_cost * (grid.cells == UNKNOWN), np.inf)
    reach = int(math.ceil(0.3 / grid.resolution))
    around = cell_cost[max(iz[0] - reach, 0) : iz[0] + reach + 1, max(ix[0] - reach, 0) : ix[0] + reach + 1]
    around[np.isinf(around)] = 1.0 + unknown_cost
    return holonomic_distance(cell_cost, (int(iz[0]), int(ix[0])), grid.resolution)


def _arc(signed_length: float, curvature: float) -> tuple[float, float, float]:
    if abs(curvature) < 1e-9:
        return signed_length, 0.0, 0.0
    turn = signed_length * curvature
    return math.sin(turn) / curvature, (1.0 - math.cos(turn)) / curvature, turn


@dataclass(frozen=True)
class _Primitives:
    direction: np.ndarray
    steer: np.ndarray
    curvature: np.ndarray
    end: np.ndarray
    probe_x: np.ndarray
    probe_z: np.ndarray


def _primitives(params: PlannerParams) -> _Primitives:
    offsets = params.footprint.circle_offsets
    direction, steer, curvatures, end, probes = [], [], [], [], []
    for gear in (1, -1):
        for fraction in params.steer_fractions:
            curvature = curvature_for_steer(fraction)
            row = []
            for travelled in (0.5, 1.0):
                x, z, turn = _arc(gear * params.step * travelled, curvature)
                row.extend((x + o * math.cos(turn), z + o * math.sin(turn)) for o in offsets)
            probes.append(row)
            direction.append(gear)
            steer.append(fraction)
            curvatures.append(curvature)
            end.append(_arc(gear * params.step, curvature))
    probe = np.asarray(probes, dtype=np.float64)
    return _Primitives(
        np.asarray(direction, dtype=np.int64),
        np.asarray(steer, dtype=np.float64),
        np.asarray(curvatures, dtype=np.float64),
        np.asarray(end, dtype=np.float64),
        np.ascontiguousarray(probe[:, :, 0]),
        np.ascontiguousarray(probe[:, :, 1]),
    )


@njit(cache=True)
def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


@njit(cache=True)
def _mod(angle: float) -> float:
    return angle % (2.0 * math.pi)


@njit(cache=True)
def _word(words: np.ndarray, index: int, t: float, p: float, q: float) -> None:
    words[index, 0] = index
    words[index, 1] = t
    words[index, 2] = p
    words[index, 3] = q


@njit(cache=True)
def _dubins(alpha: float, beta: float, d: float) -> np.ndarray:
    words = np.full((6, 4), np.nan)
    sa, sb, ca, cb = math.sin(alpha), math.sin(beta), math.cos(alpha), math.cos(beta)
    cab = math.cos(alpha - beta)
    p_sq = 2.0 + d * d - 2.0 * cab + 2.0 * d * (sa - sb)
    if p_sq >= 0:
        turn = math.atan2(cb - ca, d + sa - sb)
        _word(words, 0, _mod(turn - alpha), math.sqrt(p_sq), _mod(beta - turn))
    p_sq = 2.0 + d * d - 2.0 * cab + 2.0 * d * (sb - sa)
    if p_sq >= 0:
        turn = math.atan2(ca - cb, d - sa + sb)
        _word(words, 1, _mod(alpha - turn), math.sqrt(p_sq), _mod(turn - beta))
    p_sq = -2.0 + d * d + 2.0 * cab + 2.0 * d * (sa + sb)
    if p_sq >= 0:
        p = math.sqrt(p_sq)
        turn = math.atan2(-ca - cb, d + sa + sb) - math.atan2(-2.0, p)
        _word(words, 2, _mod(turn - alpha), p, _mod(turn - beta))
    p_sq = -2.0 + d * d + 2.0 * cab - 2.0 * d * (sa + sb)
    if p_sq >= 0:
        p = math.sqrt(p_sq)
        turn = math.atan2(ca + cb, d - sa - sb) - math.atan2(2.0, p)
        _word(words, 3, _mod(alpha - turn), p, _mod(beta - turn))
    cosine = (6.0 - d * d + 2.0 * cab + 2.0 * d * (sa - sb)) / 8.0
    if abs(cosine) <= 1.0:
        p = _mod(2.0 * math.pi - math.acos(cosine))
        t = _mod(alpha - math.atan2(ca - cb, d - sa + sb) + p / 2.0)
        _word(words, 4, t, p, _mod(alpha - beta - t + p))
    cosine = (6.0 - d * d + 2.0 * cab + 2.0 * d * (sb - sa)) / 8.0
    if abs(cosine) <= 1.0:
        p = _mod(2.0 * math.pi - math.acos(cosine))
        t = _mod(-alpha - math.atan2(ca - cb, d + sa - sb) + p / 2.0)
        _word(words, 5, t, p, _mod(beta - alpha - t + p))
    return words


_WORD_CURVATURE = np.array([[1, 0, 1], [-1, 0, -1], [1, 0, -1], [-1, 0, 1], [-1, 1, -1], [1, -1, 1]], dtype=np.float64)


@njit(cache=True)
def _drive(x: float, z: float, theta: float, curvatures: np.ndarray, lengths: np.ndarray, spacing: float) -> np.ndarray:
    total = 0
    for i in range(len(lengths)):
        if lengths[i] > 1e-9:
            total += int(math.ceil(lengths[i] / spacing))
    poses = np.empty((total, 3))
    n = 0
    for i in range(len(lengths)):
        length = lengths[i]
        if length <= 1e-9:
            continue
        count = int(math.ceil(length / spacing))
        k = curvatures[i]
        for j in range(count):
            s = length * (j + 1) / count
            if abs(k) < 1e-9:
                poses[n, 0] = x + math.cos(theta) * s
                poses[n, 1] = z + math.sin(theta) * s
                poses[n, 2] = theta
            else:
                poses[n, 0] = x + (math.sin(theta + k * s) - math.sin(theta)) / k
                poses[n, 1] = z + (math.cos(theta) - math.cos(theta + k * s)) / k
                poses[n, 2] = theta + k * s
            n += 1
        x, z, theta = poses[n - 1, 0], poses[n - 1, 1], poses[n - 1, 2]
    for i in range(total):
        poses[i, 2] = _wrap(poses[i, 2])
    return poses


@njit(cache=True)
def _dubins_shots(x: float, z: float, theta: float, gx: float, gz: float, gtheta: float, radius: float, spacing: float, word_curvature: np.ndarray):
    dx, dz = (gx - x) / radius, (gz - z) / radius
    heading = math.atan2(dz, dx)
    words = _dubins(_mod(theta - heading), _mod(gtheta - heading), math.hypot(dx, dz))
    totals = np.full(6, np.inf)
    for i in range(6):
        if not math.isnan(words[i, 0]):
            totals[i] = words[i, 1] + words[i, 2] + words[i, 3]
    order = np.argsort(totals)
    shots = []
    for i in order:
        if totals[i] == np.inf:
            break
        word = int(words[i, 0])
        poses = _drive(x, z, theta, word_curvature[word] / radius, words[i, 1:] * radius, spacing)
        if len(poses) == 0:
            continue
        last = poses[len(poses) - 1]
        if math.hypot(last[0] - gx, last[1] - gz) < 1e-3 and abs(_wrap(last[2] - gtheta)) < 1e-3:
            shots.append(poses)
    return shots


@njit(cache=True)
def _room(room: np.ndarray, unknown: np.ndarray, ox: float, oz: float, inv: float, x: float, z: float) -> tuple[float, float]:
    height, width = room.shape
    fx = (x - ox) * inv
    fz = (z - oz) * inv
    if fx < 0 or fz < 0 or fx >= width or fz >= height:
        return -1.0, 0.0
    ix = int(fx)
    iz = int(fz)
    return room[iz, ix], unknown[iz, ix]


@njit(cache=True)
def _at(values: np.ndarray, ox: float, oz: float, inv: float, x: float, z: float, outside: float) -> float:
    height, width = values.shape
    fx = (x - ox) * inv
    fz = (z - oz) * inv
    if fx < 0 or fz < 0 or fx >= width or fz >= height:
        return outside
    return values[int(fz), int(fx)]


@njit(cache=True)
def _poses_room(room: np.ndarray, unknown: np.ndarray, ox: float, oz: float, inv: float, poses: np.ndarray, offsets: np.ndarray, floor: float, band: float, prox_w: float, unk_w: float, spacing: float, sx: float, sz: float, escape_radius: float) -> float:
    cost = 0.0
    for i in range(len(poses)):
        c, s = math.cos(poses[i, 2]), math.sin(poses[i, 2])
        least = np.inf
        unseen = 0.0
        for k in range(len(offsets)):
            r, u = _room(room, unknown, ox, oz, inv, poses[i, 0] + offsets[k] * c, poses[i, 1] + offsets[k] * s)
            least = min(least, r)
            unseen += u
        if least < floor or (least < 0.0 and math.hypot(poses[i, 0] - sx, poses[i, 1] - sz) > escape_radius):
            return -1.0
        floor = min(0.0, least)
        cost += spacing * (1.0 + unk_w * unseen / len(offsets) + prox_w * max(0.0, 1.0 - least / band))
    return cost


@njit(cache=True)
def _grow(array: np.ndarray, size: int) -> np.ndarray:
    grown = np.empty(size, dtype=array.dtype)
    grown[: len(array)] = array
    return grown


@njit(cache=True, nogil=True)
def _search(
    room, unknown, untraversed, ox, oz, inv,
    heuristic, key_width, key_height, key_inv, bins,
    prim_dir, prim_steer, prim_curv, prim_end, probe_x, probe_z, offsets,
    sx, sz, stheta, gx, gz, gtheta, has_heading, goal_tolerance, heading_tolerance, goal_offset, escape_radius,
    floor0, band, prox_w, unk_w, reverse_penalty, untraversed_penalty, switch_penalty, steer_penalty, step, heuristic_weight,
    turn_radius, shot_interval, shot_distance, shot_slack, word_curvature,
    max_expansions, deadline,
):
    capacity = 4096
    xs = np.empty(capacity)
    zs = np.empty(capacity)
    ths = np.empty(capacity)
    gs = np.empty(capacity)
    floors = np.empty(capacity)
    parents = np.empty(capacity, dtype=np.int64)
    prims = np.empty(capacity, dtype=np.int64)
    best = np.full(key_width * key_height * bins, np.inf)
    bin_width = 2.0 * math.pi / bins
    count = len(prim_dir)
    probes = probe_x.shape[1]
    empty = np.empty((0, 3))

    xs[0], zs[0], ths[0], gs[0], floors[0], parents[0], prims[0] = sx, sz, _wrap(stheta), 0.0, floor0, -1, -1
    size = 1
    kx = int((sx - ox) * key_inv)
    kz = int((sz - oz) * key_inv)
    if sx < ox or sz < oz or kx >= key_width or kz >= key_height:
        return xs[:1], zs[:1], ths[:1], parents[:1], prims[:1], gs[:1], -1, empty, 0, 1, 0.0
    start_cell = kz * key_width + kx
    if heuristic[start_cell] == np.inf:
        return xs[:1], zs[:1], ths[:1], parents[:1], prims[:1], gs[:1], -1, empty, 0, 1, 0.0
    near = math.hypot(gx - sx - goal_offset * math.cos(stheta), gz - sz - goal_offset * math.sin(stheta)) <= goal_tolerance
    if near and (not has_heading or abs(_wrap(gtheta - ths[0])) <= heading_tolerance):
        return xs[:1], zs[:1], ths[:1], parents[:1], prims[:1], gs[:1], 0, empty, 0, 0, 0.0
    best[start_cell * bins + int(round(ths[0] / bin_width)) % bins] = 0.0
    h0 = heuristic[start_cell]
    heap = [(heuristic_weight * h0, h0, 0)]
    expansions = 0

    while len(heap) > 0:
        _, _, node = heapq.heappop(heap)
        x, z, theta, g = xs[node], zs[node], ths[node], gs[node]
        kx = int((x - ox) * key_inv)
        kz = int((z - oz) * key_inv)
        if g > best[(kz * key_width + kx) * bins + int(round(theta / bin_width)) % bins] + 1e-9:
            continue
        expansions += 1
        if expansions > max_expansions:
            return xs[:size], zs[:size], ths[:size], parents[:size], prims[:size], gs[:size], -1, empty, expansions, 2, 0.0
        if expansions % 256 == 0:
            with objmode(now="float64"):
                now = time.monotonic()
            if now > deadline:
                return xs[:size], zs[:size], ths[:size], parents[:size], prims[:size], gs[:size], -1, empty, expansions, 2, 0.0
        floor = floors[node]
        parent_prim = prims[node]
        parent_dir = prim_dir[parent_prim] if parent_prim >= 0 else 0
        parent_steer = prim_steer[parent_prim] if parent_prim >= 0 else 0.0

        if shot_interval > 0 and expansions % shot_interval == 1 and math.hypot(gx - x, gz - z) <= shot_distance:
            bound = heuristic[(int((z - oz) * key_inv)) * key_width + int((x - ox) * key_inv)]
            if has_heading:
                bound = max(bound, turn_radius * abs(_wrap(gtheta - theta)))
            bound = shot_slack * bound + 0.3
            if has_heading:
                shots = _dubins_shots(x, z, theta, gx, gz, gtheta, turn_radius, step * 0.5, word_curvature)
                for poses in shots:
                    travel = _poses_room(room, unknown, ox, oz, inv, poses, offsets, floor, band, prox_w, unk_w, step * 0.5, sx, sz, escape_radius)
                    if 0 <= travel <= bound:
                        return xs[:size], zs[:size], ths[:size], parents[:size], prims[:size], gs[:size], node, poses, expansions, 0, travel
            else:
                reach = math.hypot(gx - x, gz - z)
                tx = gx - goal_offset * (gx - x) / max(reach, 1e-9)
                tz = gz - goal_offset * (gz - z) / max(reach, 1e-9)
                ahead = math.atan2(tz - z, tx - x)
                alpha = _wrap(ahead - theta)
                distance = math.hypot(tx - x, tz - z)
                if reach > goal_offset and abs(alpha) < 0.5 * math.pi and distance > 1e-6:
                    curvature = 2.0 * math.sin(alpha) / distance
                    if abs(curvature) <= 1.0 / turn_radius:
                        length = distance if abs(alpha) < 1e-6 else distance * alpha / math.sin(alpha)
                        poses = _drive(x, z, theta, np.array([curvature]), np.array([length]), step * 0.5)
                        end = poses[len(poses) - 1]
                        landed = math.hypot(gx - end[0] - goal_offset * math.cos(end[2]), gz - end[1] - goal_offset * math.sin(end[2])) <= goal_tolerance
                        travel = _poses_room(room, unknown, ox, oz, inv, poses, offsets, floor, band, prox_w, unk_w, step * 0.5, sx, sz, escape_radius)
                        if landed and 0 <= travel <= bound:
                            return xs[:size], zs[:size], ths[:size], parents[:size], prims[:size], gs[:size], node, poses, expansions, 0, travel

        c, s = math.cos(theta), math.sin(theta)
        for p in range(count):
            least = np.inf
            unseen = 0.0
            fresh = 0.0
            for k in range(probes):
                px = x + c * probe_x[p, k] - s * probe_z[p, k]
                pz = z + s * probe_x[p, k] + c * probe_z[p, k]
                r, u = _room(room, unknown, ox, oz, inv, px, pz)
                if r < least:
                    least = r
                unseen += u
                if prim_dir[p] < 0:
                    fresh += _at(untraversed, ox, oz, inv, px, pz, 1.0)
            if least < floor or (prim_dir[p] < 0 and unseen > 0):
                continue
            nx = x + c * prim_end[p, 0] - s * prim_end[p, 1]
            nz = z + s * prim_end[p, 0] + c * prim_end[p, 1]
            if least < 0.0 and math.hypot(nx - sx, nz - sz) > escape_radius:
                continue
            ntheta = _wrap(theta + prim_end[p, 2])
            if nx < ox or nz < oz:
                continue
            kx = int((nx - ox) * key_inv)
            kz = int((nz - oz) * key_inv)
            if kx >= key_width or kz >= key_height:
                continue
            cell = kz * key_width + kx
            key = cell * bins + int(round(ntheta / bin_width)) % bins
            gear = prim_dir[p]
            weight = (1.0 if gear > 0 else reverse_penalty * (1.0 + untraversed_penalty * fresh / probes)) + unk_w * unseen / probes + prox_w * max(0.0, 1.0 - least / band)
            ng = g + step * weight + steer_penalty * abs(prim_steer[p] - parent_steer)
            if parent_dir != 0 and parent_dir != gear:
                ng += switch_penalty
            if ng >= best[key] - 1e-9:
                continue
            h = heuristic[cell]
            if h == np.inf:
                continue
            if has_heading:
                h = max(h, turn_radius * abs(_wrap(gtheta - ntheta)))
            if size == capacity:
                capacity *= 2
                xs, zs, ths, gs, floors = _grow(xs, capacity), _grow(zs, capacity), _grow(ths, capacity), _grow(gs, capacity), _grow(floors, capacity)
                parents, prims = _grow(parents, capacity), _grow(prims, capacity)
            child = size
            size += 1
            xs[child], zs[child], ths[child], gs[child] = nx, nz, ntheta, ng
            floors[child] = min(0.0, least)
            parents[child], prims[child] = node, p
            best[key] = ng
            landed = math.hypot(gx - nx - goal_offset * math.cos(ntheta), gz - nz - goal_offset * math.sin(ntheta)) <= goal_tolerance
            if landed and (not has_heading or abs(_wrap(gtheta - ntheta)) <= heading_tolerance):
                return xs[:size], zs[:size], ths[:size], parents[:size], prims[:size], gs[:size], child, empty, expansions, 0, 0.0
            heapq.heappush(heap, (ng + heuristic_weight * h, h, child))
    return xs[:size], zs[:size], ths[:size], parents[:size], prims[:size], gs[:size], -1, empty, expansions, 1, 0.0


def _coarse(values: np.ndarray, factor: int, fill: float, reduce) -> np.ndarray:
    height, width = values.shape
    padded = np.full((-(-height // factor) * factor, -(-width // factor) * factor), fill, dtype=values.dtype)
    padded[:height, :width] = values
    blocks = padded.reshape(padded.shape[0] // factor, factor, padded.shape[1] // factor, factor)
    return reduce(blocks, axis=(1, 3))


def _heuristic(room: np.ndarray, unknown: np.ndarray, costmap: CostMap, params: PlannerParams, start: Pose2D, goal_xz: tuple[float, float], floor: float) -> tuple[np.ndarray, int, int]:
    grid = costmap.grid
    factor = params.key_cells
    coarse_room = _coarse(room, factor, -np.inf, np.max)
    coarse_unknown = _coarse(unknown, factor, 1.0, np.min)
    multiplier = 1.0 + params.unknown_cost * coarse_unknown + params.proximity_weight * np.clip(1.0 - coarse_room / params.proximity_band, 0.0, None)
    cost = np.where(coarse_room >= min(floor, 0.0) - grid.resolution, multiplier, np.inf)
    key_res = grid.resolution * factor
    key_height, key_width = cost.shape

    def cell(x: float, z: float) -> tuple[int, int] | None:
        ix, iz = math.floor((x - grid.origin[0]) / key_res), math.floor((z - grid.origin[1]) / key_res)
        return (iz, ix) if 0 <= ix < key_width and 0 <= iz < key_height else None

    start_cell, goal_cell = cell(start.x, start.z), cell(*goal_xz)
    if start_cell is None or goal_cell is None:
        return np.full(key_height * key_width, np.inf), key_width, key_height
    for center in (start_cell, goal_cell):
        reach = int(math.ceil(0.25 / key_res))
        block = cost[max(center[0] - reach, 0) : center[0] + reach + 1, max(center[1] - reach, 0) : center[1] + reach + 1]
        block[np.isinf(block)] = 1.0 + params.proximity_weight * 2.0
    field_2d = holonomic_distance(cost, goal_cell, key_res, start_cell, params.heuristic_slack)
    return field_2d.ravel(), key_width, key_height


def _assemble(rows: list[tuple[float, float, float, int, float]], cost: float) -> Path:
    moves = [(row[3], row[4]) for row in rows[1:]]
    first = moves[0][0] if moves else 1
    waypoints = [Waypoint(x, z, theta, direction or first) for x, z, theta, direction, _ in rows]
    switches = sum(1 for (a, _), (b, _) in zip(moves, moves[1:]) if a != b)
    length = sum(ds for _, ds in moves)
    reverse_length = sum(ds for gear, ds in moves if gear < 0)
    return Path(waypoints, length, reverse_length, switches, cost)


def plan_route(
    costmap: CostMap, start: Pose2D, goal: Pose2D | tuple[float, float], params: PlannerParams = PlannerParams(), traversed: np.ndarray | None = None
) -> tuple[Path | None, SearchStats]:
    began = time.monotonic()
    grid = costmap.grid
    goal_xz = (goal.x, goal.z) if isinstance(goal, Pose2D) else (float(goal[0]), float(goal[1]))
    goal_theta = goal.theta if isinstance(goal, Pose2D) else None
    room = (costmap.distance - np.float32(costmap.collision_radius)).astype(np.float32)
    unknown = (grid.cells == UNKNOWN).astype(np.float32)
    untraversed = np.zeros_like(unknown) if traversed is None else (~traversed).astype(np.float32)
    if params.unknown_blocked:
        room[grid.cells == UNKNOWN] = -1.0
    start_room = float(pose_clearance(replace(costmap, distance=room + np.float32(costmap.collision_radius)), np.array([start.x, start.z, start.theta]))[0])
    floor = min(0.0, start_room)
    if goal_theta is not None and pose_clearance(costmap, np.array([*goal_xz, goal_theta]))[0] < 0:
        return None, SearchStats(0, 0.0, 0.0, "goal pose is in collision")
    heuristic, key_width, key_height = _heuristic(room, unknown, costmap, params, start, goal_xz, floor)
    heuristic_done = time.monotonic()
    prims = _primitives(params)
    xs, zs, ths, parents, prim_index, costs, goal_node, shot, expansions, status, shot_cost = _search(
        room, unknown, untraversed, grid.origin[0], grid.origin[1], 1.0 / grid.resolution,
        heuristic, key_width, key_height, 1.0 / (grid.resolution * params.key_cells), params.heading_bins,
        prims.direction, prims.steer, prims.curvature, prims.end, prims.probe_x, prims.probe_z, np.asarray(params.footprint.circle_offsets, dtype=np.float64),
        start.x, start.z, start.theta, goal_xz[0], goal_xz[1], goal_theta if goal_theta is not None else 0.0, goal_theta is not None,
        params.goal_tolerance, params.heading_tolerance, params.goal_offset, params.escape_radius,
        floor, params.proximity_band, params.proximity_weight, params.unknown_cost, params.reverse_penalty, params.untraversed_reverse_penalty, params.gear_switch_penalty,
        params.steer_change_penalty, params.step, params.heuristic_weight,
        params.min_turn_radius, params.shot_interval, params.shot_distance, params.shot_slack, _WORD_CURVATURE,
        params.max_expansions, began + params.time_limit,
    )
    done = time.monotonic()
    reasons = {0: "found", 1: "no route", 2: "search limit"}
    stats = SearchStats(int(expansions), (heuristic_done - began) * 1000.0, (done - heuristic_done) * 1000.0, reasons[int(status)])
    if goal_node < 0:
        return None, stats
    chain = []
    node = int(goal_node)
    while node >= 0:
        chain.append(node)
        node = int(parents[node])
    chain.reverse()
    rows: list[tuple[float, float, float, int, float]] = [(float(xs[chain[0]]), float(zs[chain[0]]), float(ths[chain[0]]), 0, 0.0)]
    for node in chain[1:]:
        p = int(prim_index[node])
        gear = int(prims.direction[p])
        parent = int(parents[node])
        x, z, theta = xs[parent], zs[parent], ths[parent]
        mx, mz, mturn = _arc(gear * params.step * 0.5, float(prims.curvature[p]))
        c, s = math.cos(theta), math.sin(theta)
        rows.append((float(x + c * mx - s * mz), float(z + s * mx + c * mz), wrap_angle(float(theta + mturn)), gear, 0.5 * params.step))
        rows.append((float(xs[node]), float(zs[node]), float(ths[node]), gear, 0.5 * params.step))
    cost = float(costs[int(goal_node)]) + float(shot_cost)
    if len(shot):
        previous = np.array(rows[-1][:2])
        for x, z, theta in shot:
            rows.append((float(x), float(z), float(theta), 1, float(math.hypot(x - previous[0], z - previous[1]))))
            previous = np.array([x, z])
    return _assemble(rows, cost), stats


def plan_hybrid_astar(
    grid: OccupancyGrid | CostMap, start: Pose2D, goal: Pose2D | tuple[float, float], params: PlannerParams = PlannerParams()
) -> Path | None:
    costmap = grid if isinstance(grid, CostMap) else build_costmap(grid, params.footprint, params.unknown_blocked, params.proximity_band)
    return plan_route(costmap, start, goal, params)[0]


def split_segments(path: Path) -> list[Segment]:
    poses = path.poses()
    directions = [w.direction for w in path.waypoints]
    segments = []
    begin = 0
    current = directions[0]
    for index in range(1, len(directions)):
        if directions[index] != current:
            segments.append(Segment(current, poses[begin:index]))
            begin = index - 1
            current = directions[index]
    segments.append(Segment(current, poses[begin:]))
    return segments


def _smooth_segment(points: np.ndarray, direction: int, iterations: int, weight: float) -> np.ndarray:
    if len(points) < 3:
        return points
    xz = points[:, :2].copy()
    for _ in range(iterations):
        xz[1:-1] += weight * (xz[:-2] + xz[2:] - 2.0 * xz[1:-1])
    delta = (xz[2:] - xz[:-2]) * direction
    theta = points[:, 2].copy()
    theta[1:-1] = np.arctan2(delta[:, 1], delta[:, 0])
    return np.column_stack([xz, theta])


def smooth(path: Path, costmap: CostMap, iterations: int = 10, weight: float = 0.25) -> Path:
    segments = split_segments(path)
    waypoints: list[Waypoint] = []
    length = 0.0
    reverse_length = 0.0
    floor = min(0.0, float(pose_clearance(costmap, path.poses()).min()))
    for index, segment in enumerate(segments):
        smoothed = _smooth_segment(segment.points, segment.direction, iterations, weight)
        if (pose_clearance(costmap, smoothed) < floor).any():
            smoothed = segment.points
        run = float(np.linalg.norm(np.diff(smoothed[:, :2], axis=0), axis=1).sum())
        length += run
        reverse_length += run if segment.direction < 0 else 0.0
        kept = smoothed if index == 0 else smoothed[1:]
        waypoints.extend(Waypoint(float(x), float(z), float(t), segment.direction) for x, z, t in kept)
    return replace(path, waypoints=waypoints, length=length, reverse_length=reverse_length)


def camera_points(path: Path) -> list[list[float]]:
    points = []
    for waypoint in path.waypoints:
        forward = np.array([math.cos(waypoint.theta), math.sin(waypoint.theta)])
        x, z = camera_point(np.array([waypoint.x, waypoint.z]), forward)
        points.append([round(float(x), 3), round(float(z), 3), int(waypoint.direction), round(float(waypoint.theta), 4)])
    return points


def frontier_mask(grid: OccupancyGrid) -> np.ndarray:
    unknown = np.pad(grid.cells == UNKNOWN, 1)
    touching = unknown[:-2, 1:-1] | unknown[2:, 1:-1] | unknown[1:-1, :-2] | unknown[1:-1, 2:]
    return (grid.cells == FREE) & touching


def connected_components(mask: np.ndarray) -> list[np.ndarray]:
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    components = []
    for seed in map(tuple, np.argwhere(mask)):
        if seen[seed]:
            continue
        seen[seed] = True
        members = [seed]
        frontier = [seed]
        while frontier:
            iz, ix = frontier.pop()
            for dz, dx, _ in _NEIGHBOURS:
                nz, nx = iz + dz, ix + dx
                if 0 <= nz < height and 0 <= nx < width and mask[nz, nx] and not seen[nz, nx]:
                    seen[nz, nx] = True
                    members.append((nz, nx))
                    frontier.append((nz, nx))
        components.append(np.asarray(members))
    return components
