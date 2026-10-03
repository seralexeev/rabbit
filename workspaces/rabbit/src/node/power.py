import asyncio
import json
import os
import shlex
import time

from lib.hardware import FakeGpio, bridge_fake_gpio, fake, open_gpio
from lib.node import RabbitNode
from lib.observability import event_subject
from lib.power_supervisor import REQUEST_SUBJECT, STATE_SUBJECT, PowerConfig, PowerSupervisor
from nats.aio.msg import Msg

INA_SUBJECT = "rabbit.ina"
NAV_STATE_SUBJECT = "rabbit.nav.state"
SAFETY_STATE_SUBJECT = "rabbit.safety.state"
ZED_EVENTS_SUBJECT = event_subject("rabbit-zed")


class Node(RabbitNode):
    TICK = 0.1
    STATE_INTERVAL = 1.0
    DEBOUNCE_MS = 20

    def __init__(self):
        super().__init__("power")
        self.core = PowerSupervisor(PowerConfig(require_safety=os.environ.get("POWER_REQUIRE_SAFETY", "1") == "1"))
        self.gpio = open_gpio("rabbit-power")
        self.poweroff_command = shlex.split(os.environ.get("POWER_POWEROFF_CMD", "systemctl poweroff"))
        self.loop: asyncio.AbstractEventLoop | None = None
        self.published_state: str | None = None

    async def prepare(self):
        self.loop = asyncio.get_running_loop()
        self.gpio.setup_output("JETSON_OFF", False)
        self.gpio.setup_output("STATUS_LED", True)
        self.gpio.setup_output("BTN_LED", True)
        self.gpio.setup_input("POWER_BTN", self.on_gpio, self.DEBOUNCE_MS)
        self.core.on_button(not self.gpio.read("POWER_BTN"), time.monotonic())
        self.tasks.append(asyncio.create_task(self.run()))

    async def init(self):
        if isinstance(self.gpio, FakeGpio):
            await bridge_fake_gpio(self, self.gpio)
        await self.subscribe(INA_SUBJECT, self.on_ina)
        await self.subscribe(NAV_STATE_SUBJECT, self.on_brain)
        await self.subscribe(SAFETY_STATE_SUBJECT, self.on_safety)
        await self.subscribe(ZED_EVENTS_SUBJECT, self.on_zed_event)
        await self.subscribe(REQUEST_SUBJECT, self.on_request)
        self.set_interval(self.publish_state, self.STATE_INTERVAL, max_parallel=1)

    async def close(self):
        self.gpio.close()

    def on_gpio(self, name: str, level: bool, ts: int):
        if self.loop is not None and name == "POWER_BTN":
            self.loop.call_soon_threadsafe(self.core.on_button, not level, time.monotonic())

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception:
                self.callback_errors += 1
                self.logger.exception("Power tick failed")
            await asyncio.sleep(self.TICK)

    async def tick(self):
        now = time.monotonic()
        self.core.tick(now)
        actions, events = self.core.drain()
        for name, reason, severity, fields in events:
            self.event(name, reason, severity=severity, **fields)
        if self.core.state != self.published_state:
            await self.publish_state()
        for action in actions:
            await self.execute(action)
        led = self.core.led(now)
        self.gpio.write("STATUS_LED", led)
        self.gpio.write("BTN_LED", led)

    async def execute(self, action: tuple):
        kind = action[0]
        if kind == "publish":
            if self.connected:
                await self.publish_json(action[1], action[2])
            else:
                self.logger.warning(f"NATS down, not sending {action[1]}")
        elif kind == "jetson_power":
            self.gpio.write("JETSON_OFF", not action[1])
        elif kind == "poweroff":
            if self.connected:
                await self.publish_logs()
            if fake():
                self.logger.warning(f"Fake hardware: not running {' '.join(self.poweroff_command)}")
                return
            await asyncio.create_subprocess_exec(*self.poweroff_command)

    async def publish_state(self):
        self.published_state = self.core.state
        if self.connected:
            await self.publish_json(STATE_SUBJECT, self.core.snapshot(time.monotonic()))

    async def on_ina(self, msg: Msg):
        self.core.on_ina(json.loads(msg.data), time.monotonic())

    async def on_brain(self, msg: Msg):
        self.core.on_brain(time.monotonic())

    async def on_safety(self, msg: Msg):
        self.core.on_safety(json.loads(msg.data), time.monotonic())

    async def on_zed_event(self, msg: Msg):
        self.core.on_map_event(str(json.loads(msg.data).get("name", "")), time.monotonic())

    async def on_request(self, msg: Msg):
        request = json.loads(msg.data or b"{}")
        action, source = str(request.get("action", "")), str(request.get("source") or "unknown")
        ok, reason = self.core.request(action, source, time.monotonic())
        self.event("power.request", f"{action} from {source}: {reason}", severity="info" if ok else "warning", action=action, source=source, accepted=ok)
        if msg.reply:
            await self.publish_json(msg.reply, {"ok": ok, "reason": reason, "state": self.core.state})
        await self.tick()


if __name__ == "__main__":
    Node().run_node()
