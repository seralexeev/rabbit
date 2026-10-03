import asyncio
import json
import math
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from sim import Clock, Event, Robot, Sim, apartment, block, explore_module, room_grid, nav_module

from lib.navmap import ObstacleMemory
from lib.planner import FREE, OccupancyGrid, Pose2D, build_costmap, footprint_centers, plan_route, pose_clearance, wrap_angle
from lib.trip import MISSION_SUBJECT, PARAMS, Goal, Navigator, Target, camera_of, free_spots, goal_candidates, object_viewpoints

FRIDGE = Target("object", 1.0, 5.5, label="refrigerator", size=0.7)


def faces(sim: Sim, x: float, z: float, within_deg: float) -> bool:
    camera = sim.robot.camera()
    bearing = math.atan2(z - camera[1], x - camera[0])
    return abs((bearing - sim.robot.theta + math.pi) % (2 * math.pi) - math.pi) <= math.radians(within_deg)


def test_long_route_through_two_doors_ends_facing_the_object():
    sim = Sim(apartment(), apartment(), Robot(1.0, 1.5, math.pi))

    state = sim.run(FRIDGE, 300)

    assert state["phase"] == "arrived"
    assert not sim.collided()
    assert 9.0 < state["path_length_m"] < 16.0
    camera = sim.robot.camera()
    assert 0.3 < np.hypot(*(camera - np.clip(camera, [0.65, 5.05], [1.35, 5.95]))) < 1.2
    assert faces(sim, FRIDGE.x, FRIDGE.z, 45.0)


def test_obstacle_missing_from_the_map_is_avoided_after_the_scan_sees_it():
    world = apartment()
    block(world, 4.8, 0.6, 5.6, 2.3)
    sim = Sim(world, apartment(), Robot(1.0, 1.5, 0.0))

    state = sim.run(FRIDGE, 300)

    assert state["phase"] == "arrived"
    assert state["replans"] >= 1 and any("path blocked" in event for event in state["events"])
    assert not sim.collided()


def test_wall_found_in_new_map_data_reroutes_through_the_other_door():
    closed = apartment(door_b_to_c=False, door_a_to_c=True)
    sim = Sim(closed, apartment(door_a_to_c=True), Robot(5.5, 1.5, 0.0))
    sim.events.append(Event(8.0, lambda s: s.set_known(apartment(door_b_to_c=False, door_a_to_c=True))))

    state = sim.run(Target("point", 6.4, 5.0), 300)

    assert state["phase"] == "arrived"
    assert state["replans"] >= 1 and any("waiting 4 s before a" in event for event in state["events"])
    assert min(z for _, z, _ in sim.trajectory) > 0 and any(x < 1.3 and 2.7 < z < 3.3 for x, z, _ in sim.trajectory)
    assert not sim.collided()


def test_route_cut_off_mid_trip_fails_with_a_reason_and_stops_the_robot():
    def close_every_door(s: Sim):
        s.world = apartment(door_b_to_c=False)
        s.set_known(s.world)

    sim = Sim(apartment(), apartment(), Robot(5.5, 1.5, 0.0))
    sim.events.append(Event(10.0, close_every_door))

    state = sim.run(Target("point", 6.4, 5.0), 120)

    assert state["phase"] == "failed" and "route blocked" in state["message"]
    assert sim.nav_state["mode"] in ("idle", "fault") and sim.nav.speed == 0
    assert sim.trajectory[-1][1] < 2.95 and not sim.collided()


def test_robot_pushed_sideways_replans_from_where_it_is():
    sim = Sim(apartment(), apartment(), Robot(1.0, 1.5, 0.0))

    def push(s: Sim):
        s.robot.z += 0.02

    sim.events.extend(Event(20.0 + 0.05 * k, push) for k in range(25))
    state = sim.run(FRIDGE, 300)

    assert state["phase"] == "arrived"
    assert any("off the path" in event for event in state["events"])


def drive_straight(navigator: Navigator, start: float, distance: float, now: float) -> float:
    for x in np.arange(start, start + distance, 0.02):
        navigator.on_pose(np.array([x, 1.0]), 0.0, now)
        now += 0.1
    return now


