import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.spatial_map import decode_chunks, encode_chunk


def test_chunks_far_from_the_origin_survive_encoding():
    vertices = np.array([[-8.9, 0.02, -138.4], [-7.2, 0.31, -137.1], [-8.1, 1.4, -139.9]])
    triangles = np.array([[0, 1, 2]])

    decoded = decode_chunks(encode_chunk(7, vertices, triangles) + encode_chunk(8, np.empty((0, 3)), np.empty((0, 3))))

    assert np.allclose(decoded[7][0], vertices, atol=0.001)
    assert decoded[7][1].tolist() == [[0, 1, 2]]
    assert decoded[8][0].shape == (0, 3)
