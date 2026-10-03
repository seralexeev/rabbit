import json
import math
from dataclasses import dataclass, field

import numpy as np

KEYFRAME_SUBJECT = "rabbit.loc.keyframe"
MAP_ODOM_SUBJECT = "rabbit.loc.map_odom"
LOC_HEALTH_SUBJECT = "rabbit.health.loc"

RELOCALIZING = "relocalizing"
LOCALIZED = "localized"
LOST = "lost"

BASE_FROM_CAMERA = np.array(
    [
        [0.0, 0.0, -1.0, 0.0],
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)
"""ZED RIGHT_HANDED_Y_UP (x right, y up, looking along -z) to RTAB-Map's base frame (x forward, y left, z up).

The same rotation maps the Y-up world to RTAB-Map's Z-up world, so a Y-up pose T becomes B T B^T."""


def to_rtabmap(transform: np.ndarray) -> np.ndarray:
    return BASE_FROM_CAMERA @ np.asarray(transform, dtype=float) @ BASE_FROM_CAMERA.T


def from_rtabmap(transform: np.ndarray) -> np.ndarray:
    return BASE_FROM_CAMERA.T @ np.asarray(transform, dtype=float) @ BASE_FROM_CAMERA


def difference(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Translation (m) and rotation (deg) between two rigid transforms."""
    d = np.linalg.inv(a) @ b
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(d[:3, :3]) - 1.0) / 2.0))))
    return float(np.linalg.norm(d[:3, 3])), angle


def encode_keyframe(
    ts: int, session: str, odom: np.ndarray, intrinsics: tuple[float, float, float, float], rgb: bytes, depth: bytes
) -> tuple[bytes, dict]:
    meta = {
        "ts": int(ts),
        "session": session,
        "odom": [round(float(v), 6) for v in np.asarray(odom, dtype=float).reshape(16)],
        "intrinsics": [round(float(v), 4) for v in intrinsics],
        "rgb_bytes": len(rgb),
    }
    return rgb + depth, {"meta": json.dumps(meta, separators=(",", ":"))}


@dataclass(slots=True)
class Keyframe:
    ts: int
    session: str
    odom: np.ndarray
    intrinsics: tuple[float, float, float, float]
    rgb: bytes
    depth: bytes


def decode_keyframe(payload: bytes, headers: dict) -> Keyframe:
    meta = json.loads(headers["meta"])
    split = int(meta["rgb_bytes"])
    return Keyframe(
        ts=int(meta["ts"]),
        session=str(meta["session"]),
        odom=np.asarray(meta["odom"], dtype=float).reshape(4, 4),
        intrinsics=tuple(float(v) for v in meta["intrinsics"]),
        rgb=payload[:split],
        depth=payload[split:],
    )


@dataclass
class LocalizationFilter:
    """Turns RTAB-Map matches into an accepted map<-odom.

    A first fix, and any jump away from the accepted transform, needs `confirmations` global (appearance-based)
    matches within `window_s` that agree with each other; a single match, even a geometrically verified one, is
    not enough (one in 40 simulated wake-ups was a lone false match 0.86 m off). Proximity matches only refine a
    transform they agree with, because RTAB-Map searches for them around its own, possibly wrong, belief.
    """

    agree_m: float = 0.3
    agree_deg: float = 10.0
    confirmations: int = 2
    window_s: float = 10.0
    lost_s: float = 30.0
    lost_m: float = 3.0
    status: str = RELOCALIZING
    map_from_odom: np.ndarray | None = None
    matches: int = 0
    corrections: int = 0
    last_match: float | None = None
    travel_m: float = 0.0
    pending: list[tuple[float, np.ndarray]] = field(default_factory=list)
    _position: np.ndarray | None = None

    def agrees(self, a: np.ndarray, b: np.ndarray) -> bool:
        metres, degrees = difference(a, b)
        return metres <= self.agree_m and degrees <= self.agree_deg

    def seed(self, now: float, map_from_odom: np.ndarray):
        self._accept(now, map_from_odom)

    def update(self, now: float, odom_position, candidate: np.ndarray | None = None, global_match: bool = False) -> bool:
        position = np.asarray(odom_position, dtype=float)
        if self._position is not None:
            self.travel_m += float(np.linalg.norm(position - self._position))
        self._position = position
        if candidate is None:
            if (
                self.status == LOCALIZED
                and self.last_match is not None
                and now - self.last_match > self.lost_s
                and self.travel_m > self.lost_m
            ):
                self.status = LOST
            return False
        if self.map_from_odom is not None and self.agrees(candidate, self.map_from_odom):
            self._accept(now, candidate)
            return True
        if not global_match:
            return False
        self.pending = [(t, m) for t, m in self.pending if now - t <= self.window_s] + [(now, candidate)]
        if sum(self.agrees(m, candidate) for _, m in self.pending) < self.confirmations:
            return False
        if self.map_from_odom is not None:
            self.corrections += 1
        self._accept(now, candidate)
        return True

    def _accept(self, now: float, map_from_odom: np.ndarray):
        self.map_from_odom = np.asarray(map_from_odom, dtype=float).copy()
        self.status = LOCALIZED
        self.matches += 1
        self.last_match = now
        self.travel_m = 0.0
        self.pending.clear()


def planar(transform: np.ndarray) -> tuple[float, float, float]:
    """x, z and the rotation about +y (deg) of a Y-up rigid transform."""
    m = np.asarray(transform, dtype=float)
    return float(m[0, 3]), float(m[2, 3]), math.degrees(math.atan2(m[0, 2], m[2, 2]))


@dataclass
class KeyframePolicy:
    min_interval_s: float = 0.5
    move_m: float = 0.1
    turn_deg: float = 5.0
    unlocalized_interval_s: float = 1.0
    last_time: float = -math.inf
    last_odom: np.ndarray | None = None

    def due(self, now: float, odom: np.ndarray, localized: bool) -> bool:
        if now - self.last_time < self.min_interval_s:
            return False
        if self.last_odom is None:
            return True
        moved, turned = difference(self.last_odom, odom)
        return moved >= self.move_m or turned >= self.turn_deg or (not localized and now - self.last_time >= self.unlocalized_interval_s)

    def sent(self, now: float, odom: np.ndarray):
        self.last_time = now
        self.last_odom = np.asarray(odom, dtype=float).copy()


GROW = "grow"
STOP = "stop"


@dataclass
class GrowthPolicy:
    """When to add the current surroundings to the map while localized.

    Grows only right after a solid fix: localized, the last accepted match at most `fix_age_s` old and at most
    `max_travel_m` of odometry behind (so a drifting or mis-localized pose is never written into the database), and
    `misses` keyframes in a row that matched nothing (the view is new). Stops as soon as the fix is in doubt, or once
    `resume_matches` keyframes match the map as it was before growing."""

    misses: int = 4
    min_travel_m: float = 0.5
    max_travel_m: float = 2.0
    fix_age_s: float = 15.0
    resume_matches: int = 2
    growing: bool = False
    missed: int = 0
    resumed: int = 0

    def update(self, now: float, fix: LocalizationFilter, matched_known: bool) -> str | None:
        if self.growing:
            if fix.status != LOCALIZED:
                self.growing = False
                return STOP
            self.resumed = self.resumed + 1 if matched_known else 0
            if self.resumed >= self.resume_matches:
                self.growing = False
                self.missed = 0
                return STOP
            return None
        self.missed = 0 if matched_known else self.missed + 1
        if (
            self.missed >= self.misses
            and fix.status == LOCALIZED
            and fix.last_match is not None
            and now - fix.last_match <= self.fix_age_s
            and self.min_travel_m <= fix.travel_m <= self.max_travel_m
        ):
            self.growing = True
            self.resumed = 0
            return GROW
        return None
