import math

import numpy as np
import pytest

rabbit_nvblox = pytest.importorskip("rabbit_nvblox")

FX = FY = 80.0
CX, CY = 80.0, 45.0


def mesh_vertices(mapper) -> np.ndarray:
    blocks = mapper.take_mesh_updates(True)
    return np.concatenate([vertices for *_, vertices, _ in blocks if len(vertices)])


def integrate_wall(yaw_deg: float) -> np.ndarray:
    mapper = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0)
    depth = np.full((90, 160), 2.0, dtype=np.float32)
    yaw = math.radians(yaw_deg)
    pose = np.eye(4, dtype=np.float32)
    pose[:3, :3] = [[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]]
    pose[:3, 3] = [1.0, 0.5, 3.0]
    for _ in range(5):
        mapper.integrate(depth, FX, FY, CX, CY, pose, -10.0)
    return mesh_vertices(mapper)


def test_wall_ahead_of_the_camera_lands_along_minus_z_in_the_y_up_world():
    vertices = integrate_wall(0.0)
    assert np.median(vertices[:, 2]) == pytest.approx(1.0, abs=0.05)
    assert np.median(vertices[:, 0]) == pytest.approx(1.0, abs=0.2)
    assert np.median(vertices[:, 1]) == pytest.approx(0.5, abs=0.2)


def test_camera_turned_left_puts_the_wall_along_minus_x():
    vertices = integrate_wall(90.0)
    assert np.median(vertices[:, 0]) == pytest.approx(-1.0, abs=0.05)
    assert np.median(vertices[:, 2]) == pytest.approx(3.0, abs=0.2)


def test_saved_map_reloads_with_the_same_surface(tmp_path):
    mapper = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0)
    depth = np.full((90, 160), 2.0, dtype=np.float32)
    pose = np.eye(4, dtype=np.float32)
    for _ in range(5):
        mapper.integrate(depth, FX, FY, CX, CY, pose, -10.0)
    path = str(tmp_path / "room.nvblx")
    assert mapper.save(path)

    restored = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0)
    assert restored.load(path)
    assert np.median(mesh_vertices(restored)[:, 2]) == pytest.approx(-2.0, abs=0.05)


def test_depth_reflected_below_the_floor_is_clipped_onto_the_floor():
    mapper = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0)
    pitch = math.radians(-30.0)
    pose = np.eye(4, dtype=np.float32)
    pose[:3, :3] = [[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]]
    pose[1, 3] = 0.3
    depth = np.full((90, 160), 3.0, dtype=np.float32)
    for _ in range(5):
        mapper.integrate(depth, FX, FY, CX, CY, pose, 0.0)
    vertices = mesh_vertices(mapper)
    assert vertices[:, 1].min() > -0.08
    assert np.median(vertices[:, 1]) == pytest.approx(0.0, abs=0.05)


def test_clearing_below_the_floor_removes_the_reflected_room():
    mapper = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0)
    depth = np.full((90, 160), 2.0, dtype=np.float32)
    pose = np.eye(4, dtype=np.float32)
    pose[1, 3] = -2.0
    for _ in range(5):
        mapper.integrate(depth, FX, FY, CX, CY, pose, -10.0)
    mapper.clear_below(-0.15)
    assert len(mesh_vertices_or_empty(mapper)) == 0


def mesh_vertices_or_empty(mapper) -> np.ndarray:
    blocks = mapper.take_mesh_updates(True)
    meshes = [vertices for *_, vertices, _ in blocks if len(vertices)]
    return np.concatenate(meshes) if meshes else np.empty((0, 3))


def test_depth_just_above_the_floor_is_flattened_onto_it():
    mapper = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0, floor_snap=0.03)
    pitch = math.radians(-35.0)
    pose = np.eye(4, dtype=np.float32)
    pose[:3, :3] = [[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]]
    pose[1, 3] = 0.3
    rows, cols = np.mgrid[0:90, 0:160].astype(np.float32)
    rise = pose[1, 0] * (cols - CX) / FX - pose[1, 1] * (rows - CY) / FY - pose[1, 2]
    depth = ((0.02 - 0.3) / rise).astype(np.float32)
    for _ in range(5):
        mapper.integrate(depth, FX, FY, CX, CY, pose, 0.0)
    vertices = mesh_vertices(mapper)
    assert np.median(vertices[:, 1]) == pytest.approx(0.0, abs=0.01)


