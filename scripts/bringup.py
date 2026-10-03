#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["nats-py"]
# ///
"""Bring-up and verification of the robot after it was off (docs/roadmap.md, "When the robot is back on").

  uv run scripts/bringup.py check
  uv run scripts/bringup.py deploy [--services rabbit-nav,rabbit-zed]
  uv run scripts/bringup.py diet [--apply]
  uv run scripts/bringup.py forge-cutover [--switch]
  uv run scripts/bringup.py motion --motion [--tests wall,restart,trip,explore]
  uv run scripts/bringup.py loc-shadow [--minutes 10]
  uv run scripts/bringup.py motion --motion --sim        (against scripts/sim.sh)

Every check prints PASS, FAIL or SKIP with its evidence; the report goes to data/bringup/<UTC time>.md.
"""

import argparse
import asyncio
import itertools
import json
import math
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import nats
from nats.errors import Error as NatsError

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "data" / "bringup"
REMOTE = "/root/rabbit/workspaces"
ROBOT_NATS = "nats://192.168.1.53:4222"
SIM_NATS = "nats://127.0.0.1:14222"

PHASES = ("check", "deploy", "diet", "forge-cutover", "motion", "loc-shadow")
MOTION_TESTS = ("wall", "restart", "trip", "explore")
DEPLOY_SERVICES = ("rabbit-zed", "rabbit-nav", "rabbit-planner", "rabbit-explore", "rabbit-roboclaw", "rabbit-telemetry", "rabbit-web")
FORGE_SERVICES = ("forge", "forge-writer", "forge-chat", "forge-clickhouse")
CONTAINERS = (
    "nats",
    "rabbit-zed",
    "rabbit-nav",
    "rabbit-planner",
    "rabbit-explore",
    "rabbit-roboclaw",
    "rabbit-steering",
    "rabbit-ina",
    "rabbit-telemetry",
    "rabbit-web",
    "tunnel",
)
RATES = {
    "rabbit.zed.pose": 10.0,
    "rabbit.zed.obstacle": 3.0,
    "rabbit.zed.imu": 20.0,
    "rabbit.roboclaw": 30.0,
    "rabbit.nav.state": 5.0,
}
SIM_RATES = {**RATES, "rabbit.zed.imu": 10.0, "rabbit.roboclaw": 5.0}
PINNED_CPU_KHZ = 1728000
PINNED_GPU_HZ = 1020000000
MIN_AVAILABLE_MB = 700
MIN_FREE_DISK_GB = 20
FORGE_T0 = "2026-10-03 01:43:53.505"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class Result:
    phase: str
    name: str
    status: str
    evidence: str


@dataclass
class Report:
    command: str
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    results: list[Result] = field(default_factory=list)
    out: object = sys.stdout

    def add(self, phase: str, name: str, status: str, evidence: str = "") -> Result:
        result = Result(phase, name, status, evidence.strip())
        self.results.append(result)
        print(f"{status:4}  {phase:13} {name}: {result.evidence.splitlines()[0] if result.evidence else ''}", file=self.out, flush=True)
        return result

    def check(self, phase: str, name: str, ok: bool, evidence: str = "") -> bool:
        self.add(phase, name, PASS if ok else FAIL, evidence)
        return ok

    def failed(self) -> int:
        return sum(result.status == FAIL for result in self.results)

    def markdown(self) -> str:
        counts = {status: sum(result.status == status for result in self.results) for status in (PASS, FAIL, SKIP)}
        lines = [
            f"# Bring-up {self.started.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"`{self.command}`",
            "",
            f"{counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped.",
        ]
        for phase in dict.fromkeys(result.phase for result in self.results):
            lines += ["", f"## {phase}", "", "| Result | Check | Evidence |", "|---|---|---|"]
            for result in (r for r in self.results if r.phase == phase):
                name, evidence = (text.replace("|", "\\|").replace("\n", "<br>") for text in (result.name, result.evidence))
                lines.append(f"| {result.status} | {name} | {evidence} |")
        return "\n".join(lines) + "\n"

    def write(self, directory: Path = REPORT_DIR) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.started.strftime('%Y%m%d-%H%M%S')}.md"
        path.write_text(self.markdown())
        return path