def accept(navigator: Navigator, mode: str = "driving", fault: str | None = None) -> None:
    trip = navigator.trip
    assert trip is not None
    navigator.on_nav({"mission_id": trip.mission_id, "mode": mode, "fault": fault})


def test_blocked_navigation_backs_up_along_its_own_trail_then_replans():
    grid = room_grid(6.0, 2.0)
    navigator = Navigator()
    navigator.on_map(build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band), np.empty((0, 2)))
    now = drive_straight(navigator, 0.8, 1.2, 0.0)
    navigator.request("t", "test", Target("point", 5.0, 1.0), now)
    job = navigator.tick(now)
    assert job is not None
    navigator.on_plan(job.run(), "t", now)
    accept(navigator)
    navigator.tick(now)
    navigator.drain()

    accept(navigator, "fault", "blocked")
    assert navigator.tick(now + 0.25) is None

    [(subject, mission)] = navigator.drain()
    points = np.array(mission["steps"][0]["points"])
    assert subject == MISSION_SUBJECT and (points[:, 2] == -1).all()
    assert points[0, 0] == pytest.approx(camera_of(navigator.robot)[0], abs=0.06)
    assert np.all(np.diff(points[:, 0]) < 0) and np.allclose(points[:, 1], 1.0, atol=0.01)
    assert 0.3 <= points[0, 0] - points[-1, 0] <= 0.45

    accept(navigator, "arrived")
    navigator.on_pose(camera_of(navigator.robot), 0.0, now + 2.0)
    job = navigator.tick(now + 2.0)
    assert job is not None and job.reason == "after backing up"


def test_object_viewpoint_is_on_the_open_side_facing_the_object():
    grid = room_grid(4.0, 4.0)
    block(grid, 1.6, 3.3, 2.4, 3.95)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)
    start = Pose2D(2.0, 1.0, math.pi / 2)

    goals = object_viewpoints(costmap, start, (2.0, 3.6), 0.8)

    assert goals
    for goal in goals:
        camera = camera_of(goal.pose)
        to_object = np.array([2.0, 3.6]) - camera
        assert not (1.6 <= camera[0] <= 2.4 and camera[1] >= 3.3)
        assert pose_clearance(costmap, np.array([goal.pose.x, goal.pose.z, goal.pose.theta]))[0] >= 0
        assert abs(wrap_angle(math.atan2(to_object[1], to_object[0]) - goal.pose.theta)) < 0.05
    front = camera_of(goals[0].pose)
    assert front[1] < 3.3 and abs(front[0] - 2.0) < 0.5


def test_point_goal_inside_furniture_moves_to_the_nearest_free_spot():
    grid = room_grid(4.0, 4.0)
    block(grid, 1.5, 1.5, 2.5, 2.5)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)
    start = Pose2D(0.6, 0.6, 0.0)

    [goal, *_] = goal_candidates(costmap, start, Target("point", 2.0, 2.0))

    distance = math.hypot(goal.pose.x - 2.0, goal.pose.z - 2.0)
    assert 0.5 < distance < 1.0
    assert free_spots(costmap, start, (2.0, 2.0), radius=0.4) == []


def test_route_prefers_the_wide_gap_over_a_slightly_shorter_tight_one():
    grid = room_grid(6.0, 4.0)
    block(grid, 2.9, 0.0, 3.1, 4.0)
    block(grid, 2.9, 1.2, 3.1, 1.62, 0)
    block(grid, 2.9, 2.4, 3.1, 3.3, 0)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)

    path, _ = plan_route(costmap, Pose2D(1.0, 1.4, 0.0), (5.0, 1.4), PARAMS)
    tight, _ = plan_route(costmap, Pose2D(1.0, 1.4, 0.0), (5.0, 1.4), replace(PARAMS, proximity_weight=0.0))

    assert path is not None and tight is not None
    crossing = path.poses()[np.argmin(np.abs(path.poses()[:, 0] - 3.0))]
    assert crossing[1] > 2.4
    assert tight.poses()[np.argmin(np.abs(tight.poses()[:, 0] - 3.0))][1] < 1.62


