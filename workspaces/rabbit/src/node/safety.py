import asyncio
import json
import time

import numpy as np
from lib.drive import DRIVE_SUBJECT, JOY_SUBJECT, SAFETY_DRIVE_SUBJECT
from lib.hardware import FakeGpio, bridge_fake_gpio, open_gpio
from lib.lidar import SCAN_SUBJECT, decode_scan, points_xy
from lib.node import RabbitNode
from lib.safety_loop import ESTOP_SUBJECT, RESET_SUBJECT, STATE_SUBJECT, Decision, SafetyConfig, SafetyLoop
from lib.tof import TOF_SUBJECT
from nats.aio.msg import Msg

NAV_STATE_SUBJECT = "rabbit.nav.state"
ROBOCLAW_SUBJECT = "rabbit.roboclaw"
INA_SUBJECT = "rabbit.ina"
POWER_STATE_SUBJECT = "rabbit.power.state"
BUMPERS = {"BUMPER_FRONT": "front", "BUMPER_REAR": "rear"}


class Node(RabbitNode):
    LOOP_INTERVAL = 0.02
    STATE_INTERVAL = 0.1
    DEBOUNCE_MS = 2

    def __init__(self):
        super().__init__("safety")
        self.config = SafetyConfig.from_env()
        self.core = SafetyLoop(self.config)
        self.gpio = open_gpio("rabbit-safety")
        self.seq = 0
        self.line: bool | None = None
        self.decision: Decision | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    async def init(self):
        self.loop = asyncio.get_running_loop()
        if not self.config.shadow:
            self.gpio.setup_output("ESTOP_RUN", False)
            self.line = False
            if self.gpio.outputs_persist():
                self.core.fail_self_test("the kernel keeps GPIO outputs driven after the process exits; set pinctrl_bcm2835.persist_gpio_outputs=n in cmdline.txt", 0)
        if "bumpers" in self.config.sensors:
            for name in BUMPERS:
                self.gpio.setup_input(name, self.on_gpio, self.DEBOUNCE_MS)
        if self.config.ina_alert:
            self.gpio.setup_input("INA_ALERT", self.on_gpio, self.DEBOUNCE_MS)
        if isinstance(self.gpio, FakeGpio):
            await bridge_fake_gpio(self, self.gpio)
        now = time.monotonic()
        for name in BUMPERS:
            if "bumpers" in self.config.sensors:
                self.core.on_bumper(BUMPERS[name], self.gpio.read(name), now)
        await self.subscribe(DRIVE_SUBJECT, self.on_drive)
        await self.subscribe(JOY_SUBJECT, self.on_joy)
        await self.subscribe(NAV_STATE_SUBJECT, self.on_brain)
        await self.subscribe(SCAN_SUBJECT, self.on_lidar)
        await self.subscribe(TOF_SUBJECT, self.on_tof)
        await self.subscribe(ROBOCLAW_SUBJECT, self.on_roboclaw)
        await self.subscribe(INA_SUBJECT, self.on_ina)
        await self.subscribe(POWER_STATE_SUBJECT, self.on_power)
        await self.subscribe(ESTOP_SUBJECT, self.on_estop)
        await self.subscribe(RESET_SUBJECT, self.on_reset)
        self.set_interval(self.tick, self.LOOP_INTERVAL, max_parallel=1)
        self.set_interval(self.publish_state, self.STATE_INTERVAL, max_parallel=1)
        self.event("safety.started", "shadow" if self.config.shadow else "active", sensors=",".join(sorted(self.config.sensors)), self_test=self.core.self_test)

    async def close(self):
        if not self.config.shadow:
            self.gpio.write("ESTOP_RUN", False)
        self.gpio.close()

    def on_gpio(self, name: str, level: bool, ts: int):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.gpio_changed, name, level)

    def gpio_changed(self, name: str, level: bool):
        now = time.monotonic()
        if name in BUMPERS:
            self.core.on_bumper(BUMPERS[name], level, now)
        elif name == "INA_ALERT":
            self.core.on_alert(not level, now)
        asyncio.ensure_future(self.tick())

    async def tick(self):
        started = time.monotonic()
        decision = self.core.step(started)
        self.decision = decision
        if not self.config.shadow and decision.line != self.line:
            self.gpio.write("ESTOP_RUN", decision.line)
            self.line = decision.line
            self.event(
                "safety.estop_line",
                "raised" if decision.line else f"dropped: {', '.join(decision.reasons) or 'stopping'}",
                severity="info" if decision.line else "warning",
                line=decision.line,
            )
        self.seq += 1
        await self.publish_json(
            SAFETY_DRIVE_SUBJECT,
            {
                "seq": self.seq,
                "speed": round(decision.speed, 4),
                "steer": round(decision.steer, 4),
                "source": decision.source,
                "cap_fwd": round(decision.cap_fwd, 4),
                "cap_rev": round(decision.cap_rev, 4),
                "reason": decision.reason,
            },
        )
        for name, reason, severity, every_s, fields in self.core.drain():
            if self.config.shadow:
                fields["shadow"] = True
            self.event(name, reason, severity=severity, every_s=every_s, **fields)
        self.observe("step_ms", (time.monotonic() - started) * 1000.0)

    async def publish_state(self):
        if self.decision is not None:
            await self.publish_json(STATE_SUBJECT, {"seq": self.seq, **self.core.snapshot(self.decision, time.monotonic())})

    async def on_drive(self, msg: Msg):
        self.core.on_drive(json.loads(msg.data), time.monotonic())

    async def on_joy(self, msg: Msg):
        self.core.on_joy(json.loads(msg.data), time.monotonic())

    async def on_brain(self, msg: Msg):
        self.core.on_brain(time.monotonic())

    async def on_lidar(self, msg: Msg):
        self.core.on_lidar(points_xy(decode_scan(msg.data)), time.monotonic())

    async def on_tof(self, msg: Msg):
        frame = json.loads(msg.data)
        points = np.array(frame.get("points") or [], dtype=float).reshape(-1, 3)
        self.core.on_tof(str(frame["sensor"]), points[:, :2], time.monotonic())

    async def on_roboclaw(self, msg: Msg):
        self.core.on_roboclaw(json.loads(msg.data), time.monotonic())

    async def on_ina(self, msg: Msg):
        self.core.on_ina(json.loads(msg.data), time.monotonic())

    async def on_power(self, msg: Msg):
        self.core.on_power(str(json.loads(msg.data).get("state", "")), time.monotonic())

    async def on_estop(self, msg: Msg):
        self.core.on_estop(json.loads(msg.data or b"{}"), time.monotonic())
        await self.tick()

    async def on_reset(self, msg: Msg):
        self.core.on_reset(json.loads(msg.data or b"{}"), time.monotonic())


if __name__ == "__main__":
    Node().run_node()
