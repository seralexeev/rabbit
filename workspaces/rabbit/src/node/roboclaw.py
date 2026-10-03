import asyncio
import json
import os
from collections import deque
import threading
import time

from lib.drive import DRIVE_SUBJECT, JOY_SUBJECT, SAFETY_DRIVE_SUBJECT, CommandArbiter, duty_limit, slew
from lib.geometry import wheel_speeds
from lib.node import RabbitNode
from lib.roboclaw import SERIAL_ERRORS, RoboClaw, RoboClawError
from nats.aio.msg import Msg

SUBJECT = "rabbit.roboclaw"
USB_PORT = "/dev/serial/by-id/usb-Basicmicro_Inc._USB_Roboclaw_2x30A-if00"
UART_PORT = "/dev/ttyTHS1"


def roboclaw_port() -> str:
    if port := os.environ.get("ROBOCLAW_PORT"):
        return port
    return USB_PORT if os.path.exists(USB_PORT) else UART_PORT


class Node(RabbitNode):
    TIMEOUT = 0.4
    ACCEL = 1.5
    DECEL = 5.0
    IO_PERIOD = 0.02
    BOARD_EVERY = 50
    COMMAND_REFRESH = 0.1
    HARDWARE_TIMEOUT = 0.5
    RECONNECT_DELAY = 1.0
    CURRENT_OFFSET_SMOOTHING = 0.05
    SUPPLY_WINDOW = 50

    def __init__(self):
        super().__init__("roboclaw")
        self.rc: RoboClaw | None = None
        self.port: str | None = None
        self.firmware: str | None = None
        self.target = (0.0, 0.0)
        self.last_command_at: float | None = None
        self.latest: tuple[int, dict] | None = None
        self.published_ts = 0
        self.board: dict = {}
        self.errors = 0
        self.reconnects = 0
        self.current_offset = {"left": 0.0, "right": 0.0}
        self.arbiter = CommandArbiter()
        self.owner = "none"
        self.status = 0
        self.supply: deque[float] = deque(maxlen=self.SUPPLY_WINDOW)
        self.duty_max = duty_limit(self.supply)
        self._stop = threading.Event()
        self._io = threading.Thread(target=self._io_loop, daemon=True)

    async def init(self):
        if os.environ.get("DRIVE_INPUT") == "safety":
            await self.subscribe(SAFETY_DRIVE_SUBJECT, self.on_safety_drive)
        else:
            await self.subscribe(JOY_SUBJECT, self.on_command)
            await self.subscribe(DRIVE_SUBJECT, self.on_command)
        self._io.start()
        self.set_interval(self.publish_motion, self.IO_PERIOD, max_parallel=1)

    async def close(self):
        self.target = (0.0, 0.0)
        self._stop.set()
        await asyncio.to_thread(self._io.join)

    def _connect(self) -> bool:
        self.port = roboclaw_port()
        rc = RoboClaw(self.port)
        try:
            self.firmware = rc.open()
            rc.set_serial_timeout(self.HARDWARE_TIMEOUT)
        except (RoboClawError, *SERIAL_ERRORS) as e:
            self.errors += 1
            self.event("motors.connect_failed", str(e), severity="error", every_s=60.0, message=f"RoboClaw connect on {self.port} failed: {e}", port=self.port, errors=self.errors)
            rc.close()
            return False
        self.rc = rc
        self.event("motors.connected", f"RoboClaw {self.firmware}", message=f"RoboClaw {self.firmware} on {self.port}", port=self.port, firmware=self.firmware, reconnects=self.reconnects)
        return True

    def _disconnect(self):
        if self.rc is not None:
            self.rc.close()
        self.rc = None
        self.reconnects += 1

    def _io_loop(self):
        sent: tuple[float, float] | None = None
        sent_at = 0.0
        output = (0.0, 0.0)
        previous = time.monotonic()
        tick = 0
        while not self._stop.is_set():
            started = time.monotonic()
            if self.rc is None and not self._connect():
                self._stop.wait(self.RECONNECT_DELAY)
                continue
            assert self.rc is not None
            try:
                if self.last_command_at is None or started - self.last_command_at > self.TIMEOUT:
                    if self.target != (0.0, 0.0):
                        self.event(
                            "motors.command_timeout",
                            "no drive command, stopping the motors",
                            severity="warning",
                            every_s=1.0,
                            command_age_s=None if self.last_command_at is None else started - self.last_command_at,
                            timeout_s=self.TIMEOUT,
                            left=self.target[0],
                            right=self.target[1],
                            owner=self.owner,
                        )
                    self.target = (0.0, 0.0)
                dt, previous = min(started - previous, self.IO_PERIOD * 5), started
                output = tuple(slew(o, t, dt, self.ACCEL, self.DECEL) for o, t in zip(output, self.target))
                if output != sent or started - sent_at > self.COMMAND_REFRESH:
                    self.rc.drive(*(o * self.duty_max for o in output))
                    sent, sent_at = output, started
                motion = self.rc.read_motion()
                self.supply.append(motion["supply_voltage"])
                self.duty_max = duty_limit(self.supply)
                if tick % self.BOARD_EVERY == 0:
                    self.board = self.rc.read_board()
                    self.rc.set_serial_timeout(self.HARDWARE_TIMEOUT)
                    if self.board.get("status", 0) != self.status:
                        self.event(
                            "motors.status_changed",
                            f"status {self.status:#x} -> {self.board['status']:#x}",
                            severity="info" if self.board["status"] == 0 else "warning",
                            status=self.board["status"],
                            previous_status=self.status,
                            temperature_c=self.board.get("temperature"),
                            supply_voltage_v=motion.get("supply_voltage"),
                        )
                        self.status = self.board["status"]
                self.latest = (time.time_ns(), motion)
                tick += 1
            except RoboClawError as e:
                self.errors += 1
                self.logger.warning(f"RoboClaw transient error: {e}")
            except SERIAL_ERRORS as e:
                self.errors += 1
                self.event("motors.port_lost", str(e), severity="error", message=f"RoboClaw port lost: {e}", port=self.port, errors=self.errors)
                self._disconnect()
                sent = None
            except Exception:
                self.errors += 1
                self.logger.exception("Unexpected RoboClaw I/O failure")
                sent = None
            self._stop.wait(max(0.0, self.IO_PERIOD - (time.monotonic() - started)))

        if self.rc is not None:
            try:
                self.rc.drive(0.0, 0.0)
            except (RoboClawError, *SERIAL_ERRORS):
                pass
            self.rc.close()

    async def publish_motion(self):
        latest = self.latest
        if latest is None or latest[0] == self.published_ts:
            return
        ts, motion = latest
        self.published_ts = ts

        for side, command in zip(("left", "right"), self.target):
            wheel = motion[side]
            wheel["command"] = command
            if wheel["pwm"] == 0:
                self.current_offset[side] += self.CURRENT_OFFSET_SMOOTHING * (
                    wheel["current"] - self.current_offset[side]
                )
            wheel["current"] = round(wheel["current"] - self.current_offset[side], 3)

        await self.publish_json(
            SUBJECT,
            {
                "ts": ts,
                **motion,
                **self.board,
                "duty_max": round(self.duty_max, 3),
                "port": self.port,
                "errors": self.errors,
                "retries": self.rc.retried if self.rc is not None else 0,
                "reconnects": self.reconnects,
            },
        )

    async def on_command(self, msg: Msg):
        command = self.arbiter.resolve(msg)
        owner = self.arbiter.owner()
        if owner != self.owner:
            self.event("drive.owner_changed", f"{self.owner} -> {owner}", previous=self.owner, owner=owner, subject=msg.subject)
            self.owner = owner
        if command is None:
            if msg.subject == DRIVE_SUBJECT:
                self.event("drive.command_ignored", "the joystick owns the motors", every_s=5.0, owner=owner, joy_hold_s=self.arbiter.joy_until - time.monotonic())
            return
        left, right = wheel_speeds(*command)
        self.target = (left, right)
        self.last_command_at = time.monotonic()

    async def on_safety_drive(self, msg: Msg):
        command = json.loads(msg.data)
        self.target = wheel_speeds(float(command["speed"]), float(command["steer"]))
        self.last_command_at = time.monotonic()


if __name__ == "__main__":
    Node().run_node()
