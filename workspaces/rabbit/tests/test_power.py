import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.drive import duty_limit
from lib.ina4235 import SHUNT_LSB_V, calibrate, channel_calibrations, is_clipped, minimum_current_lsb, shunt_cal


def ina_current(amps: float, true_ohms: float, cal) -> float:
    shunt_raw = round(amps * true_ohms / SHUNT_LSB_V)
    return (shunt_raw * cal.shunt_cal // 2048) * cal.current_lsb_a


def test_shunt_cal_matches_the_datasheet_design_example():
    assert minimum_current_lsb(10.0) == pytest.approx(305.17578e-6)
    assert shunt_cal(500e-6, 0.008) == 1280


def test_the_default_10_mohm_shunt_keeps_the_calibration_written_since_october():
    cal = calibrate(0.01)
    assert (cal.current_lsb_a, cal.shunt_cal) == (0.001, 512)
    assert cal.full_scale_a == pytest.approx(8.192)


@pytest.mark.parametrize("ohms, max_current", [(0.002, None), (0.005, None), (0.01, None), (0.1, None), (0.002, 15.0), (0.008, 10.0)])
def test_each_shunt_gets_an_lsb_the_datasheet_allows_and_reads_its_own_current(ohms, max_current):
    cal = calibrate(ohms, max_current)
    minimum = minimum_current_lsb(cal.max_current_a)
    assert minimum <= cal.current_lsb_a < 8 * minimum
    assert cal.shunt_cal == round(0.00512 / (cal.current_lsb_a * ohms))
    for amps in (0.05, 1.0, 0.8 * cal.max_current_a):
        assert ina_current(amps, ohms, cal) == pytest.approx(amps, abs=2 * cal.current_lsb_a + amps * 1e-3)


def test_a_2_mohm_battery_shunt_read_with_the_old_10_mohm_calibration_is_five_times_low():
    assert ina_current(5.0, 0.002, calibrate(0.01)) == pytest.approx(1.0, abs=0.002)
    assert ina_current(5.0, 0.002, calibrate(0.002)) == pytest.approx(5.0, abs=0.004)


def test_shunts_are_configured_per_channel_and_unknown_channels_are_refused():
    cals = channel_calibrations({1: "battery", 2: "rail_6v"}, "1=0.002", None)
    assert cals[1].shunt_ohms == 0.002 and cals[2].shunt_ohms == 0.01
    with pytest.raises(ValueError):
        channel_calibrations({1: "battery", 2: "rail_6v"}, "3=0.005", None)


def test_the_7_64_a_peak_against_the_8_19_a_range_is_flagged_as_clipped():
    shunt_raw = lambda amps: round(amps * 0.01 / SHUNT_LSB_V)
    assert is_clipped(shunt_raw(7.64), 7640)
    assert is_clipped(-shunt_raw(7.64), -7640)
    assert not is_clipped(shunt_raw(7.0), 7000)


def test_a_current_register_near_overflow_is_clipped_even_below_the_shunt_range():
    assert is_clipped(round(30.0 * 0.002 / SHUNT_LSB_V), 30000)


def test_motors_on_the_12_v_buck_keep_full_duty():
    assert duty_limit([11.9, 11.3, 12.0]) == 1.0


def test_motors_on_a_full_4s_pack_never_see_more_than_12_v():
    assert duty_limit([16.8]) == pytest.approx(0.714, abs=1e-3)
    assert duty_limit([16.8, 15.9]) == pytest.approx(12 / 16.8)
    assert duty_limit([14.0]) == pytest.approx(12 / 14.0)


def test_before_a_valid_supply_reading_the_cap_assumes_a_full_pack():
    assert duty_limit([]) == pytest.approx(12 / 16.8)
    assert duty_limit([0.0, 99.9]) == pytest.approx(12 / 16.8)
    assert duty_limit([0.0, 16.0]) == pytest.approx(12 / 16.0)
