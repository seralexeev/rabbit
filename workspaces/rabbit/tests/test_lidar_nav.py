import asyncio
from types import SimpleNamespace

import numpy as np
from sim import Clock, nav_module

from lib.lidar import Mount, encode_scan
from node import planner as planner_module


def wall_behind_scan(clock: Clock, gap_m: float) -> SimpleNamespace:
    angles = np.arange(-30.0, 30.0, 0.72)
    ranges = (Mount().x + 0.07 + gap_m) / np.cos(np.radians(angles))
    ts = clock.time_ns()
    return SimpleNamespace(data=encode_scan(ts - 100_000_000, ts, 1, Mount(), np.round(ranges * 1000), np.round((angles % 360) * 64)))


def standing_nav(clock: Clock):
    node = nav_module.Node()
    node.position, node.forward = np.array([0.0, 0.0]), np.array([1.0, 0.0])
    node.track.append((clock.now - 0.5, node.position, node.forward))
    node.track.append((clock.now, node.position, node.forward))
    node.scan_at = clock.now
    return node


def test_the_lidar_lets_nav_see_a_wall_behind_that_the_camera_cannot():
    clock = Clock()
    nav_module.time = clock
    try:
        loop = asyncio.new_event_loop()
        blind = standing_nav(clock)
        assert blind.govern(-0.22, 0.0) == -0.22 and blind.hold is None

        node = standing_nav(clock)
        loop.run_until_complete(node.on_lidar(wall_behind_scan(clock, 0.1)))
        assert node.govern(-0.22, 0.0) == 0.0 and node.hold == "obstacle behind"
        assert node.free < node.REVERSE_STOP
        assert node.govern(0.25, 0.0) > 0.0

        far = standing_nav(clock)
        loop.run_until_complete(far.on_lidar(wall_behind_scan(clock, 0.6)))
        assert far.govern(-0.22, 0.0) == -0.22

        clock.now += node.LIDAR_TIMEOUT + 0.05
        node.scan_at = clock.now
        assert node.govern(-0.22, 0.0) == -0.22
        loop.close()
    finally:
        nav_module.time = __import__("time")


def test_the_planner_remembers_lidar_hits_in_its_own_obstacle_memory():
    node = planner_module.Node()
    node.pose = {"translation": [0.0, 0.137, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]}
    clock = Clock()
    loop = asyncio.new_event_loop()
    for _ in range(planner_module.Node.LIDAR_EVERY):
        loop.run_until_complete(node.on_lidar(wall_behind_scan(clock, 0.8)))
    loop.close()
    points = node.obstacle_points(__import__("time").monotonic())
    assert len(node.obstacles.points(0.0)) == 0 and len(points) > 10
    rear = np.array([0.06, 0.1845])
    assert np.min(np.linalg.norm(points - (rear + np.array([0.0, 0.07 + 0.8])), axis=1)) < 0.05
