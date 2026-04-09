import struct
from dataclasses import dataclass

from pydantic import BaseModel


class Pose(BaseModel):
    translation: list[float]
    orientation: list[float]
    frame_number: int
    timestamp: int


class CameraIntrinsics(BaseModel):
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int


SENSOR_BUNDLE_SUBJECT = "rabbit.sensor.bundle"
SENSOR_BUNDLE_VERSION = 1
RGB_ENCODING_NONE = 0
RGB_ENCODING_JPEG = 1
DEPTH_ENCODING_MM_U16_LZ4 = "DEPTH_MM_U16_LZ4"

_SENSOR_BUNDLE_HEADER = struct.Struct("<BBIQ7fHHIHHI")


@dataclass(slots=True)
class SensorBundle:
    frame_number: int
    timestamp: int
    translation: tuple[float, float, float]
    orientation: tuple[float, float, float, float]
    depth_width: int
    depth_height: int
    depth_payload: bytes
    rgb_encoding: int = RGB_ENCODING_NONE
    rgb_width: int = 0
    rgb_height: int = 0
    rgb_payload: bytes = b""


def serialize_sensor_bundle(bundle: SensorBundle) -> bytes:
    header = _SENSOR_BUNDLE_HEADER.pack(
        SENSOR_BUNDLE_VERSION,
        bundle.rgb_encoding,
        bundle.frame_number,
        bundle.timestamp,
        *bundle.translation,
        *bundle.orientation,
        bundle.depth_width,
        bundle.depth_height,
        len(bundle.depth_payload),
        bundle.rgb_width,
        bundle.rgb_height,
        len(bundle.rgb_payload),
    )
    return header + bundle.depth_payload + bundle.rgb_payload


def deserialize_sensor_bundle(payload: bytes) -> SensorBundle:
    if len(payload) < _SENSOR_BUNDLE_HEADER.size:
        raise ValueError("Sensor bundle payload is too small")

    (
        version,
        rgb_encoding,
        frame_number,
        timestamp,
        tx,
        ty,
        tz,
        qx,
        qy,
        qz,
        qw,
        depth_width,
        depth_height,
        depth_payload_length,
        rgb_width,
        rgb_height,
        rgb_payload_length,
    ) = _SENSOR_BUNDLE_HEADER.unpack_from(payload)

    if version != SENSOR_BUNDLE_VERSION:
        raise ValueError(f"Unsupported sensor bundle version: {version}")

    offset = _SENSOR_BUNDLE_HEADER.size
    depth_end = offset + depth_payload_length
    rgb_end = depth_end + rgb_payload_length

    if rgb_end != len(payload):
        raise ValueError("Sensor bundle payload length mismatch")

    return SensorBundle(
        frame_number=frame_number,
        timestamp=timestamp,
        translation=(tx, ty, tz),
        orientation=(qx, qy, qz, qw),
        depth_width=depth_width,
        depth_height=depth_height,
        depth_payload=payload[offset:depth_end],
        rgb_encoding=rgb_encoding,
        rgb_width=rgb_width,
        rgb_height=rgb_height,
        rgb_payload=payload[depth_end:rgb_end],
    )
