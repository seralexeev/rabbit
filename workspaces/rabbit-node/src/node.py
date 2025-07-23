from typing import Optional
import nats
from nats.aio.client import Client


class Node:
    def __init__(self, name):
        self.name = name
        self.nc: Optional[Client] = None

    async def open(self):
        self.nc = await nats.connect(
            "nats://nats:4222",
            name=self.name,
            ping_interval=5,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )

    async def close(self):
        if self.nc:
            await self.nc.close()

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
