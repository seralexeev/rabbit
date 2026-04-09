import asyncio
import json
import time
from typing import Optional

from lib.node import RabbitNode
from lib.roboclaw import RoboClaw
from nats.aio.msg import Msg


class Node(RabbitNode):
    rc = RoboClaw(port="/dev/ttyTHS1", baudrate=115200, address=0x80)
    TIMEOUT = 0.25
    DECAY_RATE = 0.8

    def __init__(self):
        super().__init__("roboclaw")
        self.last_command_at: Optional[float] = None
        self.current_left = 0.0
        self.current_right = 0.0

    async def init(self):
        self.rc.open()
        await self.subscribe("rabbit.cmd.joy", self.joy_handler)
        await self.async_task(self.publish_metrics)
        await self.set_interval(self.kill_switch, 0.05)

    async def kill_switch(self):
        if not self.last_command_at:
            return
        if time.time() - self.last_command_at <= self.TIMEOUT:
            return

        if abs(self.current_left) < 0.01 and abs(self.current_right) < 0.01:
            self.current_left = 0.0
            self.current_right = 0.0
            self.rc.move(0, 0)
            self.last_command_at = None
            self.logger.warning("Kill switch activated: no control input")
            return

        self.current_left *= self.DECAY_RATE
        self.current_right *= self.DECAY_RATE
        self.rc.move(self.current_left, self.current_right)

    async def publish_metrics(self):
        while True:
            try:
                speed_m1, dir_m1 = self.rc.read_raw_speed_m1()
                speed_m2, dir_m2 = self.rc.read_raw_speed_m2()
                enc_m1, _ = self.rc.read_encoder_m1()
                enc_m2, _ = self.rc.read_encoder_m2()

                payload = json.dumps({
                    "m1": {
                        "speed": speed_m1 if dir_m1 == 0 else -speed_m1,
                        "encoder": enc_m1,
                    },
                    "m2": {
                        "speed": speed_m2 if dir_m2 == 0 else -speed_m2,
                        "encoder": enc_m2,
                    },
                }).encode()
                await self.nc.publish("rabbit.roboclaw", payload)
            except Exception as e:
                self.logger.error(f"Error reading metrics: {e}")

            await asyncio.sleep(0.1)

    async def joy_handler(self, msg: Msg):
        data = msg.data.decode()
        json_data = json.loads(data)
        r2 = json_data.get("buttons", {}).get("r2", {}).get("value", 0)
        l2 = json_data.get("buttons", {}).get("l2", {}).get("value", 0)
        speed = r2 - l2

        left_stick_x = json_data.get("sticks", {}).get("left", {}).get("x", 0)
        angle = max(min(left_stick_x, 1), -1)

        turn_factor = 0.6
        left_speed = speed
        right_speed = speed

        if angle < 0:
            left_speed = speed * (1 + angle * turn_factor)
        elif angle > 0:
            right_speed = speed * (1 - angle * turn_factor)

        self.current_left = left_speed
        self.current_right = right_speed
        self.rc.move(left_speed, right_speed)
        self.last_command_at = time.time()


if __name__ == "__main__":
    Node().run_node()
