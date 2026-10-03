import math
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib import rplidar
from lib.hardware import room_ranges
from lib.lidar import Mount, decode_scan, deskew, encode_scan, masked, point_times, points_xy, sector_minimums
from lib.simulation import Robot, lidar_rotation, room_grid


def node_bytes(start: bool, quality: int, angle_deg: float, distance_mm: float) -> bytes:
    return rplidar.encode_node(rplidar.Measurement(start, quality, round(angle_deg * 64), round(distance_mm * 4)))


def test_requests_and_descriptors_match_the_bytes_in_the_slamtec_protocol():
    assert rplidar.request(rplidar.SCAN) == bytes.fromhex("a520")
    assert rplidar.request(0x82, bytes(5)) == bytes.fromhex("a5 82 05 00 00 00 00 00 22")
    assert rplidar.decode_descriptor(bytes.fromhex("a55a0500004081")) == rplidar.SCAN_REPLY
    assert rplidar.decode_descriptor(bytes.fromhex("a55a1400000004")) == rplidar.INFO_REPLY
    assert rplidar.decode_descriptor(bytes.fromhex("a55a0300000006")) == rplidar.HEALTH_REPLY
    assert rplidar.encode_descriptor(rplidar.SCAN_REPLY) == bytes.fromhex("a55a0500004081")
    with pytest.raises(rplidar.ProtocolError):
        rplidar.decode_descriptor(bytes.fromhex("a5a50500004081"))


def test_a_measurement_node_decodes_quality_start_angle_and_distance_bit_by_bit():
    node = rplidar.decode_node(bytes.fromhex("bd012da00f"))
    assert node == rplidar.Measurement(start=True, quality=47, angle_q6=5760, distance_q2=4000)
    assert (node.angle_deg, node.distance_mm) == (90.0, 1000.0)
    assert rplidar.decode_node(bytes.fromhex("bf012da00f")) is None
    assert rplidar.decode_node(bytes.fromhex("bd002da00f")) is None
    assert rplidar.decode_node(node_bytes(False, 10, 359.98, 12000.0)).angle_q6 == round(359.98 * 64)


def test_info_and_health_payloads_decode():
    info = rplidar.decode_info(bytes([0x41, 1, 1, 18]) + bytes(range(16)))
    assert (info.model, info.firmware, info.hardware, info.serial[:6]) == (0x41, "1.01", 18, "000102")
    assert rplidar.decode_health(bytes([2, 0x34, 0x12])) == rplidar.Health("error", 0x1234)


def test_the_stream_resynchronises_after_garbage_and_back_dates_each_node():
    stream = rplidar.NodeStream()
    good = [node_bytes(i == 0, 30, i * 0.72, 500 + i) for i in range(6)]
    data = good[0] + good[1] + b"\x00" + b"".join(good[2:])
    nodes = stream.feed(data[:7], 1_000_000_000) + stream.feed(data[7:], 2_000_000_000)
    assert [round(n.distance_mm) for _, n in nodes] == [500, 501, 502, 503, 504, 505]
    assert stream.bad_nodes == 1 and stream.skipped_bytes == 1
    times = [ts for ts, _ in nodes]
    assert times[-1] == 2_000_000_000 and times[-2] == 2_000_000_000 - rplidar.NODE_SIZE * rplidar.BYTE_NS


def test_rotations_split_on_the_start_flag_and_drop_points_without_a_return():
    assembler = rplidar.ScanAssembler()
    done = []
    for turn in range(3):
        for i in range(100):
            rotation = assembler.add(turn * 100 + i, rplidar.Measurement(i == 0, 10, round(i * 3.6 * 64), 0 if i % 10 == 0 else 4000))
            if rotation:
                done.append(rotation)
    assert len(done) == 2
    assert done[0].measurements == 100 and len(done[0].distances_q2) == 90
    assert (done[0].ts_start, done[0].ts_end) == (0, 99)


