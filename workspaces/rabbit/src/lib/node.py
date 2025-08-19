import asyncio
import logging
import signal
import time
from typing import Any, Awaitable, Callable, Coroutine, Dict, Optional

import nats
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.kv import KeyValue
from nats.js.object_store import ObjectStore

logging.basicConfig(
    level=logging.INFO,
    format="🐰 [{asctime}] [{levelname}] {name}: {message}",
    datefmt="%Y-%m-%d %H:%M:%S",
    style="{",
)


class RabbitNode:
    def __init__(self, name: str):
        self.name = name
        self.__nc: Optional[Client] = None
        self.__js: Optional[JetStreamContext] = None
        self.__kv: Optional[KeyValue] = None
        self.tasks: list[asyncio.Task] = []
        self.kv_watchers: list[KeyValue.KeyWatcher] = []
        self.logger = logging.getLogger(name)

    async def watch_kv(
        self, key: str, fn: Callable[[KeyValue.Entry], Awaitable[None]]
    ) -> None:
        self.logger.info(f"Starting watcher for key: {key} ({fn.__name__})")
        watcher = await self.kv.watch(key)
        self.kv_watchers.append(watcher)

        async def task():
            async for entry in watcher:
                try:
                    await fn(entry)
                except:
                    self.logger.exception(f"Error in watcher for key {key}")

        task.__name__ = fn.__name__
        await self.async_task(task)

    async def async_task(self, fn: Callable[[], Coroutine[Any, Any, None]]):
        name = fn.__name__
        self.logger.info(f"Async task started: {name}")

        async def task():
            started = time.time()
            tick = 0

            while True:
                try:
                    await fn()
                    tick += 1
                    now = time.time()
                    if now - started > 10:
                        fps = tick / (now - started)
                        started = now
                        tick = 0
                        self.logger.info(f"Async task {name}: {fps:.2f} tps")

                    await asyncio.sleep(0)
                except:
                    self.logger.exception(f"Error in task {name}")
                    await asyncio.sleep(1)

        self.tasks.append(asyncio.create_task(task()))

    async def subscribe(self, subject: str, cb: Callable[[Msg], Awaitable[None]]):
        async def safe_cb(msg: Msg):
            try:
                await cb(msg)
            except:
                self.logger.exception(f"Error in subscriber for subject {subject}")

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

    @property
    def object_store(self) -> ObjectStore:
        if self.__object_store is None:
            raise RuntimeError("Object store is not initialized")
        return self.__object_store

    def set_timeout(
        self, callback: Callable[[], Coroutine[Any, Any, None]], delay: float
    ) -> asyncio.Task[None]:
        async def worker():
            await callback()
            await asyncio.sleep(delay)

        return asyncio.create_task(worker())

    def set_interval(
        self,
        callback: Callable[[], Awaitable[None]],
        delay: float,
        max_parallel: Optional[int] = None,
    ) -> asyncio.Task[None]:
        async def safe_callback():
            try:
                await callback()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.exception(f"Exception in interval callback: {e}")

        async def runner():
            running: set[asyncio.Task] = set()
            loop = asyncio.get_running_loop()
            next_tick = loop.time()

            try:
                while True:
                    running = {t for t in running if not t.done()}
                    if max_parallel is None or len(running) < max_parallel:
                        t = asyncio.create_task(safe_callback())
                        running.add(t)
                    else:
                        self.logger.warning(
                            f"Skipping tick: {len(running)}/{max_parallel} tasks running"
                        )

                    next_tick += delay
                    sleep_time = next_tick - loop.time()
                    await asyncio.sleep(sleep_time if sleep_time > 0 else 0)
            except asyncio.CancelledError:
                if running:
                    await asyncio.gather(*running, return_exceptions=True)
                raise

        return asyncio.create_task(runner())

    async def close(self):
        pass

    async def __close(self):
        await self.close()

        if self.__nc:
            await self.__nc.close()

        for watcher in self.kv_watchers:
            await watcher.stop()

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

        self.__js = self.nc.jetstream()
        self.__kv = await self.js.key_value("rabbit")
        self.__object_store = await self.js.create_object_store("rabbit")

        self.logger.info(f"Node {self.name} initialized with NATS and JetStream")
        await self.init()

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
                self.logger.info("Shutting down node...")
                await self.__close()
                self.logger.info("Node closed successfully")

        asyncio.run(main())

    async def init(self):
        pass