def test_unreachable_goal_fails_without_searching():
    grid = room_grid(6.0, 3.0)
    block(grid, 3.0, 0.0, 3.1, 3.0)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)
    plan_route(costmap, Pose2D(1.0, 1.5, 0.0), (2.0, 1.5), PARAMS)

    began = time.monotonic()
    path, stats = plan_route(costmap, Pose2D(1.0, 1.5, 0.0), (5.0, 1.5), PARAMS)

    assert path is None and stats.expansions == 0
    assert time.monotonic() - began < 0.1


def test_apartment_route_plans_fast_after_warm_up():
    costmap = build_costmap(apartment(), PARAMS.footprint, False, PARAMS.proximity_band)
    start = Pose2D(1.0, 1.5, math.pi)
    plan_route(costmap, start, (6.4, 5.0), PARAMS)

    began = time.monotonic()
    path, stats = plan_route(costmap, start, Pose2D(1.8, 4.9, math.pi), replace(PARAMS, heading_tolerance=math.radians(30)))

    assert path is not None
    assert time.monotonic() - began < 0.5


def test_obstacle_memory_forgets_a_hit_once_a_ray_passes_through_it():
    memory = ObstacleMemory()
    origin = np.array([0.0, 0.0])
    ends = np.array([[1.0, 0.0], [0.0, 1.0]])
    memory.add(0.0, origin, ends, np.array([True, True]))

    memory.add(0.1, origin, np.array([[2.5, 0.0], [0.0, 1.0]]), np.array([False, True]))

    points = memory.points(0.2)
    assert points.tolist() == [[0.0, 1.0]]
    assert len(memory.points(10.0)) == 0


def test_obstacle_memory_keeps_a_hit_that_moved_into_the_blind_zone():
    memory = ObstacleMemory()
    memory.add(0.0, np.array([0.0, 0.0]), np.array([[0.5, 0.0]]), np.array([True]))

    memory.add(0.1, np.array([0.2, 0.0]), np.array([[2.7, 0.0]]), np.array([False]))

    assert memory.points(0.2).tolist() == [[0.5, 0.0]]


def test_a_scan_hit_beyond_the_mapped_area_still_blocks_the_padded_costmap():
    grid = OccupancyGrid.filled((0.0, 0.0), 40, 40, 0.05, FREE)
    navigator = Navigator()
    navigator.on_map(build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band), np.array([[2.3, 1.0]]))
    navigator.on_pose(np.array([1.0, 1.0]), 0.0, 0.0)

    costmap = navigator.planning_costmap()

    iz, ix, inside = costmap.grid.cell_index(np.array([[2.3, 1.0]]))
    assert inside[0] and costmap.distance[iz[0], ix[0]] == 0.0


def test_exploration_gives_up_on_a_frontier_that_is_still_there_after_two_arrivals():
    node = explore_module.Node()

    node.arrived_at((1.0, 1.0))
    assert node.failed == []
    node.arrived_at((1.2, 1.0))
    assert node.failed == [(1.2, 1.0)]


def test_obstacle_memory_stays_small_while_the_robot_stares_at_a_wall():
    memory = ObstacleMemory()
    origin = np.array([0.0, 0.0])
    wall = np.column_stack([np.full(48, 1.0), np.linspace(-1.0, 1.0, 48)])
    for frame in range(90):
        memory.add(frame / 15, origin, wall, np.ones(48, dtype=bool))

    assert 0 < len(memory.points(6.0)) <= 48


