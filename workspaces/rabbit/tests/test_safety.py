import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.safety import bin_scan, free_distance, heights_above_floor


def polar(degrees: list[float], ranges: list[float]) -> tuple[np.ndarray, np.ndarray]:
    angles = np.radians(degrees)
    distances = np.array(ranges)
    return distances * np.cos(angles), distances * np.sin(angles)


def test_bin_scan_ignores_isolated_points_but_keeps_dense_obstacles():
    along, across = polar([-45] * 4 + [-15] * 5 + [15] * 2, [0.05, 1.0, 1.1, 1.2, 2.0, 2.1, 2.2, 2.3, 2.4, 0.5, 0.6])
    ranges = bin_scan(along, across, half_fov_deg=60, bins=4, min_points=3)
    assert ranges[:2].tolist() == [1.1, 2.2]
    assert np.isinf(ranges[2:]).all()


def test_bin_scan_without_points_is_empty():
    assert np.isinf(bin_scan(np.empty(0), np.empty(0), half_fov_deg=60, bins=4, min_points=3)).all()


def test_heights_above_floor_removes_floor_tilt_but_keeps_obstacles():
    rng = np.random.default_rng(0)
    floor_xz = rng.uniform([-1.5, 0.3], [1.5, 3.0], size=(3000, 2))
    floor_y = 0.03 * floor_xz[:, 1] - 0.01 + rng.normal(0, 0.005, len(floor_xz))
    box_xz = rng.uniform([0.2, 1.8], [0.4, 2.0], size=(300, 2))
    box_y = 0.03 * box_xz[:, 1] - 0.01 + rng.uniform(0.05, 0.2, len(box_xz))

    heights = heights_above_floor(np.vstack([floor_xz, box_xz]), np.concatenate([floor_y, box_y]))

    assert (floor_y > 0.04).sum() > 1000
    assert np.abs(heights[:3000]).max() < 0.03
    assert heights[3000:].min() > 0.04


def test_free_distance_ignores_points_beyond_its_reach_and_still_stops_at_close_ones():
    far = np.column_stack([np.linspace(2.0, 5.0, 3000), np.zeros(3000)])
    near = np.array([[0.8, 0.0]])

    assert free_distance(far, 0.0, 1.0) == 1.0
    assert free_distance(np.vstack([far, near]), 0.0, 1.0) == pytest.approx(0.8 - 0.2245 - 0.04, abs=0.021)
