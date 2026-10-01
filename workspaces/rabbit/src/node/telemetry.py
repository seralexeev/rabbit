import asyncio
import logging
import os
import re
import subprocess
import threading
import time

import docker
from jtop import jtop

from lib.node import RabbitNode

TELEMETRY_SUBJECT = "rabbit.telemetry"
PUBLISH_INTERVAL = 1.0
JTOP_SILENCE_S = 5.0
CONTAINER_STATS_INTERVAL = 10.0

KB = 1024


class ContainerStatsCollector:
    """Collects Docker container stats in a background thread on its own interval."""

    def __init__(self, client: docker.DockerClient):
        self._client = client
        self._stats: list[dict] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._stop = threading.Event()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get(self) -> list[dict]:
        with self._lock:
            return list(self._stats)

    def _loop(self):
        while not self._stop.is_set():
            try:
                results = []
                for c in self._client.containers.list():
                    try:
                        s = c.stats(stream=False)

                        cpu_delta = (
                            s["cpu_stats"]["cpu_usage"]["total_usage"]
                            - s["precpu_stats"]["cpu_usage"]["total_usage"]
                        )
                        sys_delta = (
                            s["cpu_stats"]["system_cpu_usage"]
                            - s["precpu_stats"]["system_cpu_usage"]
                        )
                        ncpus = s["cpu_stats"].get(
                            "online_cpus",
                            len(s["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])),
                        )
                        cpu_pct = (
                            round((cpu_delta / sys_delta) * ncpus * 100, 1)
                            if sys_delta > 0
                            else 0
                        )

                        mem_usage = s["memory_stats"].get("usage", 0)
                        mem_limit = s["memory_stats"].get("limit", 0)
                        mem_cache = s["memory_stats"].get("stats", {}).get("cache", 0)

                        results.append(
                            {
                                "name": c.name,
                                "cpu": cpu_pct,
                                "mem": mem_usage - mem_cache,
                                "mem_limit": mem_limit,
                            }
                        )
                    except Exception:
                        continue

                results.sort(key=lambda x: x["name"])
                with self._lock:
                    self._stats = results
            except Exception:
                pass

            self._stop.wait(CONTAINER_STATS_INTERVAL)


class WifiCollector:
    def __init__(self, interface: str):
        self.interface = interface
        self._stats: dict = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._previous: tuple[float, dict[str, int]] | None = None

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def _run(self, *args: str) -> str:
        return subprocess.run(args, capture_output=True, text=True, timeout=2).stdout

    def _counters(self) -> dict[str, int]:
        root = f"/sys/class/net/{self.interface}/statistics"
        return {
            name: int(open(f"{root}/{name}").read())
            for name in ("tx_bytes", "rx_bytes", "tx_errors", "rx_errors", "tx_dropped", "rx_dropped")
        }

    def _gateway_rtt(self) -> float | None:
        route = re.search(r"default via (\S+)", self._run("ip", "route"))
        if route is None:
            return None
        reply = re.search(r"time=([\d.]+) ms", self._run("ping", "-c", "1", "-W", "1", route.group(1)))
        return float(reply.group(1)) if reply else None

    def _loop(self):
        while not self._stop.is_set():
            try:
                link = self._run("iw", "dev", self.interface, "link")

                def field(pattern: str) -> str | None:
                    match = re.search(pattern, link)
                    return match.group(1) if match else None

                now = time.monotonic()
                counters = self._counters()
                rates = {}
                if self._previous is not None:
                    elapsed = now - self._previous[0]
                    rates = {
                        f"{name}_per_s": round((counters[name] - self._previous[1][name]) / elapsed, 1)
                        for name in counters
                    }
                self._previous = (now, counters)
                signal = field(r"signal: (-?\d+) dBm")
                rx_bitrate = field(r"rx bitrate: ([\d.]+) MBit/s")
                tx_bitrate = field(r"tx bitrate: ([\d.]+) MBit/s")
                frequency = field(r"freq: ([\d.]+)")
                stats = {
                    "connected": "Connected to" in link,
                    "ssid": field(r"SSID: (.+)"),
                    "frequency_mhz": float(frequency) if frequency else None,
                    "signal_dbm": int(signal) if signal else None,
                    "rx_bitrate_mbps": float(rx_bitrate) if rx_bitrate else None,
                    "tx_bitrate_mbps": float(tx_bitrate) if tx_bitrate else None,
                    "gateway_rtt_ms": self._gateway_rtt(),
                    **counters,
                    **rates,
                }
                with self._lock:
                    self._stats = stats
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
            self._stop.wait(1.0)


class ContainerEventWatcher:
    MESSAGES = {
        "start": "Container started",
        "die": "Container exited",
        "kill": "Container killed",
        "oom": "Container ran out of memory",
        "restart": "Container restarted",
    }

    def __init__(self, client: docker.DockerClient):
        self._client = client
        self._logger = logging.getLogger("docker.events")
        self._thread = threading.Thread(target=self._loop, name="docker-events", daemon=True)

    def start(self):
        self._thread.start()

    def _loop(self):
        while True:
            try:
                for event in self._client.events(decode=True, filters={"type": "container"}):
                    self._record(event)
            except Exception:
                self._logger.exception("Docker event stream failed")
            time.sleep(5.0)

    def _record(self, event: dict):
        action = event.get("Action", "")
        attributes = event.get("Actor", {}).get("Attributes", {})
        fields = {"container": attributes.get("name", ""), "action": action, "image": attributes.get("image", "")}
        if action.startswith("health_status"):
            health = action.split(":", 1)[-1].strip()
            level = logging.WARNING if health == "unhealthy" else logging.INFO
            self._logger.log(level, "Container health changed", extra={**fields, "health": health})
            return
        message = self.MESSAGES.get(action)
        if message is None:
            return
        exit_code = attributes.get("exitCode")
        failed = action == "oom" or (action == "die" and exit_code not in (None, "0"))
        extra = fields if exit_code is None else {**fields, "exit_code": exit_code}
        self._logger.log(logging.WARNING if failed else logging.INFO, message, extra=extra)


class Node(RabbitNode):
    def __init__(self):
        super().__init__("telemetry")
        self.jetson = jtop()
        self.jetson_seen_at = time.monotonic()
        self._wifi = WifiCollector(os.environ.get("WIFI_INTERFACE", "wlP1p1s0"))
        self._container_stats = ContainerStatsCollector(docker.DockerClient.from_env())
        self._container_events = ContainerEventWatcher(docker.DockerClient.from_env())

    async def init(self):
        self.jetson.start()
        self._container_stats.start()
        self._container_events.start()
        self._wifi.start()
        self.set_interval(self.publish_telemetry, PUBLISH_INTERVAL)

    async def publish_telemetry(self):
        if not await asyncio.to_thread(self.jetson.ok):
            if time.monotonic() - self.jetson_seen_at > JTOP_SILENCE_S:
                await asyncio.to_thread(self._reconnect_jetson)
            return
        self.jetson_seen_at = time.monotonic()

        j = self.jetson

        # CPU: per-core usage = 100 - idle
        cpu_cores = j.cpu.get("cpu", [])
        cpu_usage = [round(100 - c.get("idle", 100)) for c in cpu_cores]
        cpu_freq = [round(c.get("freq", {}).get("cur", 0) / 1000) for c in cpu_cores]

        # GPU
        gpu_load = 0
        gpu_freq = 0
        try:
            gpu_load = round(j.gpu["gpu"]["status"]["load"])
            gpu_freq = round(j.gpu["gpu"]["freq"]["cur"] / 1000)
        except (KeyError, TypeError):
            pass

        # RAM/SWAP in KB
        try:
            ram = j.memory["RAM"]
            ram_used = ram["used"] * KB
            ram_total = ram["tot"] * KB
        except (KeyError, TypeError):
            ram_used = 0
            ram_total = 0

        try:
            swap = j.memory["SWAP"]
            swap_used = swap["used"] * KB
            swap_total = swap["tot"] * KB
        except (KeyError, TypeError):
            swap_used = 0
            swap_total = 0

        # Power in mW
        power_mw = 0
        input_mv = 0
        input_ma = 0
        rails = {}
        try:
            tot = j.power["tot"]
            power_mw = tot.get("power", 0)
            input_mv = tot.get("volt", 0)
            input_ma = tot.get("curr", 0)
            rails = {
                name: rail["power"]
                for name, rail in j.power["rail"].items()
                if rail.get("online", True)
            }
        except (KeyError, TypeError):
            pass

        # Fan
        fan_speed = 0
        fan_rpm = 0
        try:
            pwm = j.fan["pwmfan"]
            fan_speed = round(pwm["speed"][0])
            fan_rpm = pwm["rpm"][0]
        except (KeyError, TypeError, IndexError):
            pass

        # Disk: already in GB
        try:
            disk_used = round(j.disk["used"], 1)
            disk_total = round(j.disk["total"], 1)
        except (KeyError, TypeError):
            disk_used = 0
            disk_total = 0

        # Temps: filter offline sensors
        temps = {}
        for name, t in j.temperature.items():
            if isinstance(t, (int, float)):
                temps[name] = round(t, 1)
            else:
                try:
                    if not t.get("online", True):
                        continue
                    temps[name] = round(t["temp"], 1)
                except (KeyError, TypeError):
                    pass

        # Uptime
        uptime = j.uptime
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h{minutes:02d}m{seconds:02d}s"

        payload = {
            "cpu": cpu_usage,
            "cpu_freq_mhz": cpu_freq,
            "gpu": gpu_load,
            "gpu_freq_mhz": gpu_freq,
            "ram": {"used": ram_used, "total": ram_total},
            "swap": {"used": swap_used, "total": swap_total},
            "temp": temps,
            "power": power_mw,
            "input_mv": input_mv,
            "input_ma": input_ma,
            "rails_mw": rails,
            "disk": {"used": disk_used, "total": disk_total},
            "uptime": uptime_str,
            "fan": fan_speed,
            "fan_rpm": fan_rpm,
            "containers": self._container_stats.get(),
            "wifi": self._wifi.get(),
        }

        await self.publish_json(TELEMETRY_SUBJECT, payload)

    def _reconnect_jetson(self):
        self.logger.warning("jtop stopped answering, reconnecting")
        try:
            self.jetson.close()
        except Exception:
            self.logger.exception("Closing the stale jtop client failed")
        self.jetson = jtop()
        self.jetson.start()
        self.jetson_seen_at = time.monotonic()

    async def close(self):
        await super().close()
        self._container_stats.stop()
        self._wifi.stop()
        self.jetson.close()


if __name__ == "__main__":
    Node().run_node()