def test_target_outside_the_mapped_area_is_planned_through_unknown_space_without_cutting_border_walls():
    grid = room_grid(3.0, 3.0)
    block(grid, 0.0, 1.0, 3.0, 3.0, -1)
    block(grid, 1.0, 0.95, 3.0, 1.0)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)
    navigator = Navigator()
    navigator.on_map(costmap, np.empty((0, 2)))
    navigator.on_pose(np.array([0.6, 0.5]), 0.0, 0.0)
    navigator.request("t", "test", Target("point", 4.5, 0.5), 0.0)

    job = navigator.tick(0.0)
    assert job is not None
    result = job.run()

    assert result.path is not None
    poses = result.path.poses()
    assert poses[:, 0].max() > 3.9
    walls = (np.argwhere(grid.cells == 1)[:, ::-1] + 0.5) * grid.resolution
    centers = footprint_centers(poses, PARAMS.footprint).reshape(-1, 2)
    nearest = np.linalg.norm(centers[:, None, :] - walls[None, :, :], axis=2).min()
    assert nearest >= PARAMS.footprint.radius + 0.5 * grid.resolution


def test_preview_plans_the_route_without_sending_a_mission():
    sim = Sim(apartment(), apartment(), Robot(1.0, 1.5, math.pi))
    sim.navigator.on_map(sim.costmap, np.empty((0, 2)))
    sim.navigator.on_pose(sim.robot.camera(), sim.robot.theta, 0.0)
    sim.navigator.request("p", "test", FRIDGE, 0.0, preview=True)

    job = sim.navigator.tick(0.0)
    sim.navigator.on_plan(job.run(), "p", 0.1)

    state = sim.navigator.state(0.2)
    assert state["phase"] == "planned" and len(state["path"]) > 20
    assert sim.navigator.drain() == []


def test_planning_costmap_ignores_map_far_from_the_trip():
    grid = room_grid(4.0, 3.0)
    huge = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)
    far = replace(huge.grid, origin=(-200.0, 0.0), width=grid.width + 4000, cells=np.pad(grid.cells, ((0, 0), (4000, 0)), constant_values=-1))
    navigator = Navigator()
    navigator.on_map(replace(huge, grid=far, distance=np.pad(huge.distance, ((0, 0), (4000, 0)), constant_values=1.0)), np.empty((0, 2)))
    navigator.on_pose(np.array([1.0, 1.5]), 0.0, 0.0)
    navigator.request("t", "test", Target("point", 3.0, 1.5), 0.0)

    job = navigator.tick(0.0)

    assert job is not None and job.costmap.grid.width < 400
    assert job.run().path is not None


def test_never_reverses_into_unmapped_space():
    grid = room_grid(6.0, 1.0)
    block(grid, 0.0, 0.0, 2.6, 1.0, -1)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)

    path, _ = plan_route(costmap, Pose2D(3.2, 0.5, 0.0), (1.2, 0.5), PARAMS)
    known, _ = plan_route(build_costmap(room_grid(6.0, 1.0), PARAMS.footprint, False, PARAMS.proximity_band), Pose2D(3.2, 0.5, 0.0), (1.2, 0.5), PARAMS)

    assert known is not None and known.reverse_length > 1.0
    assert path is None or all(w.direction > 0 or w.x > 2.6 for w in path.waypoints)


def test_viewpoint_for_an_object_on_a_counter_leaves_room_for_the_safety_stop():
    grid = room_grid(4.0, 4.0)
    block(grid, 1.0, 3.2, 3.0, 3.95)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)

    goals = object_viewpoints(costmap, Pose2D(2.0, 1.0, math.pi / 2), (2.0, 3.6), 0.2)

    assert goals
    for goal in goals:
        camera = camera_of(goal.pose)
        ahead = camera + np.arange(0.0, 0.4, 0.02)[:, None] * np.array([math.cos(goal.pose.theta), math.sin(goal.pose.theta)])
        iz, ix, inside = costmap.grid.cell_index(ahead)
        assert not (costmap.grid.cells[iz[inside], ix[inside]] == 1).any()


def test_blocked_just_short_of_the_goal_counts_as_arrived():
    grid = room_grid(6.0, 2.0)
    navigator = Navigator()
    navigator.on_map(build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band), np.empty((0, 2)))
    now = drive_straight(navigator, 0.8, 1.2, 0.0)
    navigator.request("t", "test", Target("point", 3.0, 1.0), now)
    navigator.on_plan(navigator.tick(now).run(), "t", now)
    accept(navigator)
    navigator.tick(now)
    navigator.drain()
    now = drive_straight(navigator, 2.0, 0.85, now)

    accept(navigator, "fault", "blocked")
    navigator.tick(now)

    assert navigator.trip.phase == "arrived" and "short" in navigator.trip.message
    assert navigator.drain() == []


