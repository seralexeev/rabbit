import math

import numpy as np
import pytest
from sim import Robot, Sim, block, room_grid

from lib.planner import build_costmap, pose_clearance
from lib.trip import CANCEL_SUBJECT, MISSION_SUBJECT, PARAMS, Navigator, Target, camera_of, heading_to_theta


def costmap(grid):
    return build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)


def drive(navigator: Navigator, xs, now: float, z: float = 1.0, **pose) -> float:
    for x in xs:
        navigator.on_pose(np.array([x, z]), 0.0, now, **pose)
        now += 0.1
    return now


def start_trip(navigator: Navigator, now: float, target: Target = Target("point", 5.0, 1.0)) -> None:
    navigator.request("t", "test", target, now)
    navigator.on_plan(navigator.tick(now).run(), "t", now)
    navigator.on_nav({"mission_id": navigator.trip.mission_id, "mode": "driving"})
    navigator.tick(now)
    navigator.drain()


def nav_says(navigator: Navigator, mode: str, fault: str | None = None) -> None:
    navigator.on_nav({"mission_id": navigator.trip.mission_id, "mode": mode, "fault": fault})


def back_up(navigator: Navigator, now: float) -> np.ndarray:
    return back_up_after(navigator, now, "blocked")


def back_up_after(navigator: Navigator, now: float, fault: str) -> np.ndarray:
    nav_says(navigator, "fault", fault)
    assert navigator.tick(now) is None
    [(subject, mission)] = navigator.drain()
    assert subject == MISSION_SUBJECT
    return np.array(mission["steps"][0]["points"])


def test_backing_up_stops_where_the_robot_last_changed_gear_instead_of_turning_around_on_the_trail():
    navigator = Navigator()
    navigator.on_map(costmap(room_grid(6.0, 2.0)), np.empty((0, 2)))
    now = drive(navigator, np.arange(0.8, 1.6, 0.02), 0.0)
    now = drive(navigator, np.arange(1.6, 1.3, -0.02), now)
    now = drive(navigator, np.arange(1.3, 1.52, 0.02), now)
    start_trip(navigator, now)

    points = back_up(navigator, now)

    assert (points[:, 2] == -1).all()
    assert np.all(np.diff(points[:, 0]) <= 1e-3) and np.allclose(points[:, 1], 1.0, atol=0.01)
    assert points[-1, 0] > 1.3 - 0.02


def test_backing_up_stops_short_of_an_obstacle_that_appeared_on_the_trail():
    grid = room_grid(6.0, 2.0)
    navigator = Navigator()
    navigator.on_map(costmap(grid), np.empty((0, 2)))
    now = drive(navigator, np.arange(0.6, 2.0, 0.02), 0.0)
    start_trip(navigator, now)
    block(grid, 1.35, 0.6, 1.4, 1.4)
    navigator.on_map(costmap(grid), np.empty((0, 2)))

    points = back_up(navigator, now)

    travelled = np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1).sum()
    assert 0.1 <= travelled < 0.3
    assert points[:, 0].min() > 1.4 + 0.18 + 0.15


def test_backing_up_never_leaves_mapped_space_even_on_the_trail():
    grid = room_grid(6.0, 2.0)
    navigator = Navigator()
    now = drive(navigator, np.arange(0.6, 2.0, 0.02), 0.0)
    block(grid, 0.05, 0.05, 1.75, 1.95, -1)
    navigator.on_map(costmap(grid), np.empty((0, 2)))
    start_trip(navigator, now)

    nav_says(navigator, "fault", "blocked")
    job = navigator.tick(now)

    assert job is not None and "no room to back up" in job.reason
    assert navigator.drain() == []


def test_backing_up_follows_the_odometry_trail_after_a_small_map_correction():
    navigator = Navigator()
    navigator.on_map(costmap(room_grid(6.0, 2.0)), np.empty((0, 2)))
    now = 0.0
    for x in np.arange(0.8, 1.8, 0.02):
        navigator.on_pose(np.array([x, 1.0]), 0.0, now, odom=(np.array([x, 1.0]), 0.0))
        now += 0.1
    navigator.on_pose(np.array([1.8, 1.15]), 0.0, now, odom=(np.array([1.8, 1.0]), 0.0))
    start_trip(navigator, now, Target("point", 5.0, 1.15))

    points = back_up(navigator, now)

    assert np.allclose(points[:, 1], 1.15, atol=0.01)
    assert np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1).sum() > 0.3


