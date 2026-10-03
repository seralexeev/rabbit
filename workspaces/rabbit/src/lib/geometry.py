import math

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


def rotation_deg(rotation: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0))))


MAX_POSE_HEIGHT_M = 3.0
MAX_POSE_RANGE_M = 200.0


def plausible_position(translation, floor_y: float) -> bool:
    x, y, z = (float(v) for v in translation)
    return abs(y - floor_y) < MAX_POSE_HEIGHT_M and abs(x) < MAX_POSE_RANGE_M and abs(z) < MAX_POSE_RANGE_M


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


def planar_pose(translation, orientation) -> tuple[np.ndarray, np.ndarray]:
    x, y, z, w = orientation
    forward = np.array([-2 * (x * z + y * w), -(1 - 2 * (x * x + y * y))])
    return np.array([translation[0], translation[2]], dtype=float), forward / np.linalg.norm(forward)


def rigid_transform(
    from_position: np.ndarray, from_forward: np.ndarray, to_position: np.ndarray, to_forward: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    angle = math.atan2(
        from_forward[0] * to_forward[1] - from_forward[1] * to_forward[0], float(from_forward @ to_forward)
    )
    cos, sin = math.cos(angle), math.sin(angle)
    rotation = np.array([[cos, -sin], [sin, cos]])
    return rotation, to_position - rotation @ from_position


def matrix_to_quaternion(rotation: np.ndarray) -> list[float]:
    m = np.asarray(rotation, dtype=float)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = 2.0 * math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    return q
