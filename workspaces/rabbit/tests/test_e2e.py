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
