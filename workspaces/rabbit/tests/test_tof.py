import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib import tof
from lib.planner import OCCUPIED
from lib.simulation import Robot, bumpers, room_grid, tof_frame
from lib.tof_device import FakeTof, zone_order


def open_room():
    world = room_grid(6.0, 6.0)
    return world, np.where(world.cells == OCCUPIED, 1.2, 0.0)


def test_the_floor_seen_by_the_lowest_zones_is_rejected_not_reported_as_an_obstacle():
    world = room_grid(12.0, 12.0)
    heights = np.where(world.cells == OCCUPIED, 1.2, 0.0)
    robot = Robot(6.0, 6.0, 0.0)
    for mount in tof.MOUNTS.values():
        found = tof.classify(mount, *tof_frame(world, heights, robot, mount))
        assert len(found.points) == 0 and found.floor >= 8
    nearest_floor = tof.classify(tof.MOUNTS["FL"], *tof_frame(world, heights, robot, tof.MOUNTS["FL"]))
    assert nearest_floor.valid == nearest_floor.floor


def test_a_wall_30_cm_ahead_becomes_points_in_the_robot_frame_at_the_right_place():
    world, heights = open_room()
    robot = Robot(6.0 - 0.05 - 0.2246 - 0.3, 3.0, 0.0)
    for name in ("FL", "FR"):
        found = tof.classify(tof.MOUNTS[name], *tof_frame(world, heights, robot, tof.MOUNTS[name]))
        assert len(found.points) > 10
        assert found.points[:, 0].min() == pytest.approx(0.2246 + 0.3, abs=0.03)
        assert np.all((found.points[:, 2] >= tof.FLOOR_MARGIN_M) & (found.points[:, 2] <= tof.MAX_HEIGHT_M))
        assert found.nearest_m == pytest.approx(0.3, abs=0.03)
        assert np.sign(found.points[:, 1].mean()) == np.sign(tof.MOUNTS[name].y)
    rear = tof.classify(tof.MOUNTS["RL"], *tof_frame(world, heights, robot, tof.MOUNTS["RL"]))
    assert len(rear.points) == 0


def test_only_valid_ranging_statuses_count():
    distance = [500] * 64
    good = tof.classify(tof.MOUNTS["FL"], distance, [5] * 64)
    assert len(good.points) > 0
    for status in (0, 3, 6, 13, tof.NO_TARGET):
        assert tof.classify(tof.MOUNTS["FL"], distance, [status] * 64).valid == 0
    assert tof.classify(tof.MOUNTS["FL"], [10] * 64, [5] * 64).valid == 0


def test_the_four_mounts_cover_front_and_rear_symmetrically():
    front = tof.base_directions(tof.MOUNTS["FL"])[27]
    rear = tof.base_directions(tof.MOUNTS["RR"])[27]
    assert front[0] > 0.8 and front[1] > 0 and rear[0] < -0.8 and rear[1] < 0
    assert np.degrees(np.arcsin(tof.base_directions(tof.MOUNTS["FL"])[:, 2])).max() == pytest.approx(15 + 3.5 * tof.ZONE_DEG, abs=0.5)


def test_byte_arrays_from_the_driver_are_reordered_per_4_byte_group():
    assert zone_order(list(range(8))) == [3, 2, 1, 0, 7, 6, 5, 4]


def test_the_message_carries_raw_zones_and_filtered_points():
    message = tof.frame_message(tof.MOUNTS["RL"], 3, 123, [800] * 64, [5] * 32 + [255] * 32)
    assert message["sensor"] == "RL" and message["seq"] == 3 and len(message["distance_mm"]) == 64
    assert message["valid"] == 32 and all(len(point) == 3 for point in message["points"])


def test_a_low_threshold_presses_only_the_bumper_it_touches():
    world, heights = open_room()
    robot = Robot(3.0, 3.0, 0.0)
    assert bumpers(world, heights, robot) == {"front": False, "rear": False}
    world.cells[50:70, 58:59] = OCCUPIED
    heights[50:70, 58:59] = 0.03
    robot = Robot(2.95 + 0.07 + 0.005, 3.0, 0.0)
    assert bumpers(world, heights, robot) == {"front": False, "rear": True}
    heights[50:70, 58:59] = 0.015
    assert bumpers(world, heights, robot)["rear"] is False


class Stuck:
    def __init__(self, mount):
        self.mount = mount

    def start(self):
        pass

    def read(self, timeout):
        time.sleep(timeout)
        return None

    def close(self):
        pass


def test_the_tof_node_publishes_frames_and_power_cycles_a_sensor_that_keeps_hanging(monkeypatch):
    monkeypatch.setenv("RABBIT_HW", "fake")
    monkeypatch.setenv("TOF_SENSORS", "FL,RR")
    from node import tof as tof_module

    monkeypatch.setattr(tof_module, "open_tof", lambda mount: Stuck(mount) if mount.name == "RR" else FakeTof(mount))
    monkeypatch.setattr(tof_module.Node, "FRAME_TIMEOUT", 0.1)
    monkeypatch.setattr(tof_module.Node, "RETRY_DELAY", 0.05)
    monkeypatch.setattr(tof_module.Node, "POWER_OFF_S", 0.05)
    node = tof_module.Node()
    toggles = []
    node.gpio.output_listeners.append(lambda name, value, ts: toggles.append((name, value)))
    node.gpio.setup_output("TOF_PWR_OFF", False)
    for sensor in node.sensors.values():
        sensor.thread = tof_module.threading.Thread(target=node.run_sensor, args=(sensor,), daemon=True)
        sensor.thread.start()
    time.sleep(1.0)
    node.stop.set()
    for sensor in node.sensors.values():
        sensor.thread.join(2.0)
    assert node.sensors["FL"].seq >= 10 and node.sensors["FL"].last["sensor"] == "FL"
    assert node.sensors["RR"].seq == 0 and node.sensors["RR"].resets >= 3
    assert node.power_cycles == 1 and toggles.count(("TOF_PWR_OFF", True)) == 1 and toggles[-1] == ("TOF_PWR_OFF", False)
    names = [event["name"] for event in node.event_queue]
    assert "tof.power_cycled" in names and names.count("tof.sensor_ready") >= 2
