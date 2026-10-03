import json
import os
import time

import board
import busio
from adafruit_pca9685 import PCA9685
from lib.drive import DRIVE_SUBJECT, JOY_SUBJECT, SAFETY_DRIVE_SUBJECT, CommandArbiter
from lib.node import RabbitNode
from nats.aio.msg import Msg

SUBJECT = "rabbit.steering"


class Node(RabbitNode):
    MIN_PULSE = 1000
    MAX_PULSE = 2000
    CENTER_PULSE = 1532
    TIMEOUT = 0.25
    PUBLISH_INTERVAL = 0.05

    def __init__(self):
        super().__init__("steering")
        i2c = busio.I2C(board.SCL, board.SDA)
        self.pca = PCA9685(i2c, address=0x40)
        self.pca.frequency = 50
        self.channel = 0
        self.last_command_at: float | None = None
        self.current_angle = 0.0
        self.pulse_us = float(self.CENTER_PULSE)
        self.arbiter = CommandArbiter()
        self.errors = 0

    async def init(self):
        if os.environ.get("DRIVE_INPUT") == "safety":
            await self.subscribe(SAFETY_DRIVE_SUBJECT, self.on_safety_drive)
        else:
            await self.subscribe(JOY_SUBJECT, self.on_command)
            await self.subscribe(DRIVE_SUBJECT, self.on_command)
        self.set_angle(0.0)
        self.set_interval(self.kill_switch, 0.05)
        self.set_interval(self.publish_state, self.PUBLISH_INTERVAL)

    async def close(self):
        self.set_angle(0.0)

    async def publish_state(self):
        await self.publish_json(
            SUBJECT, {"angle": self.current_angle, "pulse_us": self.pulse_us, "errors": self.errors}
        )

    async def kill_switch(self):
        if self.last_command_at is None or time.monotonic() - self.last_command_at <= self.TIMEOUT:
            return
        self.last_command_at = None
        self.set_angle(0.0)

    def pulse_for(self, angle: float) -> float:
        if angle < 0:
            return self.CENTER_PULSE + angle * (self.CENTER_PULSE - self.MIN_PULSE)
        return self.CENTER_PULSE + angle * (self.MAX_PULSE - self.CENTER_PULSE)

    async def on_command(self, msg: Msg):
        command = self.arbiter.resolve(msg)
        if command is None:
            return
        self.last_command_at = time.monotonic()
        self.set_angle(command[1])

    async def on_safety_drive(self, msg: Msg):
        self.last_command_at = time.monotonic()
        self.set_angle(float(json.loads(msg.data)["steer"]))

    def set_angle(self, angle: float):
        try:
            pulse = self.pulse_for(angle)
            self.pca.channels[self.channel].duty_cycle = int(pulse / 1_000_000 * self.pca.frequency * 65536)
        except OSError as e:
            self.errors += 1
            self.logger.error(f"Steering write failed: {e}")
            return
        self.current_angle = angle
        self.pulse_us = pulse


if __name__ == "__main__":
    Node().run_node()
