import math
import sys
import time
from pathlib import Path as FsPath

import numpy as np
import pytest

sys.path.insert(0, str(FsPath(__file__).resolve().parents[1] / "src"))

from lib.geometry import LEFT_CURVATURE_TABLE, RIGHT_CURVATURE_TABLE
from lib.planner import (
    FREE,
    OCCUPIED,
    UNKNOWN,
    Footprint,
    OccupancyGrid,
    PlannerParams,
    Pose2D,
    build_costmap,
    distance_map_from,
    find_frontiers,
    grid_from_mesh,
    inflate,
    is_path_blocked,
    plan_hybrid_astar,
    pose_clearance,
    rank_frontiers,
    smooth,
    split_segments,
)

RES = 0.05


def walled_grid(width_m: float, height_m: float) -> OccupancyGrid:
    grid = OccupancyGrid.filled((0.0, 0.0), round(width_m / RES) + 2, round(height_m / RES) + 2, RES, FREE)
    grid.cells[[0, -1], :] = OCCUPIED
    grid.cells[:, [0, -1]] = OCCUPIED
    return grid


def fill(grid: OccupancyGrid, x0: float, z0: float, x1: float, z1: float, value: int = OCCUPIED) -> None:
    grid.cells[round(z0 / RES) : round(z1 / RES), round(x0 / RES) : round(x1 / RES)] = value


def body_points(poses: np.ndarray, footprint: Footprint = Footprint()) -> np.ndarray:
    along = np.linspace(-footprint.rear_overhang, footprint.front_overhang, 12)
    across = np.linspace(-footprint.width / 2, footprint.width / 2, 6)
    a, b = (m.ravel() for m in np.meshgrid(along, across))
    c, s = np.cos(poses[:, 2:3]), np.sin(poses[:, 2:3])
    return np.stack([poses[:, :1] + c * a - s * b, poses[:, 1:2] + s * a + c * b], axis=-1).reshape(-1, 2)


def touches_obstacle(grid: OccupancyGrid, poses: np.ndarray) -> bool:
    iz, ix, inside = grid.cell_index(body_points(poses))
    return bool((~inside).any() or (grid.cells[iz[inside], ix[inside]] == OCCUPIED).any())


def max_curvature(poses: np.ndarray) -> float:
    run = np.linalg.norm(np.diff(poses[:, :2], axis=0), axis=1)
    turn = np.abs((np.diff(poses[:, 2]) + np.pi) % (2 * np.pi) - np.pi)
    return float((turn / np.maximum(run, 1e-9)).max())


@pytest.fixture(scope="module")
def corridor() -> OccupancyGrid:
    return walled_grid(6.0, 1.0)


@pytest.fixture(scope="module")
def turnaround(corridor: OccupancyGrid):
    return plan_hybrid_astar(corridor, Pose2D(3.0, 0.55, 0.0), Pose2D(2.5, 0.55, math.pi), PlannerParams(time_limit=5.0))


def test_straight_free_path():
    grid = walled_grid(4.0, 2.0)
    path = plan_hybrid_astar(grid, Pose2D(0.5, 1.05, 0.0), Pose2D(3.5, 1.05, 0.0))

    assert path is not None
    poses = path.poses()
    assert path.gear_switches == 0 and path.reverse_length == 0
    assert np.abs(poses[:, 1] - 1.05).max() < 0.03
    assert path.length == pytest.approx(3.0, abs=0.1)


def test_goal_behind_in_narrow_corridor_needs_reverse(corridor, turnaround):
    assert turnaround is not None
    poses = turnaround.poses()
    assert turnaround.gear_switches >= 1 and turnaround.reverse_length > 0
    assert any(w.direction < 0 for w in turnaround.waypoints)
    assert max_curvature(poses) <= 1.02 * max(LEFT_CURVATURE_TABLE[-1], RIGHT_CURVATURE_TABLE[-1])
    assert not touches_obstacle(corridor, poses)
    assert math.hypot(poses[-1, 0] - 2.5, poses[-1, 1] - 0.55) <= 0.12
    assert abs((poses[-1, 2] - math.pi + math.pi) % (2 * math.pi) - math.pi) <= math.radians(15)


def test_split_segments_alternates_and_shares_cusps(turnaround):
    segments = split_segments(turnaround)

    assert len(segments) == turnaround.gear_switches + 1
    assert all(a.direction != b.direction for a, b in zip(segments, segments[1:]))
    assert all(np.array_equal(a.points[-1], b.points[0]) for a, b in zip(segments, segments[1:]))
    assert sum(len(s.points) for s in segments) == len(turnaround.waypoints) + turnaround.gear_switches


