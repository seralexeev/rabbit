import asyncio
import json
from types import SimpleNamespace

import numpy as np
from sim import Clock, nav_module


def pose(x: float, captured: float) -> SimpleNamespace:
    return SimpleNamespace(data=json.dumps({"ts": int(captured * 1e9), "translation": [x, 0.137, 0.0], "orientation": [0.0, -0.7071068, 0.0, 0.7071068]}).encode())


def ahead_scan(distance: float, captured: float) -> SimpleNamespace:
    ranges = [None] * 48
    ranges[23] = ranges[24] = distance
    return SimpleNamespace(data=json.dumps({"ts": int(captured * 1e9), "scan": {"angle_min_deg": -60.0, "angle_step_deg": 2.5, "ranges": ranges, "blind": False}}).encode())


def drive_past(node, clock: Clock, loop, speed: float, delays: list[float]) -> None:
    for k, delay in enumerate(delays):
        captured = 1000.0 + 0.033 * k
        clock.now = captured + delay
        loop.run_until_complete(node.on_pose(pose(speed * (captured - 1000.0), captured)))


def test_a_scan_is_placed_with_the_pose_from_when_it_was_captured():
    clock = Clock()
    nav_module.time = clock
    try:
        node = nav_module.Node()
        loop = asyncio.new_event_loop()
        drive_past(node, clock, loop, 0.25, [0.047] * 12)
        captured = clock.now - 0.12
        loop.run_until_complete(node.on_obstacle(ahead_scan(1.0, captured)))
        loop.close()

        hit = node.remembered[-1][1].mean(axis=0)
        camera_then = 0.25 * (captured - 1000.0)
        assert abs(hit[0] - (camera_then + 1.0 * np.cos(np.radians(1.25)))) < 0.005
    finally:
        nav_module.time = __import__("time")


def test_ground_speed_comes_from_capture_times_not_delivery_jitter():
    clock = Clock()
    nav_module.time = clock
    try:
        node = nav_module.Node()
        loop = asyncio.new_event_loop()
        delays = [0.037, 0.08, 0.04, 0.078, 0.045, 0.075] * 5
        drive_past(node, clock, loop, 0.12, delays)
        loop.close()

        assert abs(node.ground_speed - 0.12) < 0.01
    finally:
        nav_module.time = __import__("time")
