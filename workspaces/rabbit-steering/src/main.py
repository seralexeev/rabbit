import asyncio
import json
from typing import Optional

import nats
from adafruit_servokit import ServoKit
from nats.aio.client import Client


class Node:
    MIN_SAFE_ANGLE = 0
    MAX_SAFE_ANGLE = 60

    def __init__(self):
        self.nc: Optional[Client] = None
        self.kit = ServoKit(channels=16)
        self.servo = self.kit.servo[0]
        self.kit.servo[0].angle = 60

    async def joy_handler(self, msg):
        try:
            data = msg.data.decode()
            json_data = json.loads(data)

            # When -1 then MIN_SAFE_ANGLE, when 1 then MAX_SAFE_ANGLE
            left_stick_x = json_data.get("sticks", {}).get("left", {}).get("x", 0)

            servo_angle = max(
                self.MIN_SAFE_ANGLE,
                min(
                    self.MAX_SAFE_ANGLE,
                    (left_stick_x + 1) / 2 * (self.MAX_SAFE_ANGLE - self.MIN_SAFE_ANGLE)
                    + self.MIN_SAFE_ANGLE,
                ),
            )

            self.servo.angle = servo_angle

        except Exception as e:
            print(f"Error processing message: {e}")
            return

    async def open(self):
        self.nc = await nats.connect(
            "nats://nats:4222",
            name="rabbit-roboclaw",
            ping_interval=5,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )

        print("Connected to NATS server")
        await self.nc.subscribe("rabbit.cmd.joy", cb=self.joy_handler)

    async def close(self):
        if self.nc:
            await self.nc.close()


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
