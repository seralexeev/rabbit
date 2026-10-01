import json
import math
import time

from nats.aio.msg import Msg

JOY_SUBJECT = "rabbit.cmd.joy"
DRIVE_SUBJECT = "rabbit.cmd.drive"
HEARTBEAT_SUBJECT = "rabbit.operator.heartbeat"

JOY_DEADZONE = 0.08
JOY_HOLD = 1.0
JOY_SPEED_LIMIT = 0.5


def clamp(value: float) -> float:
    number = float(value)
    return max(min(number, 1.0), -1.0) if math.isfinite(number) else 0.0


def parse_joy(data: dict) -> tuple[float, float]:
    buttons = data.get("buttons", {})
    speed = buttons.get("r2", {}).get("value", 0) - buttons.get("l2", {}).get("value", 0)
    return clamp(speed), clamp(data.get("sticks", {}).get("left", {}).get("x", 0))


def is_active(speed: float, steer: float) -> bool:
    return abs(speed) > JOY_DEADZONE or abs(steer) > JOY_DEADZONE


class CommandArbiter:
    def __init__(self):
        self.joy_until = 0.0

    def resolve(self, msg: Msg) -> tuple[float, float] | None:
        data = json.loads(msg.data)
        now = time.monotonic()
        if msg.subject == JOY_SUBJECT:
            speed, steer = parse_joy(data)
            if is_active(speed, steer):
                self.joy_until = now + JOY_HOLD
                return speed * JOY_SPEED_LIMIT, steer
            return (0.0, 0.0) if now < self.joy_until else None
        if now < self.joy_until:
            return None
        return clamp(data.get("speed", 0)), clamp(data.get("steer", 0))
