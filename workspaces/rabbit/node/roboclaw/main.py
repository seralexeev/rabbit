import asyncio
import json

from lib.node import RabbitNode, run_node
from lib.roboclaw import RoboClaw
from nats.aio.msg import Msg


class Node(RabbitNode):
    rc = RoboClaw(port="/dev/ttyTHS1", baudrate=115200, address=0x80)

    def __init__(self):
        super().__init__("roboclaw")

    async def init(self):
        await self.subscribe("rabbit.cmd.joy", self.joy_handler)
        await self.task(self.publish_metrics)

    async def publish_metrics(self):
        await asyncio.sleep(1)

    async def joy_handler(self, msg: Msg):
        data = msg.data.decode()
        json_data = json.loads(data)
        r2 = json_data.get("buttons", {}).get("r2", {}).get("value", 0)
        l2 = json_data.get("buttons", {}).get("l2", {}).get("value", 0)
        speed = r2 - l2
        self.rc.move(speed, speed)


if __name__ == "__main__":
    run_node(Node())
