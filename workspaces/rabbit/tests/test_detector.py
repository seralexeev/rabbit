import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.detector import TrackConfirmer, normalized_box, object_corners, to_world
from lib.geometry import quaternion_to_matrix


def test_normalized_box_spans_rotated_corners_and_clips_to_image():
    corners = np.array([[-20, 100], [640, 80], [660, 400], [0, 420]])
    assert normalized_box(corners, 1280, 720) == [0.0, 0.1111, 0.5156, 0.5833]


def test_to_world_rotates_camera_points_and_measures_height_from_floor():
    half = np.sqrt(0.5)
    rotation = quaternion_to_matrix([0.0, half, 0.0, half])
    points = to_world(np.array([[0.0, 0.5, -2.0], [0.0, 0.0, 0.0]]), rotation, np.array([1.0, 0.2, 3.0]), floor_y=0.05)
    assert points == [[-1.0, 0.65, 3.0], [1.0, 0.15, 3.0]]


def test_a_track_seen_once_is_never_published():
    tracks = TrackConfirmer(min_hits=3, forget_after=8)
    assert tracks.update([1, 2]) == set()
    assert tracks.update([1]) == set()
    assert tracks.update([1]) == {1}
    for _ in range(9):
        tracks.update([])
    assert tracks.update([2]) == set()


def test_a_wide_desk_box_is_shallow_along_the_view_ray_not_a_cube():
    corners = np.array(object_corners(np.array([0.0, 0.4, -3.0]), np.array([0.0, 0.14, 0.0]), "desk", 2.5, 0.8))
    assert np.ptp(corners[:, 0]) == np.float64(2.5)
    assert np.ptp(corners[:, 2]) == np.float64(0.75)
    assert np.ptp(corners[:, 1]) == np.float64(0.8)
    assert np.allclose(corners[:4, 1], 0.8) and np.allclose(corners[4:, 1], 0.0)
