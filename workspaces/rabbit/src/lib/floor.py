import math

from lib.geometry import CAMERA_HEIGHT


class FloorEstimator:
    SMOOTHING = 0.02
    MAX_STEP = 0.15
    CANDIDATE_TOLERANCE = 0.05
    ADOPT_AFTER_M = 1.0

    def __init__(self):
        self.floor_y: float | None = None
        self.candidate: float | None = None
        self.candidate_travel = 0.0
        self.last_position: tuple[float, float] | None = None

    def update(self, camera_x: float, camera_y: float, camera_z: float) -> float:
        estimate = camera_y - CAMERA_HEIGHT
        travel = 0.0 if self.last_position is None else math.dist(self.last_position, (camera_x, camera_z))
        self.last_position = (camera_x, camera_z)
        if self.floor_y is None:
            self.floor_y = estimate if abs(estimate) < self.MAX_STEP else 0.0
        if abs(estimate - self.floor_y) < self.MAX_STEP:
            self.floor_y += self.SMOOTHING * (estimate - self.floor_y)
            self.candidate = None
            return self.floor_y
        if self.candidate is None or abs(estimate - self.candidate) > self.CANDIDATE_TOLERANCE:
            self.candidate, self.candidate_travel = estimate, 0.0
        self.candidate_travel += travel
        if self.candidate_travel >= self.ADOPT_AFTER_M:
            self.floor_y, self.candidate = self.candidate, None
        return self.floor_y