def test_arriving_far_from_an_object_looks_for_a_closer_view():
    grid = room_grid(6.0, 3.0)
    block(grid, 5.3, 1.2, 5.9, 1.8)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)
    navigator = Navigator()
    navigator.on_map(costmap, np.empty((0, 2)))
    navigator.on_pose(np.array([1.0, 1.5]), 0.0, 0.0)
    navigator.request("t", "test", Target("object", 5.6, 1.5, label="box", size=0.6), 0.0)
    navigator.on_plan(navigator.tick(0.0).run(), "t", 0.0)
    far = Goal(Pose2D(3.4, 1.5, 0.0), True, 0.3)
    navigator.trip.goal = far
    navigator.on_pose(camera_of(far.pose), 0.0, 5.0)
    navigator.jumped = False
    accept(navigator, "arrived")

    job = navigator.tick(5.0)

    assert job is not None and job.reason == "closer view"
    result = job.run()
    assert result.goal is not None and camera_of(result.goal.pose)[0] > camera_of(far.pose)[0] + 0.5


def test_point_behind_reached_in_reverse_counts_as_arrived():
    grid = room_grid(6.0, 1.0)
    sim = Sim(grid, grid, Robot(3.0, 0.5, 0.0))

    state = sim.run(Target("point", 1.7, 0.5), 120)

    assert state["phase"] == "arrived"
    assert np.hypot(*(sim.robot.camera() - [1.7, 0.5])) < 0.25 and not sim.collided()


def test_arriving_at_a_viewpoint_at_an_angle_settles_instead_of_failing():
    grid = room_grid(4.0, 3.0)
    navigator = Navigator()
    navigator.on_map(build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band), np.empty((0, 2)))
    navigator.on_pose(np.array([1.0, 1.5]), 0.0, 0.0)
    navigator.request("t", "test", Target("point", 2.5, 1.5, heading_deg=90.0), 0.0)
    navigator.on_plan(navigator.tick(0.0).run(), "t", 0.0)
    goal = navigator.trip.goal
    assert goal.heading

    now = 1.0
    for _ in range(Navigator.HEADING_RETRIES):
        navigator.on_pose(goal.camera(), goal.pose.theta + math.radians(70), now)
        navigator.jumped = False
        accept(navigator, "arrived")
        job = navigator.tick(now)
        assert job is not None and job.reason == "stopped short of the goal"
        navigator.on_plan(job.run(), "t", now + 1.0)
        now += 2.0
    navigator.on_pose(goal.camera(), goal.pose.theta + math.radians(70), now)
    accept(navigator, "arrived")
    navigator.tick(now)

    assert navigator.trip.phase == "arrived" and "facing 70 deg off" in navigator.trip.message


def test_reach_costs_start_even_when_the_robot_stands_close_to_a_wall():
    grid = room_grid(4.0, 3.0)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)
    from lib.planner import distance_map_from

    costs = distance_map_from(costmap, (2.0, 0.12))

    assert np.isfinite(costs[30, 40])


def test_viewpoint_prefers_a_line_of_sight_through_mapped_space():
    grid = room_grid(6.0, 4.0)
    block(grid, 2.8, 1.7, 3.2, 2.3)
    block(grid, 3.3, 0.05, 5.95, 3.95, -1)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)

    goals = object_viewpoints(costmap, Pose2D(5.0, 2.0, math.pi), (3.0, 2.0), 0.4)

    assert goals and camera_of(goals[0].pose)[0] < 3.3


def test_viewpoint_prefers_where_the_robot_saw_the_object_from():
    grid = room_grid(6.0, 4.0)
    block(grid, 2.8, 1.7, 3.2, 2.3)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)
    spot = (3.1, 2.82)

    goals = object_viewpoints(costmap, Pose2D(3.1, 3.5, -math.pi / 2), (3.0, 2.0), 0.4, seen_from=(spot,))

    assert np.hypot(*(camera_of(goals[0].pose) - spot)) < 0.05


