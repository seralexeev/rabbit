import json
from pathlib import Path

import numpy as np
from pydantic import BaseModel

OBJECTS_SUBJECT = "rabbit.zed.objects"
DETECTOR_DIR = Path("/rabbit/data/detector")
DETECTOR_MODEL = DETECTOR_DIR / "detector.onnx"
DETECTOR_LABELS = DETECTOR_DIR / "detector.json"
MOVING_LABELS = frozenset({"person", "cat", "dog", "robot vacuum"})
DEFAULT_CONFIDENCE = 35.0
STRICT_CONFIDENCE = 50.0
STRICT_LABELS = frozenset(
    {
        "laptop", "cup", "bottle", "kettle", "television", "computer monitor", "picture frame", "clock",
        "shoe", "bag", "backpack", "box", "mirror", "microwave", "suitcase", "pillow",
    }
)
TYPICAL_DEPTH_M = {
    "door": 0.1, "mirror": 0.05, "picture frame": 0.05, "curtain": 0.1, "radiator": 0.15,
    "television": 0.15, "computer monitor": 0.2, "laptop": 0.3, "air conditioner": 0.3,
    "shelf": 0.35, "bookshelf": 0.35, "nightstand": 0.45, "tv stand": 0.45, "low wooden cabinet": 0.45,
    "cabinet": 0.5, "chest of drawers": 0.5, "wardrobe": 0.6, "oven": 0.6, "stove": 0.6, "dishwasher": 0.6,
    "washing machine": 0.6, "sink": 0.6, "refrigerator": 0.7, "desk": 0.75, "dining table": 1.0,
    "coffee table": 0.6, "kitchen island": 1.0, "sofa": 0.9, "armchair": 0.85, "chair": 0.55,
    "office chair": 0.6, "stool": 0.45, "person": 0.4,
}


class DetectedObject(BaseModel):
    id: int
    label: str
    confidence: float
    position: list[float]
    dimensions: list[float]
    corners: list[list[float]]
    box: list[float]
    moving: bool


class DetectedObjects(BaseModel):
    ts: int
    frame_number: int
    objects: list[DetectedObject]


def load_labels(path: Path = DETECTOR_LABELS) -> list[str]:
    return list(json.loads(path.read_text())["names"])


def normalized_box(corners: np.ndarray, width: int, height: int) -> list[float]:
    corners = np.asarray(corners, dtype=float).reshape(-1, 2)
    x0, y0 = corners.min(axis=0)
    x1, y1 = corners.max(axis=0)
    return [
        round(float(np.clip(v, 0.0, 1.0)), 4)
        for v in (x0 / width, y0 / height, x1 / width, y1 / height)
    ]


def to_world(points: np.ndarray, rotation: np.ndarray, origin: np.ndarray, floor_y: float) -> list:
    world = np.asarray(points, dtype=float) @ rotation.T + origin
    world[..., 1] -= floor_y
    return world.round(3).tolist()


def confidence_threshold(label: str) -> float:
    return STRICT_CONFIDENCE if label in STRICT_LABELS else DEFAULT_CONFIDENCE


def object_depth(label: str, width: float) -> float:
    return min(width, TYPICAL_DEPTH_M.get(label, width))


def object_corners(center: np.ndarray, camera: np.ndarray, label: str, width: float, height: float) -> list:
    depth = object_depth(label, width)
    ray = np.array([center[0] - camera[0], center[2] - camera[2]], dtype=float)
    norm = float(np.hypot(*ray))
    forward = ray / norm if norm > 1e-6 else np.array([0.0, -1.0])
    right = np.array([-forward[1], forward[0]])
    corners = []
    for dy in (height / 2, -height / 2):
        for du, dv in ((-1, -1), (-1, 1), (1, 1), (1, -1)):
            x, z = np.asarray(center, dtype=float)[[0, 2]] + right * du * width / 2 + forward * dv * depth / 2
            corners.append([round(float(x), 3), round(float(center[1] + dy), 3), round(float(z), 3)])
    return corners


class TrackConfirmer:
    def __init__(self, min_hits: int, forget_after: int):
        self.min_hits = min_hits
        self.forget_after = forget_after
        self.tracks: dict[int, tuple[int, int]] = {}
        self.calls = 0

    def update(self, ids: list[int]) -> set[int]:
        self.calls += 1
        for track_id in ids:
            hits, _ = self.tracks.get(track_id, (0, 0))
            self.tracks[track_id] = (hits + 1, self.calls)
        self.tracks = {i: t for i, t in self.tracks.items() if self.calls - t[1] <= self.forget_after}
        return {i for i in ids if self.tracks[i][0] >= self.min_hits}