class Runner:
    """Shell commands on the robot over ssh, and locally."""

    def __init__(self, host: str):
        self.host = host

    def remote(self, command: str, timeout: float = 60.0) -> tuple[int, str]:
        return self.local(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", self.host, command], timeout)

    def local(self, argv: list[str], timeout: float = 600.0) -> tuple[int, str]:
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=ROOT, check=False)
        except subprocess.TimeoutExpired:
            return 124, f"timed out after {timeout:.0f} s"
        return done.returncode, (done.stdout + done.stderr).strip()

    def copy(self, source: Path, target: str) -> tuple[int, str]:
        return self.local(["scp", "-q", "-o", "BatchMode=yes", str(source), f"{self.host}:{target}"], 60.0)


class Bus:
    """The robot NATS: JSON messages in and out."""

    def __init__(self, url: str):
        self.url = url
        self.nc = None

    async def __aenter__(self):
        self.nc = await nats.connect(self.url, connect_timeout=5, max_reconnect_attempts=3)
        return self

    async def __aexit__(self, *_):
        await self.nc.drain()

    async def publish(self, subject: str, payload: dict):
        await self.nc.publish(subject, json.dumps(payload).encode())
        await self.nc.flush()

    async def request(self, subject: str, payload: dict, timeout: float = 8.0) -> dict:
        reply = await self.nc.request(subject, json.dumps(payload).encode(), timeout=timeout)
        return json.loads(reply.data)

    async def collect(self, subjects: list[str], seconds: float) -> dict[str, list]:
        received: dict[str, list] = {subject: [] for subject in subjects}
        subscriptions = []
        for subject in subjects:

            async def handler(msg, subject=subject):
                try:
                    received[subject].append(json.loads(msg.data))
                except ValueError:
                    received[subject].append(None)

            subscriptions.append(await self.nc.subscribe(subject, cb=handler))
        await asyncio.sleep(seconds)
        for subscription in subscriptions:
            await subscription.unsubscribe()
        return received

    async def watch(self, subjects: list[str]) -> "Latest":
        latest = Latest()
        for subject in subjects:

            async def handler(msg, subject=subject):
                try:
                    latest.update(subject, json.loads(msg.data), time.monotonic())
                except ValueError:
                    pass

            await self.nc.subscribe(subject, cb=handler)
        return latest


@dataclass
class Latest:
    messages: dict[str, dict] = field(default_factory=dict)
    received_at: dict[str, float] = field(default_factory=dict)
    history: dict[str, list] = field(default_factory=dict)

    def update(self, subject: str, payload: dict, now: float):
        self.messages[subject] = payload
        self.received_at[subject] = now
        self.history.setdefault(subject, []).append(payload)

    def get(self, subject: str) -> dict:
        return self.messages.get(subject) or {}


def rates(received: dict[str, list], seconds: float, minimums: dict[str, float]) -> list[tuple[str, bool, str]]:
    out = []
    for subject, minimum in minimums.items():
        rate = len(received.get(subject, [])) / seconds
        out.append((subject, rate >= minimum, f"{rate:.1f} Hz (need {minimum:g})"))
    return out


def pinned_clocks(cpu_min_khz: list[int], gpu_min_hz: list[int]) -> tuple[bool, str]:
    cpu_ok = bool(cpu_min_khz) and all(v == PINNED_CPU_KHZ for v in cpu_min_khz)
    gpu_ok = bool(gpu_min_hz) and all(v == PINNED_GPU_HZ for v in gpu_min_hz)
    return cpu_ok and gpu_ok, f"CPU scaling_min {sorted(set(cpu_min_khz))} kHz, GPU min_freq {sorted(set(gpu_min_hz))} Hz"


def distance_to_path(x: float, z: float, path: list) -> float | None:
    """Distance from a point to the polyline of planner path points ([x, z, ...])."""
    points = [(float(p[0]), float(p[1])) for p in path if len(p) >= 2]
    if not points:
        return None
    if len(points) == 1:
        return math.hypot(x - points[0][0], z - points[0][1])
    best = math.inf
    for (ax, az), (bx, bz) in itertools.pairwise(points):
        dx, dz = bx - ax, bz - az
        length = dx * dx + dz * dz
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / length))
        best = min(best, math.hypot(x - ax - t * dx, z - az - t * dz))
    return best


