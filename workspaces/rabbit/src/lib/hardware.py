from __future__ import annotations

import math
import os
import threading
import time
from datetime import timedelta
from typing import Callable

from lib import rplidar

SIM_GPIO_IN_SUBJECT = "rabbit.sim.gpio.in"
SIM_GPIO_OUT_SUBJECT = "rabbit.sim.gpio.out"

PINS = {
    "ESTOP_RUN": 16,
    "SWITCH_OFF": 17,
    "TOF_PWR_OFF": 18,
    "STATUS_LED": 19,
    "BUMPER_FRONT": 20,
    "BUMPER_REAR": 21,
    "INA_ALERT": 24,
    "JETSON_OFF": 25,
    "POWER_BTN": 26,
    "BTN_LED": 27,
}

Listener = Callable[[str, bool, int], None]


def backend() -> str:
    return os.environ.get("RABBIT_HW", "pi")


def fake() -> bool:
    return backend() == "fake"


class FakeGpio:
    def __init__(self, levels: dict[str, bool] | None = None):
        self.levels: dict[str, bool] = dict(levels or {})
        self.outputs: dict[str, bool] = {}
        self.callbacks: dict[str, Listener] = {}
        self.output_listeners: list[Listener] = []
        self.lock = threading.Lock()

    def setup_output(self, name: str, value: bool) -> None:
        self.write(name, value)

    def write(self, name: str, value: bool) -> None:
        with self.lock:
            changed = self.outputs.get(name) != value
            self.outputs[name] = value
        if changed:
            for listener in self.output_listeners:
                listener(name, value, time.time_ns())

    def setup_input(self, name: str, on_change: Listener | None = None, debounce_ms: int = 0) -> None:
        with self.lock:
            self.levels.setdefault(name, False)
            if on_change is not None:
                self.callbacks[name] = on_change

    def read(self, name: str) -> bool:
        with self.lock:
            return self.levels.get(name, False)

    def set_input(self, name: str, level: bool) -> None:
        with self.lock:
            changed = self.levels.get(name) != level
            self.levels[name] = level
            callback = self.callbacks.get(name)
        if changed and callback is not None:
            callback(name, level, time.time_ns())

    def close(self) -> None:
        with self.lock:
            self.outputs.clear()


class PiGpio:
    CHIP = "/dev/gpiochip0"
    EDGE_WAIT_S = 0.1

    def __init__(self, consumer: str):
        import gpiod
        from gpiod.line import Bias, Direction, Edge, Value

        self.gpiod, self.Bias, self.Direction, self.Edge, self.Value = gpiod, Bias, Direction, Edge, Value
        self.consumer = consumer
        self.requests: dict[str, object] = {}
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []

    def setup_output(self, name: str, value: bool) -> None:
        settings = self.gpiod.LineSettings(direction=self.Direction.OUTPUT, output_value=self.level(value))
        self.requests[name] = self.gpiod.request_lines(self.CHIP, consumer=self.consumer, config={PINS[name]: settings})

    def write(self, name: str, value: bool) -> None:
        self.requests[name].set_value(PINS[name], self.level(value))

    def setup_input(self, name: str, on_change: Listener | None = None, debounce_ms: int = 0) -> None:
        settings = self.gpiod.LineSettings(
            direction=self.Direction.INPUT,
            bias=self.Bias.DISABLED,
            edge_detection=self.Edge.BOTH if on_change else self.Edge.NONE,
            debounce_period=timedelta(milliseconds=debounce_ms),
        )
        request = self.gpiod.request_lines(self.CHIP, consumer=self.consumer, config={PINS[name]: settings})
        self.requests[name] = request
        if on_change is not None:
            thread = threading.Thread(target=self.watch, args=(name, request, on_change), daemon=True)
            thread.start()
            self.threads.append(thread)

    def watch(self, name: str, request, on_change: Listener) -> None:
        while not self.stop.is_set():
            if request.wait_edge_events(timedelta(seconds=self.EDGE_WAIT_S)):
                request.read_edge_events()
                on_change(name, self.read(name), time.time_ns())

    def read(self, name: str) -> bool:
        return self.requests[name].get_value(PINS[name]) == self.Value.ACTIVE

    def level(self, value: bool):
        return self.Value.ACTIVE if value else self.Value.INACTIVE

    def close(self) -> None:
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=1.0)
        for request in self.requests.values():
            request.release()
        self.requests.clear()


def open_gpio(consumer: str) -> FakeGpio | PiGpio:
    return FakeGpio() if fake() else PiGpio(consumer)


