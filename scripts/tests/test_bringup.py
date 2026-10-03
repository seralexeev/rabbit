import asyncio
import io
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bringup


class FakeBus:
    def __init__(self):
        self.published = []

    async def publish(self, subject, payload):
        self.published.append((subject, payload))


def quiet_report():
    return bringup.Report(command="test", out=io.StringIO())


def test_motion_needs_the_explicit_flag():
    with pytest.raises(SystemExit):
        bringup.parse_args(["motion"])
    assert bringup.parse_args(["motion", "--motion", "--tests", "wall"]).tests == ["wall"]


def test_deploy_refuses_forge_services_before_the_cutover():
    with pytest.raises(SystemExit):
        bringup.parse_args(["deploy", "--services", "rabbit-nav,forge-chat"])
    assert bringup.parse_args(["deploy", "--services", "forge", "--forge"]).services == ["forge"]
    assert bringup.parse_args(["deploy"]).services == list(bringup.DEPLOY_SERVICES)


def test_the_simulator_only_runs_checks_and_motion_on_its_own_nats():
    assert bringup.parse_args(["motion", "--motion", "--sim"]).nats == bringup.SIM_NATS
    assert bringup.parse_args(["check"]).nats == bringup.ROBOT_NATS
    with pytest.raises(SystemExit):
        bringup.parse_args(["deploy", "--sim"])


def test_the_report_groups_results_by_phase_and_keeps_table_cells_intact(tmp_path):
    report = quiet_report()
    report.add("check", "rate a|b", bringup.PASS, "10.0 Hz")
    report.add("check", "dry run", bringup.FAIL, "would mask cups\nwould pin snapd")
    report.add("diet", "apply", bringup.SKIP, "pass --apply")
    path = report.write(tmp_path)
    text = path.read_text()
    assert path.name.endswith(".md") and "1 passed, 1 failed, 1 skipped." in text
    assert "| FAIL | dry run | would mask cups<br>would pin snapd |" in text
    assert "rate a\\|b" in text and text.index("## check") < text.index("## diet")
    assert report.failed() == 1


def test_rates_and_clock_floors():
    received = {"a": [{}] * 50, "b": [{}] * 4}
    assert [(s, ok) for s, ok, _ in bringup.rates(received, 5.0, {"a": 10.0, "b": 1.0})] == [("a", True), ("b", False)]
    assert bringup.pinned_clocks([1728000] * 6, [1020000000])[0]
    assert not bringup.pinned_clocks([1728000, 729600], [1020000000])[0]
    assert not bringup.pinned_clocks([], [])[0]


def test_tracking_error_is_the_distance_to_the_planned_path():
    path = [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 2.0, 1.57]]
    assert bringup.distance_to_path(1.0, 0.1, path) == pytest.approx(0.1)
    assert bringup.distance_to_path(2.3, 1.0, path) == pytest.approx(0.3)
    assert bringup.distance_to_path(1.0, 1.0, []) is None


def test_the_guard_stops_on_a_close_obstacle_while_driving_or_a_silent_nav():
    guard = bringup.MotionGuard()
    now = 100.0
    assert guard.problem({"mode": "driving", "free_distance": 0.05}, now, now).startswith("free distance 0.05")
    assert guard.problem({"mode": "blocked", "free_distance": 0.05}, now, now) is None
    assert guard.problem({"mode": "driving", "free_distance": 0.4}, now, now) is None
    assert "no rabbit.nav.state" in guard.problem({"mode": "driving"}, now - 3.0, now)
    assert "no rabbit.nav.state" in guard.problem({}, None, now)


def test_a_motion_test_always_ends_with_cancel_and_a_zero_drive():
    bus = FakeBus()
    latest = bringup.Latest()
    latest.update("rabbit.nav.state", {"mode": "driving", "free_distance": 0.05}, time.monotonic())

    async def start():
        await bus.publish("rabbit.nav.mission", {"id": "m"})

    outcome = asyncio.run(bringup.drive_test(bus, latest, start, lambda _: None, 5.0, bringup.MotionGuard()))

    assert outcome.startswith("aborted: free distance")
    assert [subject for subject, _ in bus.published] == ["rabbit.nav.mission", "rabbit.nav.cancel", "rabbit.cmd.drive"]
    assert bus.published[-1][1]["speed"] == 0.0


def test_a_failing_start_still_cancels():
    bus = FakeBus()

    async def start():
        raise RuntimeError("planner refused")

    with pytest.raises(RuntimeError):
        asyncio.run(bringup.drive_test(bus, bringup.Latest(), start, lambda _: None, 5.0, bringup.MotionGuard()))
    assert [subject for subject, _ in bus.published] == ["rabbit.nav.cancel", "rabbit.cmd.drive"]


def test_motion_does_nothing_without_the_operator_typing_floor(monkeypatch):
    args = bringup.parse_args(["motion", "--motion", "--nats", "nats://127.0.0.1:1"])
    report = quiet_report()
    monkeypatch.setattr(bringup, "Bus", lambda url: pytest.fail("connected to NATS without confirmation"))
    asyncio.run(bringup.motion(args, report, bringup.Runner("none"), ask=lambda prompt: "yes"))
    assert [(r.name, r.status) for r in report.results] == [("operator confirmation", bringup.SKIP)]


def test_the_obstacle_ahead_comes_from_the_corridor_reading_or_the_central_scan_bins():
    assert bringup.ahead_distance({"ahead": {"distance": 0.8}, "scan": {}}) == 0.8
    scan = {"angle_min_deg": -60.0, "angle_step_deg": 2.5, "ranges": [0.5] * 20 + [1.4, 1.3, 1.2, 1.25] + [None] * 24}
    assert bringup.ahead_distance({"ahead": None, "scan": scan}) == 1.2
    assert bringup.ahead_distance({"ahead": None, "scan": {**scan, "ranges": [None] * 48}}) is None


def test_the_clickhouse_export_is_valid_shell_with_the_cutoff_in_the_query():
    import subprocess

    command = bringup.clickhouse_export("/root/rabbit/data/export x", "2026-10-03 01:43:53.505")
    assert subprocess.run(["bash", "-n", "-c", command], check=False).returncode == 0
    assert "toDateTime64('2026-10-03 01:43:53.505', 9, 'UTC')" in command and "'/root/rabbit/data/export x'" in command
