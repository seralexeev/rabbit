import asyncio
import threading
import time
from collections import deque

from lib.hardware import FakeGpio, bridge_fake_gpio, open_gpio
from lib.node import RabbitNode
from lib.tof import HEALTH_SUBJECT, TOF_SUBJECT, Mount, frame_message, mounts_from_env
from lib.tof_device import open_tof


class Sensor:
    def __init__(self, mount: Mount):
        self.mount = mount
        self.state = "starting"
        self.seq = 0
        self.errors = 0
        self.resets = 0
        self.failures_in_row = 0
        self.frames: deque[float] = deque(maxlen=64)
        self.last: dict | None = None
        self.last_at = 0.0
        self.init_s: float | None = None
        self.thread: threading.Thread | None = None


class Node(RabbitNode):
    FRAME_TIMEOUT = 0.5
    RESETS_BEFORE_POWER_CYCLE = 3
    POWER_OFF_S = 0.5
    POWER_CYCLE_MIN_INTERVAL = 30.0
    RETRY_DELAY = 1.0
    HEALTH_INTERVAL = 1.0

    def __init__(self):
        super().__init__("tof")
        self.sensors = {name: Sensor(mount) for name, mount in mounts_from_env().items()}
        self.gpio = open_gpio("rabbit-tof")
        self.stop = threading.Event()
        self.power_lock = threading.Lock()
        self.power_generation = 0
        self.power_cycles = 0
        self.power_cycled_at = -float("inf")
        self.loop: asyncio.AbstractEventLoop | None = None

    async def init(self):
        self.loop = asyncio.get_running_loop()
        self.gpio.setup_output("TOF_PWR_OFF", False)
        if isinstance(self.gpio, FakeGpio):
            await bridge_fake_gpio(self, self.gpio)
        for sensor in self.sensors.values():
            sensor.thread = threading.Thread(target=self.run_sensor, args=(sensor,), daemon=True)
            sensor.thread.start()
        self.set_interval(self.publish_health, self.HEALTH_INTERVAL, max_parallel=1)

    async def close(self):
        self.stop.set()
        for sensor in self.sensors.values():
            if sensor.thread is not None:
                await asyncio.to_thread(sensor.thread.join, 3.0)
        self.gpio.close()

    def run_sensor(self, sensor: Sensor):
        device = None
        generation = self.power_generation
        while not self.stop.is_set():
            if device is None or generation != self.power_generation:
                if device is not None:
                    device.close()
                generation = self.power_generation
                device = self.start(sensor)
                if device is None:
                    self.stop.wait(self.RETRY_DELAY)
                    continue
            try:
                frame = device.read(self.FRAME_TIMEOUT)
            except Exception as e:
                frame = None
                sensor.errors += 1
                self.event("tof.read_failed", str(e), severity="warning", every_s=10.0, sensor=sensor.mount.name, errors=sensor.errors)
            if frame is None:
                if time.monotonic() - sensor.last_at > self.FRAME_TIMEOUT:
                    device.close()
                    device = None
                    self.failed(sensor, "no frame")
                continue
            sensor.failures_in_row = 0
            self.emit(sensor, *frame)
        if device is not None:
            device.close()

    def start(self, sensor: Sensor):
        began = time.monotonic()
        sensor.state = "starting"
        device = open_tof(sensor.mount)
        try:
            device.start()
        except Exception as e:
            device.close()
            sensor.errors += 1
            self.failed(sensor, f"start failed: {e}")
            return None
        sensor.init_s = time.monotonic() - began
        sensor.state = "ranging"
        sensor.last_at = time.monotonic()
        self.event("tof.sensor_ready", f"{sensor.mount.name} on i2c-{sensor.mount.bus}", sensor=sensor.mount.name, bus=sensor.mount.bus, init_s=sensor.init_s, resets=sensor.resets)
        return device

    def failed(self, sensor: Sensor, reason: str):
        sensor.state = "failed"
        sensor.resets += 1
        sensor.failures_in_row += 1
        self.event("tof.sensor_reset", reason, severity="warning", every_s=10.0, sensor=sensor.mount.name, bus=sensor.mount.bus, resets=sensor.resets, failures_in_row=sensor.failures_in_row)
        if sensor.failures_in_row >= self.RESETS_BEFORE_POWER_CYCLE:
            self.power_cycle(f"{sensor.mount.name} failed {sensor.failures_in_row} times: {reason}")

    def power_cycle(self, reason: str):
        with self.power_lock:
            if time.monotonic() - self.power_cycled_at < self.POWER_CYCLE_MIN_INTERVAL:
                return
            self.power_cycled_at = time.monotonic()
            self.power_cycles += 1
            self.event("tof.power_cycled", reason, severity="warning", power_cycles=self.power_cycles)
            self.gpio.write("TOF_PWR_OFF", True)
            self.stop.wait(self.POWER_OFF_S)
            self.gpio.write("TOF_PWR_OFF", False)
            self.power_generation += 1
            for sensor in self.sensors.values():
                sensor.failures_in_row = 0

    def emit(self, sensor: Sensor, distance_mm: list[int], status: list[int]):
        sensor.seq += 1
        now = time.monotonic()
        sensor.frames.append(now)
        sensor.last_at = now
        message = frame_message(sensor.mount, sensor.seq, time.time_ns(), distance_mm, status)
        sensor.last = message
        if self.loop is not None:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.publish_json(TOF_SUBJECT, message)))

    async def publish_health(self):
        now = time.monotonic()
        sensors = []
        for name, sensor in self.sensors.items():
            frames = [t for t in sensor.frames if now - t <= 1.0]
            last = sensor.last or {}
            sensors.append(
                {
                    "sensor": name,
                    "bus": sensor.mount.bus,
                    "state": sensor.state,
                    "hz": len(frames),
                    "frame_age_s": round(now - sensor.last_at, 3) if sensor.last else None,
                    "valid": last.get("valid"),
                    "floor": last.get("floor"),
                    "overhead": last.get("overhead"),
                    "obstacles": len(last.get("points", [])),
                    "nearest_m": last.get("nearest_m"),
                    "errors": sensor.errors,
                    "resets": sensor.resets,
                    "init_s": None if sensor.init_s is None else round(sensor.init_s, 2),
                }
            )
        await self.publish_json(HEALTH_SUBJECT, {"sensors": sensors, "power_cycles": self.power_cycles})


if __name__ == "__main__":
    Node().run_node()
