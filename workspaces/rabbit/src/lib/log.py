import json
import logging
import re
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

LOG_SUBJECT = "rabbit.log"
REPEAT_WINDOW_S = 10.0
MAX_QUEUED = 10_000

LEVELS = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warning",
    logging.ERROR: "error",
    logging.CRITICAL: "critical",
}

RECORD_ATTRIBUTES = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

NUMBER = re.compile(r"\d+(\.\d+)?")


def time_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")[:-3]


def log_subject(node: str) -> str:
    return f"{LOG_SUBJECT}.{node}"


def field_value(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str)


def record_payload(record: logging.LogRecord, node: str, context: dict[str, str]) -> dict[str, Any]:
    exception_type = ""
    exception = record.exc_text or ""
    if record.exc_info and record.exc_info[0] is not None:
        exception_type = record.exc_info[0].__name__
        exception = "".join(traceback.format_exception(*record.exc_info))
    extra = {key: field_value(value) for key, value in vars(record).items() if key not in RECORD_ATTRIBUTES}
    return {
        "ts": int(record.created * 1_000_000) * 1000,
        "node": node,
        "level": LEVELS.get(record.levelno, "info"),
        "logger": record.name,
        "message": record.getMessage(),
        "template": str(record.msg),
        "exception_type": exception_type,
        "exception": exception,
        "location": f"{record.module}:{record.funcName}:{record.lineno}",
        "fields": extra,
        "context": {key: value for key, value in context.items() if value},
        "pid": record.process,
    }


def repeat_key(payload: dict[str, Any]) -> tuple[str, ...]:
    return (
        payload["logger"],
        payload["level"],
        NUMBER.sub("#", payload["template"]),
        payload["exception_type"],
    )


@dataclass
class RepeatWindow:
    started: float
    suppressed: int = 0
    last: dict[str, Any] | None = None


class RepeatSuppressor:
    def __init__(self, window_s: float = REPEAT_WINDOW_S, clock: Callable[[], float] = time.monotonic):
        self.window_s = window_s
        self.clock = clock
        self.windows: dict[tuple[str, ...], RepeatWindow] = {}

    def admit(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        now = self.clock()
        key = repeat_key(payload)
        window = self.windows.get(key)
        if window is not None and now - window.started < self.window_s:
            window.suppressed += 1
            window.last = payload
            return []
        self.windows[key] = RepeatWindow(started=now)
        return [*self.summary(window), {**payload, "repeats": 0}]

    def expire(self, everything: bool = False) -> list[dict[str, Any]]:
        now = self.clock()
        expired = [key for key, window in self.windows.items() if everything or now - window.started >= self.window_s]
        return [payload for key in expired for payload in self.summary(self.windows.pop(key))]

    @staticmethod
    def summary(window: RepeatWindow | None) -> list[dict[str, Any]]:
        if window is None or window.last is None:
            return []
        return [{**window.last, "repeats": window.suppressed - 1}]


class NatsLogHandler(logging.Handler):
    def __init__(self, node: str, suppressor: RepeatSuppressor | None = None):
        super().__init__()
        self.node = node
        self.context: dict[str, str] = {}
        self.queue: deque[dict[str, Any]] = deque(maxlen=MAX_QUEUED)
        self.dropped = 0
        self.dropped_total = 0
        self.suppressor = suppressor or RepeatSuppressor()

    def emit(self, record: logging.LogRecord):
        try:
            if len(self.queue) == self.queue.maxlen:
                self.dropped += 1
                self.dropped_total += 1
            self.queue.append(record_payload(record, self.node, self.context))
        except Exception:
            self.handleError(record)

    def drain(self, final: bool = False) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        while self.queue:
            payloads.extend(self.suppressor.admit(self.queue.popleft()))
        payloads.extend(self.suppressor.expire(everything=final))
        if self.dropped > 0 and payloads:
            payloads[-1] = {**payloads[-1], "dropped": self.dropped}
            self.dropped = 0
        return payloads


def install_crash_hooks(logger: logging.Logger):
    def on_uncaught(kind, value, trace):
        logger.critical("Uncaught exception", exc_info=(kind, value, trace))

    def on_thread_crash(args: threading.ExceptHookArgs):
        logger.critical(
            "Uncaught exception in a thread",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            extra={"crashed_thread": args.thread.name if args.thread else ""},
        )

    sys.excepthook = on_uncaught
    threading.excepthook = on_thread_crash
