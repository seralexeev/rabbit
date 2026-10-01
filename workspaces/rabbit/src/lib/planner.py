from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field, replace

import numpy as np
from lib.geometry import MAX_CURVATURE, curvature_for_steer

FREE = 0
OCCUPIED = 1
UNKNOWN = -1

WHEELBASE = 0.1715
MIN_TURN_RADIUS = 1.0 / MAX_CURVATURE

_SQRT2 = math.sqrt(2.0)
_NEIGHBOURS = ((0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0), (1, 1, _SQRT2), (1, -1, _SQRT2), (-1, 1, _SQRT2), (-1, -1, _SQRT2))


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

    def clear_ray(self, origin_xz: tuple[float, float], points_xz: np.ndarray) -> None:
        ends = np.asarray(points_xz, dtype=np.float64).reshape(-1, 2)
        start = np.asarray(origin_xz, dtype=np.float64)
        spans = ends - start
        lengths = np.linalg.norm(spans, axis=1)
        step = 0.5 * self.resolution
        for span, length in zip(spans, lengths):
            reach = length - self.resolution
            if reach <= 0:
                continue
            t = np.arange(0.0, reach, step) / length
            self.mark_points(start + t[:, None] * span, FREE)


@dataclass(frozen=True)
class Pose2D:
    x: float
    z: float
    theta: float


@dataclass(frozen=True)
class Footprint:
    rear_overhang: float = 0.07
    front_overhang: float = 0.20
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
    wheelbase: float = WHEELBASE
    min_turn_radius: float = MIN_TURN_RADIUS
    step: float = 0.08
    heading_bins: int = 72
    steer_fractions: tuple[float, ...] = (-1.0, -0.5, 0.0, 0.5, 1.0)
    reverse_penalty: float = 3.0
    gear_switch_penalty: float = 1.0
    steer_change_penalty: float = 0.05
    unknown_cost: float = 2.0
    unknown_blocked: bool = False
    proximity_band: float = 0.15
    proximity_weight: float = 1.0
    goal_tolerance: float = 0.12
    heading_tolerance: float = math.radians(15.0)
    heuristic_weight: float = 1.5
    shot_interval: int = 10
    max_expansions: int = 200_000
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


@dataclass(frozen=True)
class Frontier:
    cells: int
    centroid: tuple[float, float]
    viewpoint: Pose2D


@dataclass(frozen=True)
class Segment:
    direction: int
    points: np.ndarray


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


def inflate(grid: OccupancyGrid, radius_m: float, unknown_blocked: bool = False) -> np.ndarray:
    blocked = grid.cells == OCCUPIED
    if unknown_blocked:
        blocked |= grid.cells == UNKNOWN
    distance = np.full(blocked.shape, radius_m, dtype=np.float32)
    reach = int(math.ceil(radius_m / grid.resolution))
    height, width = blocked.shape
    for dz in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            offset = math.hypot(dx, dz) * grid.resolution
            if offset >= radius_m or abs(dz) >= height or abs(dx) >= width:
                continue
            target = distance[max(dz, 0) : height + min(dz, 0), max(dx, 0) : width + min(dx, 0)]
            source = blocked[max(-dz, 0) : height + min(-dz, 0), max(-dx, 0) : width + min(-dx, 0)]
            np.minimum(target, np.where(source, np.float32(offset), np.float32(radius_m)), out=target)
    return distance


def build_costmap(
    grid: OccupancyGrid, footprint: Footprint = Footprint(), unknown_blocked: bool = False, proximity_band: float = 0.15
) -> CostMap:
    reach = footprint.radius + proximity_band + 2.0 * grid.resolution
    return CostMap(grid, inflate(grid, reach, unknown_blocked), footprint)


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


