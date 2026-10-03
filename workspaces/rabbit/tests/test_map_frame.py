import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.loc import LOCALIZED, LOST, RELOCALIZING
from lib.map_frame import MapFrame, parse_transform


def pose(x=0.0, y=0.0, z=0.0, yaw_deg=0.0) -> np.ndarray:
    a = math.radians(yaw_deg)
    m = np.eye(4)
    m[:3, :3] = [[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]
    m[:3, 3] = [x, y, z]
    return m


def message(transform=None, status=LOCALIZED, map_id="m1", odom_session="s1"):
    return {
        "status": status,
        "transform": None if transform is None else [float(v) for v in transform.reshape(16)],
        "map_id": map_id,
        "odom_session": odom_session,
    }


def depth():
    return np.zeros((2, 2), dtype=np.float16)


def localized_frame(correction=None) -> MapFrame:
    frame = MapFrame(odom_session="s1")
    frame.receive(message(pose() if correction is None else correction), 0.0)
    return frame


def test_the_map_pose_is_the_correction_applied_to_odometry():
    frame = localized_frame(pose(1.0, 0.0, -2.0, 90.0))
    odom = pose(0.5, 0.137, 0.0, 0.0)
    map_pose = frame.to_map(odom)
    np.testing.assert_allclose(map_pose[:3, 3], [1.0, 0.137, -2.5], atol=1e-12)
    np.testing.assert_allclose(map_pose, pose(1.0, 0.0, -2.0, 90.0) @ odom)


def test_a_correction_below_5_cm_and_2_degrees_keeps_the_map_and_moves_only_the_pose():
    frame = localized_frame()
    frame.store(depth(), pose(), 0.1)
    plan = frame.receive(message(pose(0.04, 0.0, 0.0, 1.5)), 1.0)
    assert not plan.rebuild and not plan.reset
    np.testing.assert_allclose(frame.integration_pose(pose()), pose())
    np.testing.assert_allclose(frame.to_map(pose()), pose(0.04, 0.0, 0.0, 1.5))


def test_a_larger_correction_rebuilds_every_stored_frame_from_its_odometry_pose():
    frame = localized_frame()
    frame.store(depth(), pose(1.0, 0.0, 0.0), 0.1)
    frame.store(depth(), pose(2.0, 0.0, 0.0), 0.2)
    correction = pose(0.0, 0.0, 0.3, 10.0)
    plan = frame.receive(message(correction), 1.0)
    assert plan.rebuild and not plan.reset
    poses = [m for _, m in frame.rebuild_poses()]
    np.testing.assert_allclose(poses[0], correction @ pose(1.0, 0.0, 0.0))
    np.testing.assert_allclose(poses[1], correction @ pose(2.0, 0.0, 0.0))
    np.testing.assert_allclose(frame.integration_pose(pose(3.0)), correction @ pose(3.0))


def test_small_steps_that_add_up_rebuild_against_the_correction_the_map_was_built_with():
    frame = localized_frame()
    frame.store(depth(), pose(), 0.1)
    plans = [frame.receive(message(pose(0.03 * i, 0.0, 0.0)), float(i)) for i in range(1, 4)]
    assert [p.rebuild for p in plans] == [False, True, False]


def test_frames_taken_while_relocalizing_wait_and_enter_the_map_with_the_first_correction():
    frame = MapFrame(odom_session="s1")
    frame.receive(message(status=RELOCALIZING), 0.0)
    assert not frame.store(depth(), pose(1.0), 0.5)
    assert not frame.store(depth(), pose(2.0), 1.0)
    assert frame.integration_pose(pose()) is None and frame.to_map(pose()) is None
    correction = pose(5.0, 0.0, 0.0, 180.0)
    plan = frame.receive(message(correction), 2.0)
    assert plan.rebuild
    np.testing.assert_allclose(frame.rebuild_poses()[1][1], correction @ pose(2.0))
    assert frame.health(2.0)["pending"] == 0
    assert frame.store(depth(), pose(3.0), 2.5)


def test_after_losing_localization_the_waiting_frames_are_flushed_without_a_rebuild():
    frame = localized_frame()
    frame.store(depth(), pose(1.0), 0.5)
    frame.receive(message(pose(), status=LOST), 1.0)
    assert not frame.localized(1.0)
    assert not frame.store(depth(), pose(2.0), 1.5)
    plan = frame.receive(message(pose(0.01)), 2.0)
    assert plan.flush and not plan.rebuild
    assert [m[0, 3] for _, m in frame.pending_poses()] == [2.0]
    assert frame.health(2.0)["pending"] == 0


def test_a_silent_rabbit_loc_stops_integration():
    frame = localized_frame()
    assert frame.localized(5.0)
    assert not frame.localized(5.1)
    assert not frame.store(depth(), pose(1.0), 6.0)


def test_a_new_map_id_resets_the_map_and_reintegrates_the_frames_in_the_new_frame():
    frame = localized_frame(pose(1.0))
    frame.store(depth(), pose(1.0), 0.1)
    plan = frame.receive(message(status=RELOCALIZING, map_id="m2"), 1.0)
    assert plan.reset and not plan.rebuild
    assert frame.to_map(pose()) is None and frame.health(1.0)["pending"] == 1
    plan = frame.receive(message(pose(1.0), map_id="m2"), 2.0)
    assert plan.rebuild and frame.resets == 1
    np.testing.assert_allclose(frame.rebuild_poses()[0][1], pose(2.0))


def test_a_map_file_of_another_map_is_reset_on_the_first_message():
    frame = MapFrame(odom_session="s1", map_id="old")
    assert frame.receive(message(pose()), 0.0).reset


def test_a_correction_for_another_odometry_session_is_ignored():
    frame = localized_frame(pose(1.0))
    plan = frame.receive(message(pose(9.0), odom_session="s0"), 1.0)
    assert not plan.rebuild
    np.testing.assert_allclose(frame.to_map(pose()), pose(1.0))


def test_a_malformed_transform_is_rejected_and_counted():
    frame = localized_frame(pose(1.0))
    bad = pose(2.0)
    bad[0, 0] = 3.0
    frame.receive(message(bad), 1.0)
    assert frame.rejected == 1
    np.testing.assert_allclose(frame.to_map(pose()), pose(1.0))
    assert parse_transform([float("nan")] * 16) is None
    assert parse_transform([1.0, 2.0]) is None
    mirrored = np.diag([-1.0, 1.0, 1.0, 1.0])
    assert parse_transform(mirrored.reshape(16)) is None


def test_saving_the_map_keeps_only_the_frames_that_are_not_in_it_yet():
    frame = MapFrame(odom_session="s1", max_frames=2)
    frame.receive(message(status=RELOCALIZING), 0.0)
    frame.store(depth(), pose(9.0), 0.1)
    frame.receive(message(pose()), 0.2)
    frame.pending_poses()
    frame.receive(message(pose(), status=LOST), 0.3)
    frame.store(depth(), pose(10.0), 0.4)
    frame.receive(message(pose()), 0.5)
    for x in (1.0, 2.0):
        frame.store(depth(), pose(x), 1.0)
    assert frame.over_capacity()
    frame.receive(message(pose(), status=LOST), 2.0)
    frame.store(depth(), pose(3.0), 2.5)
    frame.saved()
    assert [f.odom_from_camera[0, 3] for f in frame.frames] == [10.0, 3.0]


def test_nearby_frames_are_not_stored_twice_and_waiting_frames_are_capped():
    frame = MapFrame(odom_session="s1", max_pending=2)
    for x in (0.0, 0.1, 0.5, 1.0, 1.5):
        frame.store(depth(), pose(x), 0.0)
    assert [f.odom_from_camera[0, 3] for f in frame.frames] == [1.0, 1.5]
