import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.geometry import camera_point, rear_axle_path, rear_axle_point


def test_rear_axle_path_keeps_the_axle_behind_the_camera_in_both_gears():
    facing_minus_z = np.array([0.0, -1.0])
    expected = rear_axle_point(np.array([[0.0, -0.1], [0.0, -0.2]]), facing_minus_z)
    forward_path = rear_axle_path(np.array([[0.0, -0.1], [0.0, -0.2]]), np.array([1.0, 1.0]), facing_minus_z)
    reverse_path = rear_axle_path(np.array([[0.0, -0.2], [0.0, -0.1]]), np.array([-1.0, -1.0]), facing_minus_z)
    assert np.allclose(forward_path, expected)
    assert np.allclose(reverse_path, expected[::-1])


def test_rear_axle_path_holds_heading_over_repeated_points():
    path = rear_axle_path(np.array([[0.0, -0.1], [0.0, -0.1], [0.0, -0.2]]), np.array([1.0, 1.0, 1.0]), np.array([1.0, 0.0]))
    assert np.allclose(path[1], rear_axle_point(np.array([0.0, -0.1]), np.array([0.0, -1.0])))


def test_camera_point_inverts_rear_axle_point():
    camera, forward = np.array([0.3, -1.2]), np.array([0.6, 0.8])
    assert np.allclose(camera_point(rear_axle_point(camera, forward), forward), camera)