def test_the_scan_message_round_trips_and_puts_the_c1_zero_behind_a_cable_forward_mount():
    scan = decode_scan(encode_scan(10, 110_000_000, 7, Mount(), [1000, 1000, 2000], [0, 90 * 64, 180 * 64]))
    assert scan.seq == 7 and scan.mount == Mount() and len(scan) == 3
    xy = points_xy(scan)
    x = Mount().x
    assert xy[0] == pytest.approx([x - 1.0, 0.0], abs=1e-6)
    assert xy[1] == pytest.approx([x, 1.0], abs=1e-6)
    assert xy[2] == pytest.approx([x + 2.0, 0.0], abs=1e-6)
    assert sector_minimums(scan)[0] == pytest.approx(x + 2.0, abs=1e-3)


def test_point_times_follow_the_rotation_and_deskew_removes_motion_smear():
    angles = np.arange(0, 360, 0.72)
    scan = decode_scan(encode_scan(0, 100_000_000, 1, Mount(yaw_deg=0.0), np.full(len(angles), 2000), np.round(angles * 64)))
    times = point_times(scan)
    assert times[0] == 0 and times[-1] == 100_000_000 and np.all(np.diff(times) >= 0)

    speed = 0.5
    wall_x = 3.0
    true_distance = []
    for t, angle in zip(times, angles):
        robot_x = speed * t * 1e-9
        true_distance.append((wall_x - robot_x - Mount().x) / math.cos(math.radians(angle)) if math.cos(math.radians(angle)) > 0.5 else 0.0)
    keep = np.array(true_distance) > 0
    moving = decode_scan(encode_scan(0, 100_000_000, 1, Mount(yaw_deg=0.0), np.round(np.array(true_distance)[keep] * 1000), np.round(angles[keep] * 64)))
    world = deskew(moving, lambda at: (speed * at * 1e-9, np.zeros(len(at)), np.zeros(len(at))))
    raw = points_xy(moving)
    assert np.ptp(world[:, 0]) < 0.004 < np.ptp(raw[:, 0])
    assert world[:, 0].mean() == pytest.approx(wall_x, abs=0.002)


def test_masked_sectors_wrap_around_zero():
    assert masked(np.array([350.0, 5.0, 20.0, 180.0]), [(345.0, 10.0)]).tolist() == [True, True, False, False]


def test_the_lidar_node_talks_to_an_emulated_c1_from_handshake_to_full_rotations(monkeypatch):
    monkeypatch.setenv("RABBIT_HW", "fake")
    monkeypatch.setenv("LIDAR_MASK", "80:100")
    from node import lidar as lidar_module

    node = lidar_module.Node()
    assert node.connect()
    device = node.device
    commands = [write[1] for write in device.writes]
    assert commands[:3] == [rplidar.STOP, rplidar.GET_INFO, rplidar.GET_SAMPLERATE] and commands[-2:] == [rplidar.GET_HEALTH, rplidar.SCAN]
    assert node.sample_hz == 5000.0
    worker = threading.Thread(target=node.io_loop, daemon=True)
    worker.start()
    time.sleep(0.45)
    node.stop.set()
    worker.join(2.0)
    assert node.seq >= 2
    scan = decode_scan(node.latest)
    assert 0.09 <= (scan.ts_end - scan.ts_start) * 1e-9 <= 0.11
    assert 400 <= len(scan) <= 500 and not masked(scan.angle_deg, [(80.0, 100.0)]).any()
    expected = np.array([room_ranges()(a) for a in scan.angle_deg])
    assert np.abs(scan.distance_mm - expected).max() <= 1.0
    assert node.stream.bad_nodes == 0
    assert device.writes[-1] == rplidar.request(rplidar.STOP) and node.device is None


def test_the_simulated_lidar_sees_walls_above_its_plane_and_ignores_low_furniture():
    world = room_grid(4.0, 4.0)
    heights = np.where(world.cells != 0, 1.2, 0.0)
    world.cells[38:42, 30:40] = 100
    heights[38:42, 30:40] = 0.1
    distance, angle = lidar_rotation(world, heights, [Robot(1.0, 2.0, 0.0)])
    forward = np.argmin(np.abs(((angle / 64.0) - 180.0)))
    assert distance[forward] / 1000.0 == pytest.approx(4.0 - 0.05 - 1.0 - Mount().x, abs=0.03)