def ahead_distance(obstacle: dict, half_width_deg: float = 8.0) -> float | None:
    """Nearest obstacle straight ahead: the camera's corridor reading, else the scan bins within the given bearing."""
    ahead = obstacle.get("ahead")
    if ahead and ahead.get("distance") is not None:
        return float(ahead["distance"])
    scan = obstacle.get("scan") or {}
    start, step = scan.get("angle_min_deg"), scan.get("angle_step_deg")
    if start is None or step is None:
        return None
    near = [r for i, r in enumerate(scan.get("ranges") or []) if r is not None and abs(start + (i + 0.5) * step) <= half_width_deg]
    return min(near) if near else None


@dataclass
class MotionGuard:
    """Stops a motion test when nav lets the robot get too close while driving, or when nav goes silent."""

    min_free_m: float = 0.1
    stale_s: float = 2.0

    def problem(self, nav_state: dict, received_at: float | None, now: float) -> str | None:
        if received_at is None or now - received_at > self.stale_s:
            return "no rabbit.nav.state for more than 2 s"
        free = nav_state.get("free_distance")
        if nav_state.get("mode") in ("driving", "maneuvering") and free is not None and free < self.min_free_m:
            return f"free distance {free:.2f} m while {nav_state.get('mode')}"
        return None


def confirm_on_floor(ask=input) -> bool:
    print("Motion tests drive the robot. It must be on the floor with about 2 m of free space around it, and someone near it.")
    return ask("Type 'floor' to confirm the robot is on the floor and motion is fine: ").strip().lower() == "floor"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("phases", nargs="+", choices=PHASES)
    parser.add_argument("--host", default="rabbit", help="ssh host of the robot")
    parser.add_argument("--nats", default=None, help=f"NATS URL (default {ROBOT_NATS}, or {SIM_NATS} with --sim)")
    parser.add_argument("--sim", action="store_true", help="run against scripts/sim.sh: no ssh, simulated camera restart")
    parser.add_argument("--services", default=",".join(DEPLOY_SERVICES), help="services for deploy")
    parser.add_argument("--forge", action="store_true", help="allow forge services in deploy (after the cutover)")
    parser.add_argument("--apply", action="store_true", help="diet: apply instead of the dry run")
    parser.add_argument("--switch", action="store_true", help="forge-cutover: go on past the switch")
    parser.add_argument("--cutoff", default=FORGE_T0, help="forge-cutover: ClickHouse rows before this UTC time are imported")
    parser.add_argument("--motion", action="store_true", help="required for the motion phase")
    parser.add_argument("--tests", default=",".join(MOTION_TESTS), help="motion tests to run")
    parser.add_argument("--minutes", type=float, default=10.0, help="loc-shadow: how long to watch")
    parser.add_argument("--rate-seconds", type=float, default=5.0, help="check: how long to count NATS messages")
    args = parser.parse_args(argv)
    args.nats = args.nats or (SIM_NATS if args.sim else ROBOT_NATS)
    args.services = [s for s in args.services.split(",") if s]
    args.tests = [t for t in args.tests.split(",") if t]
    if "motion" in args.phases and not args.motion:
        parser.error("the motion phase needs --motion")
    unknown = [t for t in args.tests if t not in MOTION_TESTS]
    if unknown:
        parser.error(f"unknown motion tests: {', '.join(unknown)}")
    forge = [s for s in args.services if s in FORGE_SERVICES or s.startswith("forge")]
    if "deploy" in args.phases and forge and not args.forge:
        parser.error(f"refusing to deploy {', '.join(forge)} before the Forge cutover (pass --forge after it)")
    if args.sim and set(args.phases) - {"motion", "check"}:
        parser.error("--sim supports only the check and motion phases")
    return args


