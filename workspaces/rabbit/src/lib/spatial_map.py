import struct
from pathlib import Path

import numpy as np

MAP_CHUNKS_SUBJECT = "rabbit.map.chunks"
MAP_SNAPSHOT_SUBJECT = "rabbit.map.snapshot"
MAP_SAVE_SUBJECT = "rabbit.map.save"
MAP_DIR = Path("/rabbit/data/map")
AREA_FILE = MAP_DIR / "room.area"
MESH_FILE = MAP_DIR / "room.ply"
CHUNKS_FILE = MAP_DIR / "room.chunks"
AREA_ARCHIVE_DIR = MAP_DIR / "archive"

_CHUNK_HEADER = struct.Struct("<IIIfff")


def encode_chunk(index: int, vertices: np.ndarray, triangles: np.ndarray) -> bytes:
    points = np.asarray(vertices, dtype=np.float64)[:, :3]
    origin = (points.min(axis=0) + points.max(axis=0)) / 2.0 if len(points) else np.zeros(3)
    positions = np.round((points - origin) * 1000.0).astype("<i2")
    indices = np.asarray(triangles, dtype="<u2")
    body = positions.tobytes() + indices.tobytes()
    return b"".join(
        (
            _CHUNK_HEADER.pack(index, len(positions), len(indices), *origin),
            body,
            b"\0" * (-len(body) % 4),
        )
    )


def decode_chunks(payload: bytes) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    chunks = {}
    offset = 0
    while offset < len(payload):
        index, vertex_count, triangle_count, *origin = _CHUNK_HEADER.unpack_from(payload, offset)
        offset += _CHUNK_HEADER.size
        vertices = np.frombuffer(payload, dtype="<i2", count=vertex_count * 3, offset=offset)
        offset += vertex_count * 6
        triangles = np.frombuffer(payload, dtype="<u2", count=triangle_count * 3, offset=offset)
        offset += triangle_count * 6
        offset += -(vertex_count * 6 + triangle_count * 6) % 4
        chunks[index] = (
            (vertices.reshape(-1, 3) / 1000.0 + np.asarray(origin)).astype(np.float32),
            triangles.reshape(-1, 3).astype(np.int32),
        )
    return chunks
