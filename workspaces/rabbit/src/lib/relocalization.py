import numpy as np

LOCALIZED_STATES = ("KNOWN_MAP", "MAP_UPDATE", "OK", "LOOP_CLOSED")


class Relocalization:
    def __init__(self, stable_s: float, give_up_m: float, max_step_m: float, give_up_s: float):
        self.stable_s = stable_s
        self.give_up_s = give_up_s
        self.started: float | None = None
        self.last_localized = -np.inf
        self.give_up_m = give_up_m
        self.max_step_m = max_step_m
        self.localized_since: float | None = None
        self.travel_m = 0.0
        self.position: np.ndarray | None = None

    def update(self, memory: str, now: float, position: np.ndarray | None) -> str | None:
        if self.started is None:
            self.started = now
        if memory in LOCALIZED_STATES:
            self.last_localized = now
            self.position = None
            if self.localized_since is None:
                self.localized_since = now
            return "relocalized" if now - self.localized_since >= self.stable_s else None
        self.localized_since = None
        if now - self.started >= self.give_up_s and now - self.last_localized > 2 * self.stable_s:
            return "timeout"
        if position is None:
            return None
        if self.position is not None:
            step = float(np.linalg.norm(position - self.position))
            if step < self.max_step_m:
                self.travel_m += step
        self.position = position
        return "give_up" if self.travel_m >= self.give_up_m else None