async def check(args, report: Report, runner: Runner):
    phase = "check"
    if args.sim:
        report.add(phase, "robot over ssh", SKIP, "--sim")
    else:
        code, out = runner.remote("hostname && uptime -p", 20)
        if not report.check(phase, "robot reachable over ssh", code == 0, out):
            return
        code, out = runner.remote("docker ps -a --format '{{.Names}}\t{{.Status}}'")
        status = dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)
        for name in CONTAINERS:
            state = status.get(name, "missing")
            report.check(phase, f"container {name}", state.startswith("Up") and "unhealthy" not in state and "Restarting" not in state, state)
        code, out = runner.remote("cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_min_freq; echo --; cat /sys/class/devfreq/*gpu*/min_freq")
        cpu, _, gpu = out.partition("--")
        ok, evidence = pinned_clocks([int(v) for v in cpu.split()], [int(v) for v in gpu.split()])
        report.check(phase, "clocks pinned by jetson_clocks", code == 0 and ok, evidence)
        code, out = runner.remote("test -f /etc/systemd/system/nvpmodel.service.d/rabbit.conf && systemctl is-active rabbit-performance")
        report.check(phase, "nvpmodel drop-in and rabbit-performance", code == 0, out or "drop-in missing")
        code, out = runner.remote("awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; df -BG --output=avail / | tail -1")
        memory, disk = (out.split() + ["0", "0G"])[:2]
        report.check(phase, "RAM available", int(memory) >= MIN_AVAILABLE_MB, f"{memory} MB (need {MIN_AVAILABLE_MB})")
        report.check(phase, "disk free", int(disk.rstrip("G")) >= MIN_FREE_DISK_GB, f"{disk} on /")
    try:
        async with Bus(args.nats) as bus:
            await bus.publish("rabbit.zed.wake", {"seconds": 30, "source": "bringup"})
            await asyncio.sleep(2.0)
            received = await bus.collect([*RATES, "rabbit.health.zed", "rabbit.telemetry"], args.rate_seconds)
    except (OSError, TimeoutError, NatsError) as e:
        report.add(phase, "NATS", FAIL, f"{args.nats}: {e}")
        return
    for subject, ok, evidence in rates(received, args.rate_seconds, SIM_RATES if args.sim else RATES):
        report.check(phase, f"rate {subject}", ok, evidence)
    health = (received["rabbit.health.zed"] or [None])[-1] or {}
    report.check(
        phase,
        "ZED health",
        bool(health) and health.get("last_pose_state") == "OK" and float(health.get("current_fps") or 0) > 5,
        f"fps {health.get('current_fps')}, pose {health.get('last_pose_state')}, relocalizing {health.get('relocalizing')}, "
        f"tracking {health.get('tracking_fusion_status')}, odom_rejected {health.get('odom_rejected')}, held_poses {health.get('held_poses')}"
        if health
        else "no rabbit.health.zed",
    )
    telemetry = (received["rabbit.telemetry"] or [None])[-1] or {}
    wifi = telemetry.get("wifi") or {}
    if args.sim:
        report.add(phase, "Wi-Fi link", SKIP, "--sim")
    else:
        signal, rtt = wifi.get("signal_dbm"), wifi.get("gateway_rtt_ms")
        report.check(
            phase,
            "Wi-Fi link",
            bool(wifi.get("connected")) and signal is not None and signal > -72 and rtt is not None and rtt < 50,
            f"{wifi.get('ssid')} {signal} dBm, router ping {rtt} ms, tx {wifi.get('tx_bitrate_mbps')} Mbit/s",
        )


def deploy(args, report: Report, runner: Runner):
    phase = "deploy"
    code, out = runner.local(["scripts/deploy.sh", *args.services], 1800)
    if not report.check(phase, f"scripts/deploy.sh {' '.join(args.services)}", code == 0, out[-1500:]):
        return
    status: dict[str, str] = {}
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        code, out = runner.remote("docker ps --format '{{.Names}}\t{{.Status}}'")
        status = dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)
        if all(status.get(s, "").startswith("Up") and "second" not in status.get(s, "") for s in args.services if s != "rabbit-web"):
            break
        time.sleep(5)
    for service in args.services:
        state = status.get(service, "missing")
        code, logs = runner.remote(f"docker logs --since 3m {shlex.quote(service)} 2>&1 | grep -c Traceback")
        tracebacks = int(logs.split()[-1]) if logs.split() and logs.split()[-1].isdigit() else -1
        report.check(phase, f"{service} running", state.startswith("Up") and tracebacks == 0, f"{state}; tracebacks in the last 3 min: {tracebacks}")
        if service.startswith("rabbit-") and service != "rabbit-web":
            module = service.removeprefix("rabbit-")
            code, out = runner.remote(
                f"docker exec {shlex.quote(service)} sh -c 'cd /rabbit && PYTHONPATH=src:$PYTHONPATH .venv/bin/python -c \"import node.{module}\"'",
                120,
            )
            report.check(phase, f"{service} imports node.{module}", code == 0, out[-500:] or "ok")
    if "rabbit-zed" in args.services:
        code, out = runner.remote(
            'docker exec rabbit-zed sh -c "cd /rabbit && uv run -q --with pytest python -m pytest tests/test_nvblox_mapper.py -q"', 600
        )
        report.check(phase, "nvblox tests in rabbit-zed", code == 0, out[-800:])


