import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.geometry import camera_point, matrix_to_quaternion, plausible_position, quaternion_to_matrix, rear_axle_path, rear_axle_point, rigid_transform


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


def test_millimetre_poses_from_the_sdk_after_relocalizing_are_implausible():
    assert not plausible_position([-2803.18, 64.24, -3331.73], floor_y=-0.04)
    assert not plausible_position([-77.1, 11.4, -341.3], floor_y=0.0)
    assert plausible_position([-2.80, 0.10, -3.33], floor_y=-0.04)
    assert plausible_position([0.0, 0.83, 0.0], floor_y=0.0)


def test_matrix_to_quaternion_round_trips_through_every_branch():
    for quaternion in ([0.0, 0.0, 0.0, 1.0], [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.3, -0.5, 0.1, 0.8]):
        q = np.array(quaternion) / np.linalg.norm(quaternion)
        assert np.allclose(quaternion_to_matrix(matrix_to_quaternion(quaternion_to_matrix(q))), quaternion_to_matrix(q))


def test_rigid_transform_maps_the_odometry_pose_onto_the_map_pose():
    rotation, translation = rigid_transform(np.array([1.0, 2.0]), np.array([1.0, 0.0]), np.array([-3.0, 0.5]), np.array([0.0, 1.0]))
    assert np.allclose(rotation @ np.array([1.0, 2.0]) + translation, [-3.0, 0.5])
    assert np.allclose(rotation @ np.array([1.0, 0.0]), [0.0, 1.0])
