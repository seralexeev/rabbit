import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib import hardware
from lib.drive import METRES_PER_SECOND_PER_DUTY
from lib.safety_loop import ROBOCLAW_ESTOP_FLAG, SafetyConfig, SafetyLoop, speed_for_clearance, stopping_distance

DT = 0.02
CRUISE = 0.35
REVERSE_15_CM_S = -0.15 / METRES_PER_SECOND_PER_DUTY


def wall_behind(gap: float) -> np.ndarray:
    return np.stack([np.full(31, -0.072 - gap), np.linspace(-0.3, 0.3, 31)], axis=1)


def wall_ahead(gap: float) -> np.ndarray:
    return np.stack([np.full(31, 0.2452 + gap), np.linspace(-0.3, 0.3, 31)], axis=1)


class Rig:
    def __init__(self, **config):
        self.loop = SafetyLoop(SafetyConfig(**config))
        self.now = 100.0
        self.lidar = np.empty((0, 2))
        self.silent: set[str] = set()
        self.battery_v = 15.8
        self.battery_a = 1.0
        self.roboclaw_status: int | None = None
        self.decision = None

    def tick(self, command: dict | None = None, joy: dict | None = None):
        loop, now = self.loop, self.now
        if "roboclaw" not in self.silent:
            status = self.roboclaw_status if self.roboclaw_status is not None else (0 if loop.line else ROBOCLAW_ESTOP_FLAG)
            loop.on_roboclaw({"left": {"pwm": 0.0}, "right": {"pwm": 0.0}, "status": status}, now)
        if "ina" not in self.silent:
            loop.on_ina({"channels": [{"name": "battery", "voltage": self.battery_v, "current": self.battery_a}]}, now)
        if "brain" not in self.silent:
            loop.on_brain(now)
        if "lidar" not in self.silent:
            loop.on_lidar(self.lidar, now)
        for sensor in ("FL", "FR", "RL", "RR"):
            if f"tof_{sensor}" not in self.silent:
                loop.on_tof(sensor, np.empty((0, 2)), now)
        if command is not None:
            loop.on_drive(command, now)
        if joy is not None:
            loop.on_joy(joy, now)
        self.decision = loop.step(now)
        self.now += DT
        return self.decision

    def run(self, seconds: float, command: dict | None = None, joy: dict | None = None):
        for _ in range(round(seconds / DT)):
            self.tick(command, joy)
        return self.decision

    def ready(self):
        self.run(1.5)
        assert self.loop.self_test == "passed" and self.decision.line
        self.loop.drain()
        return self


def drive(speed: float, source: str = "nav", steer: float = 0.0) -> dict:
    return {"speed": speed, "steer": steer, "source": source}


def joystick(throttle: float, steer: float = 0.0) -> dict:
    return {"buttons": {"r2": {"value": max(throttle, 0.0)}, "l2": {"value": max(-throttle, 0.0)}}, "sticks": {"left": {"x": steer}}}


def names(rig: Rig) -> list[str]:
    return [name for name, *_ in rig.loop.drain()]


def test_the_line_stays_low_until_inputs_are_fresh_and_the_estop_wiring_is_proven():
    rig = Rig()
    rig.silent = {"lidar"}
    assert not rig.run(1.0).line and rig.loop.self_test == "waiting"
    rig.silent = set()
    rig.run(1.0)
    assert rig.decision.line and rig.loop.self_test == "passed"
    assert "safety.self_test" in names(rig)


def test_a_roboclaw_that_never_reports_estop_is_an_estop_line_fault_and_never_drives():
    rig = Rig()
    rig.roboclaw_status = 0
    decision = rig.run(5.0, drive(CRUISE))
    assert rig.loop.self_test == "failed" and not decision.line and decision.speed == 0.0
    assert decision.mode == "estop" and "estop_line_fault" in decision.reasons
    [(name, reason, severity, *_)] = [event for event in rig.loop.drain() if event[0] == "safety.self_test"]
    assert severity == "critical" and reason.startswith("estop_line_fault")


