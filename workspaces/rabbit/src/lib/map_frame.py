import math
from dataclasses import dataclass, field

import numpy as np

from lib.geometry import rotation_deg
from lib.loc import LOCALIZED, RELOCALIZING, difference

CORRECTION_M = 0.05
CORRECTION_DEG = 2.0
STALE_S = 5.0
ORTHONORMAL_TOLERANCE = 1e-3


def parse_transform(values) -> np.ndarray | None:
    """A 4x4 rigid transform from 16 row-major floats, or None when it is not one."""
    try:
        m = np.asarray(values, dtype=float).reshape(4, 4)
    except (TypeError, ValueError):
        return None
    if not np.all(np.isfinite(m)) or not np.allclose(m[3], [0.0, 0.0, 0.0, 1.0]):
        return None
    rotation = m[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=ORTHONORMAL_TOLERANCE) or np.linalg.det(rotation) < 0:
        return None
    return m


@dataclass(slots=True)
class OdomFrame:
    depth: np.ndarray
    odom_from_camera: np.ndarray
    integrated: bool


@dataclass(slots=True)
class Plan:
    """What the map worker has to do after a map<-odom update.

    reset: the map changed (a new RTAB-Map database), so the nvblox map starts empty.
    rebuild: rebuild the map from its file and every stored frame with the new correction, because it moved more than
    the thresholds since the map was built (or the map was reset).
    flush: integrate the frames that waited while rabbit-loc was not localized.
    """

    reset: bool = False
    rebuild: bool = False
    flush: bool = False


@dataclass
class MapFrame:
    """The map frame of rabbit-zed in LOC_MODE=apply: map pose = C @ odom, with C (map<-odom) from rabbit-loc.

    Depth frames are kept with their odometry pose, so whenever C changes enough the map is rebuilt from them with the
    new C. While rabbit-loc is not localized (relocalizing, lost, or silent for `stale_s`) nothing is integrated: the
    frames wait unintegrated and go into the map with the first C that follows, because odometry is continuous within
    the odom session. A map_odom of another odom session is ignored; a new map_id empties the nvblox map.
    """

    correction_m: float = CORRECTION_M
    correction_deg: float = CORRECTION_DEG
    stale_s: float = STALE_S
    step_m: float = 0.2
    step_deg: float = 10.0
    max_frames: int = 400
    max_pending: int = 300
    odom_session: str = ""
    status: str = RELOCALIZING
    map_id: str | None = None
    map_from_odom: np.ndarray | None = None
    applied: np.ndarray | None = None
    received_at: float = -math.inf
    rejected: int = 0
    rebuilds: int = 0
    resets: int = 0
    frames: list[OdomFrame] = field(default_factory=list)

    def localized(self, now: float) -> bool:
        return self.status == LOCALIZED and self.map_from_odom is not None and now - self.received_at <= self.stale_s

    def receive(self, message: dict, now: float) -> Plan:
        if message.get("odom_session", self.odom_session) != self.odom_session:
            return Plan()
        transform = message.get("transform")
        candidate = None if transform is None else parse_transform(transform)
        if transform is not None and candidate is None:
            self.rejected += 1
            return Plan()
        was_localized = self.localized(now)
        self.received_at = now
        self.status = str(message.get("status", RELOCALIZING))
        plan = Plan()
        map_id = message.get("map_id")
        if map_id is not None and map_id != self.map_id:
            if self.map_id is not None:
                plan.reset = True
                self.resets += 1
                self.applied = None
                self.map_from_odom = None
                for frame in self.frames:
                    frame.integrated = False
            self.map_id = map_id
        if self.status != LOCALIZED or candidate is None:
            return plan
        self.map_from_odom = candidate
        if self.applied is None or self._beyond_threshold(self.applied, candidate):
            self.applied = candidate.copy()
            plan.rebuild = plan.reset or bool(self.frames)
        elif not was_localized:
            plan.flush = any(not frame.integrated for frame in self.frames)
        if plan.rebuild:
            self.rebuilds += 1
        return plan

    def _beyond_threshold(self, a: np.ndarray, b: np.ndarray) -> bool:
        metres, degrees = difference(a, b)
        return metres > self.correction_m or degrees > self.correction_deg

    def to_map(self, odom: np.ndarray) -> np.ndarray | None:
        """The published map pose: the newest correction."""
        return None if self.map_from_odom is None else self.map_from_odom @ np.asarray(odom, dtype=float)

    def integration_pose(self, odom_from_camera: np.ndarray) -> np.ndarray | None:
        """Where a frame goes in the nvblox map: the correction the map was built with, so it stays consistent."""
        return None if self.applied is None else self.applied @ np.asarray(odom_from_camera, dtype=float)

    def store(self, depth: np.ndarray, odom_from_camera: np.ndarray, now: float) -> bool:
        """Keeps a frame for later rebuilds; returns whether it should be integrated now."""
        integrate = self.localized(now)
        odom_from_camera = np.asarray(odom_from_camera, dtype=float)
        if self.frames:
            last = self.frames[-1].odom_from_camera
            moved = float(np.linalg.norm(odom_from_camera[:3, 3] - last[:3, 3]))
            if moved < self.step_m and rotation_deg(last[:3, :3].T @ odom_from_camera[:3, :3]) < self.step_deg:
                return integrate
        self.frames.append(OdomFrame(depth, odom_from_camera.copy(), integrate))
        pending = [i for i, frame in enumerate(self.frames) if not frame.integrated]
        if len(pending) > self.max_pending:
            del self.frames[pending[0]]
        return integrate

    def over_capacity(self) -> bool:
        """Too many integrated frames are kept: save the map to its file, then call `saved`."""
        return sum(frame.integrated for frame in self.frames) > self.max_frames

    def rebuild_poses(self) -> list[tuple[np.ndarray, np.ndarray]]:
        """Depth and map<-camera of every stored frame for a rebuild; they all count as integrated afterwards."""
        if self.applied is None:
            return []
        for frame in self.frames:
            frame.integrated = True
        return [(frame.depth, self.applied @ frame.odom_from_camera) for frame in self.frames]

    def pending_poses(self) -> list[tuple[np.ndarray, np.ndarray]]:
        """Depth and map<-camera of the frames that waited for a correction; they count as integrated afterwards."""
        if self.applied is None:
            return []
        pending = [frame for frame in self.frames if not frame.integrated]
        for frame in pending:
            frame.integrated = True
        return [(frame.depth, self.applied @ frame.odom_from_camera) for frame in pending]

    def saved(self):
        """The nvblox map was saved to its file: the integrated frames are in it now."""
        self.frames = [frame for frame in self.frames if not frame.integrated]

    def health(self, now: float) -> dict:
        offset = None
        if self.map_from_odom is not None:
            m = self.map_from_odom
            offset = [round(float(m[0, 3]), 3), round(float(m[1, 3]), 3), round(float(m[2, 3]), 3), round(rotation_deg(m[:3, :3]), 2)]
        return {
            "status": self.status,
            "localized": self.localized(now),
            "map_id": self.map_id,
            "age_s": None if math.isinf(self.received_at) else round(now - self.received_at, 1),
            "map_from_odom": offset,
            "frames": len(self.frames),
            "pending": sum(not frame.integrated for frame in self.frames),
            "rebuilds": self.rebuilds,
            "resets": self.resets,
            "rejected": self.rejected,
        }
