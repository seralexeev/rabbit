import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pyzed = types.ModuleType("pyzed")
pyzed.sl = mock.MagicMock()
with mock.patch.dict(sys.modules, {"pyzed": pyzed, "pyzed.sl": pyzed.sl, "cv2": mock.MagicMock(), "rabbit_nvblox": mock.MagicMock()}):
    from node import zed


@pytest.fixture
def node(tmp_path, monkeypatch):
    monkeypatch.setattr(zed, "NVBLOX_FILE", tmp_path / "room.nvblx")
    monkeypatch.setattr(zed, "MESH_FILE", tmp_path / "room.ply")
    camera = zed.Node()
    camera.mapper.save.side_effect = lambda path: Path(path).write_bytes(b"map") or True
    return camera


def test_a_failing_map_update_restarts_the_camera_instead_of_silently_freezing_the_map(node):
    node.mapper.integrate.side_effect = RuntimeError("CUDA out of memory")
    node.depth_intrinsics = (100.0, 100.0, 80.0, 45.0)
    node.map_job = (np.zeros((90, 160), dtype=np.float32), np.eye(4, dtype=np.float32), 0)
    restarts = []
    node._restart_process = lambda reason, archive: restarts.append(reason)

    node._map_loop()

    assert restarts == ["the map worker failed"] and node.mapping_state == "FAILED"


def test_stored_frames_are_baked_into_the_saved_map_before_they_pile_up(node):
    depth = np.ones((90, 160), dtype=np.float32)
    sizes = []
    for i in range(1000):
        pose = np.eye(4)
        pose[0, 3] = 0.3 * i
        node._store_frame(depth, pose, 0, np.eye(4))
        sizes.append(len(node.stored_frames))

    assert max(sizes) <= node.MAX_STORED_FRAMES + 1 and node.map_from_file


def test_a_recording_stops_before_it_fills_the_disk(node, monkeypatch):
    monkeypatch.setattr(zed.shutil, "disk_usage", lambda path: SimpleNamespace(free=1024**3))
    node.zed.get_recording_status.return_value = SimpleNamespace(number_frames_encoded=100, number_frames_ingested=100, average_compression_time=5.0)
    node.recording_since = 0.0

    asyncio.run(node.publish_health())

    assert node.recording_since is None and node.zed.disable_recording.called


def test_a_camera_that_keeps_failing_to_grab_restarts_the_process(node):
    restarts = []
    node._restart_process = lambda reason, archive: restarts.append(reason)

    for _ in range(node.MAX_GRAB_FAILURES):
        with pytest.raises(RuntimeError):
            node._grab()

    assert len(restarts) == 1 and restarts[0].startswith("grab keeps failing")


def y_up_pose(x=0.0, y=0.0, z=0.0, yaw_deg=0.0) -> np.ndarray:
    a = np.radians(yaw_deg)
    m = np.eye(4)
    m[:3, :3] = [[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]]
    m[:3, 3] = [x, y, z]
    return m


