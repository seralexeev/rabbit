import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.safety import bin_scan


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