def test_a_robot_that_was_lifted_does_not_back_up_along_where_it_was_carried():
    navigator = Navigator()
    navigator.on_map(costmap(room_grid(6.0, 2.0)), np.empty((0, 2)))
    now = drive(navigator, np.arange(0.8, 1.6, 0.02), 0.0, height=0.36)
    now = drive(navigator, np.arange(1.6, 1.64, 0.02), now, height=0.137)
    start_trip(navigator, now)

    nav_says(navigator, "fault", "blocked")
    job = navigator.tick(now)

    assert job is not None and "no room to back up" in job.reason


def tick_at(navigator: Navigator, now: float):
    navigator.on_pose(camera_of(navigator.robot), navigator.robot.theta, now)
    return navigator.tick(now)


def recovering(navigator: Navigator, now: float) -> float:
    navigator.on_map(costmap(room_grid(6.0, 2.0)), np.empty((0, 2)))
    now = drive(navigator, np.arange(0.8, 2.0, 0.02), now)
    start_trip(navigator, now)
    back_up(navigator, now)
    nav_says(navigator, "driving")
    navigator.tick(now)
    assert navigator.trip.phase == "recovering"
    return now


def test_backing_up_that_makes_no_progress_is_stopped_and_replanned():
    navigator = Navigator()
    now = recovering(navigator, 0.0)

    assert tick_at(navigator, now + 5.0) is None
    job = tick_at(navigator, now + 12.0)

    assert job is not None and job.reason == "after backing up"
    assert [subject for subject, _ in navigator.drain()] == [CANCEL_SUBJECT]


def test_backing_up_that_runs_away_from_the_trail_is_stopped():
    navigator = Navigator()
    now = recovering(navigator, 0.0)
    for k in range(1, 30):
        navigator.on_pose(np.array([2.0 - 0.02 * k, 1.0 + 0.03 * k]), 0.0, now + 0.1 * k)

    job = navigator.tick(now + 3.0)

    assert job is not None and job.reason == "after backing up"
    assert [subject for subject, _ in navigator.drain()] == [CANCEL_SUBJECT]


def test_hitting_something_while_backing_up_forgets_the_trail():
    navigator = Navigator()
    now = recovering(navigator, 0.0)
    nav_says(navigator, "fault", "stuck")

    job = navigator.tick(now + 0.5)

    assert job is not None and job.reason == "after backing up" and len(navigator.trail) == 0


def test_a_collision_while_backing_up_ends_the_trip():
    navigator = Navigator()
    now = recovering(navigator, 0.0)
    nav_says(navigator, "fault", "collision")

    assert navigator.tick(now + 0.5) is None
    assert navigator.trip.phase == "failed" and "collision" in navigator.trip.message


def test_blocked_again_where_it_already_backed_out_fails_the_trip():
    navigator = Navigator()
    now = drive(navigator, np.arange(1.98, 1.64, -0.02), recovering(navigator, 0.0))
    nav_says(navigator, "arrived")
    navigator.on_plan(navigator.tick(now).run(), "t", now)
    navigator.drain()
    now = drive(navigator, np.arange(1.66, 2.0, 0.02), now)
    nav_says(navigator, "driving")
    navigator.tick(now)

    nav_says(navigator, "fault", "blocked")
    navigator.tick(now + 0.5)

    assert navigator.trip.phase == "failed" and "already tried to back out" in navigator.trip.message


def test_a_goal_the_robot_already_stands_on_is_reached_without_driving_a_loop():
    navigator = Navigator()
    navigator.on_map(costmap(room_grid(5.0, 5.0)), np.empty((0, 2)))
    theta = heading_to_theta(0.0)
    navigator.on_pose(np.array([2.5, 2.5]), theta, 0.0)
    navigator.request("t", "explore", Target("point", 2.44, 2.53, 22.5, tolerance=0.3), 0.0)

    navigator.on_plan(navigator.tick(0.0).run(), "t", 0.0)

    assert navigator.trip.phase == "arrived" and navigator.trip.message == "already at the goal"
    assert all(subject != MISSION_SUBJECT for subject, _ in navigator.drain())


def test_nav_does_not_count_a_loop_blocked_at_its_start_as_arrived():
    grid = room_grid(5.0, 5.0)
    sim = Sim(grid, grid, Robot(2.0, 1.5, 0.0))
    camera = sim.robot.camera()
    angles = np.linspace(-math.pi / 2, 1.47 * math.pi, 40)
    loop = [[float(camera[0] + 0.6 * math.cos(a)), float(camera[1] + 0.6 + 0.6 * math.sin(a)), 1] for a in angles]
    sim.nav.remembered.append((sim.clock.now, camera[None, :] + [0.15, 0.0]))

    timeline = sim.run_mission([{"type": "path", "points": loop}], 2.0)

    assert {mode for *_, mode in timeline[5:]} == {"blocked"}


