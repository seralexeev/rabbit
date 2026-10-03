from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np
from lib.geometry import CAMERA_TO_REAR_AXLE, camera_point, curvature_for_steer, rear_axle_point
from lib.planner import (
    OCCUPIED,
    UNKNOWN,
    CostMap,
    Path,
    PlannerParams,
    Pose2D,
    SearchStats,
    Waypoint,
    camera_points,
    crop,
    distance_map_from,
    expand,
    footprint_centers,
    plan_route,
    pose_clearance,
    smooth,
    swept_cells,
    with_obstacles,
    wrap_angle,
)

MISSION_SUBJECT = "rabbit.nav.mission"
CANCEL_SUBJECT = "rabbit.nav.cancel"

STEER_HEADROOM = 0.7
PARAMS = PlannerParams(
    min_turn_radius=1.0 / min(abs(curvature_for_steer(STEER_HEADROOM)), abs(curvature_for_steer(-STEER_HEADROOM))),
    steer_fractions=(-STEER_HEADROOM, -0.5 * STEER_HEADROOM, 0.0, 0.5 * STEER_HEADROOM, STEER_HEADROOM),
    reverse_penalty=4.0,
    untraversed_reverse_penalty=1.5,
    gear_switch_penalty=2.0,
    time_limit=1.0,
    max_expansions=150_000,
)
VIEWPOINT_HEADING_TOLERANCE = math.radians(30.0)
ARRIVAL_HEADING_TOLERANCE = math.radians(50.0)
FRONT_CLEARANCE = 0.4
APPROACH = 0.3
BURIED = -0.1
APPROACH_SPACING = 0.075
SEEN_FROM_BONUS = 0.5
SEEN_FROM_MAX_STANDOFF = 1.2
PREFERRED_STANDOFF = 0.5
REACH_WEIGHT = 0.6
PLAN_BUDGET = 1.2
GOAL_SWITCH_WEIGHT = 0.5
DETOUR_HOLD = 4.0
COMFORT_MARGIN = 0.07
COMFORT_SHARE = 0.4
DETOUR_HOLD_EXTRA = 3.0
TERMINAL = ("arrived", "failed", "cancelled", "planned")


def heading_to_theta(heading_deg: float) -> float:
    h = math.radians(heading_deg)
    return math.atan2(-math.cos(h), math.sin(h))


def theta_to_heading(theta: float) -> float:
    return math.degrees(math.atan2(math.cos(theta), -math.sin(theta)))


def forward(theta: float) -> np.ndarray:
    return np.array([math.cos(theta), math.sin(theta)])


def rear_pose(camera_xz: np.ndarray, theta: float) -> Pose2D:
    x, z = rear_axle_point(np.asarray(camera_xz, dtype=float), forward(theta))
    return Pose2D(float(x), float(z), theta)


def camera_of(pose: Pose2D) -> np.ndarray:
    return camera_point(np.array([pose.x, pose.z]), forward(pose.theta))


@dataclass(frozen=True)
class Target:
    kind: str
    x: float
    z: float
    heading_deg: float | None = None
    label: str | None = None
    size: float = 0.0
    tolerance: float = 0.25
    seen_from: tuple[tuple[float, float], ...] = ()

    def summary(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "x": round(self.x, 3),
            "z": round(self.z, 3),
            "heading_deg": None if self.heading_deg is None else round(self.heading_deg, 1),
        }


@dataclass(frozen=True)
class Goal:
    pose: Pose2D
    heading: bool
    tolerance: float

    def target(self) -> Pose2D | tuple[float, float]:
        return self.pose if self.heading else (self.pose.x, self.pose.z)

    def camera(self) -> np.ndarray:
        return camera_of(self.pose) if self.heading else np.array([self.pose.x, self.pose.z])

    def summary(self) -> dict:
        x, z = self.camera()
        return {"x": round(float(x), 3), "z": round(float(z), 3), "heading_deg": round(theta_to_heading(self.pose.theta), 1) if self.heading else None}


