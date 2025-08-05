import asyncio
import signal
from typing import Any, Awaitable, Callable, Coroutine, Dict, Optional

import nats
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import KeyValueConfig
from nats.js.errors import BucketNotFoundError
from nats.js.kv import KeyValue


class RabbitNode:
    def __init__(self, name: str):
        self.name = name
        self.__nc: Optional[Client] = None
        self.__js: Optional[JetStreamContext] = None
        self.__kv: Optional[KeyValue] = None
        self.tasks: list[asyncio.Task] = []

    async def task(self, task: Callable[[], Coroutine[Any, Any, None]]):
        async def wrapper():
            while True:
                try:
                    await task()
                except Exception as e:
                    print(f"Error in task {task.__name__}: {e}")

        self.tasks.append(asyncio.create_task(wrapper()))

    async def subscribe(self, subject: str, cb: Callable[[Msg], Awaitable[None]]):
        async def safe_cb(msg: Msg):
            try:
                await cb(msg)
            except Exception as e:
                print(f"Error in callback for subject {subject}: {e}")

        await self.nc.subscribe(subject, cb=safe_cb)

    @property
    def nc(self) -> Client:
        if self.__nc is None:
            raise RuntimeError("NATS client is not connected")
        return self.__nc

    @property
    def js(self) -> JetStreamContext:
        if self.__js is None:
            raise RuntimeError("JetStream context is not initialized")
        return self.__js

    @property
    def kv(self) -> KeyValue:
        if self.__kv is None:
            raise RuntimeError("KeyValue store is not initialized")
        return self.__kv

    async def close(self):
        if self.__nc:
            await self.__nc.close()
        for worker in self.tasks:
            if not worker.done():
                worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

    async def __run(self):
        self.__nc = await nats.connect(
            "nats://nats:4222",
            name=self.name,
            ping_interval=5,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )

        await self.ensure_js()
        await self.ensure_kv()

        print("Connected to NATS server")
        await self.init()

    async def ensure_js(self):
        self.__js = self.nc.jetstream()

    async def ensure_kv(self):
        try:
            self.__kv = await self.js.key_value("rabbit")
        except BucketNotFoundError as e:
            await self.js.create_key_value(
                KeyValueConfig(
                    bucket="rabbit",
                )
            )
            self.__kv = await self.js.key_value("rabbit")
        except Exception as e:
            raise

    def run_node(self):
        async def main():
            loop = asyncio.get_running_loop()
            stop = asyncio.Event()

            def _shutdown():
                print("Received shutdown signal")
                stop.set()

            loop.add_signal_handler(signal.SIGINT, _shutdown)
            loop.add_signal_handler(signal.SIGTERM, _shutdown)

            try:
                await self.__run()
                await stop.wait()
            finally:
                print("Gracefully shutting down node")
                await self.close()
                print("Node closed successfully")

        asyncio.run(main())

    async def init(self):
        pass
