import json
import math
import time

from nats.aio.msg import Msg

JOY_SUBJECT = "rabbit.cmd.joy"
DRIVE_SUBJECT = "rabbit.cmd.drive"
SAFETY_DRIVE_SUBJECT = "rabbit.safety.drive"
HEARTBEAT_SUBJECT = "rabbit.operator.heartbeat"
CAMERA_WAKE_SUBJECT = "rabbit.zed.wake"

JOY_DEADZONE = 0.08
JOY_HOLD = 1.0
JOY_SPEED_LIMIT = 0.5
METRES_PER_SECOND_PER_DUTY = 0.464

MOTOR_VOLTAGE = 12.0
MAX_SUPPLY_VOLTAGE = 16.8
SUPPLY_RANGE = (6.0, 34.0)


def clamp(value: float) -> float:
    number = float(value)
    return max(min(number, 1.0), -1.0) if math.isfinite(number) else 0.0


def parse_joy(data: dict) -> tuple[float, float]:
    buttons = data.get("buttons", {})
    speed = buttons.get("r2", {}).get("value", 0) - buttons.get("l2", {}).get("value", 0)
    return clamp(speed), clamp(data.get("sticks", {}).get("left", {}).get("x", 0))


def slew(current: float, target: float, dt: float, accel: float, decel: float) -> float:
    braking = abs(target) < abs(current) or target * current < 0
    step = (decel if braking else accel) * dt
    return current + max(-step, min(step, target - current))


def duty_limit(supply_voltages) -> float:
    valid = [v for v in supply_voltages if SUPPLY_RANGE[0] <= v <= SUPPLY_RANGE[1]]
    supply = max(valid) if valid else MAX_SUPPLY_VOLTAGE
    return min(1.0, MOTOR_VOLTAGE / supply)


def is_active(speed: float, steer: float) -> bool:
    return abs(speed) > JOY_DEADZONE or abs(steer) > JOY_DEADZONE


class CommandArbiter:
    def __init__(self):
        self.joy_until = 0.0

    def owner(self, now: float | None = None) -> str:
        return "joystick" if (time.monotonic() if now is None else now) < self.joy_until else "auto"

    def resolve(self, msg: Msg) -> tuple[float, float] | None:
        return self.decide(msg.subject, json.loads(msg.data), time.monotonic())

    def decide(self, subject: str, data: dict, now: float) -> tuple[float, float] | None:
        if subject == JOY_SUBJECT:
            speed, steer = parse_joy(data)
            if is_active(speed, steer):
                self.joy_until = now + JOY_HOLD
                return speed * JOY_SPEED_LIMIT, steer
            return (0.0, 0.0) if now < self.joy_until else None
        if now < self.joy_until:
            return None
        return clamp(data.get("speed", 0)), clamp(data.get("steer", 0))
