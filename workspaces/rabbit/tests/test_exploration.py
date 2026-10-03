import math

import numpy as np
from sim import Robot, ScannedMap, Sim, block, room_grid
from test_navigation import apartment

from lib.exploration import next_view
from lib.geometry import camera_point
from lib.planner import UNKNOWN, Pose2D, build_costmap, distance_map_from
from lib.trip import PARAMS


def view_from(grid, start: Pose2D, failed=()):
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)
    return next_view(costmap, start, distance_map_from(costmap, (start.x, start.z), PARAMS.unknown_cost), list(failed))


def camera(view) -> np.ndarray:
    return camera_point(np.array([view.pose.x, view.pose.z]), np.array([math.cos(view.pose.theta), math.sin(view.pose.theta)]))


def test_a_room_behind_a_doorway_is_looked_into_from_the_corridor():
    grid = room_grid(6.0, 4.5)
    block(grid, 0.0, 1.5, 2.6, 1.6)
    block(grid, 3.4, 1.5, 6.0, 1.6)
    block(grid, 0.05, 1.6, 5.95, 4.45, UNKNOWN)

    view = view_from(grid, Pose2D(1.0, 0.75, 0.0))

    assert view is not None and view.gain > 1.5
    assert camera(view)[1] < 1.5 and math.sin(view.pose.theta) > 0.5


def test_exploration_is_done_when_no_view_would_reveal_a_square_metre():
    grid = room_grid(4.0, 3.0)
    block(grid, 3.5, 2.5, 3.8, 2.8, UNKNOWN)

    assert view_from(grid, Pose2D(1.0, 1.5, 0.0)) is None


def test_unknown_space_right_behind_the_robot_is_looked_at_without_driving_away():
    grid = room_grid(5.0, 3.0)
    block(grid, 0.05, 0.05, 1.2, 2.95, UNKNOWN)

    view = view_from(grid, Pose2D(2.4, 1.5, 0.0))

    assert view is not None and math.cos(view.pose.theta) < -0.5
    assert math.hypot(view.pose.x - 2.4, view.pose.z - 1.5) < 1.0


def test_an_unknown_apartment_is_mostly_mapped_quickly_and_exploration_then_stops():
    world = apartment(door_a_to_c=True)
    sim = Sim(world, world, Robot(1.0, 1.5, 0.0))
    sim.mapper = ScannedMap(world)
    coverage = []
    original = sim.advance

    def advance(dt):
        original(dt)
        coverage.append((sim.clock.now - 1000.0, sim.mapper.explored()))

    sim.advance = advance

    outcomes = sim.explore(400.0)

    assert next(t for t, explored in coverage if explored >= 0.9) < 120.0
    assert outcomes[-1] == "nothing left worth looking at" and sim.clock.now - 1000.0 < 200.0
    assert not sim.collided()


def test_a_corner_left_in_the_current_room_is_finished_before_a_big_room_far_away():
    grid = room_grid(12.0, 4.0)
    block(grid, 6.95, 0.0, 7.05, 1.6)
    block(grid, 6.95, 2.4, 7.05, 4.0)
    block(grid, 7.05, 0.05, 11.95, 3.95, UNKNOWN)
    block(grid, 0.05, 2.9, 1.0, 3.95, UNKNOWN)

    view = view_from(grid, Pose2D(2.0, 1.2, 0.0))

    assert view is not None and camera(view)[0] < 6.0


def test_a_small_pocket_far_away_does_not_earn_a_trip():
    grid = room_grid(12.0, 3.0)
    block(grid, 10.8, 1.9, 11.95, 2.95, UNKNOWN)

    assert view_from(grid, Pose2D(1.0, 1.0, 0.0)) is None


def test_a_spot_given_up_on_is_not_turned_around_on_again():
    grid = room_grid(5.0, 3.0)
    block(grid, 0.05, 0.05, 1.2, 2.95, UNKNOWN)
    start = Pose2D(2.4, 1.5, 0.0)

    view = view_from(grid, start, failed=[(start.x, start.z)])

    assert view is None or math.hypot(view.pose.x - start.x, view.pose.z - start.z) > 0.1
