import asyncio
import json
import logging
import math
import os
import signal
import sys
import time
from typing import Any, Awaitable, Callable, Coroutine, Optional

import nats
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.errors import ConnectionClosedError, ConnectionReconnectingError, NoServersError, OutboundBufferLimitError
from nats.js import JetStreamContext
from nats.js.errors import BucketNotFoundError
from nats.js.kv import KeyValue

from lib.log import NatsLogHandler, install_crash_hooks, log_subject

logging.basicConfig(
    level=logging.INFO,
    format="🐰 [{asctime}] [{levelname}] {name}: {message}",
    datefmt="%Y-%m-%d %H:%M:%S",
    style="{",
)


def finite(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(item) for item in value]
    return value


class RabbitNode:
    LOG_PUBLISH_INTERVAL = 0.5
    CONNECT_RETRY_S = 1.0

    def __init__(self, name: str):
        self.name = name
        self.__nc: Optional[Client] = None
        self.dropped_publishes = 0
        self.__js: Optional[JetStreamContext] = None
        self.__kv: Optional[KeyValue] = None
        self.tasks: list[asyncio.Task] = []
        self.kv_watchers: list[KeyValue.KeyWatcher] = []
        self.logger = logging.getLogger(name)
        self.log_handler = NatsLogHandler(name)
        logging.getLogger().addHandler(self.log_handler)
        install_crash_hooks(self.logger)
        self.crashed = False

    def set_log_context(self, **values: str | None):
        self.log_handler.context.update({key: value or "" for key, value in values.items()})

    async def publish_logs(self, final: bool = False):
        for payload in self.log_handler.drain(final):
            await self.publish(log_subject(self.name), json.dumps(finite(payload), default=str).encode())

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
                except Exception:
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
                except Exception:
                    self.logger.exception(f"Error in task {name}")
                    await asyncio.sleep(1)

        self.tasks.append(asyncio.create_task(task()))

    async def subscribe(self, subject: str, cb: Callable[[Msg], Awaitable[None]]):
        async def safe_cb(msg: Msg):
            try:
                await cb(msg)
            except Exception:
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

    async def publish(self, subject: str, data: bytes, headers: dict[str, str] | None = None):
        try:
            await self.nc.publish(subject, data, headers=headers)
        except (ConnectionReconnectingError, ConnectionClosedError, OutboundBufferLimitError):
            self.dropped_publishes += 1

    async def publish_json(self, subject: str, payload: dict[str, Any]):
        await self.publish(subject, json.dumps(finite({"ts": time.time_ns(), **payload}), allow_nan=False).encode())

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
                        pass  # skip tick, previous still running

                    next_tick += delay
                    sleep_time = next_tick - loop.time()
                    await asyncio.sleep(sleep_time if sleep_time > 0 else 0)
            except asyncio.CancelledError:
                if running:
                    await asyncio.gather(*running, return_exceptions=True)
                raise

        task = asyncio.create_task(runner())
        self.tasks.append(task)
        return task

    async def close(self):
        pass

    async def __close(self):
        for worker in self.tasks:
            worker.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

        for watcher in self.kv_watchers:
            await watcher.stop()

        await self.close()

        if self.__nc:
            await self.publish_logs(final=True)
            await self.__nc.drain()

    async def __connect(self):
        waiting = False
        while True:
            nc: Client | None = None
            try:
                nc = await nats.connect(
                    os.environ.get("NATS_URL", "nats://nats:4222"),
                    name=self.name,
                    ping_interval=20,
                    max_outstanding_pings=5,
                    max_reconnect_attempts=-1,
                    reconnect_time_wait=2,
                )
                js = nc.jetstream()
                return nc, js, await js.key_value("rabbit")
            except (OSError, asyncio.TimeoutError, NoServersError, BucketNotFoundError) as e:
                if nc is not None:
                    await nc.close()
                if not waiting:
                    self.logger.warning(f"Waiting for NATS: {e!r}")
                    waiting = True
                await asyncio.sleep(self.CONNECT_RETRY_S)

    async def __run(self):
        self.__nc, self.__js, self.__kv = await self.__connect()

        asyncio.get_running_loop().set_exception_handler(self.on_loop_exception)
        self.set_interval(self.publish_logs, self.LOG_PUBLISH_INTERVAL, max_parallel=1)

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
            except Exception:
                self.crashed = True
                self.logger.critical("Node crashed", exc_info=True)
            finally:
                self.logger.info("Shutting down node...")
                await self.__close()
                self.logger.info("Node closed successfully")

        asyncio.run(main())
        if self.crashed:
            sys.exit(1)

    def on_loop_exception(self, loop: asyncio.AbstractEventLoop, context: dict[str, Any]):
        self.logger.error(
            "Unhandled asyncio exception",
            exc_info=context.get("exception"),
            extra={"asyncio_message": context.get("message", "")},
        )

    async def init(self):
        pass
