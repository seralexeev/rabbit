import numpy as np
from lib.geometry import rotation_deg


class JumpGate:
    def __init__(self, jump_m: float, max_speed: float, settle_s: float, max_gap_s: float = 1.0):
        self.jump_m = jump_m
        self.max_gap_s = max_gap_s
        self.max_speed = max_speed
        self.settle_s = settle_s
        self.accepted: tuple[float, np.ndarray] | None = None
        self.pending: tuple[float, float, np.ndarray] | None = None

    def reachable(self, origin: tuple[float, np.ndarray], now: float, position: np.ndarray) -> bool:
        return float(np.linalg.norm(position - origin[1])) <= self.jump_m + self.max_speed * min(max(0.0, now - origin[0]), self.max_gap_s)

    def update(self, now: float, position) -> bool:
        position = np.asarray(position, dtype=float)
        if self.accepted is None or self.reachable(self.accepted, now, position):
            self.accepted = (now, position)
            self.pending = None
            return True
        if self.pending is not None and self.reachable(self.pending[1:], now, position):
            if now - self.pending[0] >= self.settle_s:
                self.accepted = (now, position)
                self.pending = None
                return True
            self.pending = (self.pending[0], now, position)
            return False
        self.pending = (now, now, position)
        return False


def odometry_step_ok(step: np.ndarray, elapsed: float, max_speed: float, max_turn_rate_deg: float, slack_m: float, slack_deg: float) -> bool:
    if not np.isfinite(step).all():
        return False
    moved = float(np.linalg.norm(step[:3, 3]))
    return moved <= slack_m + max_speed * elapsed and rotation_deg(step[:3, :3]) <= slack_deg + max_turn_rate_deg * elapsed
