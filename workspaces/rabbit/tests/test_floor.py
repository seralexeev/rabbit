import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.floor import FloorEstimator
from lib.geometry import CAMERA_HEIGHT

TABLE = 0.69


def test_lifting_the_robot_onto_a_table_keeps_the_room_floor():
    floor = FloorEstimator()
    for _ in range(100):
        floor.update(0.0, CAMERA_HEIGHT, 0.0)
    for _ in range(500):
        floor.update(0.0, TABLE + CAMERA_HEIGHT, 0.0)
    assert floor.floor_y == pytest.approx(0.0, abs=0.01)


def test_starting_on_a_table_assumes_the_world_floor():
    floor = FloorEstimator()
    for _ in range(500):
        floor.update(0.0, TABLE + CAMERA_HEIGHT, 0.0)
    assert floor.floor_y == 0.0


def test_driving_a_metre_on_a_new_level_adopts_it_as_the_floor():
    floor = FloorEstimator()
    floor.update(0.0, CAMERA_HEIGHT, 0.0)
    for step in range(1, 120):
        floor.update(step * 0.01, CAMERA_HEIGHT - 0.4, 0.0)
    assert floor.floor_y == pytest.approx(-0.4)


def test_slow_drift_is_followed():
    floor = FloorEstimator()
    for step in range(2000):
        floor.update(0.0, CAMERA_HEIGHT + step * 0.00005, 0.0)
    assert floor.floor_y == pytest.approx(0.1, abs=0.01)