def _cells(costmap: CostMap, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    iz, ix, inside = costmap.grid.cell_index(points)
    return np.where(inside, iz, 0), np.where(inside, ix, 0), inside


def _reach_costs(costmap: CostMap, start: Pose2D, points: np.ndarray) -> np.ndarray:
    field_2d = distance_map_from(costmap, (start.x, start.z), PARAMS.unknown_cost)
    iz, ix, inside = costmap.grid.cell_index(points)
    return np.where(inside, field_2d[np.clip(iz, 0, costmap.grid.height - 1), np.clip(ix, 0, costmap.grid.width - 1)], np.inf)


def _unknown_share(costmap: CostMap, poses: np.ndarray) -> np.ndarray:
    centers = footprint_centers(poses, costmap.footprint).reshape(-1, 2)
    iz, ix, inside = costmap.grid.cell_index(centers)
    unknown = ~inside | (costmap.grid.cells[np.clip(iz, 0, costmap.grid.height - 1), np.clip(ix, 0, costmap.grid.width - 1)] == UNKNOWN)
    return unknown.reshape(len(poses), -1).mean(axis=1)


def _blocking(costmap: CostMap, samples: np.ndarray, unknown_blocks: bool) -> np.ndarray:
    iz, ix, inside = costmap.grid.cell_index(samples)
    cells = costmap.grid.cells[np.clip(iz, 0, costmap.grid.height - 1), np.clip(ix, 0, costmap.grid.width - 1)]
    blocked = cells == OCCUPIED
    if unknown_blocks:
        blocked = blocked | (cells == UNKNOWN) | ~inside
    return blocked & (inside | unknown_blocks)


def line_of_sight(costmap: CostMap, cameras: np.ndarray, center: np.ndarray, stop_short: float, unknown_blocks: bool = False) -> np.ndarray:
    visible = np.ones(len(cameras), dtype=bool)
    for i, camera in enumerate(cameras):
        span = center - camera
        length = float(np.linalg.norm(span))
        reach = length - stop_short
        if reach <= 0:
            continue
        samples = camera + (np.arange(0.0, reach, 0.5 * costmap.grid.resolution) / length)[:, None] * span
        visible[i] = not _blocking(costmap, samples, unknown_blocks).any()
    return visible


def front_clear(costmap: CostMap, cameras: np.ndarray, facing: np.ndarray, reach: float, unknown_blocks: bool = False) -> np.ndarray:
    steps = np.arange(0.0, reach + 1e-9, 0.5 * costmap.grid.resolution)
    samples = cameras[:, None, :] + steps[None, :, None] * facing[:, None, :]
    return ~_blocking(costmap, samples.reshape(-1, 2), unknown_blocks).reshape(len(cameras), -1).any(axis=1)


def free_spots(costmap: CostMap, start: Pose2D, center: tuple[float, float], radius: float = 1.0, count: int = 3, tolerance: float = 0.25) -> list[Goal]:
    grid = costmap.grid
    reach = distance_map_from(costmap, (start.x, start.z), PARAMS.unknown_cost)
    iz, ix, inside = grid.cell_index(np.array([center]))
    span = int(math.ceil(radius / grid.resolution))
    cz, cx = int(iz[0]), int(ix[0])
    z0, z1 = max(cz - span, 0), min(cz + span + 1, grid.height)
    x0, x1 = max(cx - span, 0), min(cx + span + 1, grid.width)
    if z0 >= z1 or x0 >= x1:
        return []
    zz, xx = np.mgrid[z0:z1, x0:x1]
    px = grid.origin[0] + (xx + 0.5) * grid.resolution
    pz = grid.origin[1] + (zz + 0.5) * grid.resolution
    offset = np.hypot(px - center[0], pz - center[1])
    roomy = costmap.distance[z0:z1, x0:x1] >= costmap.collision_radius + 0.05
    reachable = np.isfinite(reach[z0:z1, x0:x1])
    valid = roomy & reachable & (offset <= radius)
    if not valid.any():
        return []
    score = np.where(valid, offset + 0.02 * reach[z0:z1, x0:x1] - 0.5 * np.minimum(costmap.distance[z0:z1, x0:x1], 0.5), np.inf).ravel()
    goals: list[Goal] = []
    for index in np.argsort(score):
        if not math.isfinite(score[index]) or len(goals) >= count:
            break
        x, z = float(px.ravel()[index]), float(pz.ravel()[index])
        if all(math.hypot(x - g.pose.x, z - g.pose.z) > 0.3 for g in goals):
            theta = math.atan2(z - start.z, x - start.x)
            goals.append(Goal(Pose2D(x, z, theta), False, tolerance))
    return goals


def snap_to_obstacle(costmap: CostMap, center: tuple[float, float], reach: float = 0.6, cluster: float = 0.3) -> np.ndarray:
    target = np.asarray(center, dtype=float)
    grid = costmap.grid
    span = int(math.ceil(reach / grid.resolution))
    iz, ix, _ = grid.cell_index(target)
    z0, x0 = max(int(iz[0]) - span, 0), max(int(ix[0]) - span, 0)
    window = grid.cells[z0 : int(iz[0]) + span + 1, x0 : int(ix[0]) + span + 1]
    cells = np.argwhere(window == OCCUPIED)
    if len(cells) == 0:
        return target
    points = np.asarray(grid.origin) + (cells[:, ::-1] + np.array([x0, z0]) + 0.5) * grid.resolution
    distance = np.linalg.norm(points - target, axis=1)
    if distance.min() > reach:
        return target
    nearest = points[int(np.argmin(distance))]
    return points[np.linalg.norm(points - nearest, axis=1) <= cluster].mean(axis=0)


def surface_distance(costmap: CostMap, cameras: np.ndarray, facing: np.ndarray, fallback: np.ndarray, reach: float = 2.5) -> np.ndarray:
    steps = np.arange(0.0, reach, 0.5 * costmap.grid.resolution)
    samples = cameras[:, None, :] + steps[None, :, None] * facing[:, None, :]
    iz, ix, inside = costmap.grid.cell_index(samples.reshape(-1, 2))
    hit = (inside & (costmap.grid.cells[np.clip(iz, 0, costmap.grid.height - 1), np.clip(ix, 0, costmap.grid.width - 1)] == OCCUPIED)).reshape(len(cameras), -1)
    first = np.where(hit.any(axis=1), steps[hit.argmax(axis=1)], np.inf)
    return np.minimum(first, fallback)


def object_viewpoints(
    costmap: CostMap,
    start: Pose2D,
    center: tuple[float, float],
    size: float,
    standoffs: tuple[float, ...] = (0.3, 0.45, 0.6, 0.8, 1.0, 1.25, 1.5),
    bearings: int = 24,
    count: int = 4,
    seen_from: tuple[tuple[float, float], ...] = (),
    previous: np.ndarray | None = None,
) -> list[Goal]:
    half = float(np.clip(0.5 * size, 0.1, 0.6)) if size > 0 else 0.25
    target = snap_to_obstacle(costmap, center)
    angles = np.linspace(0.0, 2.0 * math.pi, bearings, endpoint=False)
    units = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    standoff = np.repeat(np.asarray(standoffs), bearings)
    unit = np.tile(units, (len(standoffs), 1))
    cameras = target + (half + standoff)[:, None] * unit
    observed = np.zeros(len(cameras), dtype=bool)
    if seen_from:
        spots = np.asarray(seen_from, dtype=float).reshape(-1, 2)
        offsets = spots - target
        distance = np.maximum(np.linalg.norm(offsets, axis=1), 1e-6)
        keep = (distance > half + 0.3) & (distance < half + SEEN_FROM_MAX_STANDOFF)
        cameras = np.vstack([cameras, spots[keep]])
        unit = np.vstack([unit, offsets[keep] / distance[keep, None]])
        standoff = np.concatenate([standoff, distance[keep] - half])
        observed = np.concatenate([observed, np.ones(int(keep.sum()), dtype=bool)])
    facing = -unit
    rear = rear_axle_point(cameras, facing)
    thetas = np.arctan2(facing[:, 1], facing[:, 0])
    poses = np.column_stack([rear, thetas])
    room = pose_clearance(costmap, poses)
    reach = _reach_costs(costmap, start, rear)
    unknown = _unknown_share(costmap, poses)
    surface = surface_distance(costmap, cameras, facing, standoff)
    base = (room >= 0.02) & np.isfinite(reach) & (surface >= FRONT_CLEARANCE)
    lead = np.ones(len(poses), dtype=bool)
    for fraction in (0.5, 1.0):
        behind = np.column_stack([rear - fraction * APPROACH * facing, thetas])
        lead &= pose_clearance(costmap, behind) >= 0
    sighted_known = front_clear(costmap, cameras, facing, FRONT_CLEARANCE, True) & (observed | line_of_sight(costmap, cameras, target, half + 0.1, True))
    sighted = front_clear(costmap, cameras, facing, FRONT_CLEARANCE) & (observed | line_of_sight(costmap, cameras, target, half + 0.1))
    tiers = [
        base & sighted_known & lead,
        base & sighted & lead,
        base & sighted_known,
        base & sighted,
        base & front_clear(costmap, cameras, facing, FRONT_CLEARANCE),
        (room >= 0.02) & np.isfinite(reach),
    ]
    valid = next((tier for tier in tiers if tier.any()), None)
    if valid is None:
        return []
    score = (
        REACH_WEIGHT * reach
        + 3.0 * np.abs(surface - PREFERRED_STANDOFF)
        + 1.0 * unknown
        + 2.0 * np.clip(0.25 - room, 0.0, None)
        - SEEN_FROM_BONUS * observed
        + (0.0 if previous is None else GOAL_SWITCH_WEIGHT * np.linalg.norm(cameras - previous, axis=1))
    )
    score = np.where(valid, score, np.inf)
    goals: list[Goal] = []
    for index in np.argsort(score):
        if not math.isfinite(score[index]) or len(goals) >= count:
            break
        pose = Pose2D(float(rear[index, 0]), float(rear[index, 1]), float(thetas[index]))
        if all(abs(wrap_angle(pose.theta - g.pose.theta)) > math.radians(40) for g in goals):
            goals.append(Goal(pose, True, 0.3))
    return goals


def goal_candidates(costmap: CostMap, start: Pose2D, target: Target, previous: np.ndarray | None = None) -> list[Goal]:
    if target.kind == "object":
        goals = object_viewpoints(costmap, start, (target.x, target.z), target.size, seen_from=target.seen_from, previous=previous)
        return goals or free_spots(costmap, start, (target.x, target.z), radius=0.5 * target.size + 1.2, tolerance=0.3)
    camera = np.array([target.x, target.z])
    if target.heading_deg is not None:
        pose = rear_pose(camera, heading_to_theta(target.heading_deg))
        if pose_clearance(costmap, np.array([pose.x, pose.z, pose.theta]))[0] >= 0:
            return [Goal(pose, True, target.tolerance)]
    iz, ix, inside = costmap.grid.cell_index(camera)
    if inside[0] and costmap.distance[iz[0], ix[0]] >= costmap.collision_radius:
        return [Goal(Pose2D(target.x, target.z, math.atan2(target.z - start.z, target.x - start.x)), False, target.tolerance)]
    return free_spots(costmap, start, (target.x, target.z), tolerance=target.tolerance)


def comfortable(costmap: CostMap) -> CostMap:
    return replace(costmap, footprint=replace(costmap.footprint, margin=costmap.footprint.margin + COMFORT_MARGIN))


def approach(costmap: CostMap, goal: Goal) -> tuple[Pose2D, np.ndarray] | None:
    heading = forward(goal.pose.theta)
    start = Pose2D(goal.pose.x - APPROACH * heading[0], goal.pose.z - APPROACH * heading[1], goal.pose.theta)
    steps = np.arange(APPROACH_SPACING, APPROACH + 1e-9, APPROACH_SPACING)
    poses = np.column_stack([start.x + steps * heading[0], start.z + steps * heading[1], np.full(len(steps), goal.pose.theta)])
    if pose_clearance(costmap, np.vstack([[start.x, start.z, start.theta], poses])).min() < 0:
        return None
    return start, poses


def extend(path: Path, poses: np.ndarray) -> Path:
    tail = [Waypoint(float(x), float(z), float(theta), 1) for x, z, theta in poses]
    switches = path.gear_switches + (1 if path.waypoints and path.waypoints[-1].direction < 0 else 0)
    return replace(path, waypoints=path.waypoints + tail, length=path.length + APPROACH, gear_switches=switches)


@dataclass
class PlanResult:
    path: Path | None
    goal: Goal | None
    goals: list[Goal]
    milliseconds: float
    expansions: int
    message: str
    room: np.ndarray | None = None


@dataclass
class PlanJob:
    trip_id: str
    costmap: CostMap
    start: Pose2D
    target: Target
    goals: list[Goal] | None
    reason: str
    params: PlannerParams = PARAMS
    previous: np.ndarray | None = None
    driven: np.ndarray | None = None

    def run(self) -> PlanResult:
        began = time.monotonic()
        traversed = None if self.driven is None else swept_cells(self.costmap.grid, self.driven, self.costmap.footprint)
        goals = self.goals if self.goals else goal_candidates(self.costmap, self.start, self.target, self.previous)
        if not goals:
            return PlanResult(None, None, [], (time.monotonic() - began) * 1000.0, 0, self.explain("no free, reachable spot near the target"))
        expansions = 0
        reasons = []
        deadline = began + PLAN_BUDGET
        for goal in goals[:3]:
            remaining = deadline - time.monotonic()
            if remaining < 0.1:
                reasons.append("out of time")
                break
            budget = min(self.params.time_limit, remaining)
            params = (
                replace(self.params, heading_tolerance=VIEWPOINT_HEADING_TOLERANCE if self.target.kind == "object" else self.params.heading_tolerance, time_limit=budget)
                if goal.heading
                else replace(self.params, goal_offset=CAMERA_TO_REAR_AXLE, time_limit=budget)
            )
            for costmap, share in ((comfortable(self.costmap), COMFORT_SHARE), (self.costmap, 1.0)):
                limit = max(0.05, share * min(budget, deadline - time.monotonic()))
                path, lead, stats = self.route(costmap, goal, replace(params, time_limit=limit), traversed)
                expansions += stats.expansions
                if path is not None:
                    path = smooth(path, costmap)
                    if lead is not None:
                        path = extend(path, lead[1])
                    room = pose_clearance(self.costmap, path.poses())
                    return PlanResult(path, goal, goals, (time.monotonic() - began) * 1000.0, expansions, "route found", room)
            reasons.append(stats.reason)
        return PlanResult(None, None, goals, (time.monotonic() - began) * 1000.0, expansions, self.explain(f"no route ({', '.join(sorted(set(reasons)))})"))

    def route(self, costmap: CostMap, goal: Goal, params: PlannerParams, traversed: np.ndarray | None) -> tuple[Path | None, tuple[Pose2D, np.ndarray] | None, SearchStats]:
        lead = approach(costmap, goal) if goal.heading else None
        path, stats = plan_route(costmap, self.start, goal.target() if lead is None else lead[0], params, traversed)
        if path is None and lead is not None:
            lead = None
            path, stats = plan_route(costmap, self.start, goal.target(), params, traversed)
        return path, lead, stats

    def explain(self, message: str) -> str:
        room = float(pose_clearance(self.costmap, np.array([self.start.x, self.start.z, self.start.theta]))[0])
        if room < BURIED:
            return f"{message}; the map shows obstacles where the robot stands, so the map is probably wrong here"
        return message


@dataclass
class Trip:
    id: str
    source: str
    target: Target
    started_at: float
    preview: bool = False
    phase: str = "planning"
    goals: list[Goal] = field(default_factory=list)
    goal: Goal | None = None
    path: Path | None = None
    path_room: np.ndarray | None = None
    index: int = 0
    mission_id: str | None = None
    mission_seq: int = 0
    mission_sent_at: float = 0.0
    accepted: bool = False
    recovery: bool = False
    recovery_deadline: float = math.inf
    recovery_reach: float = 0.0
    recovery_origin: tuple[float, float] = (0.0, 0.0)
    recovery_spots: list[tuple[float, float]] = field(default_factory=list)
    replans: int = 0
    recoveries: int = 0
    plan_failures: int = 0
    blocked_replans: int = 0
    short_arrivals: int = 0
    refinements: int = 0
    refining: bool = False
    remaining_before: float | None = None
    detour_held: bool = False
    blocked_since: float | None = None
    wait_until: float = 0.0
    last_plan_at: float = 0.0
    plan_ms: float | None = None
    expansions: int = 0
    reason: str = "start"
    message: str = "planning"
    finished_at: float | None = None
    events: list[str] = field(default_factory=list)


class Navigator:
    REPLAN_INTERVAL = 0.75
    DEVIATION = 0.35
    NAV_BLOCKED_REPLAN = 1.5
    BLOCKED_REPLANS_BEFORE_RECOVERY = 2
    MISSION_ACCEPT = 2.0
    MAX_REPLANS = 60
    MAX_RECOVERIES = 3
    MAX_PLAN_FAILURES = 3
    MAX_SHORT_ARRIVALS = 3
    RETRY_WAIT = 3.0
    TRIP_TIMEOUT = 900.0
    POSE_TIMEOUT = 1.0
    RECOVERY_DISTANCE = 0.35
    RECOVERY_MIN_DISTANCE = 0.1
    RECOVERY_GRACE = 3.0
    RECOVERY_SPEED = 0.08
    RECOVERY_OVERSHOOT = 0.15
    RECOVERY_SAME_SPOT = 0.3
    PATH_TOLERANCE = 0.03
    TRAIL_STEP = 0.05
    TRAIL_POINTS = 4000
    TRAIL_MAX_AGE = 120.0
    TRAIL_TURN = math.radians(25.0)
    TRAIL_LIFT = 0.05
    JUMP_DISTANCE = 0.25
    JUMP_HEADING = math.radians(10.0)
    PROGRESS_WINDOW = 60
    NEAR_GOAL = 0.5
    CLOSER_VIEW = 0.9
    MAX_REFINEMENTS = 2
    HEADING_RETRIES = 2
    CROP_MARGIN = 8.0

    def __init__(self, params: PlannerParams = PARAMS):
        self.params = params
        self.trip: Trip | None = None
        self.outbox: list[tuple[str, dict]] = []
        self.records: list[tuple[str, str, str, dict]] = []
        self.robot: Pose2D | None = None
        self.pose_at = -math.inf
        self.nav: dict = {}
        self.costmap: CostMap | None = None
        self.obstacles: np.ndarray = np.empty((0, 2))
        self.bumps: np.ndarray = np.empty((0, 2))
        self.reversing = False
        self.local: Pose2D | None = None
        self.map_from_local = (0.0, 0.0, 0.0)
        self.trail: deque[tuple[float, float, float, float, float]] = deque(maxlen=self.TRAIL_POINTS)
        self.planning = False
        self.jumped = False
        self.cached: tuple[int, CostMap] | None = None
        self.map_version = 0

    def send(self, subject: str, payload: dict) -> None:
        self.outbox.append((subject, payload))

    def drain(self) -> list[tuple[str, dict]]:
        messages, self.outbox = self.outbox, []
        return messages

    def record(self, name: str, reason: str, severity: str = "info", **fields) -> None:
        trip = self.trip
        if trip is not None:
            fields = {"trip_id": trip.id, "mission_id": trip.mission_id, "phase": trip.phase, **fields}
        self.records.append((name, reason, severity, fields))
        del self.records[:-200]

    def drain_records(self) -> list[tuple[str, str, str, dict]]:
        records, self.records = self.records, []
        return records

    def to_map(self, poses: np.ndarray) -> np.ndarray:
        rotation, tx, tz = self.map_from_local
        poses = np.asarray(poses, dtype=float).reshape(-1, 3)
        c, s = math.cos(rotation), math.sin(rotation)
        theta = (poses[:, 2] + rotation + math.pi) % (2.0 * math.pi) - math.pi
        return np.column_stack([tx + c * poses[:, 0] - s * poses[:, 1], tz + s * poses[:, 0] + c * poses[:, 1], theta])

    def trail_points(self) -> np.ndarray:
        return self.to_map(np.array([point[:3] for point in self.trail], dtype=float))[:, :2]

    def driven(self, now: float) -> np.ndarray:
        recent = [point[:3] for point in self.trail if now - point[3] <= self.TRAIL_MAX_AGE]
        poses = self.to_map(np.array(recent, dtype=float))
        return poses if self.robot is None else np.vstack([poses, [[self.robot.x, self.robot.z, self.robot.theta]]])

    def forget_trail(self) -> None:
        self.trail.clear()

    @classmethod
    def jumped_between(cls, before: Pose2D, after: Pose2D) -> bool:
        return math.hypot(after.x - before.x, after.z - before.z) > cls.JUMP_DISTANCE or abs(wrap_angle(after.theta - before.theta)) > cls.JUMP_HEADING

    def on_pose(self, camera_xz: np.ndarray, theta: float, now: float, odom: tuple[np.ndarray, float] | None = None, height: float | None = None) -> None:
        pose = rear_pose(camera_xz, theta)
        local = pose if odom is None else rear_pose(odom[0], odom[1])
        if self.robot is not None and self.jumped_between(self.robot, pose):
            self.jumped = True
        if self.local is not None and self.jumped_between(self.local, local):
            self.trail.clear()
        rotation = wrap_angle(pose.theta - local.theta)
        c, s = math.cos(rotation), math.sin(rotation)
        self.map_from_local = (rotation, pose.x - (c * local.x - s * local.z), pose.z - (s * local.x + c * local.z))
        self.robot = pose
        self.local = local
        self.pose_at = now
        height = math.nan if height is None else height
        if self.trail and abs(height - self.trail[-1][4]) > self.TRAIL_LIFT:
            self.trail.clear()
        if not self.trail or math.hypot(local.x - self.trail[-1][0], local.z - self.trail[-1][1]) >= self.TRAIL_STEP:
            self.trail.append((local.x, local.z, local.theta, now, height))

    def on_nav(self, state: dict) -> None:
        self.nav = state
        if state.get("mode") == "driving" and state.get("speed"):
            self.reversing = float(state["speed"]) < 0

    def on_map(self, costmap: CostMap, obstacles: np.ndarray) -> None:
        self.costmap = costmap
        self.obstacles = np.vstack([np.asarray(obstacles, dtype=float).reshape(-1, 2), self.bumps])
        self.map_version += 1

    def active(self) -> bool:
        return self.trip is not None and self.trip.phase not in TERMINAL

    def request(self, trip_id: str, source: str, target: Target, now: float, preview: bool = False) -> None:
        if self.active() and not preview:
            self.finish("cancelled", f"replaced by trip {trip_id}", now, stop=False)
        elif self.active():
            raise ValueError("a trip is running")
        self.trip = Trip(trip_id, source, target, now, preview)
        self.jumped = False
        self.bumps = np.empty((0, 2))
        self.event(f"trip to {target.label or target.kind} at ({target.x:.2f}, {target.z:.2f}) from {source}")
        self.record(
            "planner.trip_started",
            f"to {target.label or target.kind} from {source}",
            source=source,
            preview=preview,
            target_kind=target.kind,
            target_label=target.label,
            target_x=target.x,
            target_z=target.z,
            target_heading_deg=target.heading_deg,
            tolerance_m=target.tolerance,
            robot_x=None if self.robot is None else self.robot.x,
            robot_z=None if self.robot is None else self.robot.z,
        )

    def cancel(self, reason: str, now: float) -> None:
        if self.active():
            self.finish("cancelled", reason, now, stop=False)

    def event(self, text: str) -> None:
        if self.trip is not None:
            self.trip.events.append(text)
            del self.trip.events[:-20]

    def finish(self, phase: str, message: str, now: float, stop: bool = True) -> None:
        trip = self.trip
        if trip is None:
            return
        trip.phase = phase
        trip.message = message
        trip.finished_at = now
        self.event(f"{phase}: {message}")
        self.record(
            "planner.trip_finished",
            message,
            "warning" if phase == "failed" else "info",
            message=f"Trip {phase}: {message}",
            outcome=phase,
            duration_s=now - trip.started_at,
            replans=trip.replans,
            recoveries=trip.recoveries,
            plan_failures=trip.plan_failures,
            short_arrivals=trip.short_arrivals,
            path_length_m=None if trip.path is None else trip.path.length,
            goal_distance_m=self.goal_distance() if math.isfinite(self.goal_distance()) else None,
        )
        if stop and trip.accepted:
            self.send(CANCEL_SUBJECT, {"source": "planner", "trip_id": trip.id})

    def job(self, reason: str, now: float, fresh_goals: bool = False) -> PlanJob | None:
        trip = self.trip
        if trip is None or self.costmap is None or self.robot is None:
            return None
        if trip.path is not None and now - trip.last_plan_at < self.REPLAN_INTERVAL:
            return None
        costmap = self.planning_costmap()
        goals = None if fresh_goals or trip.goal is None else self.valid_goals(costmap)
        trip.reason = reason
        trip.last_plan_at = now
        if trip.path is not None and trip.phase not in ("waiting",):
            trip.phase = "replanning"
        self.planning = True
        if trip.path is not None:
            trip.remaining_before = float(np.linalg.norm(np.diff(trip.path.poses()[trip.index :, :2], axis=0), axis=1).sum())
        previous = None if trip.goal is None else trip.goal.camera()
        return PlanJob(trip.id, costmap, self.robot, trip.target, goals, reason, self.params, previous, self.driven(now))

    def planning_costmap(self) -> CostMap:
        assert self.costmap is not None
        key = self.map_version
        if self.cached is None or self.cached[0] != key:
            points = [] if self.robot is None else [(self.robot.x, self.robot.z)]
            if self.trip is not None:
                points.append((self.trip.target.x, self.trip.target.z))
                if self.trip.path is not None:
                    poses = self.trip.path.poses()
                    points.extend([tuple(poses[:, :2].min(axis=0)), tuple(poses[:, :2].max(axis=0))])
            merged = self.costmap
            if points:
                span = np.array(points)
                merged = crop(merged, tuple(span.min(axis=0) - self.CROP_MARGIN), tuple(span.max(axis=0) + self.CROP_MARGIN))
            merged = expand(merged, np.vstack([np.array(points).reshape(-1, 2), self.obstacles]), 1.5, self.params.proximity_band)
            if len(self.obstacles):
                merged = with_obstacles(merged, self.obstacles, self.params.proximity_band)
            self.cached = (key, merged)
        return self.cached[1]

    def valid_goals(self, costmap: CostMap) -> list[Goal] | None:
        trip = self.trip
        assert trip is not None and trip.goal is not None
        ordered = [trip.goal] + [g for g in trip.goals if g is not trip.goal]
        valid = [g for g in ordered if self.goal_still_good(costmap, g)]
        return valid or None

    def goal_still_good(self, costmap: CostMap, goal: Goal) -> bool:
        trip = self.trip
        assert trip is not None
        if not goal.heading:
            return True
        if pose_clearance(costmap, np.array([goal.pose.x, goal.pose.z, goal.pose.theta]))[0] < 0:
            return False
        if trip.target.kind != "object":
            return True
        camera = goal.camera()[None, :]
        facing = forward(goal.pose.theta)[None, :]
        half = float(np.clip(0.5 * trip.target.size, 0.1, 0.6)) if trip.target.size > 0 else 0.25
        target = np.array([trip.target.x, trip.target.z])
        return bool(front_clear(costmap, camera, facing, FRONT_CLEARANCE)[0] and line_of_sight(costmap, camera, target, half + 0.1)[0])

    def on_plan(self, result: PlanResult, trip_id: str, now: float) -> None:
        self.planning = False
        trip = self.trip
        if trip is None or trip.id != trip_id or trip.phase in TERMINAL:
            return
        trip.plan_ms = round(result.milliseconds, 1)
        trip.expansions = result.expansions
        if result.path is None:
            trip.plan_failures += 1
            self.event(f"planning failed ({trip.reason}): {result.message}")
            self.record(
                "planner.plan",
                trip.reason,
                "warning",
                message=f"Plan {result.message} in {result.milliseconds:.0f} ms ({trip.reason})",
                outcome="no route",
                detail=result.message,
                plan_ms=result.milliseconds,
                expansions=result.expansions,
                goals=len(result.goals),
                plan_failures=trip.plan_failures,
            )
            if trip.refining:
                trip.refining = False
                self.finish("arrived", "arrived; no closer view", now, stop=False)
            elif trip.path is None and trip.replans == 0 and trip.recoveries == 0:
                self.finish("failed", f"cannot reach the target: {result.message}", now)
            elif trip.plan_failures >= self.MAX_PLAN_FAILURES:
                self.finish("failed", f"route blocked: {result.message}", now)
            else:
                if trip.accepted:
                    self.send(CANCEL_SUBJECT, {"source": "planner", "trip_id": trip.id})
                trip.phase = "waiting"
                trip.wait_until = now + self.RETRY_WAIT
                trip.message = f"no route right now ({result.message}), retrying"
                self.record("planner.waiting", "no route right now", "warning", message=trip.message, wait_s=self.RETRY_WAIT, detail=result.message)
            return
        if trip.refining:
            trip.refining = False
            assert self.robot is not None and result.goal is not None
            if float(np.linalg.norm(result.goal.camera() - camera_of(self.robot))) < 0.25:
                self.finish("arrived", "arrived", now, stop=False)
                return
        first = trip.path is None
        if first and not trip.preview:
            trip.goal = result.goal
            if self.at_goal():
                self.finish("arrived", "already at the goal", now, stop=False)
                return
        before = trip.remaining_before
        if not first and not trip.detour_held and before is not None and result.path.length > max(2.0 * before, before + DETOUR_HOLD_EXTRA):
            trip.detour_held = True
            if trip.accepted:
                self.send(CANCEL_SUBJECT, {"source": "planner", "trip_id": trip.id})
            trip.phase = "waiting"
            trip.wait_until = now + DETOUR_HOLD
            trip.message = f"way blocked; waiting {DETOUR_HOLD:.0f} s before a {result.path.length:.1f} m detour"
            self.event(trip.message)
            self.record("planner.waiting", "long detour", message=trip.message, wait_s=DETOUR_HOLD, detour_m=result.path.length, remaining_before_m=before)
            return
        if result.path.length <= max(2.0 * (before or 0.0), (before or 0.0) + DETOUR_HOLD_EXTRA):
            trip.detour_held = False
        trip.plan_failures = 0
        trip.goals = result.goals
        trip.goal = result.goal
        trip.path = result.path
        trip.path_room = result.room
        trip.index = 0
        trip.recovery = False
        if not first:
            trip.replans += 1
            self.event(f"replanned ({trip.reason}): {result.path.length:.1f} m in {result.milliseconds:.0f} ms")
        else:
            self.event(f"route {result.path.length:.1f} m in {result.milliseconds:.0f} ms")
        goal = None if result.goal is None else result.goal.summary()
        self.record(
            "planner.plan",
            trip.reason,
            message=f"Plan {result.message} in {result.milliseconds:.0f} ms ({trip.reason})",
            outcome="route found",
            first=first,
            replans=trip.replans,
            length_m=result.path.length,
            remaining_before_m=before,
            gear_switches=result.path.gear_switches,
            plan_ms=result.milliseconds,
            expansions=result.expansions,
            goals=len(result.goals),
            goal_x=None if goal is None else goal["x"],
            goal_z=None if goal is None else goal["z"],
            goal_heading_deg=None if goal is None else goal["heading_deg"],
            min_clearance_m=None if result.room is None or not len(result.room) else float(np.min(result.room)),
        )
        if trip.replans > self.MAX_REPLANS:
            self.finish("failed", "too many replans", now)
            return
        if trip.preview:
            self.finish("planned", f"route of {result.path.length:.1f} m planned, not driving", now, stop=False)
            return
        trip.phase = "driving"
        trip.message = "driving" if first else f"driving (replanned: {trip.reason})"
        self.send_path(camera_points(result.path), now)

    def send_path(self, points: list[list[float]], now: float) -> None:
        trip = self.trip
        assert trip is not None
        trip.mission_seq += 1
        trip.mission_id = f"{trip.id}.{trip.mission_seq}"
        trip.mission_sent_at = now
        trip.accepted = False
        trip.blocked_since = None
        self.send(MISSION_SUBJECT, {"id": trip.mission_id, "steps": [{"type": "path", "points": points}], "source": "planner", "trip_id": trip.id})

    def recover(self, reason: str, now: float) -> PlanJob | None:
        trip = self.trip
        assert trip is not None
        assert self.local is not None
        if trip.recoveries >= self.MAX_RECOVERIES:
            self.record("planner.recovery", reason, "warning", outcome="out of recoveries", recoveries=trip.recoveries)
            self.finish("failed", f"stuck: {reason}", now)
            return None
        spot = (self.local.x, self.local.z)
        if any(math.dist(spot, other) <= self.RECOVERY_SAME_SPOT for other in trip.recovery_spots):
            self.record("planner.recovery", reason, "warning", outcome="same spot again", recoveries=trip.recoveries)
            self.finish("failed", f"stuck: {reason}, again where it already tried to back out", now)
            return None
        trip.recovery_spots.append(spot)
        trip.recoveries += 1
        trip.blocked_replans = 0
        poses = self.backup_route(now)
        length = float(np.linalg.norm(np.diff(poses[:, :2], axis=0), axis=1).sum())
        if length < self.RECOVERY_MIN_DISTANCE:
            self.event(f"recovery {trip.recoveries}: no known free trail behind to back up along ({reason})")
            self.record("planner.recovery", reason, "warning", outcome="no trail to back up along", recoveries=trip.recoveries, length_m=length, trail_points=len(self.trail))
            trip.last_plan_at = -math.inf
            return self.job(f"{reason}, no room to back up", now, fresh_goals=True)
        trip.recovery = True
        trip.recovery_origin = spot
        trip.recovery_reach = length + self.RECOVERY_OVERSHOOT
        trip.recovery_deadline = now + self.RECOVERY_GRACE + length / self.RECOVERY_SPEED
        trip.phase = "recovering"
        trip.message = f"backing up ({reason})"
        self.event(f"recovery {trip.recoveries}: backing up {length:.2f} m ({reason})")
        self.record("planner.recovery", reason, "warning", message=f"Backing up {length:.2f} m: {reason}", outcome="backing up", recoveries=trip.recoveries, length_m=length, deadline_s=trip.recovery_deadline - now)
        waypoints = [Waypoint(float(x), float(z), float(theta), -1) for x, z, theta in poses]
        self.send_path(camera_points(Path(waypoints, length, length, 0, 0.0)), now)
        return None

    def bump(self) -> None:
        assert self.robot is not None
        footprint = self.params.footprint
        ahead = forward(self.robot.theta)
        reach = -(footprint.rear_overhang + 0.05) if self.reversing else footprint.front_overhang + 0.05
        side = np.array([-ahead[1], ahead[0]]) * 0.5 * footprint.width
        center = np.array([self.robot.x, self.robot.z]) + reach * ahead
        self.bumps = np.vstack([self.bumps, center - side, center, center + side])
        self.obstacles = np.vstack([self.obstacles, self.bumps[-3:]])
        self.map_version += 1
        self.event(f"something unmapped stopped the robot {'behind' if self.reversing else 'ahead'}; avoiding that spot")
        self.record("planner.bump", "an unmapped obstacle stopped the robot", side="behind" if self.reversing else "ahead", x=float(center[0]), z=float(center[1]))

    def watch_recovery(self, mode: str | None, fault: str | None, now: float) -> PlanJob | None:
        trip = self.trip
        assert trip is not None and self.local is not None
        if mode == "fault" and fault not in ("blocked", "step timeout", "manoeuvre failed", "stuck"):
            self.finish("failed", f"navigation safety stop while backing up: {fault}", now, stop=False)
            return None
        if mode == "fault":
            if fault == "stuck":
                self.bump()
            self.trail.clear()
            self.event(f"backing up stopped: {fault}")
            self.record("planner.recovery_ended", f"nav stopped: {fault}", fault=fault)
        elif mode not in ("arrived", "idle"):
            if now <= trip.recovery_deadline and math.dist(trip.recovery_origin, (self.local.x, self.local.z)) <= trip.recovery_reach:
                return None
            trip.recovery_deadline = trip.recovery_reach = math.inf
            self.trail.clear()
            self.event("backing up took too long or went too far, stopping it")
            self.record("planner.recovery_ended", "took too long or went too far", "warning")
            self.send(CANCEL_SUBJECT, {"source": "planner", "trip_id": trip.id})
        trip.last_plan_at = -math.inf
        return self.job("after backing up", now, fresh_goals=True)

    def backup_route(self, now: float) -> np.ndarray:
        assert self.local is not None
        rows = [(self.local.x, self.local.z, self.local.theta)]
        travelled = 0.0
        for x, z, theta, at, _ in reversed(self.trail):
            nx, nz, ntheta = rows[-1]
            step = math.hypot(nx - x, nz - z)
            if step < 0.01:
                continue
            ahead = (nx - x) * math.cos(ntheta) + (nz - z) * math.sin(ntheta)
            if now - at > self.TRAIL_MAX_AGE or ahead < 0.5 * step or abs(wrap_angle(ntheta - theta)) > self.TRAIL_TURN:
                break
            rows.append((x, z, theta))
            travelled += step
            if travelled >= self.RECOVERY_DISTANCE:
                break
        poses = self.to_map(np.array(rows))
        costmap = self.planning_costmap()
        room = pose_clearance(costmap, poses)
        bad = (room < min(0.0, float(room[0])) - 1e-6) | (_unknown_share(costmap, poses) > 0)
        bad[0] = False
        return poses[: int(np.argmax(bad))] if bad.any() else poses

    def at_goal(self) -> bool:
        trip = self.trip
        if trip is None or trip.goal is None or self.robot is None:
            return False
        close = self.goal_distance() <= max(trip.goal.tolerance, 0.2)
        if not trip.goal.heading or not close:
            return close
        return trip.short_arrivals >= self.HEADING_RETRIES or self.heading_error() <= ARRIVAL_HEADING_TOLERANCE

    def heading_error(self) -> float:
        trip = self.trip
        assert trip is not None and trip.goal is not None and self.robot is not None
        return abs(wrap_angle(self.robot.theta - trip.goal.pose.theta))

    def wants_closer_view(self) -> bool:
        trip = self.trip
        assert trip is not None and self.robot is not None
        if trip.target.kind != "object" or trip.refinements >= self.MAX_REFINEMENTS or self.costmap is None:
            return False
        camera = camera_of(self.robot)
        costmap = self.planning_costmap()
        target = snap_to_obstacle(costmap, (trip.target.x, trip.target.z))
        geometric = float(np.linalg.norm(camera - target)) - 0.5 * trip.target.size
        surface = surface_distance(costmap, camera[None, :], forward(self.robot.theta)[None, :], np.array([geometric]))[0]
        return min(surface, geometric) > self.CLOSER_VIEW

    def goal_distance(self) -> float:
        trip = self.trip
        if trip is None or trip.goal is None or self.robot is None:
            return math.inf
        return float(np.linalg.norm(camera_of(self.robot) - trip.goal.camera()))

    def near_goal(self) -> bool:
        trip = self.trip
        assert trip is not None
        if self.goal_distance() > self.NEAR_GOAL:
            return False
        return trip.goal is not None and (not trip.goal.heading or abs(wrap_angle(self.robot.theta - trip.goal.pose.theta)) <= math.radians(45))

    def progress(self) -> tuple[float, float]:
        trip = self.trip
        assert trip is not None and trip.path is not None and self.robot is not None
        poses = trip.path.poses()
        window = poses[trip.index : trip.index + self.PROGRESS_WINDOW, :2]
        distance = np.linalg.norm(window - np.array([self.robot.x, self.robot.z]), axis=1)
        nearest = int(np.argmin(distance))
        trip.index += nearest
        remaining = float(np.linalg.norm(np.diff(poses[trip.index :, :2], axis=0), axis=1).sum())
        return float(distance[nearest]), remaining

    def blocked_ahead(self) -> int | None:
        trip = self.trip
        assert trip is not None and trip.path is not None
        if self.costmap is None or trip.path_room is None:
            return None
        poses = trip.path.poses()[trip.index :]
        room = pose_clearance(self.planning_costmap(), poses)
        bad = np.flatnonzero(room < np.minimum(trip.path_room[trip.index :], 0.0) - self.PATH_TOLERANCE)
        return None if len(bad) == 0 else int(bad[0])

    def tick(self, now: float) -> PlanJob | None:
        trip = self.trip
        if trip is None or trip.phase in TERMINAL or self.planning:
            return None
        if now - trip.started_at > self.TRIP_TIMEOUT:
            self.finish("failed", "trip timed out", now)
            return None
        if self.robot is None or now - self.pose_at > self.POSE_TIMEOUT:
            trip.message = "waiting for the pose"
            return None
        if self.costmap is None:
            trip.message = "waiting for the map"
            return None
        if trip.path is None and trip.phase == "planning":
            return self.job("start", now)
        if trip.phase == "waiting":
            return self.job("retry", now, fresh_goals=True) if now >= trip.wait_until else None
        nav = self.nav
        ours = nav.get("mission_id") == trip.mission_id
        if not trip.accepted:
            if not ours:
                if now - trip.mission_sent_at > self.MISSION_ACCEPT:
                    fault = nav.get("fault") or "no answer"
                    self.finish("failed", f"navigation did not take the route: {fault}", now)
                return None
            trip.accepted = True
        if not ours:
            self.finish("cancelled", "another mission took over", now, stop=False)
            return None
        mode = nav.get("mode")
        if self.jumped:
            self.jumped = False
            if not trip.recovery:
                return self.job("pose corrected", now)
        if trip.recovery:
            return self.watch_recovery(mode, nav.get("fault"), now)
        if mode == "fault":
            fault = nav.get("fault") or "fault"
            if fault in ("blocked", "step timeout", "manoeuvre failed", "stuck"):
                if fault == "stuck":
                    self.bump()
                if self.near_goal():
                    self.finish("arrived", f"stopped {self.goal_distance():.2f} m short: {fault}", now, stop=False)
                    return None
                return self.recover(f"navigation stopped: {fault}", now)
            if fault == "manual override":
                self.finish("cancelled", "manual override", now, stop=False)
            else:
                self.finish("failed", f"navigation safety stop: {fault}", now, stop=False)
            return None
        if mode == "idle":
            self.finish("cancelled", "navigation was cancelled", now, stop=False)
            return None
        if mode == "arrived":
            if self.at_goal():
                if self.wants_closer_view():
                    trip.refinements += 1
                    trip.refining = True
                    return self.job("closer view", now, fresh_goals=True)
                message = "arrived" if not trip.goal.heading or self.heading_error() <= ARRIVAL_HEADING_TOLERANCE else f"arrived, facing {math.degrees(self.heading_error()):.0f} deg off"
                self.finish("arrived", message, now, stop=False)
                return None
            trip.short_arrivals += 1
            if trip.short_arrivals > self.MAX_SHORT_ARRIVALS:
                self.finish("failed", "could not settle at the goal", now)
                return None
            return self.job("stopped short of the goal", now)
        deviation, remaining = self.progress()
        if mode == "blocked":
            trip.blocked_since = trip.blocked_since or now
            if now - trip.blocked_since > self.NAV_BLOCKED_REPLAN and self.near_goal():
                self.finish("arrived", f"stopped {self.goal_distance():.2f} m short: obstacle ahead", now)
                return None
            if now - trip.blocked_since > self.NAV_BLOCKED_REPLAN:
                trip.blocked_replans += 1
                trip.blocked_since = None
                if trip.blocked_replans > self.BLOCKED_REPLANS_BEFORE_RECOVERY:
                    return self.recover("obstacle in the way", now)
                return self.job("obstacle in the way", now)
            return None
        trip.blocked_since = None
        blocked = self.blocked_ahead()
        if blocked is not None:
            return self.job(f"path blocked {self.distance_along(blocked):.1f} m ahead", now)
        if deviation > self.DEVIATION:
            return self.job(f"off the path by {deviation:.2f} m", now)
        trip.message = f"driving, {remaining:.1f} m to go"
        return None

    def distance_along(self, offset: int) -> float:
        trip = self.trip
        assert trip is not None and trip.path is not None
        poses = trip.path.poses()[trip.index : trip.index + offset + 1, :2]
        return float(np.linalg.norm(np.diff(poses, axis=0), axis=1).sum())

    def state(self, now: float) -> dict:
        trip = self.trip
        if trip is None:
            return {"phase": "idle", "trip_id": None}
        remaining = None
        path: list[list[float]] = []
        if trip.path is not None and (trip.phase not in TERMINAL or trip.phase == "planned"):
            points = [point[:3] for point in camera_points(trip.path)[trip.index :]]
            step = max(1, len(points) // 400)
            path = points[::step] + ([points[-1]] if points and (len(points) - 1) % step else [])
            remaining = round(float(np.linalg.norm(np.diff(trip.path.poses()[trip.index :, :2], axis=0), axis=1).sum()), 2)
        return {
            "phase": trip.phase,
            "trip_id": trip.id,
            "source": trip.source,
            "preview": trip.preview,
            "target": trip.target.summary(),
            "goal": None if trip.goal is None else trip.goal.summary(),
            "path": path,
            "path_length_m": None if trip.path is None else round(trip.path.length, 2),
            "remaining_m": remaining,
            "replans": trip.replans,
            "recoveries": trip.recoveries,
            "reason": trip.reason,
            "message": trip.message,
            "plan_ms": trip.plan_ms,
            "expansions": trip.expansions,
            "mission_id": trip.mission_id,
            "elapsed_s": round((trip.finished_at or now) - trip.started_at, 1),
            "events": trip.events[-8:],
        }