def diet(args, report: Report, runner: Runner):
    phase = "diet"
    code, out = runner.copy(ROOT / "workspaces/jetson/diet.sh", "/root/diet.sh")
    if not report.check(phase, "copy diet.sh", code == 0, out or "/root/diet.sh"):
        return
    code, out = runner.remote("bash /root/diet.sh --dry-run", 120)
    pending = [line for line in out.splitlines() if line.startswith(("would", "warn"))]
    report.check(phase, "dry run", code == 0, "\n".join(pending) or out[-1000:])
    if not args.apply:
        report.add(phase, "apply", SKIP, "pass --apply to make these changes")
        return
    code, out = runner.remote("bash /root/diet.sh", 900)
    changes = [line for line in out.splitlines() if line.startswith(("change", "warn", "Mem:"))]
    report.check(phase, "applied", code == 0, "\n".join(changes) or out[-1500:])
    code, out = runner.remote("bash /root/diet.sh --dry-run | tail -1", 120)
    report.check(phase, "idempotent", code == 0 and "0 change(s) pending" in out, out)


def clickhouse_export(directory: str, cutoff: str) -> str:
    """Shell for the robot: every forge MergeTree table as <table>.parquet with the rows before `cutoff`."""
    url = "http://127.0.0.1:18123/?user=forge_writer&password=forge_writer&database=forge&output_format_parquet_compression_method=zstd&max_threads=1"
    tables = "SELECT name FROM system.tables WHERE database = 'forge' AND engine LIKE '%MergeTree' ORDER BY name FORMAT TSV"
    return (
        f"set -e; mkdir -p {shlex.quote(directory)}; "
        f"for t in $(curl -sS --fail {shlex.quote(url)} --data-binary {shlex.quote(tables)}); do "
        'col=ts; [ "$t" = run_events ] && col=at; '
        f"echo \"SELECT * FROM $t WHERE $col < toDateTime64('{cutoff}', 9, 'UTC') ORDER BY run_id, $col FORMAT Parquet\" "
        f"| nice -n 19 curl -sS --fail {shlex.quote(url)} --data-binary @- > {shlex.quote(directory)}/$t.parquet; "
        f'echo "$t $(wc -c < {shlex.quote(directory)}/$t.parquet) bytes"; done'
    )