def test_stuck_while_reversing_replans_forward_around_the_spot_it_hit():
    navigator = Navigator()
    navigator.on_map(costmap(room_grid(6.0, 2.0)), np.empty((0, 2)))
    now = drive(navigator, np.arange(0.8, 2.0, 0.02), 0.0)
    start_trip(navigator, now)
    navigator.on_nav({"mission_id": navigator.trip.mission_id, "mode": "driving", "speed": -0.22})
    now = drive(navigator, np.arange(2.0, 1.9, -0.02), now)

    nav_says(navigator, "fault", "stuck")
    job = navigator.tick(now)

    assert job is not None and "no room to back up" in job.reason
    assert not [m for s, m in navigator.drain() if s == MISSION_SUBJECT]
    behind = navigator.robot.x - 0.15
    assert pose_clearance(job.costmap, np.array([behind, navigator.robot.z, 0.0]))[0] < 0


def test_stuck_while_driving_forward_backs_up_and_avoids_the_spot_ahead():
    navigator = Navigator()
    navigator.on_map(costmap(room_grid(6.0, 2.0)), np.empty((0, 2)))
    now = drive(navigator, np.arange(0.8, 2.0, 0.02), 0.0)
    start_trip(navigator, now)
    navigator.on_nav({"mission_id": navigator.trip.mission_id, "mode": "driving", "speed": 0.25})

    points = back_up_after(navigator, now, "stuck")

    assert (points[:, 2] == -1).all() and np.all(np.diff(points[:, 0]) <= 1e-3)
    ahead = navigator.robot.x + 0.15
    assert pose_clearance(navigator.planning_costmap(), np.array([ahead, navigator.robot.z, 0.0]))[0] < 0


def plan_after_driving(grid, z: float, xs, target: Target):
    navigator = Navigator()
    navigator.on_map(costmap(grid), np.empty((0, 2)))
    now = drive(navigator, xs, 0.0, z=z)
    navigator.request("t", "test", target, now)
    return navigator.tick(now).run().path


def test_turning_around_in_a_room_loops_forward_instead_of_reversing_where_it_never_drove():
    path = plan_after_driving(room_grid(3.0, 2.4), 1.2, np.arange(0.7, 2.2, 0.02), Target("point", 1.2, 1.2, -90.0))

    poses, directions = path.poses(), path.directions()
    assert path.reverse_length < 0.3 and np.all(np.abs(poses[directions < 0, 1] - 1.2) < 0.12)


def test_a_dead_end_is_still_left_in_reverse_along_the_way_in():
    grid = room_grid(3.0, 1.2)
    block(grid, 2.6, 0.0, 3.0, 1.2)

    path = plan_after_driving(grid, 0.6, np.arange(0.6, 2.4, 0.02), Target("point", 1.2, 0.6, -90.0))

    assert path is not None and path.reverse_length > 0.3


@pytest.mark.parametrize("width", [1.1, 1.2])
def test_turning_around_in_a_corridor_needs_no_guard_stops(width):
    grid = room_grid(6.0, width)
    sim = Sim(grid, grid, Robot(3.0, width / 2, 0.0))

    state = sim.run(Target("point", 1.7, width / 2, -90.0), 120)

    assert state["phase"] == "arrived" and state["replans"] == 0 and state["recoveries"] == 0


def test_turning_around_in_a_one_metre_corridor_still_arrives():
    grid = room_grid(6.0, 1.0)
    sim = Sim(grid, grid, Robot(3.0, 0.5, 0.0))

    state = sim.run(Target("point", 1.7, 0.5, -90.0), 120)

    assert state["phase"] == "arrived" and not sim.collided()


def test_nav_drives_up_to_a_gear_switch_close_to_a_wall_instead_of_stopping_short():
    grid = room_grid(3.0, 2.0)
    block(grid, 1.85, 0.0, 3.0, 2.0)
    sim = Sim(grid, grid, Robot(0.8, 1.0, 0.0))
    camera = sim.robot.camera()
    forward_leg = [[float(camera[0] + d), float(camera[1]), 1] for d in np.arange(0.0, 0.71, 0.05)]
    back_leg = [[float(camera[0] + d), float(camera[1]), -1] for d in np.arange(0.65, 0.29, -0.05)]

    timeline = sim.run_mission([{"type": "path", "points": forward_leg + back_leg}], 20.0)

    assert max(x for _, x, _, _ in timeline) > 0.8 + 0.65 and timeline[-1][3] == "arrived"
    assert not sim.collided()