def test_object_trip_ends_close_to_the_object_not_where_it_was_first_seen():
    grid = room_grid(6.0, 4.0)
    block(grid, 0.05, 2.9, 2.0, 3.95)
    block(grid, 3.0, 2.9, 5.95, 3.95)
    block(grid, 2.2, 3.5, 2.8, 3.95)
    costmap = build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band)

    goals = object_viewpoints(costmap, Pose2D(1.0, 1.0, 0.0), (2.5, 3.6), 0.35, seen_from=((2.4, 1.0), (1.5, 1.2)))

    camera = camera_of(goals[0].pose)
    assert 2.0 < camera[0] < 3.0 and camera[1] > 2.6
    assert 3.5 - camera[1] < 0.9


def test_nav_creeps_close_to_a_wall_and_stays_stopped_after_its_scan_memory_expires():
    grid = room_grid(4.0, 2.0)
    block(grid, 2.5, 0.0, 2.6, 2.0)
    sim = Sim(grid, grid, Robot(1.0, 1.0, 0.0))

    timeline = sim.run_mission([{"type": "move", "forward": 3.0}], 25.0)

    bumper = sim.robot.x + 0.2245
    assert 2.5 - bumper < 0.3 and not sim.collided()
    stopped = next(t for t, *_, mode in timeline if mode == "blocked")
    moved_after = [x for t, x, _, _ in timeline if t > stopped + 1.0]
    assert max(moved_after) - min(moved_after) < 0.01
    assert timeline[-1][3] == "fault"


def test_exploration_maps_most_of_an_unknown_apartment_without_touching_anything():
    world = apartment(door_a_to_c=True)
    sim = Sim(world, world, Robot(1.0, 1.5, 0.0))

    outcomes = sim.explore(400.0)

    assert sim.mapper.explored() > 0.7
    assert outcomes.count("arrived") >= 3 and not sim.collided()


def test_planning_from_inside_a_phantom_obstacle_says_the_map_is_wrong():
    grid = room_grid(4.0, 3.0)
    block(grid, 0.3, 0.6, 2.4, 2.4)
    navigator = Navigator()
    navigator.on_map(build_costmap(grid, PARAMS.footprint, False, PARAMS.proximity_band), np.empty((0, 2)))
    navigator.on_pose(np.array([1.4, 1.5]), 0.0, 0.0)
    navigator.request("t", "test", Target("point", 3.2, 1.5), 0.0)

    result = navigator.tick(0.0).run()

    assert result.path is None and "map is probably wrong" in result.message


def test_a_phantom_point_stuck_in_the_blind_zone_cannot_hold_the_robot_forever():
    clock = Clock()
    nav_module.time = clock
    try:
        node = nav_module.Node()
        node.position = np.array([0.0, 0.0])
        node.forward = np.array([1.0, 0.0])
        node.remembered.append((clock.now, np.array([[0.2, 0.0]])))
        held = {}
        for step in range(1, 81):
            clock.now += 0.5
            held[step * 0.5] = len(node.obstacles()) > 0
        assert held[20.0] and not held[40.0]
    finally:
        nav_module.time = __import__("time")


def sideways_glitch(at: float) -> tuple[float, float]:
    return (0.0, 0.2) if 2.0 <= at < 7.0 else (0.0, 0.0)


@pytest.mark.parametrize("odom", [True, False])
def test_a_map_pose_glitch_makes_nav_swerve_only_without_odometry(odom):
    grid = room_grid(6.0, 3.0)
    sim = Sim(grid, grid, Robot(0.5, 1.5, 0.0), odom=odom, map_error=sideways_glitch)

    timeline = sim.run_mission([{"type": "move", "forward": 3.0}], 30.0)

    swerve = max(abs(z - 1.5) for _, z, _ in sim.trajectory)
    assert (swerve < 0.03) == odom
    assert timeline[-1][3] == "arrived"


