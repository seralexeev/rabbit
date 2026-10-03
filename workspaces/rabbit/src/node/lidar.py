import asyncio
import os
import threading
import time
from collections import deque

import numpy as np
from lib import rplidar
from lib.hardware import open_serial
from lib.lidar import HEALTH_SUBJECT, SCAN_SUBJECT, decode_scan, encode_scan, mask_from_env, masked, mount_from_env, scan_period_s, sector_minimums
from lib.node import RabbitNode

PORT = "/dev/ttyAMA4"


class LidarError(Exception):
    pass


class Node(RabbitNode):
    REPLY_TIMEOUT = 1.0
    STALL_S = 1.0
    RESTARTS_BEFORE_REOPEN = 3
    RECONNECT_DELAY = 1.0
    HEALTH_INTERVAL = 1.0
    READ_CHUNK = 256

    def __init__(self):
        super().__init__("lidar")
        self.port = os.environ.get("LIDAR_PORT", PORT)
        self.mount = mount_from_env()
        self.mask = mask_from_env()
        self.latency_ns = int(float(os.environ.get("LIDAR_LATENCY_MS", "0")) * 1e6)
        self.device = None
        self.info: rplidar.DeviceInfo | None = None
        self.health: rplidar.Health | None = None
        self.stream = rplidar.NodeStream(self.latency_ns)
        self.assembler = rplidar.ScanAssembler()
        self.seq = 0
        self.restarts = 0
        self.reconnects = 0
        self.errors = 0
        self.recent: deque[tuple[int, int, int, float]] = deque(maxlen=50)
        self.latest = None
        self.last_scan_at = 0.0
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.io_loop, daemon=True)

    async def init(self):
        self.loop = asyncio.get_running_loop()
        self.thread.start()
        self.set_interval(self.publish_health, self.HEALTH_INTERVAL, max_parallel=1)

    async def close(self):
        self.stop.set()
        await asyncio.to_thread(self.thread.join, 3.0)

    def exchange(self, command: int, expected: rplidar.Descriptor) -> bytes:
        assert self.device is not None
        self.device.write(rplidar.request(command))
        descriptor = rplidar.decode_descriptor(self.read_exact(rplidar.DESCRIPTOR_SIZE))
        if descriptor != expected:
            raise LidarError(f"command {command:#x}: unexpected reply {descriptor}")
        return self.read_exact(descriptor.length) if descriptor.mode == rplidar.SINGLE else b""

    def read_exact(self, size: int) -> bytes:
        assert self.device is not None
        data = bytearray()
        deadline = time.monotonic() + self.REPLY_TIMEOUT
        while len(data) < size:
            if time.monotonic() > deadline:
                raise LidarError(f"timeout waiting for {size} bytes, got {bytes(data).hex()}")
            data += self.device.read(size - len(data))
        return bytes(data)

    def stop_scan(self):
        assert self.device is not None
        self.device.write(rplidar.request(rplidar.STOP))
        time.sleep(rplidar.STOP_SETTLE_S)
        self.device.reset_input_buffer()

    def start_scan(self):
        self.stop_scan()
        self.health = rplidar.decode_health(self.exchange(rplidar.GET_HEALTH, rplidar.HEALTH_REPLY))
        if self.health.status == "error":
            self.event("lidar.device_error", f"device health error {self.health.error_code:#06x}, resetting", severity="error", error_code=self.health.error_code)
            self.device.write(rplidar.request(rplidar.RESET))
            time.sleep(rplidar.RESET_SETTLE_S)
            self.stop_scan()
            self.health = rplidar.decode_health(self.exchange(rplidar.GET_HEALTH, rplidar.HEALTH_REPLY))
            if self.health.status == "error":
                raise LidarError(f"device health error {self.health.error_code:#06x} after a reset")
        self.exchange(rplidar.SCAN, rplidar.SCAN_REPLY)
        self.stream.buffer.clear()
        self.assembler.started = False

    def connect(self) -> bool:
        try:
            self.device = open_serial(self.port, rplidar.BAUD)
            self.stop_scan()
            self.info = rplidar.decode_info(self.exchange(rplidar.GET_INFO, rplidar.INFO_REPLY))
            self.start_scan()
        except Exception as e:
            self.errors += 1
            self.event("lidar.connect_failed", str(e), severity="error", every_s=60.0, message=f"Lidar on {self.port} failed to start: {e}", port=self.port, errors=self.errors)
            self.disconnect()
            return False
        assert self.info is not None and self.health is not None
        self.event(
            "lidar.connected",
            f"model {self.info.model:#04x} firmware {self.info.firmware}",
            message=f"Lidar model {self.info.model:#04x} firmware {self.info.firmware} hardware {self.info.hardware} on {self.port}, health {self.health.status}",
            port=self.port,
            model=self.info.model,
            firmware=self.info.firmware,
            hardware=self.info.hardware,
            serial=self.info.serial,
            device_health=self.health.status,
            reconnects=self.reconnects,
        )
        self.last_scan_at = time.monotonic()
        return True

    def disconnect(self):
        if self.device is not None:
            try:
                self.device.close()
            except Exception:
                pass
        self.device = None

    def io_loop(self):
        restarts_in_row = 0
        while not self.stop.is_set():
            if self.device is None:
                if not self.connect():
                    self.stop.wait(self.RECONNECT_DELAY)
                    continue
                restarts_in_row = 0
            try:
                data = self.device.read(max(self.READ_CHUNK, self.device.in_waiting))
                if data:
                    for ts, node in self.stream.feed(data, time.time_ns()):
                        rotation = self.assembler.add(ts, node)
                        if rotation is not None:
                            self.emit(rotation)
                            restarts_in_row = 0
                if time.monotonic() - self.last_scan_at > self.STALL_S:
                    restarts_in_row += 1
                    self.restarts += 1
                    self.event("lidar.stalled", f"no full rotation for {self.STALL_S:.0f} s, restarting the scan", severity="warning", every_s=10.0, restarts=self.restarts, restarts_in_row=restarts_in_row)
                    if restarts_in_row >= self.RESTARTS_BEFORE_REOPEN:
                        self.reconnects += 1
                        self.disconnect()
                        continue
                    self.start_scan()
                    self.last_scan_at = time.monotonic()
            except Exception as e:
                self.errors += 1
                self.event("lidar.port_lost", str(e), severity="error", every_s=10.0, message=f"Lidar I/O failed: {e}", port=self.port, errors=self.errors)
                self.reconnects += 1
                self.disconnect()
                self.stop.wait(self.RECONNECT_DELAY)
        if self.device is not None:
            try:
                self.device.write(rplidar.request(rplidar.STOP))
            except Exception:
                pass
            self.disconnect()

    def emit(self, rotation: rplidar.Rotation):
        angles = np.asarray(rotation.angles_q6)
        distances = np.round(np.asarray(rotation.distances_q2) / 4.0)
        keep = ~masked(angles / 64.0, self.mask)
        self.seq += 1
        payload = encode_scan(rotation.ts_start, rotation.ts_end, self.seq, self.mount, distances[keep], angles[keep])
        self.recent.append((rotation.ts_start, rotation.ts_end, int(keep.sum()), rotation.measurements))
        self.latest = payload
        self.last_scan_at = time.monotonic()
        if self.loop is not None:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.publish(SCAN_SUBJECT, payload)))

    async def publish_health(self):
        recent = list(self.recent)
        window = [r for r in recent if r[1] >= time.time_ns() - 2_000_000_000]
        span = (window[-1][1] - window[0][0]) * 1e-9 if len(window) > 1 else 0.0
        scan = decode_scan(self.latest) if self.latest is not None else None
        await self.publish_json(
            HEALTH_SUBJECT,
            {
                "connected": self.device is not None,
                "port": self.port,
                "model": None if self.info is None else self.info.model,
                "firmware": None if self.info is None else self.info.firmware,
                "device_health": None if self.health is None else self.health.status,
                "error_code": None if self.health is None else self.health.error_code,
                "scan_hz": round(len(window) / span, 2) if span > 0 else 0.0,
                "points": round(float(np.mean([r[2] for r in window])), 1) if window else 0.0,
                "measurements": round(float(np.mean([r[3] for r in window])), 1) if window else 0.0,
                "rotation_s": None if scan is None else round(scan_period_s(scan), 4),
                "scan_age_s": round(time.monotonic() - self.last_scan_at, 3) if self.latest is not None else None,
                "rotations": self.seq,
                "bad_nodes": self.stream.bad_nodes,
                "skipped_bytes": self.stream.skipped_bytes,
                "short_rotations": self.assembler.short_rotations,
                "restarts": self.restarts,
                "reconnects": self.reconnects,
                "errors": self.errors,
                "sector_min_m": [] if scan is None else sector_minimums(scan),
                "mount": [self.mount.x, self.mount.y, self.mount.z, self.mount.yaw_deg],
                "masked_deg": [list(sector) for sector in self.mask],
            },
        )


if __name__ == "__main__":
    Node().run_node()