def holonomic_distance(cell_cost: np.ndarray, seed_cell: tuple[int, int], resolution: float) -> np.ndarray:
    height, width = cell_cost.shape
    stride = width + 2
    weights = np.pad(cell_cost.astype(np.float64), 1, constant_values=np.inf).ravel().tolist()
    cost = [math.inf] * len(weights)
    moves = [(dz * stride + dx, step * resolution) for dz, dx, step in _NEIGHBOURS]
    seed = (seed_cell[0] + 1) * stride + seed_cell[1] + 1
    cost[seed] = 0.0
    heap = [(0.0, seed)]
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        current, cell = pop(heap)
        if current > cost[cell]:
            continue
        for move, step in moves:
            neighbour = cell + move
            candidate = current + step * weights[neighbour]
            if candidate < cost[neighbour]:
                cost[neighbour] = candidate
                push(heap, (candidate, neighbour))
    return np.asarray(cost).reshape(height + 2, stride)[1:-1, 1:-1]


def _arc(signed_length: float, curvature: float) -> tuple[float, float, float]:
    if abs(curvature) < 1e-9:
        return signed_length, 0.0, 0.0
    turn = signed_length * curvature
    return math.sin(turn) / curvature, (1.0 - math.cos(turn)) / curvature, turn


@dataclass(frozen=True)
class _Primitives:
    direction: list[int]
    steer: list[float]
    end: list[tuple[float, float, float]]
    probe_x: np.ndarray
    probe_z: np.ndarray
    probes_per_primitive: int


def _primitives(params: PlannerParams) -> _Primitives:
    offsets = params.footprint.circle_offsets
    direction, steer, end, probes = [], [], [], []
    for gear in (1, -1):
        for fraction in params.steer_fractions:
            curvature = curvature_for_steer(fraction)
            for travelled in (0.5, 1.0):
                x, z, turn = _arc(gear * params.step * travelled, curvature)
                probes.extend((x + o * math.cos(turn), z + o * math.sin(turn)) for o in offsets)
            direction.append(gear)
            steer.append(fraction)
            end.append(_arc(gear * params.step, curvature))
    probe = np.asarray(probes)
    return _Primitives(direction, steer, end, probe[:, 0], probe[:, 1], 2 * len(offsets))


def distance_map_from(costmap: CostMap, origin_xz: tuple[float, float], unknown_cost: float = 0.0) -> np.ndarray:
    grid = costmap.grid
    iz, ix, inside = grid.cell_index(np.asarray(origin_xz))
    if not inside[0]:
        return np.full((grid.height, grid.width), np.inf)
    nearest_offset = min(abs(o) for o in costmap.footprint.circle_offsets)
    passable = costmap.distance >= costmap.collision_radius - nearest_offset - 1.5 * grid.resolution
    cell_cost = np.where(passable, 1.0 + unknown_cost * (grid.cells == UNKNOWN), np.inf)
    return holonomic_distance(cell_cost, (int(iz[0]), int(ix[0])), grid.resolution)


def _mod2pi(angle: float) -> float:
    return angle % (2.0 * math.pi)


def _dubins_words(alpha: float, beta: float, d: float) -> list[tuple[str, float, float, float]]:
    sa, sb, ca, cb = math.sin(alpha), math.sin(beta), math.cos(alpha), math.cos(beta)
    cab = math.cos(alpha - beta)
    words = []
    p_sq = 2.0 + d * d - 2.0 * cab + 2.0 * d * (sa - sb)
    if p_sq >= 0:
        turn = math.atan2(cb - ca, d + sa - sb)
        words.append(("LSL", _mod2pi(turn - alpha), math.sqrt(p_sq), _mod2pi(beta - turn)))
    p_sq = 2.0 + d * d - 2.0 * cab + 2.0 * d * (sb - sa)
    if p_sq >= 0:
        turn = math.atan2(ca - cb, d - sa + sb)
        words.append(("RSR", _mod2pi(alpha - turn), math.sqrt(p_sq), _mod2pi(turn - beta)))
    p_sq = -2.0 + d * d + 2.0 * cab + 2.0 * d * (sa + sb)
    if p_sq >= 0:
        p = math.sqrt(p_sq)
        turn = math.atan2(-ca - cb, d + sa + sb) - math.atan2(-2.0, p)
        words.append(("LSR", _mod2pi(turn - alpha), p, _mod2pi(turn - beta)))
    p_sq = -2.0 + d * d + 2.0 * cab - 2.0 * d * (sa + sb)
    if p_sq >= 0:
        p = math.sqrt(p_sq)
        turn = math.atan2(ca + cb, d - sa - sb) - math.atan2(2.0, p)
        words.append(("RSL", _mod2pi(alpha - turn), p, _mod2pi(beta - turn)))
    cosine = (6.0 - d * d + 2.0 * cab + 2.0 * d * (sa - sb)) / 8.0
    if abs(cosine) <= 1.0:
        p = _mod2pi(2.0 * math.pi - math.acos(cosine))
        t = _mod2pi(alpha - math.atan2(ca - cb, d - sa + sb) + p / 2.0)
        words.append(("RLR", t, p, _mod2pi(alpha - beta - t + p)))
    cosine = (6.0 - d * d + 2.0 * cab + 2.0 * d * (sb - sa)) / 8.0
    if abs(cosine) <= 1.0:
        p = _mod2pi(2.0 * math.pi - math.acos(cosine))
        t = _mod2pi(-alpha - math.atan2(ca - cb, d + sa - sb) + p / 2.0)
        words.append(("LRL", t, p, _mod2pi(beta - alpha - t + p)))
    return words


