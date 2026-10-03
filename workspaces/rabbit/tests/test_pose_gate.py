import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from lib.pose_gate import JumpGate, odometry_step_ok


def gate():
    return JumpGate(jump_m=0.5, max_speed=1.5, settle_s=4.0)


def test_a_millimetre_glitch_near_the_origin_is_dropped_and_the_pose_comes_back():
    jump_gate = gate()
    assert jump_gate.update(0.0, [0.07, 0.0, 0.11])
    assert not any(jump_gate.update(0.2 * i, [70.13, -0.27, 114.38]) for i in range(1, 15))
    assert jump_gate.update(3.0, [0.07, 0.0, 0.11])


def test_a_relocalization_into_the_map_frame_is_accepted_once_it_holds():
    jump_gate = gate()
    assert jump_gate.update(0.0, [0.03, 0.14, -0.12])
    outcomes = [jump_gate.update(0.1 * i, [-2.8, 0.1, -3.33]) for i in range(1, 50)]
    assert not any(outcomes[:39]) and all(outcomes[40:])


def test_driving_at_full_speed_is_not_a_jump():
    jump_gate = gate()
    assert all(jump_gate.update(t / 30, [0.03 * t, 0.0, 0.0]) for t in range(300))


def yaw_step(degrees: float, forward_m: float = 0.0) -> np.ndarray:
    angle = np.radians(degrees)
    step = np.eye(4)
    step[0, 0], step[0, 2], step[2, 0], step[2, 2] = np.cos(angle), np.sin(angle), -np.sin(angle), np.cos(angle)
    step[2, 3] = -forward_m
    return step


def odometry_step(step: np.ndarray) -> bool:
    return odometry_step_ok(step, 1 / 30, max_speed=1.5, max_turn_rate_deg=120.0, slack_m=0.05, slack_deg=2.0)


def test_odometry_takes_a_fast_turn_but_not_a_heading_correction_folded_into_one_frame():
    assert odometry_step(yaw_step(3.0, 0.02))
    assert not odometry_step(yaw_step(15.0))
    assert not odometry_step(yaw_step(0.0, 0.5))
