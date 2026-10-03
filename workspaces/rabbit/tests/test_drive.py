import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.drive import slew


def ramp(start: float, target: float, seconds: float) -> float:
    value = start
    for _ in range(round(seconds / 0.02)):
        value = slew(value, target, 0.02, accel=1.5, decel=5.0)
    return value


def test_a_burst_of_full_throttle_after_a_wifi_gap_ramps_up_instead_of_jerking():
    assert ramp(0.0, 0.5, 0.1) == pytest.approx(0.15)
    assert ramp(0.0, 0.5, 0.4) == pytest.approx(0.5)


def test_stopping_and_reversing_brake_at_the_fast_rate():
    assert ramp(0.5, 0.0, 0.1) == pytest.approx(0.0)
    assert ramp(0.5, -0.5, 0.1) == pytest.approx(0.0)