def drive_arcs(start: Pose2D, arcs: list[tuple[float, float]], spacing: float) -> np.ndarray:
    poses = []
    x, z, theta = start.x, start.z, start.theta
    for curvature, length in arcs:
        if length <= 1e-9:
            continue
        travelled = np.linspace(length, 0.0, int(math.ceil(length / spacing)), endpoint=False)[::-1]
        if abs(curvature) < 1e-9:
            lx, lz, turn = travelled, np.zeros_like(travelled), np.zeros_like(travelled)
        else:
            turn = travelled * curvature
            lx, lz = np.sin(turn) / curvature, (1.0 - np.cos(turn)) / curvature
        c, s = math.cos(theta), math.sin(theta)
        poses.append(np.column_stack([x + c * lx - s * lz, z + s * lx + c * lz, theta + turn]))
        x, z, theta = poses[-1][-1]
    if not poses:
        return np.empty((0, 3))
    result = np.concatenate(poses)
    result[:, 2] = (result[:, 2] + math.pi) % (2.0 * math.pi) - math.pi
    return result


def dubins_shots(start: Pose2D, goal: Pose2D, radius: float, spacing: float) -> list[np.ndarray]:
    dx, dz = (goal.x - start.x) / radius, (goal.z - start.z) / radius
    heading = math.atan2(dz, dx)
    curvature = {"L": 1.0 / radius, "S": 0.0, "R": -1.0 / radius}
    words = sorted(_dubins_words(_mod2pi(start.theta - heading), _mod2pi(goal.theta - heading), math.hypot(dx, dz)), key=lambda w: sum(w[1:]))
    shots = []
    for word, *lengths in words:
        poses = drive_arcs(start, [(curvature[letter], length * radius) for letter, length in zip(word, lengths)], spacing)
        if len(poses) and math.hypot(poses[-1, 0] - goal.x, poses[-1, 1] - goal.z) < 1e-3 and abs(wrap_angle(poses[-1, 2] - goal.theta)) < 1e-3:
            shots.append(poses)
    return shots


def _travel_cost(costmap: CostMap, poses: np.ndarray, clearance: np.ndarray, spacing: np.ndarray, params: PlannerParams) -> float:
    iz, ix, inside = costmap.grid.cell_index(footprint_centers(poses, costmap.footprint).reshape(-1, 2))
    unknown = (costmap.grid.cells[iz.clip(0, costmap.grid.height - 1), ix.clip(0, costmap.grid.width - 1)] == UNKNOWN) & inside
    proximity = np.clip(1.0 - clearance / params.proximity_band, 0.0, None) if params.proximity_band > 0 else 0.0
    weight = 1.0 + params.unknown_cost * unknown.reshape(len(poses), -1).mean(axis=1) + params.proximity_weight * proximity
    return float((spacing * weight).sum())


