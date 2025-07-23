import json

from adafruit_pca9685 import PCA9685
from lib.node import RabbitNode, run_node
from nats.aio.msg import Msg
from smbus2 import SMBus


class Node(RabbitNode):
    MIN_PULSE = 1200
    MAX_PULSE = 2700
    MID_PULSE = 1750

    def __init__(self):
        super().__init__("steering")
        i2c = SMBus(7)
        self.pca = PCA9685(i2c, address=0x40)
        self.pca.frequency = 50
        self.channel = 0

    async def init(self):
        await self.subscribe("rabbit.cmd.joy", self.joy_handler)

    def map_angle(self, angle):
        if angle < 0:
            return self.MID_PULSE + angle * (self.MID_PULSE - self.MIN_PULSE)
        else:
            return self.MID_PULSE + angle * (self.MAX_PULSE - self.MID_PULSE)

    async def joy_handler(self, msg: Msg):
        data = msg.data.decode()
        json_data = json.loads(data)
        left_stick_x = json_data.get("sticks", {}).get("left", {}).get("x", 0)
        angle = max(min(left_stick_x, 1), -1)
        value = self.map_angle(angle)
        pulse_length_s = value / 1_000_000
        duty_cycle = int(pulse_length_s * self.pca.frequency * 65536)
        self.pca.channels[self.channel].duty_cycle = duty_cycle


if __name__ == "__main__":
    run_node(Node())