def test_a_turnaround_loop_that_ends_next_to_its_start_is_driven_not_skipped():
    grid = room_grid(5.0, 5.0)
    sim = Sim(grid, grid, Robot(2.0, 1.5, 0.0))
    camera = sim.robot.camera()
    angles = np.linspace(-math.pi / 2, 1.4 * math.pi, 40)
    loop = [[float(camera[0] + 0.6 * math.cos(a)), float(camera[1] + 0.6 + 0.6 * math.sin(a)), 1] for a in angles]

    sim.run_mission([{"type": "path", "points": loop}], 40.0)

    driven = sum(math.dist(a[:2], b[:2]) for a, b in zip(sim.trajectory, sim.trajectory[1:]))
    assert driven > 2.0


def imu_message(acceleration: list[float]) -> SimpleNamespace:
    return SimpleNamespace(data=json.dumps({"acceleration": acceleration, "orientation": [0.0, 0.0, 0.0, 1.0]}).encode())


def test_single_noisy_imu_samples_do_not_trip_collision_but_a_sustained_impact_does():
    clock = Clock()
    nav_module.time = clock
    try:
        node = nav_module.Node()
        node.mode, node.speed, node.speed_changed_at = "driving", 0.25, clock.now - 5.0
        trips = []

        async def trip(fault, **details):
            trips.append(fault)

        node.trip = trip
        loop = asyncio.new_event_loop()
        for step in range(40):
            spike = 9.0 if step % 5 == 4 else 0.0
            loop.run_until_complete(node.on_imu(imu_message([spike, 9.81, 0.0])))
            clock.now += 0.01
        assert trips == []
        for _ in range(6):
            loop.run_until_complete(node.on_imu(imu_message([8.0, 9.81, 0.0])))
            clock.now += 0.01
        loop.close()
        assert trips and set(trips) == {"collision"}
    finally:
        nav_module.time = __import__("time")


def roboclaw_message(current: float) -> SimpleNamespace:
    return SimpleNamespace(data=json.dumps({"left": {"current": current}, "right": {"current": current}}).encode())


def test_backing_into_an_unseen_wall_at_low_current_trips_stuck():
    clock = Clock()
    nav_module.time = clock
    try:
        node = nav_module.Node()
        node.mode, node.speed, node.speed_changed_at, node.ground_speed = "driving", -0.22, clock.now - 1.0, 0.0
        trips = []

        async def trip(fault, **details):
            trips.append((round(clock.now - 1000.0, 2), fault))

        node.trip = trip
        loop = asyncio.new_event_loop()
        for _ in range(200):
            node.pose_at = clock.now
            loop.run_until_complete(node.on_roboclaw(roboclaw_message(0.6)))
            clock.now += 0.02
        loop.close()
        assert trips and trips[0][1] == "stuck" and trips[0][0] < 3.0
    finally:
        nav_module.time = __import__("time")


def pose_message(x: float, session: str) -> SimpleNamespace:
    orientation = [0.0, 0.0, 0.0, 1.0]
    translation = [x, 0.137, 0.0]
    odom = {"translation": translation, "orientation": orientation, "session": session}
    return SimpleNamespace(data=json.dumps({"translation": translation, "orientation": orientation, "odom": odom}).encode())


def test_a_camera_restart_mid_mission_stops_instead_of_driving_in_the_new_odometry_frame():
    clock = Clock()
    nav_module.time = clock
    try:
        node = nav_module.Node()

        async def capture(subject, payload):
            pass

        node.publish_json = capture
        loop = asyncio.new_event_loop()
        loop.run_until_complete(node.on_pose(pose_message(3.0, "before")))
        loop.run_until_complete(node.on_mission(SimpleNamespace(data=json.dumps({"id": "m", "steps": [{"type": "goto", "x": 3.0, "z": -2.0}]}).encode())))
        node.remembered.append((clock.now, np.array([[3.0, -0.5]])))
        clock.now += 0.05
        loop.run_until_complete(node.on_pose(pose_message(0.0, "after")))
        loop.close()
        assert node.mode == "fault" and node.fault == "odometry reset"
        assert not node.remembered
    finally:
        nav_module.time = __import__("time")
