import dataclasses
import hashlib
import importlib.metadata
import json
import logging
import math
import numbers
import os
import platform
import re
import resource
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

SRC = Path(__file__).resolve().parents[1]
ROOT = SRC.parent
EVENT_SUBJECT = "rabbit.log.{node}.event"
METRICS_SUBJECT = "rabbit.metrics.{node}"
ID_FIELDS = ("mission_id", "trip_id", "exploration_id", "odom_session", "map_id", "map_session")
SEVERITIES = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR, "critical": logging.CRITICAL}
EVENTS_PER_S = 20.0
EVENT_BURST = 100.0
MAX_QUEUED_EVENTS = 2000
MAX_CONFIG_VALUE = 2000
PACKAGES = ("numpy", "numba", "nats-py", "pydantic", "opencv-python", "opencv-python-headless", "jetson-stats", "docker", "smbus2", "pyserial")
ENV_PREFIXES = ("SIM_", "LOC_", "USE_", "ROBOCLAW_", "INA_", "RABBIT_", "WIFI_", "NATS_URL")
SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def event_subject(node: str) -> str:
    return EVENT_SUBJECT.format(node=node)


def metrics_subject(node: str) -> str:
    return METRICS_SUBJECT.format(node=node)


def boot_id() -> str:
    if value := os.environ.get("RABBIT_BOOT_ID"):
        return value
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def code_hash() -> str:
    digest = hashlib.sha1()
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(str(path.relative_to(SRC)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def git_revision() -> str:
    try:
        return (ROOT / "REVISION").read_text().strip()
    except OSError:
        pass
    try:
        result = subprocess.run(["git", "-C", str(ROOT), "describe", "--always", "--dirty"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def versions() -> dict[str, str]:
    found = {"python": platform.python_version()}
    for package in PACKAGES:
        try:
            found[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    return found


def environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key.startswith(ENV_PREFIXES) and not any(word in key for word in SECRET_WORDS)
    }


def constant(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return json.dumps(value)
    if isinstance(value, (tuple, list)) and len(value) <= 32 and all(isinstance(item, (bool, int, float, str)) for item in value):
        return json.dumps(list(value))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return repr(value)[:MAX_CONFIG_VALUE]
    return None


def module_constants(prefix: str, namespace: dict[str, Any]) -> dict[str, str]:
    found = {}
    for key, value in namespace.items():
        if not key.isupper() or "SUBJECT" in key:
            continue
        text = constant(value)
        if text is not None:
            found[f"{prefix}.{key}"] = text
    return found


def config_snapshot(node: object, name: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for module_name, module in list(sys.modules.items()):
        if module is None:
            continue
        if module_name == "__main__":
            found.update(module_constants(name, vars(module)))
        elif module_name.startswith(("lib.", "node.")) and module_name != "lib.observability":
            found.update(module_constants(module_name.removeprefix("lib."), vars(module)))
    for cls in reversed(type(node).__mro__):
        if cls is not object:
            found.update(module_constants(f"{name}.{cls.__name__}", vars(cls)))
    return found


def start_snapshot(node: object, name: str) -> dict[str, Any]:
    return {
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "code_hash": code_hash(),
        "git_rev": git_revision(),
        "versions": versions(),
        "env": environment(),
        "config": config_snapshot(node, name),
    }


def split_fields(fields: dict[str, Any]) -> tuple[dict[str, float], dict[str, str]]:
    values: dict[str, float] = {}
    labels: dict[str, str] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            values[key] = float(value)
        elif isinstance(value, numbers.Real):
            number = float(value)
            if math.isfinite(number):
                values[key] = round(number, 6)
        elif isinstance(value, str):
            labels[key] = value
        else:
            labels[key] = json.dumps(value, default=str)
    return values, labels


class EventLimiter:
    def __init__(self, rate: float = EVENTS_PER_S, burst: float = EVENT_BURST, clock: Callable[[], float] = time.monotonic):
        self.rate = rate
        self.burst = burst
        self.clock = clock
        self.tokens = burst
        self.refilled = clock()
        self.last: dict[str, float] = {}
        self.pending: dict[str, int] = {}
        self.suppressed = 0
        self.dropped = 0
        self.lock = threading.Lock()

    def admit(self, key: str, every_s: float = 0.0) -> int | None:
        with self.lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.refilled) * self.rate)
            self.refilled = now
            if every_s > 0 and now - self.last.get(key, -math.inf) < every_s:
                self.pending[key] = self.pending.get(key, 0) + 1
                self.suppressed += 1
                return None
            if self.tokens < 1.0:
                self.dropped += 1
                return None
            self.tokens -= 1.0
            if every_s > 0:
                self.last[key] = now
            return self.pending.pop(key, 0)


class MetricWindow:
    def __init__(self):
        self.lock = threading.Lock()
        self.stats: dict[str, list[float]] = {}

    def observe(self, name: str, value: float) -> None:
        if not math.isfinite(value):
            return
        with self.lock:
            stat = self.stats.get(name)
            if stat is None:
                self.stats[name] = [1.0, value, value]
            else:
                stat[0] += 1.0
                stat[1] += value
                stat[2] = max(stat[2], value)

    def drain(self) -> dict[str, float]:
        with self.lock:
            stats, self.stats = self.stats, {}
        values = {}
        for name, (count, total, peak) in stats.items():
            values[f"{name}_max"] = round(peak, 3)
            values[f"{name}_mean"] = round(total / count, 3)
            values[f"{name}_count"] = count
        return values


def process_stats() -> dict[str, float]:
    try:
        status = Path("/proc/self/status").read_text()
        rss = re.search(r"VmRSS:\s+(\d+)", status)
        threads = re.search(r"Threads:\s+(\d+)", status)
        if rss is not None and threads is not None:
            return {"rss_bytes": int(rss.group(1)) * 1024, "threads": int(threads.group(1))}
    except OSError:
        pass
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"rss_bytes": peak if sys.platform == "darwin" else peak * 1024, "threads": threading.active_count()}
