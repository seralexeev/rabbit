import asyncio
import json
from typing import Optional
import nats
from nats.aio.client import Client
from roboclaw import RoboClaw


class Node:
    def __init__(self):
        self.nc: Optional[Client] = None
        self.rc = RoboClaw("/dev/ttyTHS1", 115200, 0x80)
        self.metric_task: Optional[asyncio.Task] = None

    async def publish_metrics(self):
        # while True:
        #     if self.nc is None:
        #         await asyncio.sleep(1)
        #         continue

        #     try:
        #         for row in self.rc.get_metrics():
        #             await self.nc.publish(
        #                 "rabbit.metrics",
        #                 json.dumps(row).encode(),
        #             )
        #     except Exception as e:
        #         print(f"Failed to publish metrics: {e}")
        await asyncio.sleep(1)

    a = 1

    async def joy_handler(self, msg):
        try:
            data = msg.data.decode()
            json_data = json.loads(data)

            r2 = json_data.get("buttons", {}).get("r2", {}).get("value", 0)
            l2 = json_data.get("buttons", {}).get("l2", {}).get("value", 0)

            speed = r2 - l2
            self.rc.move(speed, speed)
        except Exception as e:
            print(f"Error processing message: {e}")
            return

    async def open(self):
        self.rc.open()
        self.nc = await nats.connect(
            "nats://nats:4222",
            name="rabbit-roboclaw",
            ping_interval=5,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )

        self.metric_task = asyncio.create_task(self.publish_metrics())
        await self.nc.subscribe("rabbit.cmd.joy", cb=self.joy_handler)

    async def close(self):
        if self.metric_task:
            self.metric_task.cancel()
            try:
                await self.metric_task
            except asyncio.CancelledError:
                pass
        if self.nc:
            await self.nc.close()
        self.rc.close()


async def main():
    node = Node()
    try:
        await node.open()
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Received shutdown signal")
    finally:
        await node.close()


if __name__ == "__main__":
    asyncio.run(main())