def _assemble(rows: list[tuple[float, float, float, int, float]], cost: float) -> Path:
    moves = [(row[3], row[4]) for row in rows[1:]]
    first = moves[0][0] if moves else 1
    waypoints = [Waypoint(x, z, theta, direction or first) for x, z, theta, direction, _ in rows]
    switches = sum(1 for (a, _), (b, _) in zip(moves, moves[1:]) if a != b)
    length = sum(ds for _, ds in moves)
    reverse_length = sum(ds for gear, ds in moves if gear < 0)
    return Path(waypoints, length, reverse_length, switches, cost)


def plan_hybrid_astar(
    grid: OccupancyGrid, start: Pose2D, goal: Pose2D | tuple[float, float], params: PlannerParams = PlannerParams()
) -> Path | None:
    deadline = time.monotonic() + params.time_limit
    costmap = build_costmap(grid, params.footprint, params.unknown_blocked, params.proximity_band)
    goal_xz = (goal.x, goal.z) if isinstance(goal, Pose2D) else (float(goal[0]), float(goal[1]))
    goal_theta = goal.theta if isinstance(goal, Pose2D) else None
    start_clearance = float(pose_clearance(costmap, np.array([start.x, start.z, start.theta]))[0])
    if goal_theta is not None and pose_clearance(costmap, np.array([*goal_xz, goal_theta]))[0] < 0:
        return None
    field_2d = distance_map_from(costmap, goal_xz, params.unknown_cost)

    width, height = grid.width, grid.height
    ox, oz = grid.origin
    inv_res = 1.0 / grid.resolution
    bins = params.heading_bins
    bin_width = 2.0 * math.pi / bins
    heuristic = field_2d.ravel().tolist()
    radius = costmap.collision_radius
    pad = int(math.ceil((params.step + max(abs(o) for o in params.footprint.circle_offsets)) * inv_res)) + 2
    padded_width = width + 2 * pad
    clearance_map = np.pad(costmap.distance - np.float32(radius), pad, constant_values=-1.0).ravel()
    unknown_map = np.pad((grid.cells == UNKNOWN).astype(np.float32), pad).ravel()
    probe_origin_x = ox - pad * grid.resolution
    probe_origin_z = oz - pad * grid.resolution
    gx, gz = goal_xz
    turn_radius = params.min_turn_radius
    heuristic_weight = params.heuristic_weight
    goal_tolerance = params.goal_tolerance
    heading_tolerance = params.heading_tolerance
    band = params.proximity_band
    step = params.step
    prims = _primitives(params)
    count = len(prims.direction)
    per = prims.probes_per_primitive
    unknown_weight = params.unknown_cost / per

    def cell_key(x: float, z: float, theta: float) -> int:
        ix = int((x - ox) * inv_res)
        iz = int((z - oz) * inv_res)
        if x < ox or z < oz or ix >= width or iz >= height:
            return -1
        return ((iz * width + ix) * bins) + int(round(theta / bin_width)) % bins

    def estimate(x: float, z: float, theta: float, key: int) -> float:
        h = max(math.hypot(gx - x, gz - z), heuristic[key // bins])
        if goal_theta is not None:
            h = max(h, turn_radius * abs(wrap_angle(goal_theta - theta)))
        return heuristic_weight * h

    def at_goal(x: float, z: float, theta: float) -> bool:
        if math.hypot(gx - x, gz - z) > goal_tolerance:
            return False
        return goal_theta is None or abs(wrap_angle(goal_theta - theta)) <= heading_tolerance

    xs, zs, thetas = [start.x], [start.z], [wrap_angle(start.theta)]
    directions, steers, parents, costs = [0], [0.0], [-1], [0.0]
    floors = [min(0.0, start_clearance)]

    def chain(node: int) -> list[tuple[float, float, float, int, float]]:
        rows = []
        while node >= 0:
            rows.append((xs[node], zs[node], thetas[node], directions[node], step if parents[node] >= 0 else 0.0))
            node = parents[node]
        return rows[::-1]

    def shoot(node: int) -> Path | None:
        origin = Pose2D(xs[node], zs[node], thetas[node])
        for poses in dubins_shots(origin, Pose2D(gx, gz, goal_theta), turn_radius, step):
            clearance = pose_clearance(costmap, poses)
            if (clearance < 0).any():
                continue
            spacing = np.linalg.norm(np.diff(np.vstack([[origin.x, origin.z], poses[:, :2]]), axis=0), axis=1)
            cost = costs[node] + _travel_cost(costmap, poses, clearance, spacing, params)
            if directions[node] < 0:
                cost += params.gear_switch_penalty
            tail = [(float(x), float(z), float(t), 1, float(ds)) for (x, z, t), ds in zip(poses, spacing)]
            return _assemble(chain(node) + tail, cost)
        return None

    start_key = cell_key(start.x, start.z, thetas[0])
    if start_key < 0 or math.isinf(heuristic[start_key // bins]):
        return None
    if at_goal(start.x, start.z, thetas[0]):
        return _assemble(chain(0), 0.0)
    keys = [start_key]
    best = {start_key: 0.0}
    start_estimate = estimate(start.x, start.z, thetas[0], start_key)
    heap = [(start_estimate, start_estimate, 0)]
    expansions = 0

    while heap:
        _, _, node = heapq.heappop(heap)
        g = costs[node]
        if g > best[keys[node]] + 1e-9:
            continue
        expansions += 1
        if expansions > params.max_expansions or (expansions & 127 == 0 and time.monotonic() > deadline):
            return None
        if goal_theta is not None and expansions % params.shot_interval == 1:
            shot = shoot(node)
            if shot is not None:
                return shot
        x, z, theta = xs[node], zs[node], thetas[node]
        c, s = math.cos(theta), math.sin(theta)
        ix = ((x - probe_origin_x + c * prims.probe_x - s * prims.probe_z) * inv_res).astype(np.intp)
        iz = ((z - probe_origin_z + s * prims.probe_x + c * prims.probe_z) * inv_res).astype(np.intp)
        cells = iz * padded_width + ix
        clearance = clearance_map.take(cells).reshape(count, per).min(axis=1).tolist()
        unknown_share = unknown_map.take(cells).reshape(count, per).sum(axis=1).tolist()
        parent_direction = directions[node]
        parent_steer = steers[node]
        floor = floors[node]

        for p in range(count):
            room = clearance[p]
            if room < floor:
                continue
            ex, ez, turn = prims.end[p]
            nx = x + c * ex - s * ez
            nz = z + s * ex + c * ez
            ntheta = wrap_angle(theta + turn)
            key = cell_key(nx, nz, ntheta)
            if key < 0:
                continue
            gear = prims.direction[p]
            steer = prims.steer[p]
            proximity = max(0.0, 1.0 - room / band) if band > 0 else 0.0
            weight = (1.0 if gear > 0 else params.reverse_penalty) + unknown_weight * unknown_share[p] + params.proximity_weight * proximity
            ng = g + step * weight + params.steer_change_penalty * abs(steer - parent_steer)
            if parent_direction and parent_direction != gear:
                ng += params.gear_switch_penalty
            if ng >= best.get(key, math.inf) - 1e-9:
                continue
            h = estimate(nx, nz, ntheta, key)
            if math.isinf(h):
                continue
            child = len(xs)
            xs.append(nx)
            zs.append(nz)
            thetas.append(ntheta)
            directions.append(gear)
            steers.append(steer)
            parents.append(node)
            costs.append(ng)
            keys.append(key)
            floors.append(min(0.0, room))
            best[key] = ng
            if at_goal(nx, nz, ntheta):
                return _assemble(chain(child), ng)
            heapq.heappush(heap, (ng + h, h, child))
    return None


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
    for index, segment in enumerate(segments):
        smoothed = _smooth_segment(segment.points, segment.direction, iterations, weight)
        if (pose_clearance(costmap, smoothed) < 0).any():
            smoothed = segment.points
        run = float(np.linalg.norm(np.diff(smoothed[:, :2], axis=0), axis=1).sum())
        length += run
        reverse_length += run if segment.direction < 0 else 0.0
        kept = smoothed if index == 0 else smoothed[1:]
        waypoints.extend(Waypoint(float(x), float(z), float(t), segment.direction) for x, z, t in kept)
    return replace(path, waypoints=waypoints, length=length, reverse_length=reverse_length)


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


def _toward_unknown(grid: OccupancyGrid, cells: np.ndarray) -> np.ndarray:
    unknown = np.pad(grid.cells == UNKNOWN, 1)
    iz, ix = cells[:, 0] + 1, cells[:, 1] + 1
    pull = np.stack(
        [unknown[iz, ix + 1].astype(float) - unknown[iz, ix - 1], unknown[iz + 1, ix].astype(float) - unknown[iz - 1, ix]], axis=1
    )
    norms = np.linalg.norm(pull, axis=1, keepdims=True)
    return (pull / np.maximum(norms, 1e-9)).mean(axis=0)


def _viewpoint(
    costmap: CostMap, centroid: np.ndarray, toward_unknown: np.ndarray, radii: tuple[float, ...], bearings: int, alignment_weight: float
) -> Pose2D | None:
    angles = np.linspace(0.0, 2.0 * np.pi, bearings, endpoint=False)
    directions = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    offsets = (np.asarray(radii)[:, None, None] * directions[None]).reshape(-1, 2)
    unit = offsets / np.linalg.norm(offsets, axis=1, keepdims=True)
    positions = centroid + offsets
    poses = np.column_stack([positions, np.arctan2(-offsets[:, 1], -offsets[:, 0])])
    probes = np.concatenate([positions[:, None], footprint_centers(poses, costmap.footprint)], axis=1)
    iz, ix, inside = costmap.grid.cell_index(probes.reshape(-1, 2))
    free = (inside & (costmap.grid.cells[iz.clip(0, costmap.grid.height - 1), ix.clip(0, costmap.grid.width - 1)] == FREE)).reshape(len(poses), -1).all(axis=1)
    clearance = pose_clearance(costmap, poses)
    valid = free & (clearance >= 0)
    if not valid.any():
        return None
    score = np.where(valid, clearance - alignment_weight * unit @ toward_unknown, -np.inf)
    x, z, theta = poses[int(np.argmax(score))]
    return Pose2D(float(x), float(z), float(theta))


def find_frontiers(
    costmap: CostMap,
    min_cluster_cells: int = 8,
    viewpoint_radii: tuple[float, ...] = (0.5, 0.65, 0.8),
    viewpoint_bearings: int = 16,
    alignment_weight: float = 0.2,
) -> list[Frontier]:
    grid = costmap.grid
    frontiers = []
    for cells in connected_components(frontier_mask(grid)):
        if len(cells) < min_cluster_cells:
            continue
        centroid = np.array(grid.origin) + (cells[:, ::-1].mean(axis=0) + 0.5) * grid.resolution
        viewpoint = _viewpoint(costmap, centroid, _toward_unknown(grid, cells), viewpoint_radii, viewpoint_bearings, alignment_weight)
        if viewpoint is not None:
            frontiers.append(Frontier(len(cells), (float(centroid[0]), float(centroid[1])), viewpoint))
    return frontiers


def rank_frontiers(
    frontiers: list[Frontier],
    start: Pose2D,
    grid: OccupancyGrid,
    heuristic_costs: np.ndarray,
    size_weight: float = 1.0,
    turn_penalty: float = 0.3,
    max_detour: float = 3.0,
) -> list[Frontier]:
    scored = []
    for frontier in frontiers:
        iz, ix, inside = grid.cell_index(np.array([frontier.viewpoint.x, frontier.viewpoint.z]))
        cost = float(heuristic_costs[iz[0], ix[0]]) if inside[0] else math.inf
        if cost > max_detour * math.hypot(frontier.viewpoint.x - start.x, frontier.viewpoint.z - start.z) + 1.0:
            continue
        effort = cost + turn_penalty * abs(wrap_angle(frontier.viewpoint.theta - start.theta))
        scored.append((size_weight * frontier.cells / max(effort, grid.resolution), frontier))
    return [frontier for _, frontier in sorted(scored, key=lambda item: -item[0])]
