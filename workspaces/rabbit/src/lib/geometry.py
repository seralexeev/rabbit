import numpy as np

CAMERA_TO_REAR_AXLE = 0.1845
CAMERA_HEIGHT = 0.137
CENTERLINE_OFFSET = 0.06
GRAVITY = 9.80665


def quaternion_to_matrix(quaternion) -> np.ndarray:
    x, y, z, w = (float(v) for v in quaternion)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def tilt_deg(quaternion) -> float:
    up = quaternion_to_matrix(quaternion) @ np.array([0.0, 1.0, 0.0])
    return float(np.degrees(np.arccos(np.clip(up[1], -1.0, 1.0))))


def linear_acceleration(acceleration, orientation) -> np.ndarray:
    gravity = quaternion_to_matrix(orientation).T @ np.array([0.0, GRAVITY, 0.0])
    return np.asarray(acceleration, dtype=float) - gravity


REAR_TRACK = 0.1674
DIFFERENTIAL_GAIN = 1.6
STEER_TABLE = np.array([0.0, 0.5, 1.0])
LEFT_CURVATURE_TABLE = np.array([0.0, 1.70, 3.34])
RIGHT_CURVATURE_TABLE = np.array([0.0, 1.33, 2.49])
MAX_CURVATURE = float(min(LEFT_CURVATURE_TABLE[-1], RIGHT_CURVATURE_TABLE[-1]))


def rear_axle_point(camera: np.ndarray, forward: np.ndarray) -> np.ndarray:
    right = np.stack([-forward[..., 1], forward[..., 0]], axis=-1)
    return camera + CENTERLINE_OFFSET * right - CAMERA_TO_REAR_AXLE * forward


def camera_point(rear: np.ndarray, forward: np.ndarray) -> np.ndarray:
    right = np.stack([-forward[..., 1], forward[..., 0]], axis=-1)
    return rear + CAMERA_TO_REAR_AXLE * forward - CENTERLINE_OFFSET * right


def rear_axle_path(points: np.ndarray, directions: np.ndarray, fallback_forward: np.ndarray) -> np.ndarray:
    tangents = np.diff(points, axis=0, prepend=points[:1])
    if len(points) > 1:
        tangents[0] = points[1] - points[0]
    lengths = np.linalg.norm(tangents, axis=1)
    valid = lengths > 1e-6
    if not valid.any():
        return rear_axle_point(points, np.broadcast_to(fallback_forward, points.shape))
    last_valid = np.maximum.accumulate(np.where(valid, np.arange(len(points)), -1))
    source = np.where(last_valid >= 0, last_valid, int(np.argmax(valid)))
    travel = tangents[source] / lengths[source][:, None]
    return rear_axle_point(points, travel * np.sign(directions)[:, None])


def curvature_for_steer(steer: float) -> float:
    table = RIGHT_CURVATURE_TABLE if steer >= 0 else LEFT_CURVATURE_TABLE
    return float(np.copysign(np.interp(abs(steer), STEER_TABLE, table), steer))


def steer_for_curvature(curvature: float) -> float:
    table = RIGHT_CURVATURE_TABLE if curvature >= 0 else LEFT_CURVATURE_TABLE
    return float(np.copysign(np.interp(abs(curvature), table, STEER_TABLE), curvature))


def wheel_speeds(speed: float, steer: float) -> tuple[float, float]:
    offset = DIFFERENTIAL_GAIN * curvature_for_steer(steer) * REAR_TRACK / 2
    left, right = speed * (1 + offset), speed * (1 - offset)
    scale = max(abs(left), abs(right), 1.0)
    return left / scale, right / scale
