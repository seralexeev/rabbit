import asyncio
import json
import logging
import math
import os
import signal
import sys
import time
from collections import deque
from typing import Any, Awaitable, Callable, Coroutine, Optional

import nats
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.errors import ConnectionClosedError, ConnectionReconnectingError, NoServersError, OutboundBufferLimitError
from nats.js import JetStreamContext
from nats.js.errors import BucketNotFoundError
from nats.js.kv import KeyValue

from lib.log import RECORD_ATTRIBUTES, NatsLogHandler, install_crash_hooks, log_subject, time_id
from lib.observability import (
    ID_FIELDS,
    MAX_QUEUED_EVENTS,
    SEVERITIES,
    EventLimiter,
    MetricWindow,
    boot_id,
    event_subject,
    metrics_subject,
    process_stats,
    split_fields,
    start_snapshot,
)

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
    METRICS_INTERVAL = 10.0
    LOOP_PROBE_INTERVAL = 0.1

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
        self.boot_id = boot_id()
        self.instance_id = f"{time_id()}-{os.getpid()}"
        self.node_started_at = time.monotonic()
        self.stop_reason: str | None = None
        self.event_queue: deque[dict[str, Any]] = deque(maxlen=MAX_QUEUED_EVENTS)
        self.event_limiter = EventLimiter()
        self.metric_window = MetricWindow()
        self.callback_errors = 0
        self.events_sent = 0
        self.metrics_baseline: dict[str, float] = {}

    def set_log_context(self, **values: str | None):
        self.log_handler.context.update({key: value or "" for key, value in values.items()})

    def event(
        self,
        name: str,
        reason: str = "",
        *,
        severity: str = "info",
        message: str | None = None,
        every_s: float = 0.0,
        snapshot: dict[str, Any] | None = None,
        **fields: Any,
    ) -> None:
        suppressed = self.event_limiter.admit(f"{name}|{reason}", every_s)
        if suppressed is None:
            return
        context = dict(self.log_handler.context)
        ids = {key: str(fields.pop(key) if fields.get(key) is not None else context.get(key, "")) for key in ID_FIELDS}
        fields = {key: value for key, value in fields.items() if key not in ID_FIELDS}
        values, labels = split_fields(fields)
        payload = {
            "ts": time.time_ns(),
            "node": self.name,
            "name": name,
            "severity": severity,
            "reason": reason,
            "boot_id": self.boot_id,
            "instance_id": self.instance_id,
            "ids": {key: value for key, value in ids.items() if value},
            "values": values,
            "labels": labels,
            "suppressed": suppressed,
        }
        if snapshot is not None:
            payload["snapshot"] = snapshot
        self.event_queue.append(payload)
        extra = {key: value for key, value in fields.items() if key not in RECORD_ATTRIBUTES and value is not None}
        text = message or (f"{name}: {reason}" if reason else name)
        self.logger.log(SEVERITIES.get(severity, logging.INFO), text, extra={**extra, "event": name}, stacklevel=2)

    def observe(self, name: str, value: float) -> None:
        self.metric_window.observe(name, float(value))

    async def publish_logs(self, final: bool = False):
        while self.event_queue:
            payload = self.event_queue.popleft()
            await self.publish(event_subject(self.name), json.dumps(finite(payload), default=str).encode())
            self.events_sent += 1
        for payload in self.log_handler.drain(final):
            await self.publish(log_subject(self.name), json.dumps(finite(payload), default=str).encode())

    async def probe_loop(self):
        loop = asyncio.get_running_loop()
        expected = loop.time() + self.LOOP_PROBE_INTERVAL
        while True:
            await asyncio.sleep(self.LOOP_PROBE_INTERVAL)
            now = loop.time()
            self.metric_window.observe("loop_lag_ms", max(0.0, now - expected) * 1000.0)
            expected = now + self.LOOP_PROBE_INTERVAL

    def metric_counters(self) -> dict[str, float]:
        stats = self.__nc.stats if self.__nc is not None else {}
        return {
            "cpu_s": time.process_time(),
            "wall_s": time.monotonic(),
            "sent_msgs": stats.get("out_msgs", 0),
            "sent_bytes": stats.get("out_bytes", 0),
            "received_msgs": stats.get("in_msgs", 0),
            "received_bytes": stats.get("in_bytes", 0),
            "events": self.events_sent,
            "events_suppressed": self.event_limiter.suppressed,
            "events_dropped": self.event_limiter.dropped,
        }

    async def publish_node_metrics(self):
        counters = self.metric_counters()
        previous, self.metrics_baseline = self.metrics_baseline or counters, counters
        delta = {key: counters[key] - previous[key] for key in counters}
        values = self.metric_window.drain()
        stats = self.__nc.stats if self.__nc is not None else {}
        await self.publish_json(
            metrics_subject(self.name),
            {
                "node": self.name,
                "instance_id": self.instance_id,
                "boot_id": self.boot_id,
                "uptime_s": round(time.monotonic() - self.node_started_at, 1),
                "interval_s": round(delta["wall_s"], 2),
                "cpu_pct": round(100.0 * delta["cpu_s"] / delta["wall_s"], 1) if delta["wall_s"] > 0 else None,
                **process_stats(),
                "loop_lag_max_ms": values.pop("loop_lag_ms_max", None),
                "loop_lag_mean_ms": values.pop("loop_lag_ms_mean", None),
                "sent_msgs": delta["sent_msgs"],
                "sent_bytes": delta["sent_bytes"],
                "received_msgs": delta["received_msgs"],
                "received_bytes": delta["received_bytes"],
                "reconnects": stats.get("reconnects", 0),
                "dropped_publishes": self.dropped_publishes,
                "log_dropped": self.log_handler.dropped_total,
                "events": delta["events"],
                "events_suppressed": delta["events_suppressed"],
                "events_dropped": delta["events_dropped"],
                "callback_errors": self.callback_errors,
                "values": {key: value for key, value in values.items() if not key.startswith("loop_lag_ms")},
            },
        )

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
                    self.callback_errors += 1
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
                        self.observe(f"task_{name}_tps", fps)
                        self.logger.info(f"Async task {name}: {fps:.2f} tps")

                    await asyncio.sleep(0)
                except Exception:
                    self.callback_errors += 1
                    self.logger.exception(f"Error in task {name}")
                    await asyncio.sleep(1)

        self.tasks.append(asyncio.create_task(task()))

    async def subscribe(self, subject: str, cb: Callable[[Msg], Awaitable[None]]):
        async def safe_cb(msg: Msg):
            try:
                await cb(msg)
            except Exception:
                self.callback_errors += 1
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
                self.callback_errors += 1
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
            reason = self.stop_reason or ("crash" if self.crashed else "signal")
            self.event(
                "node.stop",
                reason,
                severity="warning" if self.crashed or self.stop_reason else "info",
                uptime_s=time.monotonic() - self.node_started_at,
            )
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
        self.set_interval(self.publish_node_metrics, self.METRICS_INTERVAL, max_parallel=1)
        self.tasks.append(asyncio.create_task(self.probe_loop()))

        self.logger.info(f"Node {self.name} initialized with NATS and JetStream")
        snapshot = await asyncio.to_thread(start_snapshot, self, self.name)
        self.event(
            "node.start",
            message=f"Node {self.name} started: revision {snapshot['git_rev'] or 'unknown'}, code {snapshot['code_hash']}",
            snapshot=snapshot,
            pid=snapshot["pid"],
            host=snapshot["host"],
            code_hash=snapshot["code_hash"],
            git_rev=snapshot["git_rev"],
            python=snapshot["versions"]["python"],
        )
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