def forge_cutover(args, report: Report, runner: Runner):
    phase = "forge-cutover"
    code, out = runner.remote(
        "docker logs forge-shadow 2>&1 | grep -ci 'unfinished\\|Removed' ; "
        "find /var/lib/docker/volumes/workspaces_forge-data/_data -name '*.tmp' | wc -l"
    )
    report.check(phase, "shadow store after the power cuts", code == 0 and out.split()[-1:] == ["0"], f"recoveries logged / tmp files: {out.split()}")
    code, out = runner.remote(
        f"cd {REMOTE} && docker cp forge/evals forge-chat:/app/evals && mkdir -p /root/rabbit/data && "
        "docker exec forge-chat node src/cli.ts eval > /root/rabbit/data/eval-before.json 2>/dev/null; "
        "python3 -c \"import json; d=json.JSONDecoder().raw_decode(open('/root/rabbit/data/eval-before.json').read())[0]; "
        "print(d['passed'], d['cases'], d['check_pass_rate'])\"",
        2400,
    )
    report.check(phase, "eval before (old code, ClickHouse)", code == 0, f"passed / cases / check rate: {out}")
    export = f"/root/rabbit/data/clickhouse-export-{args.cutoff[:10]}"
    code, out = runner.remote(clickhouse_export(export, args.cutoff), 1800)
    if not report.check(phase, f"ClickHouse export before {args.cutoff}", code == 0, out[-1200:]):
        return
    code, out = runner.remote(
        "docker run --rm --network none --memory 768m --cpus 1 -e FORGE_DATA_DIR=/app/data -v workspaces_forge-data:/app/data "
        f"-v {REMOTE}/forge-next/src:/app/src:ro -v {REMOTE}/forge-next/slabs:/app/slabs:ro -v {REMOTE}/forge-next/graph:/app/graph:ro "
        f"-v {export}:/export:ro --entrypoint nice forge:chdb -n 19 node --liftoff-only src/cli.ts import /export --before {shlex.quote(args.cutoff)}",
        3600,
    )
    if not report.check(phase, "history imported into the Parquet store", code == 0, out[-1200:]):
        return
    if not args.switch:
        report.add(phase, "switch", SKIP, "stopped before the switch; pass --switch to go on (runbook steps 3-10)")
        return
    patch = ROOT / "docs/reports/2026-10-03-forge-cutover-compose.patch"
    code, out = runner.local(["git", "apply", "--check", str(patch)], 30)
    if not report.check(phase, "compose patch applies", code == 0, out or str(patch)):
        return
    steps = [
        ("tag images", "docker tag forge:latest forge:alpine-clickhouse && docker tag forge:chdb forge:latest"),
        ("stop forge-shadow", "docker stop -t 45 forge-shadow && docker rm forge-shadow"),
    ]
    for name, command in steps:
        code, out = runner.remote(command, 120)
        if not report.check(phase, name, code == 0, out):
            return
    code, out = runner.local(["git", "apply", str(patch)], 30)
    if code == 0:
        for path, old, new in (
            ("scripts/deploy.sh", "^(rabbit-|forge-writer|forge-chat)", "^(rabbit-|forge$)"),
            ("workspaces/web/nginx.conf", "http://forge-chat:18080", "http://forge:18080"),
        ):
            file = ROOT / path
            file.write_text(file.read_text().replace(old, new))
    if not report.check(phase, "compose, deploy.sh and nginx.conf switched in the tree", code == 0, out):
        return
    code, out = runner.local(["scripts/deploy.sh", "forge"], 900)
    if not report.check(phase, "deploy forge", code == 0, out[-1500:]):
        return
    for name, command, timeout in (
        ("old log consumer removed", "docker run --rm --network workspaces_default bitnami/natscli consumer rm LOGS forge-writer -f --server nats://nats:4222", 120),
        ("eval after", f"cd {REMOTE} && docker cp forge/evals forge:/app/evals && docker exec forge node --liftoff-only src/cli.ts eval > /root/rabbit/data/eval-after.json 2>/dev/null; tail -c 300 /root/rabbit/data/eval-after.json", 2400),
        ("parity on the robot", f"docker exec forge node --liftoff-only src/cli.ts parity http://forge-clickhouse:8123 --before {shlex.quote(args.cutoff)} --limit 14 | head -c 600", 3600),
        ("bench on the robot", "docker exec forge node --liftoff-only src/cli.ts bench | head -c 1500", 900),
    ):
        code, out = runner.remote(command, timeout)
        report.check(phase, name, code == 0, out)


async def drive_test(bus: Bus, latest: Latest, start, until, timeout_s: float, guard: MotionGuard) -> str:
    """Starts a motion, waits until `until(latest)` returns an outcome, and always cancels at the end."""
    outcome = "timeout"
    try:
        await start()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            problem = guard.problem(latest.get("rabbit.nav.state"), latest.received_at.get("rabbit.nav.state"), time.monotonic())
            if problem is not None:
                outcome = f"aborted: {problem}"
                break
            result = until(latest)
            if result is not None:
                outcome = result
                break
    finally:
        await bus.publish("rabbit.nav.cancel", {"source": "bringup"})
        await bus.publish("rabbit.cmd.drive", {"speed": 0.0, "steer": 0.0, "source": "bringup"})
    return outcome


async def motion(args, report: Report, runner: Runner, ask=input):
    phase = "motion"
    if not confirm_on_floor(ask):
        report.add(phase, "operator confirmation", SKIP, "the robot was not confirmed on the floor")
        return
    guard = MotionGuard()
    async with Bus(args.nats) as bus:
        latest = await bus.watch(["rabbit.nav.state", "rabbit.zed.pose", "rabbit.zed.obstacle", "rabbit.planner.state", "rabbit.explore.state"])
        await bus.publish("rabbit.zed.wake", {"seconds": 300, "source": "bringup"})
        await asyncio.sleep(3.0)
        if guard.problem(latest.get("rabbit.nav.state"), latest.received_at.get("rabbit.nav.state"), time.monotonic()):
            report.add(phase, "nav", FAIL, "no rabbit.nav.state: is rabbit-nav running?")
            return
        for test in args.tests:
            await asyncio.sleep(1.0)
            await MOTION[test](bus, latest, report, runner, guard, args)


