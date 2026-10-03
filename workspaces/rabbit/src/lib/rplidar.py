from __future__ import annotations

from dataclasses import dataclass

SYNC = 0xA5
SYNC_REPLY = 0x5A
STOP = 0x25
RESET = 0x40
SCAN = 0x20
GET_INFO = 0x50
GET_HEALTH = 0x52
GET_SAMPLERATE = 0x59
SINGLE = 0x0
MULTIPLE = 0x1
DESCRIPTOR_SIZE = 7
NODE_SIZE = 5
FULL_TURN_Q6 = 360 * 64
STOP_SETTLE_S = 0.01
RESET_SETTLE_S = 0.5
BAUD = 460800
BYTE_NS = round(10 * 1e9 / BAUD)
HEALTH_STATUS = {0: "good", 1: "warning", 2: "error"}


class ProtocolError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Descriptor:
    length: int
    mode: int
    data_type: int


SCAN_REPLY = Descriptor(NODE_SIZE, MULTIPLE, 0x81)
INFO_REPLY = Descriptor(20, SINGLE, 0x04)
HEALTH_REPLY = Descriptor(3, SINGLE, 0x06)
SAMPLERATE_REPLY = Descriptor(4, SINGLE, 0x15)


def request(command: int, payload: bytes = b"") -> bytes:
    if not payload:
        return bytes([SYNC, command])
    body = bytes([SYNC, command, len(payload)]) + payload
    checksum = 0
    for byte in body:
        checksum ^= byte
    return body + bytes([checksum])


def encode_descriptor(descriptor: Descriptor) -> bytes:
    word = (descriptor.length & 0x3FFFFFFF) | (descriptor.mode << 30)
    return bytes([SYNC, SYNC_REPLY]) + word.to_bytes(4, "little") + bytes([descriptor.data_type])


def decode_descriptor(data: bytes) -> Descriptor:
    if len(data) != DESCRIPTOR_SIZE or data[0] != SYNC or data[1] != SYNC_REPLY:
        raise ProtocolError(f"bad response descriptor {data.hex()}")
    word = int.from_bytes(data[2:6], "little")
    return Descriptor(word & 0x3FFFFFFF, word >> 30, data[6])


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    model: int
    firmware: str
    hardware: int
    serial: str


def decode_info(data: bytes) -> DeviceInfo:
    if len(data) != INFO_REPLY.length:
        raise ProtocolError(f"device info has {len(data)} bytes")
    return DeviceInfo(data[0], f"{data[2]}.{data[1]:02d}", data[3], data[4:20].hex().upper())


def encode_info(info: DeviceInfo) -> bytes:
    major, minor = (int(part) for part in info.firmware.split("."))
    return bytes([info.model, minor, major, info.hardware]) + bytes.fromhex(info.serial)


@dataclass(frozen=True, slots=True)
class Health:
    status: str
    error_code: int


def decode_health(data: bytes) -> Health:
    if len(data) != HEALTH_REPLY.length:
        raise ProtocolError(f"health has {len(data)} bytes")
    return Health(HEALTH_STATUS.get(data[0], f"unknown {data[0]}"), int.from_bytes(data[1:3], "little"))


@dataclass(frozen=True, slots=True)
class Measurement:
    start: bool
    quality: int
    angle_q6: int
    distance_q2: int

    @property
    def angle_deg(self) -> float:
        return self.angle_q6 / 64.0

    @property
    def distance_mm(self) -> float:
        return self.distance_q2 / 4.0


def decode_node(data: bytes | memoryview) -> Measurement | None:
    start = data[0] & 0x1
    if start == (data[0] >> 1) & 0x1 or not data[1] & 0x1:
        return None
    angle_q6 = (data[1] >> 1) | (data[2] << 7)
    if angle_q6 >= FULL_TURN_Q6:
        return None
    return Measurement(bool(start), data[0] >> 2, angle_q6, data[3] | (data[4] << 8))


def encode_node(node: Measurement) -> bytes:
    first = (node.quality << 2) | (0b01 if node.start else 0b10)
    return bytes([first, ((node.angle_q6 & 0x7F) << 1) | 1, node.angle_q6 >> 7, node.distance_q2 & 0xFF, node.distance_q2 >> 8])


class NodeStream:
    def __init__(self, latency_ns: int = 0):
        self.latency_ns = latency_ns
        self.buffer = bytearray()
        self.bad_nodes = 0
        self.skipped_bytes = 0

    def feed(self, data: bytes, received_ns: int) -> list[tuple[int, Measurement]]:
        self.buffer += data
        nodes: list[tuple[int, Measurement]] = []
        offset = 0
        end = len(self.buffer)
        while end - offset >= NODE_SIZE:
            node = decode_node(memoryview(self.buffer)[offset : offset + NODE_SIZE])
            if node is None:
                self.bad_nodes += 1
                self.skipped_bytes += 1
                offset += 1
                continue
            offset += NODE_SIZE
            nodes.append((received_ns - self.latency_ns - (end - offset) * BYTE_NS, node))
        del self.buffer[:offset]
        return nodes


@dataclass(frozen=True, slots=True)
class Rotation:
    ts_start: int
    ts_end: int
    angles_q6: list[int]
    distances_q2: list[int]
    qualities: list[int]
    measurements: int


class ScanAssembler:
    MIN_POINTS = 50

    def __init__(self):
        self.started = False
        self.measurements = 0
        self.ts_start = 0
        self.ts_end = 0
        self.angles: list[int] = []
        self.distances: list[int] = []
        self.qualities: list[int] = []
        self.short_rotations = 0

    def add(self, ts: int, node: Measurement) -> Rotation | None:
        done = None
        if node.start:
            if self.started and self.measurements >= self.MIN_POINTS:
                done = Rotation(self.ts_start, self.ts_end, self.angles, self.distances, self.qualities, self.measurements)
            elif self.started:
                self.short_rotations += 1
            self.started = True
            self.measurements = 0
            self.ts_start = ts
            self.angles, self.distances, self.qualities = [], [], []
        if not self.started:
            return None
        self.measurements += 1
        self.ts_end = ts
        if node.distance_q2 > 0:
            self.angles.append(node.angle_q6)
            self.distances.append(node.distance_q2)
            self.qualities.append(node.quality)
        return done
