from __future__ import annotations

import time
from typing import Callable

import numpy as np
from lib.hardware import fake
from lib.tof import NO_TARGET, RESOLUTION, ZONES, Mount

Frame = tuple[list[int], list[int]]
FRAME_HZ = 15


def wall_frame(distance_m: float = 1.5) -> Frame:
    along = np.maximum(ZONES[:, 0], 1e-6)
    distance = np.full(RESOLUTION * RESOLUTION, round(distance_m * 1000))
    status = np.where(along > 0, 5, NO_TARGET)
    return distance.astype(int).tolist(), status.astype(int).tolist()


class FakeTof:
    def __init__(self, mount: Mount, frames: Callable[[Mount], Frame | None] | None = None):
        self.mount = mount
        self.frames = frames or (lambda _: wall_frame())
        self.started = False
        self.next_at = 0.0

    def start(self) -> None:
        self.started = True
        self.next_at = time.monotonic()

    def read(self, timeout: float) -> Frame | None:
        if not self.started:
            raise RuntimeError("not ranging")
        wait = self.next_at - time.monotonic()
        if wait > timeout:
            time.sleep(timeout)
            return None
        time.sleep(max(wait, 0.0))
        self.next_at = max(self.next_at + 1.0 / FRAME_HZ, time.monotonic() - 1.0 / FRAME_HZ)
        return self.frames(self.mount)

    def close(self) -> None:
        self.started = False


def zone_order(raw) -> list[int]:
    return [int(raw[i ^ 3]) for i in range(len(raw))]


def smbus_driver(bus: int, address: int):
    from pathlib import Path

    import vl53lxcx
    from smbus2 import SMBus, i2c_msg

    def config_file(self, name: str = "vl_fw_config.bin"):
        self._file_name = str(Path(vl53lxcx.__file__).with_name(name))

    vl53lxcx.ConfigDataFile.__init__ = config_file

    class Driver(vl53lxcx.VL53LxCX):
        POLL_TRIES = 200
        POLL_SLEEP_S = 0.01

        def __init__(self):
            self.bus = SMBus(bus)
            super().__init__(None, addr=address)

        def _rd_multi(self, reg16, size):
            read = i2c_msg.read(address, size)
            self.bus.i2c_rdwr(i2c_msg.write(address, [reg16 >> 8, reg16 & 0xFF]), read)
            return bytearray(bytes(read))

        def _rd_byte(self, reg16):
            return self._rd_multi(reg16, 1)[0]

        def _wr_multi(self, reg16, data):
            self.bus.i2c_rdwr(i2c_msg.write(address, bytes([reg16 >> 8, reg16 & 0xFF]) + bytes(data)))

        def _wr_byte(self, reg16, val):
            self._wr_multi(reg16, bytes([val]))

        def _poll_for_answer(self, size, pos, reg16, mask, val):
            for _ in range(self.POLL_TRIES):
                data = self._rd_multi(reg16, size)
                if (data[pos] & mask) == val:
                    return 0
                if size >= 4 and data[2] >= 0x7F:
                    break
                time.sleep(self.POLL_SLEEP_S)
            raise ValueError(f"no answer from register {reg16:#06x}")

        def close(self):
            self.bus.close()

    return vl53lxcx, Driver()


class Vl53l8cx:
    ADDRESS = 0x29
    READY_POLL_S = 0.005

    def __init__(self, mount: Mount):
        self.mount = mount
        self.module = None
        self.driver = None

    def start(self) -> None:
        self.module, self.driver = smbus_driver(self.mount.bus, self.ADDRESS)
        module, driver = self.module, self.driver
        status = driver.init()
        if status != 0:
            raise RuntimeError(f"VL53L8CX init failed with {status}")
        driver.resolution = module.RESOLUTION_8X8
        driver.ranging_mode = module.RANGING_MODE_CONTINUOUS
        driver.ranging_freq = FRAME_HZ
        driver.target_order = module.TARGET_ORDER_CLOSEST
        if not driver.start_ranging({module.DATA_DISTANCE_MM, module.DATA_TARGET_STATUS, module.DATA_NB_TARGET_DETECTED}):
            raise RuntimeError("VL53L8CX did not start ranging")

    def read(self, timeout: float) -> Frame | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.driver.check_data_ready():
                result = self.driver.get_ranging_data()
                targets = zone_order(result.nb_target_detected)
                status = [NO_TARGET if count == 0 else value for count, value in zip(targets, zone_order(result.target_status))]
                return [int(v) for v in result.distance_mm], status
            time.sleep(self.READY_POLL_S)
        return None

    def close(self) -> None:
        if self.driver is None:
            return
        try:
            self.driver.stop_ranging()
        except Exception:
            pass
        self.driver.close()
        self.driver = None


def open_tof(mount: Mount):
    return FakeTof(mount) if fake() else Vl53l8cx(mount)
