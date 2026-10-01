import logging
import sys
from pathlib import Path as FsPath

sys.path.insert(0, str(FsPath(__file__).resolve().parents[1] / "src"))

from lib.log import NatsLogHandler, RepeatSuppressor


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def handler_with_clock() -> tuple[NatsLogHandler, Clock, logging.Logger]:
    clock = Clock()
    handler = NatsLogHandler("roboclaw", RepeatSuppressor(window_s=10.0, clock=clock))
    logger = logging.getLogger(f"test-{id(handler)}")
    logger.propagate = False
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return handler, clock, logger


def total_records(payloads: list[dict]) -> int:
    return sum(1 + payload["repeats"] for payload in payloads)


def test_a_burst_collapses_to_first_and_summary_and_keeps_the_count():
    handler, clock, logger = handler_with_clock()
    first = []
    for attempt in range(50):
        clock.now = attempt * 0.1
        logger.warning(f"RoboClaw transient error after {attempt} retries")
        first.extend(handler.drain())
    clock.now = 10.0
    later = handler.drain()

    assert [payload["repeats"] for payload in first] == [0]
    assert [payload["repeats"] for payload in later] == [48]
    assert later[0]["message"] == "RoboClaw transient error after 49 retries"
    assert total_records(first + later) == 50


def test_different_messages_and_levels_are_not_merged():
    handler, _, logger = handler_with_clock()
    logger.warning("Pose jump 1.00 m")
    logger.error("Pose jump 1.00 m")
    logger.warning("Safety stop: stall")

    assert len(handler.drain()) == 3


def test_final_drain_flushes_pending_repeats():
    handler, _, logger = handler_with_clock()
    for _ in range(5):
        logger.info("Async task capture: 28.09 tps")

    payloads = handler.drain(final=True)

    assert total_records(payloads) == 5
    assert handler.drain(final=True) == []


def test_payload_carries_exception_fields_and_context():
    handler, _, logger = handler_with_clock()
    handler.context.update({"mission_id": "42", "map_session": ""})
    try:
        raise OSError(5, "Input/output error")
    except OSError:
        logger.exception("Unexpected RoboClaw I/O failure", extra={"port": "/dev/ttyTHS1", "retries": 3})

    [payload] = handler.drain()

    assert payload["level"] == "error"
    assert payload["exception_type"] == "OSError"
    assert "Input/output error" in payload["exception"]
    assert payload["fields"] == {"port": "/dev/ttyTHS1", "retries": "3"}
    assert payload["context"] == {"mission_id": "42"}
    assert payload["node"] == "roboclaw"