def test_smooth_keeps_gears_endpoints_and_clearance(corridor, turnaround):
    smoothed = smooth(turnaround, build_costmap(corridor))

    assert [s.direction for s in split_segments(smoothed)] == [s.direction for s in split_segments(turnaround)]
    assert np.allclose(smoothed.poses()[[0, -1]], turnaround.poses()[[0, -1]])
    assert not touches_obstacle(corridor, smoothed.poses())


def test_obstacle_between_start_and_goal_is_avoided():
    grid = walled_grid(4.0, 3.0)
    fill(grid, 1.7, 0.6, 2.3, 2.4)
    path = plan_hybrid_astar(grid, Pose2D(0.6, 1.5, 0.0), (3.4, 1.5))

    assert path is not None
    assert not touches_obstacle(grid, path.poses())
    assert math.hypot(path.waypoints[-1].x - 3.4, path.waypoints[-1].z - 1.5) <= 0.12


def test_start_inside_inflated_clearance_escapes_without_cutting_closer():
    grid = walled_grid(4.0, 2.0)
    start = Pose2D(1.0, 0.17, 0.0)
    costmap = build_costmap(grid)
    start_clearance = pose_clearance(costmap, np.array([start.x, start.z, start.theta]))[0]
    assert start_clearance < 0

    path = plan_hybrid_astar(grid, start, Pose2D(3.0, 1.05, 0.0))

    assert path is not None
    assert not touches_obstacle(grid, path.poses())
    assert pose_clearance(costmap, path.poses()).min() >= start_clearance - 1e-6
    assert math.hypot(path.waypoints[-1].x - 3.0, path.waypoints[-1].z - 1.05) <= 0.12


def test_is_path_blocked_only_looks_ahead_of_index():
    grid = walled_grid(4.0, 2.0)
    path = plan_hybrid_astar(grid, Pose2D(0.5, 1.05, 0.0), Pose2D(3.5, 1.05, 0.0))
    assert path is not None and not is_path_blocked(grid, path)

    grid.mark_points(np.array([[1.5, 1.05]]), OCCUPIED)
    past = next(i for i, w in enumerate(path.waypoints) if w.x > 2.2)

    assert is_path_blocked(grid, path, 0)
    assert not is_path_blocked(grid, path, past)


def sealed_goal_room() -> OccupancyGrid:
    grid = walled_grid(4.0, 3.0)
    fill(grid, 2.5, 0.0, 2.55, 3.1)
    return grid


def narrow_gap_room() -> OccupancyGrid:
    grid = sealed_goal_room()
    fill(grid, 2.5, 1.45, 2.55, 1.6, FREE)
    return grid


@pytest.mark.parametrize("build", [sealed_goal_room, narrow_gap_room])
def test_unreachable_goal_returns_none_within_time_limit(build):
    params = PlannerParams(time_limit=0.5)
    began = time.monotonic()
    path = plan_hybrid_astar(build(), Pose2D(1.0, 1.5, 0.0), (3.5, 1.5), params)

    assert path is None
    assert time.monotonic() - began < params.time_limit + 0.4


def test_unknown_blocked_refuses_unknown_shortcut():
    grid = walled_grid(4.0, 3.0)
    fill(grid, 1.7, 0.05, 2.3, 3.05, UNKNOWN)
    start, goal = Pose2D(0.6, 1.5, 0.0), (3.4, 1.5)

    assert plan_hybrid_astar(grid, start, goal) is not None
    assert plan_hybrid_astar(grid, start, goal, PlannerParams(unknown_blocked=True)) is None


def test_inflate_gives_euclidean_distance_capped_at_radius():
    grid = OccupancyGrid.filled((0.0, 0.0), 21, 21, RES, FREE)
    grid.cells[10, 10] = OCCUPIED
    distance = inflate(grid, 0.3)

    assert distance[10, 10] == 0
    assert distance[13, 14] == pytest.approx(0.25)
    assert distance[10, 1] == pytest.approx(0.3)
    assert pose_clearance(build_costmap(grid), np.array([[0.525, 0.525, 0.0]]))[0] < 0


def test_clear_ray_frees_cells_up_to_the_hit():
    grid = OccupancyGrid.filled((0.0, 0.0), 40, 10, RES, OCCUPIED)
    grid.clear_ray((0.025, 0.225), np.array([[1.525, 0.225]]))

    assert (grid.cells[4, :29] == FREE).all()
    assert grid.cells[4, 30] == OCCUPIED
    assert grid.cells[3, 10] == OCCUPIED


def quad(a, b, c, d) -> list[list[float]]:
    return [a, b, c, a, c, d]


