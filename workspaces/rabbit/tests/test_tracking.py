import asyncio
import json
import math
from types import SimpleNamespace

import numpy as np
from sim import Event, Robot, Sim, block, nav_module, room_grid

from lib.geometry import camera_point, curvature_for_steer
from lib.planner import Path, Waypoint, camera_points
from lib.trip import STEER_HEADROOM, Target


def planned_arc(steer: float, start: tuple[float, float]) -> tuple[list[list[float]], np.ndarray, float]:
    radius = 1.0 / abs(curvature_for_steer(steer))
    side = math.copysign(1.0, curvature_for_steer(steer))
    center = np.array([start[0], start[1] + side * radius])
    waypoints = []
    for angle in np.arange(0.0, 3.0, 0.075 / radius):
        rear = center + radius * np.array([math.sin(angle), -side * math.cos(angle)])
        waypoints.append(Waypoint(float(rear[0]), float(rear[1]), float(side * angle), 1))
    return camera_points(Path(waypoints, 0.0, 0.0, 0, 0.0)), center, radius


def test_a_planned_arc_at_the_planning_limit_is_tracked_on_the_rear_axle_without_saturating():
    for steer in (STEER_HEADROOM, -STEER_HEADROOM):
        points, center, radius = planned_arc(steer, (2.0, 4.0))
        sim = Sim(room_grid(8.0, 8.0), room_grid(8.0, 8.0), Robot(2.0, 4.0, 0.0))
        steers = []
        original = sim.advance

        def advance(dt, original=original, sim=sim):
            steers.append(sim.nav.steer)
            original(dt)

        sim.advance = advance
        sim.run_mission([{"type": "path", "points": points}], 20.0)

        settled = np.array([abs(math.hypot(x - center[0], z - center[1]) - radius) for x, z, _ in sim.trajectory[40:-40]])
        assert settled.mean() < 0.01
        assert max(abs(s) for s in steers[40:-40]) < 0.95


def pose_message(x: float, z: float, yaw: float, odom_yaw: float) -> SimpleNamespace:
    def orientation(theta):
        psi = math.atan2(-math.cos(theta), -math.sin(theta))
        return [0.0, math.sin(psi / 2), 0.0, math.cos(psi / 2)]

    pose = {"translation": [x, 0.137, z], "orientation": orientation(yaw), "odom": {"translation": [0.0, 0.137, 0.0], "orientation": orientation(odom_yaw), "session": "s"}}
    return SimpleNamespace(data=json.dumps(pose).encode())


def test_path_headings_are_turned_into_the_odometry_frame_with_the_points():
    clock = Sim(room_grid(2.0, 2.0), room_grid(2.0, 2.0), Robot(1.0, 1.0, 0.0)).clock
    nav_module.time = clock
    try:
        node = nav_module.Node()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(node.on_pose(pose_message(1.0, 1.0, 0.0, math.pi / 2)))
        node.start_mission([{"type": "path", "points": [[1.0 + 0.1 * k, 1.0, 1, 0.0] for k in range(10)]}])
        node.begin_next_step()
        loop.close()

        travel = np.diff(node.path[:, :2], axis=0)[0]
        assert abs(node.path[0, 3] - math.atan2(travel[1], travel[0])) < 1e-6
        rear = node.rear_axle_points()
        assert np.allclose(np.diff(rear, axis=0), np.diff(node.path[:, :2], axis=0), atol=1e-9)
        assert np.allclose(camera_point(rear[0], np.array([math.cos(node.path[0, 3]), math.sin(node.path[0, 3])])), node.path[0, :2], atol=1e-9)
    finally:
        nav_module.time = __import__("time")


def test_at_cruise_speed_a_wall_appearing_just_beyond_the_blind_zone_is_not_touched():
    grid = room_grid(6.0, 2.0)
    sim = Sim(grid.__class__(grid.origin, grid.resolution, grid.width, grid.height, grid.cells.copy()), grid, Robot(0.6, 1.0, 0.0))
    walls = []

    def step_in(s: Sim) -> None:
        wall = float(s.robot.camera()[0]) + 0.32
        block(s.world, wall, 0.0, wall + 0.15, 2.0)
        walls.append(wall)

    sim.events.append(Event(4.0, step_in))
    sim.run(Target("point", 5.0, 1.0), 30.0)

    bumper = max(x for x, _, _ in sim.trajectory) + 0.2245
    assert not sim.collided() and walls[0] - bumper > 0.15