def test_stopping_distance_formula_matches_the_design_table():
    config = SafetyConfig()
    assert [round(stopping_distance(v, config), 2) for v in (0.16, 0.30, 0.50)] == [0.10, 0.17, 0.30]
    assert speed_for_clearance(stopping_distance(0.3, config), config) == pytest.approx(0.3)
    assert speed_for_clearance(0.04, config) == 0.0


def test_reversing_into_a_wall_slows_down_and_stops_between_5_and_12_cm():
    rig = Rig().ready()
    gap = 0.6
    for _ in range(round(10.0 / DT)):
        rig.lidar = wall_behind(gap)
        decision = rig.tick(drive(REVERSE_15_CM_S, source="forge"))
        gap += decision.speed * METRES_PER_SECOND_PER_DUTY * DT
    assert 0.05 <= gap <= 0.12
    assert decision.speed == 0.0 and decision.mode == "stopped" and decision.reason.startswith("obstacle behind")
    events = rig.loop.drain()
    assert any(name == "safety.limit" and reason.startswith("obstacle behind") for name, reason, *_ in events)
    assert rig.tick(drive(CRUISE, source="forge")).speed == CRUISE


def test_a_stale_lidar_caps_both_directions_to_10_cm_s():
    rig = Rig().ready()
    rig.silent = {"lidar"}
    decision = rig.run(0.5, drive(CRUISE))
    assert decision.speed == pytest.approx(0.1 / METRES_PER_SECOND_PER_DUTY) and decision.reason == "lidar stale"
    assert rig.tick(drive(-CRUISE)).speed == pytest.approx(-0.1 / METRES_PER_SECOND_PER_DUTY)
    assert "safety.input_stale" in names(rig)


def test_a_stale_tof_lets_the_robot_crawl_toward_it_only_while_the_lidar_is_fresh():
    rig = Rig().ready()
    rig.silent = {"tof_FL"}
    decision = rig.run(0.5, drive(CRUISE))
    assert decision.speed == pytest.approx(0.08 / METRES_PER_SECOND_PER_DUTY) and decision.reason == "tof FL stale"
    assert rig.tick(drive(-CRUISE)).speed == -CRUISE
    rig.silent = {"tof_RL", "lidar"}
    rig.run(0.5, drive(-CRUISE))
    assert rig.tick(drive(-CRUISE)).speed == 0.0
    assert rig.tick(drive(CRUISE)).speed == pytest.approx(0.1 / METRES_PER_SECOND_PER_DUTY)


def test_a_bumper_stops_at_once_holds_its_side_and_allows_half_a_metre_of_crawling_away():
    rig = Rig().ready()
    rig.run(0.2, drive(-CRUISE))
    rig.loop.on_bumper("rear", True, rig.now)
    assert rig.tick(drive(-CRUISE)).speed == 0.0
    assert rig.tick(drive(CRUISE)).speed == pytest.approx(0.1 / METRES_PER_SECOND_PER_DUTY)
    rig.run(4.0, drive(CRUISE))
    assert rig.decision.speed > 0
    rig.run(1.5, drive(CRUISE))
    assert rig.decision.speed == 0.0 and rig.decision.reason.startswith("crawled 0.5 m")
    rig.loop.on_bumper("rear", False, rig.now)
    assert rig.tick(drive(-CRUISE)).speed == 0.0
    rig.run(1.1, drive(CRUISE))
    assert rig.tick(drive(-CRUISE)).speed == -CRUISE
    assert names(rig).count("safety.bump") == 1


def test_a_silent_brain_rejects_nav_commands_but_the_joystick_still_drives():
    rig = Rig().ready()
    rig.silent = {"brain"}
    decision = rig.run(0.7, drive(CRUISE, source="nav"))
    assert decision.speed == 0.0 and "brain lost" in decision.reasons and decision.source == "nav rejected"
    assert rig.tick(drive(CRUISE, source="forge")).speed == CRUISE
    assert rig.run(0.1, joy=joystick(0.6)).speed == pytest.approx(0.3)
    assert "safety.brain_lost" in names(rig)


