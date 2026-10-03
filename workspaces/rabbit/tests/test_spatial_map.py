import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.spatial_map import GRID_UNKNOWN, decode_chunks, decode_grid, encode_chunk, encode_grid


def test_chunks_far_from_the_origin_survive_encoding():
    vertices = np.array([[-8.9, 0.02, -138.4], [-7.2, 0.31, -137.1], [-8.1, 1.4, -139.9]])
    triangles = np.array([[0, 1, 2]])

    decoded = decode_chunks(encode_chunk(7, vertices, triangles) + encode_chunk(8, np.empty((0, 3)), np.empty((0, 3))))

    assert np.allclose(decoded[7][0], vertices, atol=0.001)
    assert decoded[7][1].tolist() == [[0, 1, 2]]
    assert decoded[8][0].shape == (0, 3)


def test_grid_keeps_unknown_occupied_and_clearance_cells_in_place():
    clearance = np.array([[GRID_UNKNOWN, 0, 120], [450, GRID_UNKNOWN, 32767]], dtype=np.int16)

    origin, resolution, decoded = decode_grid(encode_grid((-3.25, 7.5), 0.05, clearance))

    assert origin == (-3.25, 7.5)
    assert resolution == pytest.approx(0.05)
    assert decoded.tolist() == clearance.tolist()