async def wall_test(bus, latest, report, runner, guard, args):
    ahead = ahead_distance(latest.get("rabbit.zed.obstacle"))
    if ahead is None or ahead > 1.8:
        report.add("motion", "creep to a wall", SKIP, f"face a wall 0.5-1.8 m ahead first (ahead distance {ahead})")
        return
    mission = f"bringup-wall-{int(time.time())}"

    async def start():
        await bus.publish("rabbit.nav.mission", {"id": mission, "source": "bringup", "steps": [{"type": "move", "forward": round(ahead + 0.3, 2), "right": 0}]})

    def until(latest):
        state = latest.get("rabbit.nav.state")
        if state.get("mission_id") == mission and state.get("mode") in ("blocked", "arrived", "fault"):
            return state.get("mode")
        return None

    outcome = await drive_test(bus, latest, start, until, 40.0, guard)
    await asyncio.sleep(0.5)
    state = latest.get("rabbit.nav.state")
    remaining = ahead_distance(latest.get("rabbit.zed.obstacle"))
    free = state.get("free_distance")
    report.check(
        "motion",
        "creep to a wall stops 0.15-0.2 m short",
        outcome in ("blocked", "arrived") and free is not None and 0.13 <= free <= 0.22,
        f"outcome {outcome}, free distance {free} m, obstacle ahead {remaining} m, fault {state.get('fault')!r}",
    )


async def restart_test(bus, latest, report, runner, guard, args):
    mission = f"bringup-restart-{int(time.time())}"

    async def start():
        await bus.publish("rabbit.nav.mission", {"id": mission, "source": "bringup", "steps": [{"type": "move", "forward": 1.0, "right": 0}]})
        await asyncio.sleep(1.0)
        if args.sim:
            await bus.request("rabbit.sim.restart", {})
        else:
            await asyncio.to_thread(runner.remote, "docker restart -t 10 rabbit-zed", 60)

    def until(latest):
        state = latest.get("rabbit.nav.state")
        fault = state.get("fault") or ""
        return fault if state.get("mission_id") == mission and "odometry reset" in fault else None

    outcome = await drive_test(bus, latest, start, until, 60.0, MotionGuard(stale_s=30.0))
    report.check("motion", "camera restart during a mission ends it with odometry reset", "odometry reset" in outcome, f"outcome {outcome!r}")


async def trip_test(bus, latest, report, runner, guard, args):
    pose = latest.get("rabbit.zed.pose")
    translation = pose.get("translation")
    orientation = pose.get("orientation")
    if not translation or not orientation:
        report.add("motion", "2 m trip", SKIP, "no pose")
        return
    qx, qy, qz, qw = orientation
    fx, fz = -2 * (qx * qz + qy * qw), -(1 - 2 * (qx * qx + qy * qy))
    norm = math.hypot(fx, fz) or 1.0
    target = {"x": round(translation[0] + 2.0 * fx / norm, 2), "z": round(translation[2] + 2.0 * fz / norm, 2)}
    errors: list[float] = []
    trip: dict = {}

    async def start():
        reply = await bus.request("rabbit.planner.goal", {**target, "source": "bringup"}, 10.0)
        trip.update(reply)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error"))

    def until(latest):
        state = latest.get("rabbit.planner.state")
        nav = latest.get("rabbit.nav.state")
        position = latest.get("rabbit.zed.pose").get("translation")
        if state.get("trip_id") == trip.get("trip_id") and nav.get("mode") == "driving" and position and state.get("path"):
            error = distance_to_path(position[0], position[2], state["path"])
            if error is not None:
                errors.append(error)
        if state.get("trip_id") == trip.get("trip_id") and state.get("phase") in ("arrived", "failed", "cancelled"):
            return state.get("phase")
        return None

    try:
        outcome = await drive_test(bus, latest, start, until, 90.0, guard)
    except (RuntimeError, TimeoutError, NatsError) as e:
        report.add("motion", "2 m trip", FAIL, f"planner refused or did not answer: {e}")
        return
    state = latest.get("rabbit.planner.state")
    errors.sort()
    summary = f"median {errors[len(errors) // 2]:.3f} m, max {errors[-1]:.3f} m over {len(errors)} samples" if errors else "no samples"
    report.check(
        "motion",
        "2 m trip with the new tracker",
        outcome == "arrived" and bool(errors) and errors[-1] < 0.25,
        f"outcome {outcome}, tracking error {summary}, replans {state.get('replans')}, recoveries {state.get('recoveries')}, {state.get('message')!r}",
    )


