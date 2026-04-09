import json
import time
from typing import Optional

import board
import busio
from adafruit_pca9685 import PCA9685
from lib.node import RabbitNode
from nats.aio.msg import Msg


class Node(RabbitNode):
    MIN_PULSE = 1000
    MID_PULSE = 1500
    MAX_PULSE = 2000
    TIMEOUT = 0.25
    DECAY_RATE = 0.85

    def __init__(self):
        super().__init__("steering")
        i2c = busio.I2C(board.SCL, board.SDA)
        self.pca = PCA9685(i2c, address=0x40)
        self.pca.frequency = 50
        self.channel = 0
        self.last_command_at: Optional[float] = None
        self.current_angle = 0.0

    async def init(self):
        await self.subscribe("rabbit.cmd.joy", self.joy_handler)
        await self.set_interval(self.kill_switch, 0.05)

    async def kill_switch(self):
        if not self.last_command_at:
            return
        if time.time() - self.last_command_at <= self.TIMEOUT:
            return

        if abs(self.current_angle) < 0.01:
            self.current_angle = 0.0
            self.set_angle(0.0)
            self.last_command_at = None
            self.logger.warning("Kill switch activated: no control input")
            return

        self.current_angle *= self.DECAY_RATE
        self.set_angle(self.current_angle)

    def map_angle(self, angle):
        if angle < 0:
            return self.MID_PULSE + angle * (self.MID_PULSE - self.MIN_PULSE)
        else:
            return self.MID_PULSE + angle * (self.MAX_PULSE - self.MID_PULSE)

    async def joy_handler(self, msg: Msg):
        self.last_command_at = time.time()

        data = msg.data.decode()
        json_data = json.loads(data)
        left_stick_x = json_data.get("sticks", {}).get("left", {}).get("x", 0)
        self.current_angle = max(min(left_stick_x, 1), -1)
        self.set_angle(self.current_angle)

    def set_angle(self, angle: float):
        value = self.map_angle(angle)
        pulse_length_s = value / 1_000_000
        duty_cycle = int(pulse_length_s * self.pca.frequency * 65536)
        self.pca.channels[self.channel].duty_cycle = duty_cycle


if __name__ == "__main__":
    Node().run_node()