async def bridge_fake_gpio(node, gpio: FakeGpio) -> None:
    import asyncio
    import json

    loop = asyncio.get_running_loop()

    async def on_input(msg):
        for name, level in json.loads(msg.data).get("pins", {}).items():
            gpio.set_input(name, bool(level))

    def on_output(name: str, value: bool, ts: int):
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(node.publish_json(SIM_GPIO_OUT_SUBJECT, {"ts": ts, "node": node.name, "pins": {name: value}})))

    gpio.output_listeners.append(on_output)
    await node.subscribe(SIM_GPIO_IN_SUBJECT, on_input)
    for name, value in list(gpio.outputs.items()):
        on_output(name, value, time.time_ns())


def room_ranges(width_m: float = 3.0, depth_m: float = 4.0, x_m: float = 1.0, y_m: float = 1.5) -> Callable[[float], float]:
    def distance_mm(angle_deg: float) -> float:
        theta = math.radians(-angle_deg)
        dx, dy = math.cos(theta), math.sin(theta)
        hits = []
        for wall, direction, origin in ((depth_m, dx, x_m), (0.0, dx, x_m), (width_m, dy, y_m), (0.0, dy, y_m)):
            if abs(direction) > 1e-9:
                t = (wall - origin) / direction
                if t > 0:
                    hits.append(t)
        return min(hits) * 1000.0

    return distance_mm


class FakeC1:
    SAMPLE_RATE = 5000
    SCAN_HZ = 10.0
    INFO = rplidar.DeviceInfo(model=0x41, firmware="1.01", hardware=18, serial="00" * 16)

    def __init__(self, ranges: Callable[[float], float] | None = None, timeout: float = 0.05):
        self.ranges = ranges or room_ranges()
        self.timeout = timeout
        self.pending = bytearray()
        self.scanning = False
        self.scan_started = 0.0
        self.emitted = 0
        self.health = rplidar.Health("good", 0)
        self.lock = threading.Lock()
        self.silent = False
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        command = data[1] if len(data) > 1 and data[0] == rplidar.SYNC else None
        with self.lock:
            if command in (rplidar.STOP, rplidar.RESET):
                self.scanning = False
            elif command == rplidar.GET_HEALTH:
                status = {value: key for key, value in rplidar.HEALTH_STATUS.items()}[self.health.status]
                self.pending += rplidar.encode_descriptor(rplidar.HEALTH_REPLY) + bytes([status]) + self.health.error_code.to_bytes(2, "little")
            elif command == rplidar.GET_INFO:
                self.pending += rplidar.encode_descriptor(rplidar.INFO_REPLY) + rplidar.encode_info(self.INFO)
            elif command == rplidar.SCAN:
                self.pending += rplidar.encode_descriptor(rplidar.SCAN_REPLY)
                self.scanning = True
                self.scan_started = time.monotonic()
                self.emitted = 0
        return len(data)

    def node(self, index: int) -> bytes:
        per_turn = round(self.SAMPLE_RATE / self.SCAN_HZ)
        step = index % per_turn
        angle_q6 = round(step * rplidar.FULL_TURN_Q6 / per_turn) % rplidar.FULL_TURN_Q6
        distance = self.ranges(angle_q6 / 64.0)
        quality = 47 if distance > 0 else 0
        return rplidar.encode_node(rplidar.Measurement(step == 0, quality, angle_q6, max(0, min(round(distance * 4), 0xFFFF))))

    def stream(self) -> None:
        if not self.scanning or self.silent:
            return
        due = int((time.monotonic() - self.scan_started) * self.SAMPLE_RATE)
        while self.emitted < due:
            self.pending += self.node(self.emitted)
            self.emitted += 1

    def read(self, size: int = 1) -> bytes:
        deadline = time.monotonic() + self.timeout
        while True:
            with self.lock:
                self.stream()
                if len(self.pending) >= size or (self.pending and time.monotonic() >= deadline):
                    data = bytes(self.pending[:size])
                    del self.pending[:size]
                    return data
            if time.monotonic() >= deadline:
                return b""
            time.sleep(0.002)

    @property
    def in_waiting(self) -> int:
        with self.lock:
            self.stream()
            return len(self.pending)

    def reset_input_buffer(self) -> None:
        with self.lock:
            self.pending.clear()

    def close(self) -> None:
        with self.lock:
            self.scanning = False


def open_serial(port: str, baud: int):
    if fake():
        return FakeC1()
    import serial

    return serial.Serial(port, baud, timeout=0.05)