def grid_value(origin, resolution, cells, x, z) -> int:
    return int(cells[int((z - origin[1]) / resolution), int((x - origin[0]) / resolution)])


def test_clearance_grid_measures_distance_to_a_wall_ahead():
    mapper = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0, floor_snap=0.03)
    pose = np.eye(4, dtype=np.float32)
    pose[1, 3] = 0.25
    depth = np.full((90, 160), 2.0, dtype=np.float32)
    for _ in range(10):
        mapper.integrate(depth, FX, FY, CX, CY, pose, 0.0)
    origin_x, origin_z, resolution, cells = mapper.clearance_grid(0.0)
    origin = (origin_x, origin_z)
    assert min(grid_value(origin, resolution, cells, 0.0, z) for z in (-2.15, -2.1, -2.05, -2.0)) == 0
    assert grid_value(origin, resolution, cells, 0.0, -1.0) == pytest.approx(1000, abs=100)
    assert grid_value(origin, resolution, cells, 0.0, -1.0) > grid_value(origin, resolution, cells, 0.0, -1.5)


def test_clearance_grid_is_available_right_after_loading_a_map(tmp_path):
    mapper = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0, floor_snap=0.03)
    pose = np.eye(4, dtype=np.float32)
    pose[1, 3] = 0.25
    depth = np.full((90, 160), 2.0, dtype=np.float32)
    for _ in range(10):
        mapper.integrate(depth, FX, FY, CX, CY, pose, 0.0)
    path = str(tmp_path / "room.nvblx")
    assert mapper.save(path)

    restored = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0, floor_snap=0.03)
    assert restored.load(path)
    origin_x, origin_z, resolution, cells = restored.clearance_grid(0.0)
    assert grid_value((origin_x, origin_z), resolution, cells, 0.0, -1.0) == pytest.approx(1000, abs=100)


def integrate_wall_at(mapper, x: float):
    pose = np.eye(4, dtype=np.float32)
    pose[0, 3] = x
    pose[1, 3] = 0.25
    depth = np.full((90, 160), 2.0, dtype=np.float32)
    for _ in range(5):
        mapper.integrate(depth, FX, FY, CX, CY, pose, 0.0)


def test_far_away_debris_neither_inflates_the_grid_nor_survives_clearing():
    mapper = rabbit_nvblox.Mapper(0.05, 4.0, 0.3, 6.0, floor_snap=0.03)
    integrate_wall_at(mapper, 0.0)
    integrate_wall_at(mapper, 500.0)
    *_, windowed = mapper.clearance_grid(0.0, 0.0, 0.0, 25.0)
    assert windowed.shape[1] * 0.05 <= 50.0

    mapper.clear_outside(0.0, 0.0, 50.0)
    *_, cleared = mapper.clearance_grid(0.0)
    assert cleared.shape[1] * 0.05 < 50.0


def floor_and_wall_depth(camera_height: float, wall_distance: float) -> np.ndarray:
    rows, cols = np.mgrid[0:90, 0:160].astype(np.float32)
    down = (rows - CY) / FY
    floor = np.where(down > 1e-3, camera_height / np.maximum(down, 1e-3), np.inf)
    return np.minimum(floor, wall_distance).astype(np.float32)


def test_far_floor_seen_through_a_one_degree_pitch_error_is_not_an_obstacle_but_a_far_wall_is():
    mapper = rabbit_nvblox.Mapper(0.05, 5.0, 0.3, 6.0, floor_snap=0.03)
    depth = floor_and_wall_depth(0.25, 4.5)
    pitch = math.radians(1.0)
    pose = np.eye(4, dtype=np.float32)
    pose[:3, :3] = [[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]]
    pose[1, 3] = 0.25
    for _ in range(10):
        mapper.integrate(depth, FX, FY, CX, CY, pose, 0.0)
    origin_x, origin_z, resolution, cells = mapper.clearance_grid(0.0)
    origin = (origin_x, origin_z)
    assert all(grid_value(origin, resolution, cells, 0.0, -z) != 0 for z in (2.2, 2.6, 3.0, 3.5, 4.0))
    assert min(grid_value(origin, resolution, cells, 0.0, -z) for z in (4.4, 4.45, 4.5, 4.55)) == 0