def test_a_stale_command_stops_the_motors():
    rig = Rig().ready()
    assert rig.tick(drive(CRUISE)).speed == CRUISE
    assert rig.run(0.25).speed == CRUISE
    assert rig.run(0.1).speed == 0.0 and rig.decision.source == "none"


def test_the_joystick_owns_the_motors_for_a_second_and_is_limited_like_nav():
    rig = Rig().ready()
    rig.lidar = wall_behind(0.05)
    assert rig.tick(joy=joystick(-0.8)).speed == 0.0
    assert rig.decision.source == "joystick" and rig.decision.reason.startswith("obstacle behind")
    assert rig.tick(drive(CRUISE)).speed == 0.0
    rig.run(1.1, joy=joystick(0.0))
    assert rig.tick(drive(CRUISE)).speed == CRUISE


def test_silent_roboclaw_telemetry_drops_the_estop_line_until_a_second_of_fresh_idle_telemetry():
    rig = Rig().ready()
    rig.silent = {"roboclaw"}
    decision = rig.run(0.4, drive(CRUISE))
    assert not decision.line and decision.mode == "estop" and decision.speed == 0.0 and "roboclaw lost" in decision.reasons
    rig.silent = set()
    rig.run(0.8, drive(CRUISE))
    assert not rig.decision.line
    rig.run(0.4, drive(CRUISE))
    assert rig.decision.line and rig.decision.speed == CRUISE
    assert {"safety.roboclaw_lost", "safety.roboclaw_ready"} <= set(names(rig))


def test_silent_ina_caps_speed_and_overcurrent_drops_the_line_for_two_seconds():
    rig = Rig().ready()
    rig.silent = {"ina"}
    assert rig.run(1.1, drive(CRUISE)).speed == pytest.approx(0.1 / METRES_PER_SECOND_PER_DUTY)
    rig.silent = set()
    rig.battery_a = 13.5
    assert not rig.tick(drive(CRUISE)).line
    rig.battery_a = 2.0
    assert not rig.run(1.9, drive(CRUISE)).line
    assert rig.run(0.2, drive(CRUISE)).line
    assert "safety.overcurrent" in names(rig)


def test_a_low_battery_halves_speed_and_a_critical_one_stops():
    rig = Rig().ready()
    rig.battery_v = 13.1
    decision = rig.run(5.5, drive(CRUISE))
    assert decision.speed == pytest.approx(CRUISE / 2) and decision.reason == "battery low"
    rig.battery_v = 12.7
    assert rig.run(9.0, drive(CRUISE)).speed > 0
    assert rig.run(1.5, drive(CRUISE)).speed == 0.0 and rig.decision.reason == "battery critical"
    assert {"safety.battery_low", "safety.battery_critical"} <= set(names(rig))


def test_a_software_estop_latches_until_reset_and_power_shutdown_holds_the_line_low():
    rig = Rig().ready()
    rig.loop.on_estop({"source": "hud"}, rig.now)
    assert not rig.run(2.0, drive(CRUISE)).line and rig.decision.reason == "estop by hud"
    rig.loop.on_reset({"source": "hud"}, rig.now)
    assert rig.tick(drive(CRUISE)).line and rig.decision.speed == CRUISE
    rig.loop.on_power("stopping", rig.now)
    assert not rig.tick(drive(CRUISE)).line and rig.decision.reason == "power stopping"


def test_shadow_mode_never_drives_the_line_but_reports_what_it_would_do():
    rig = Rig(shadow=True)
    rig.lidar = wall_ahead(0.05)
    decision = rig.run(1.5, drive(CRUISE))
    assert rig.loop.self_test == "skipped" and not decision.line and decision.speed == 0.0
    assert decision.reason.startswith("obstacle ahead")


def test_kernel_gpio_output_persistence_is_detected(tmp_path, monkeypatch):
    parameter = tmp_path / "persist_gpio_outputs"
    monkeypatch.setattr(hardware, "PERSIST_PARAMETER", parameter)
    parameter.write_text("Y\n")
    assert hardware.PiGpio.outputs_persist(object())
    parameter.write_text("N\n")
    assert not hardware.PiGpio.outputs_persist(object())
