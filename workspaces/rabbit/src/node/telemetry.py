import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import docker
from jtop import jtop

from lib.node import RabbitNode

TELEMETRY_SUBJECT = "rabbit.telemetry"
PUBLISH_INTERVAL = 1.0
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


class Node(RabbitNode):
    def __init__(self):
        super().__init__("telemetry")
        self.jetson = jtop()
        self._container_stats = ContainerStatsCollector(
            docker.DockerClient.from_env()
        )

    async def init(self):
        self.jetson.start()
        self._container_stats.start()
        self.set_interval(self.publish_telemetry, PUBLISH_INTERVAL)

    async def publish_telemetry(self):
        if not self.jetson.ok():
            return

        j = self.jetson

        # CPU: per-core usage = 100 - idle
        cpu_cores = j.cpu.get("cpu", [])
        cpu_usage = [round(100 - c.get("idle", 100)) for c in cpu_cores]

        # GPU
        gpu_load = 0
        try:
            gpu_load = round(j.gpu["gpu"]["status"]["load"])
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
        try:
            tot = j.power["tot"]
            power_mw = tot.get("avg", tot.get("power", 0))
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
            "gpu": gpu_load,
            "ram": {"used": ram_used, "total": ram_total},
            "swap": {"used": swap_used, "total": swap_total},
            "temp": temps,
            "power": power_mw,
            "disk": {"used": disk_used, "total": disk_total},
            "uptime": uptime_str,
            "fan": fan_speed,
            "fan_rpm": fan_rpm,
            "containers": self._container_stats.get(),
        }

        await self.nc.publish(
            TELEMETRY_SUBJECT,
            json.dumps(payload).encode(),
        )

    async def close(self):
        await super().close()
        self._container_stats.stop()
        self.jetson.close()


if __name__ == "__main__":
    Node().run_node()
