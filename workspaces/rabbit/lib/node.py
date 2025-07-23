import asyncio
import signal
from types import CoroutineType
from typing import Any, Awaitable, Callable, Optional, Type

import nats
from nats.aio.client import Client
from nats.aio.msg import Msg


class RabbitNode:
    def __init__(self, name: str):
        self.name = name
        self.nc: Optional[Client] = None
        self.tasks: list[asyncio.Task] = []

    async def task(self, task: Callable[[], CoroutineType[Any, Any, None]]):
        self.tasks.append(asyncio.create_task(task()))

    async def subscribe(self, subject: str, cb: Callable[[Msg], Awaitable[None]]):
        if self.nc is None:
            raise RuntimeError("NATS client is not connected")

        async def safe_cb(msg: Msg):
            try:
                await cb(msg)
            except Exception as e:
                print(f"Error in callback for subject {subject}: {e}")

        await self.nc.subscribe(subject, cb=safe_cb)

    async def close(self):
        if self.nc:
            await self.nc.close()
        for worker in self.tasks:
            if not worker.done():
                worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

    async def __run(self):
        self.nc = await nats.connect(
            "nats://nats:4222",
            name=self.name,
            ping_interval=5,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )
        print("Connected to NATS server")
        await self.init()

    async def init(self):
        pass


def run_node(node: RabbitNode):
    async def main():
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()

        def _shutdown():
            print("Received shutdown signal")
            stop.set()

        loop.add_signal_handler(signal.SIGINT, _shutdown)
        loop.add_signal_handler(signal.SIGTERM, _shutdown)

        try:
            await node.__run()
            await stop.wait()
        finally:
            print("Gracefully shutting down node")
            await node.close()
            print("Node closed successfully")

    asyncio.run(main())
