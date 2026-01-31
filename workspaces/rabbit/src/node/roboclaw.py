import asyncio
import json
import time
from typing import Optional

from lib.node import RabbitNode
from lib.roboclaw import RoboClaw
from nats.aio.msg import Msg


class Node(RabbitNode):
    rc = RoboClaw(port="/dev/ttyTHS1", baudrate=115200, address=0x80)

    def __init__(self):
        super().__init__("roboclaw")
        self.last_command_at: Optional[float] = None

    async def init(self):
        self.rc.open()
        await self.subscribe("rabbit.cmd.joy", self.joy_handler)
        await self.async_task(self.publish_metrics)
        await self.set_interval(self.kill_switch, 0.1)

    async def kill_switch(self):
        if self.last_command_at and time.time() - self.last_command_at > 0.1:
            self.rc.move(0, 0)
            self.last_command_at = None

    async def publish_metrics(self):
        await asyncio.sleep(1)

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

        self.rc.move(left_speed, right_speed)


if __name__ == "__main__":
    Node().run_node()
