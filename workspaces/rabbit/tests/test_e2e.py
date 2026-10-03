import asyncio
import json
import math
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import nats
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.spatial_map import decode_chunks

ROOT = Path(__file__).resolve().parents[3]
PORT = 0
pytestmark = pytest.mark.skipif(os.environ.get("RABBIT_E2E") != "1", reason="end-to-end over NATS: set RABBIT_E2E=1 (scripts/sim.sh, ~3 min)")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextmanager
def stack(tmp_path: Path, **env: str):
    global PORT
    PORT = free_port()
    environment = {**os.environ, "SIM_RUN_DIR": str(tmp_path), "SIM_NATS_PORT": str(PORT), "SIM_WS_PORT": str(free_port()), **env}
    subprocess.run([ROOT / "scripts/sim.sh", "start"], env=environment, check=True, stdout=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 120.0
        while "Planner ready" not in (tmp_path / "planner.log").read_text() or "initialized" not in (tmp_path / "explore.log").read_text():
            assert time.monotonic() < deadline, "the simulated stack did not come up"
            time.sleep(0.5)
        time.sleep(3.0)
        yield
    finally:
        subprocess.run([ROOT / "scripts/sim.sh", "stop"], env=environment, check=False, stdout=subprocess.DEVNULL)


class Bus:
    def __init__(self, nc):
        self.nc = nc
        self.latest: dict[str, dict] = {}

    @classmethod
    async def connect(cls) -> "Bus":
        bus = cls(await nats.connect(f"nats://127.0.0.1:{PORT}"))
        for subject in ("rabbit.nav.state", "rabbit.planner.state", "rabbit.explore.state", "rabbit.health.zed", "rabbit.telemetry"):
            await bus.nc.subscribe(subject, cb=bus.remember)
        return bus

    async def remember(self, msg) -> None:
        self.latest[msg.subject] = json.loads(msg.data)

    async def request(self, subject: str, payload: dict | None = None) -> dict:
        return json.loads((await self.nc.request(subject, json.dumps(payload or {}).encode(), timeout=10)).data)

    async def until(self, subject: str, check, seconds: float) -> dict:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            state = self.latest.get(subject, {})
            if state and check(state):
                return state
            await asyncio.sleep(0.2)
        raise AssertionError(f"{subject} never matched; last state {self.latest.get(subject)}")


def run(scenario) -> None:
    async def main():
        bus = await Bus.connect()
        try:
            await scenario(bus)
        finally:
            await bus.nc.close()

    asyncio.run(main())


def test_exploration_over_nats_maps_the_apartment(tmp_path):
    async def scenario(bus: Bus):
        start = await bus.request("rabbit.sim.state")
        await bus.nc.publish("rabbit.nav.explore", json.dumps({"source": "e2e", "max_duration_s": 60, "max_distance_m": 20}).encode())
        await bus.until("rabbit.explore.state", lambda s: s.get("phase") == "done", 90.0)
        end = await bus.request("rabbit.sim.state")
        assert end["coverage"] >= max(0.45, start["coverage"] + 0.2) and end["contacts"] == 0
        chunks = decode_chunks((await bus.nc.request("rabbit.map.snapshot", b"", timeout=10)).data)
        assert len(chunks) > 50 and sum(len(vertices) for vertices, _ in chunks.values()) > 1000
        health = await bus.until("rabbit.health.zed", lambda s: s.get("map_chunks", 0) > 0, 3.0)
        assert health["map_bytes"] > 0 and bus.latest["rabbit.telemetry"]["wifi"]["connected"]

    with stack(tmp_path):
        run(scenario)


def test_planner_trip_cancel_and_camera_restart_over_nats(tmp_path):
    async def scenario(bus: Bus):
        fridge = {"label": "refrigerator", "x": 1.0, "z": 5.5, "width": 0.7, "length": 0.9}
        reply = await bus.request("rabbit.planner.goal", {"id": "e2e-fridge", "source": "e2e", "object": fridge})
        assert reply["ok"]
        await bus.until("rabbit.planner.state", lambda s: s.get("trip_id") == "e2e-fridge" and s.get("phase") == "arrived", 150.0)
        state = await bus.request("rabbit.sim.state")
        assert math.dist(state["camera"], (1.0, 5.5)) < 1.6 and state["contacts"] == 0

        assert (await bus.request("rabbit.planner.goal", {"id": "e2e-cancel", "source": "e2e", "x": 6.5, "z": 1.5}))["ok"]
        await bus.until("rabbit.nav.state", lambda s: s.get("mode") == "driving" and s.get("mission_id", "").startswith("e2e-cancel"), 20.0)
        await asyncio.sleep(2.0)
        await bus.nc.publish("rabbit.nav.cancel", json.dumps({"source": "e2e"}).encode())
        await bus.until("rabbit.planner.state", lambda s: s.get("trip_id") == "e2e-cancel" and s.get("phase") == "cancelled", 5.0)
        await bus.until("rabbit.nav.state", lambda s: s.get("mode") == "idle", 5.0)
        stopped = await bus.request("rabbit.sim.state")
        await asyncio.sleep(1.5)
        assert math.dist(stopped["camera"], (await bus.request("rabbit.sim.state"))["camera"]) < 0.02

        assert (await bus.request("rabbit.planner.goal", {"id": "e2e-restart", "source": "e2e", "x": 6.5, "z": 1.5}))["ok"]
        await bus.until("rabbit.nav.state", lambda s: s.get("mode") == "driving" and s.get("mission_id", "").startswith("e2e-restart"), 20.0)
        await bus.request("rabbit.sim.restart")
        await bus.until("rabbit.nav.state", lambda s: s.get("fault") == "odometry reset", 5.0)
        await bus.until("rabbit.planner.state", lambda s: s.get("trip_id") == "e2e-restart" and s.get("phase") == "failed", 5.0)

    with stack(tmp_path, SIM_KNOWN_MAP="1"):
        run(scenario)


def test_reversing_into_a_wall_is_stopped_by_the_body_safety_with_each_rear_sensor(tmp_path):
    async def scenario(bus: Bus):
        events: list[dict] = []

        async def remember_event(msg):
            events.append(json.loads(msg.data))

        await bus.nc.subscribe("rabbit.log.safety.event", cb=remember_event)
        pins: list[dict] = []
        commands: list[dict] = []

        async def remember_pins(msg):
            pins.append(json.loads(msg.data))

        async def remember_command(msg):
            commands.append(json.loads(msg.data))

        await bus.nc.subscribe("rabbit.sim.gpio.in", cb=remember_pins)
        await bus.nc.subscribe("rabbit.safety.drive", cb=remember_command)
        for subject in ("rabbit.safety.state", "rabbit.power.state"):
            await bus.nc.subscribe(subject, cb=bus.remember)
        await bus.until("rabbit.safety.state", lambda s: s.get("self_test") == "passed" and s.get("estop_line"), 30.0)
        await bus.until("rabbit.power.state", lambda s: s.get("state") == "running", 10.0)

        async def drive(speed: float, seconds: float) -> list[dict]:
            track = []
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                await bus.nc.publish("rabbit.cmd.drive", json.dumps({"speed": speed, "steer": 0.0, "source": "e2e"}).encode())
                await asyncio.sleep(0.05)
                track.append({**await bus.request("rabbit.sim.state"), "at": time.monotonic()})
            return track

        async def reverse_into(setup: dict) -> tuple[float, dict, list[dict]]:
            events.clear()
            await bus.request("rabbit.sim.setup", setup)
            await asyncio.sleep(1.0)
            track = await drive(-0.32, 8.0)
            return track[-1]["x"], track[0], track

        rear_gap = lambda x, face: x - 0.072 - face
        x, start, track = await reverse_into({"robot": [0.8, 1.5, 90], "lidar": True, "tof": True})
        assert 0.04 <= rear_gap(x, 0.05) <= 0.12 and track[-1]["contacts"] == start["contacts"]
        assert any(e["name"] == "safety.limit" and e["reason"].startswith("obstacle behind") for e in events)
        assert bus.latest["rabbit.safety.state"]["mode"] == "stopped"

        x, start, track = await reverse_into({"robot": [0.8, 1.5, 90], "lidar": False})
        assert 0.04 <= rear_gap(x, 0.05) <= 0.12 and track[-1]["contacts"] == start["contacts"]
        names = [e["name"] for e in events]
        assert "safety.input_stale" in names and any(e["name"] == "safety.limit" and e["reason"] == "lidar stale" for e in events)
        speeds = [abs(b["x"] - a["x"]) / (b["at"] - a["at"]) for a, b in zip(track, track[10:])]
        assert 0.08 < max(speeds) < 0.11

        x, start, track = await reverse_into({"robot": [2.5, 1.5, 90], "lidar": True, "blocks": [[1.95, 1.0, 2.0, 2.0, 0.03]]})
        [bump] = [e for e in events if e["name"] == "safety.bump"]
        pressed = next(p["ts"] for p in pins if p["pins"].get("BUMPER_REAR"))
        zeroed = next(c["ts"] for c in commands if c["ts"] >= pressed and c["speed"] == 0.0)
        assert (zeroed - pressed) * 1e-9 <= 0.05
        assert bump["labels"]["end"] == "rear" and not any(e["reason"].startswith("obstacle behind") for e in events if e["name"] == "safety.limit")
        assert rear_gap(x, 2.0) < 0.01 and abs(track[-1]["x"] - track[-20]["x"]) < 0.002
        assert bus.latest["rabbit.safety.state"]["reason"] == "rear bumper"

        await bus.request("rabbit.sim.setup", {"robot": [2.5, 1.5, 90]})
        await asyncio.sleep(1.0)
        moving = await drive(0.32, 1.5)
        assert moving[-1]["x"] - moving[0]["x"] > 0.1
        safety_pid = int((tmp_path / "safety.pid").read_text())
        subprocess.run(["pkill", "-9", "-P", str(safety_pid)], check=False)
        killed = time.monotonic()
        after = await drive(0.32, 2.0)
        still = [s for s in after if s["at"] - killed > 0.8]
        assert still and abs(still[-1]["x"] - still[0]["x"]) < 0.002

    with stack(tmp_path, SIM_BODY="1"):
        run(scenario)