async def explore_test(bus, latest, report, runner, guard, args):
    modes: list[str] = []
    faults: list[str] = []
    before = latest.get("rabbit.explore.state").get("exploration_id")

    async def start():
        await bus.publish("rabbit.nav.explore", {"max_duration_s": 60, "max_distance_m": 10, "source": "bringup"})

    def until(latest):
        nav = latest.get("rabbit.nav.state")
        if not modes or modes[-1] != nav.get("mode"):
            modes.append(nav.get("mode"))
        if nav.get("fault") and (not faults or faults[-1] != nav.get("fault")):
            faults.append(nav.get("fault"))
        state = latest.get("rabbit.explore.state")
        fresh = state.get("exploration_id") not in (None, before)
        return state.get("phase") if fresh and state.get("phase") in ("done", "failed") else None

    outcome = await drive_test(bus, latest, start, until, 75.0, guard)
    state = latest.get("rabbit.explore.state")
    blocked = modes.count("blocked")
    stuck = sum("stuck" in fault for fault in faults)
    report.check(
        "motion",
        "60 s exploration",
        not outcome.startswith("aborted") and (state.get("travelled_m") or 0) > 0.5 and stuck == 0,
        f"outcome {outcome}, travelled {state.get('travelled_m')} m, frontiers {state.get('frontiers')}, failed frontiers {state.get('failed_frontiers')}, "
        f"blocked {blocked} times, stuck {stuck}, faults {faults}, {state.get('message')!r}",
    )


MOTION = {"wall": wall_test, "restart": restart_test, "trip": trip_test, "explore": explore_test}


async def loc_shadow(args, report: Report, runner: Runner):
    phase = "loc-shadow"
    code, out = runner.remote("docker image inspect rabbit-loc --format '{{.Created}}'")
    if not report.check(phase, "rabbit-loc image on the robot", code == 0, out if code == 0 else "build it off the robot (docker/Dockerfile.loc) and docker load it"):
        return
    code, out = runner.remote(f"cd {REMOTE} && docker compose --profile loc up -d rabbit-loc && docker exec rabbit-zed printenv LOC_MODE || true", 180)
    report.check(phase, "rabbit-loc started (zed in shadow)", code == 0 and "apply" not in out, out[-600:])
    async with Bus(args.nats) as bus:
        received = await bus.collect(["rabbit.loc.map_odom", "rabbit.health.loc"], args.minutes * 60)
    states = [m for m in received["rabbit.loc.map_odom"] if m]
    counts = {status: sum(m.get("status") == status for m in states) for status in ("relocalizing", "localized", "lost")}
    last = states[-1] if states else {}
    report.check(
        phase,
        f"map_odom over {args.minutes:g} min",
        bool(states) and counts["localized"] > 0,
        f"{len(states)} messages, {counts}, last: mode {last.get('mode')}, matches {last.get('matches')}, corrections {last.get('corrections')}, "
        f"pending {last.get('pending')}, map {last.get('map_id')}, translation {last.get('translation')}",
    )


async def run(args, report: Report, runner: Runner, ask=input):
    for phase in args.phases:
        if phase == "check":
            await check(args, report, runner)
        elif phase == "deploy":
            await asyncio.to_thread(deploy, args, report, runner)
        elif phase == "diet":
            await asyncio.to_thread(diet, args, report, runner)
        elif phase == "forge-cutover":
            await asyncio.to_thread(forge_cutover, args, report, runner)
        elif phase == "motion":
            await motion(args, report, runner, ask)
        elif phase == "loc-shadow":
            await loc_shadow(args, report, runner)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = Report(command="scripts/bringup.py " + " ".join(argv))
    try:
        asyncio.run(run(args, report, Runner(args.host)))
    except KeyboardInterrupt:
        report.add("bringup", "interrupted", FAIL, "Ctrl-C")
    path = report.write()
    print(f"report: {path.relative_to(ROOT)}")
    return 1 if report.failed() else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