def box_room_mesh() -> tuple[np.ndarray, np.ndarray]:
    corners = []
    corners += quad([0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3])
    for (x0, z0), (x1, z1) in [((0, 0), (4, 0)), ((4, 0), (4, 3)), ((4, 3), (0, 3)), ((0, 3), (0, 0))]:
        corners += quad([x0, 0, z0], [x1, 0, z1], [x1, 2.5, z1], [x0, 2.5, z0])
    corners += quad([0, 2.5, 0], [4, 2.5, 0], [4, 2.5, 3], [0, 2.5, 3])
    corners += quad([3.0, 0.75, 0.5], [3.6, 0.75, 0.5], [3.6, 0.75, 1.2], [3.0, 0.75, 1.2])
    for (x0, z0), (x1, z1) in [((1, 1), (1.4, 1)), ((1.4, 1), (1.4, 1.4)), ((1.4, 1.4), (1, 1.4)), ((1, 1.4), (1, 1))]:
        corners += quad([x0, 0, z0], [x1, 0, z1], [x1, 0.3, z1], [x0, 0.3, z0])
    vertices = np.asarray(corners, dtype=np.float64)
    return vertices, np.arange(len(vertices)).reshape(-1, 3)


def test_grid_from_mesh_marks_walls_floor_and_ignores_overhangs():
    vertices, triangles = box_room_mesh()
    grid = grid_from_mesh(vertices, triangles, resolution=RES)

    def at(x: float, z: float) -> int:
        iz, ix, _ = grid.cell_index(np.array([[x, z]]))
        return int(grid.cells[iz[0], ix[0]])

    assert grid.origin == pytest.approx((-0.5, -0.5))
    assert [at(2.0, 0.0), at(4.0, 1.5), at(2.0, 3.0), at(0.0, 1.5)] == [OCCUPIED] * 4
    assert [at(2.0, 1.5), at(0.3, 2.7), at(3.3, 0.8)] == [FREE] * 3
    assert [at(1.2, 1.0), at(1.4, 1.2)] == [OCCUPIED] * 2
    assert at(1.2, 1.2) == FREE
    assert [at(-0.3, 1.5), at(2.0, 3.3)] == [UNKNOWN] * 2


def half_seen_room() -> OccupancyGrid:
    grid = walled_grid(4.0, 3.0)
    fill(grid, 2.0, 0.0, 4.15, 3.15, UNKNOWN)
    return grid


def test_frontier_along_seen_boundary_with_viewpoint_facing_unknown():
    grid = half_seen_room()
    grid.mark_points(np.array([[0.8, 0.8]]), UNKNOWN)
    costmap = build_costmap(grid)

    frontiers = find_frontiers(costmap)

    assert len(frontiers) == 1
    frontier = frontiers[0]
    view = frontier.viewpoint
    assert frontier.cells >= 50
    assert frontier.centroid[0] == pytest.approx(1.975, abs=0.03)
    assert 0.5 - 1e-6 <= math.hypot(view.x - frontier.centroid[0], view.z - frontier.centroid[1]) <= 0.8 + 1e-6
    assert view.x < frontier.centroid[0] and math.cos(view.theta) > 0.7
    assert pose_clearance(costmap, np.array([view.x, view.z, view.theta]))[0] >= 0


def test_frontiers_rank_by_path_cost_not_straight_line():
    grid = walled_grid(10.0, 4.0)
    fill(grid, 3.0, 0.0, 3.1, 3.2)
    fill(grid, 3.6, 1.8, 4.0, 2.2, UNKNOWN)
    fill(grid, 0.4, 0.4, 0.8, 0.8, UNKNOWN)
    costmap = build_costmap(grid)
    start = Pose2D(2.0, 2.0, 0.0)
    frontiers = find_frontiers(costmap)
    behind_wall, open_side = sorted(frontiers, key=lambda f: -f.centroid[0])

    assert behind_wall.cells == open_side.cells
    assert math.dist((start.x, start.z), behind_wall.centroid) < math.dist((start.x, start.z), open_side.centroid)
    assert rank_frontiers(frontiers, start, grid, distance_map_from(costmap, (start.x, start.z)), turn_penalty=0.0) == [open_side, behind_wall]


def test_unreachable_frontier_is_excluded_from_ranking():
    grid = walled_grid(6.0, 3.0)
    fill(grid, 3.0, 0.0, 3.1, 3.1)
    fill(grid, 4.4, 1.3, 4.8, 1.7, UNKNOWN)
    costmap = build_costmap(grid)
    start = Pose2D(1.0, 1.5, 0.0)

    frontiers = find_frontiers(costmap)

    assert len(frontiers) == 1
    assert rank_frontiers(frontiers, start, grid, distance_map_from(costmap, (start.x, start.z))) == []