@pytest.fixture
def applying(tmp_path, monkeypatch):
    monkeypatch.setenv("LOC_MODE", "apply")
    monkeypatch.setattr(zed, "LOC_NVBLOX_FILE", tmp_path / "loc.nvblx")
    monkeypatch.setattr(zed, "LOC_NVBLOX_ID_FILE", tmp_path / "loc.nvblx.id")
    monkeypatch.setattr(zed, "AREA_ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(zed, "MESH_FILE", tmp_path / "room.ply")
    camera = zed.Node()
    camera.mapper = mock.MagicMock()
    camera.mapper.save.side_effect = lambda path: Path(path).write_bytes(b"map") or True
    camera.mapper.take_mesh_updates.return_value = []
    camera.mapper.clearance_grid.return_value = (0.0, 0.0, 0.05, np.empty((0, 0)))
    camera.depth_intrinsics = (100.0, 100.0, 80.0, 45.0)
    camera.pose = SimpleNamespace(twist=np.zeros(6), pose_covariance=np.zeros(36), pose_confidence=90)
    return camera


def map_odom(camera, transform, status="localized", map_id="m1"):
    payload = {
        "status": status,
        "transform": None if transform is None else transform.reshape(16).tolist(),
        "map_id": map_id,
        "odom_session": camera.session,
    }
    asyncio.run(camera.on_loc_map_odom(SimpleNamespace(data=zed.json.dumps(payload).encode())))


def integrated_poses(camera):
    return [np.asarray(call.args[5], dtype=float) for call in camera.mapper.integrate.call_args_list]


def test_area_memory_is_off_only_when_the_map_frame_comes_from_rabbit_loc(applying, monkeypatch):
    assert applying.tracking_parameters.enable_area_memory is False and not applying.mapping_mode
    monkeypatch.setenv("LOC_MODE", "shadow")
    assert zed.Node().tracking_parameters.enable_area_memory is True


def test_the_published_map_pose_is_the_loc_correction_applied_to_odometry(applying):
    applying.odom = y_up_pose(0.5, 0.137, -1.0, 30.0)
    correction = y_up_pose(2.0, 0.0, 1.0, 90.0)
    map_odom(applying, correction)

    pose = applying._read_pose()

    np.testing.assert_allclose(pose["translation"], (correction @ applying.odom)[:3, 3], atol=1e-4)
    np.testing.assert_allclose(pose["odom"]["translation"], [0.5, 0.137, -1.0], atol=1e-4)


def test_frames_wait_while_relocalizing_and_enter_the_map_with_the_first_correction(applying):
    depth = np.ones((90, 160), dtype=np.float32)
    map_odom(applying, None, status="relocalizing")
    applying._integrate_odom_frame(depth, y_up_pose(1.0), 0)
    applying._integrate_odom_frame(depth, y_up_pose(2.0), 0)
    assert integrated_poses(applying) == []
    assert asyncio.run(_relocalizing(applying)) is True

    correction = y_up_pose(5.0, 0.0, 0.0, 180.0)
    map_odom(applying, correction)
    applying._apply_plan(applying.map_plan)
    applying._integrate_odom_frame(depth, y_up_pose(3.0), 0)

    expected = [correction @ y_up_pose(x) for x in (1.0, 2.0, 3.0)]
    for got, want in zip(integrated_poses(applying), expected, strict=True):
        np.testing.assert_allclose(got, want, atol=1e-5)


async def _relocalizing(camera) -> bool:
    published = []

    async def capture(subject, payload):
        published.append(payload)

    camera.status = {"spatial_memory_status": "OFF"}
    camera.publish_json = capture
    await camera.publish_health()
    return published[0]["relocalizing"]


def test_a_correction_beyond_5_cm_rebuilds_the_map_from_the_saved_file_and_the_odometry_frames(applying):
    depth = np.ones((90, 160), dtype=np.float32)
    map_odom(applying, np.eye(4))
    applying._integrate_odom_frame(depth, y_up_pose(1.0), 0)
    applying.map_from_file = True
    applying.mapper.integrate.reset_mock()

    map_odom(applying, y_up_pose(0.0, 0.0, 0.2))
    assert applying.map_plan.rebuild
    applying._apply_plan(applying.map_plan)

    applying.mapper.load.assert_called_once_with(str(zed.LOC_NVBLOX_FILE))
    np.testing.assert_allclose(integrated_poses(applying)[0], y_up_pose(1.0, 0.0, 0.2), atol=1e-5)


def test_a_new_loc_map_archives_the_nvblox_map_and_starts_an_empty_one(applying):
    map_odom(applying, np.eye(4))
    applying._integrate_odom_frame(np.ones((90, 160), dtype=np.float32), y_up_pose(1.0), 0)
    applying._save_nvblox()
    assert zed.LOC_NVBLOX_ID_FILE.read_text() == "m1"

    map_odom(applying, None, status="relocalizing", map_id="m2")
    applying._apply_plan(applying.map_plan)

    assert applying.mapper.reset.called and not zed.LOC_NVBLOX_FILE.exists() and not applying.map_from_file
    assert applying.map_id == "m2" and list((zed.AREA_ARCHIVE_DIR).glob("loc.*.nvblx"))
