import struct
import termios
import threading
import time

import serial

DUTY_MAX = 32767
SERIAL_ERRORS = (OSError, serial.SerialException, termios.error)

READ_FIRMWARE = 21
READ_MAIN_BATTERY = 24
READ_PWMS = 48
READ_CURRENTS = 49
READ_MAIN_BATTERY_LIMITS = 59
READ_PIN_MODES = 75
READ_ENCODERS = 78
READ_SPEEDS = 79
READ_TEMPERATURE = 82
READ_STATUS = 90
READ_ENCODER_MODES = 91
READ_CONFIG = 99
READ_AVERAGE_SPEEDS = 108
READ_MAX_CURRENT = {1: 135, 2: 136}
READ_PWM_MODE = 149
READ_SERIAL_TIMEOUT = 15
SET_SERIAL_TIMEOUT = 14
SET_MAIN_BATTERY_LIMITS = 57
SET_PIN_MODES = 74
SET_MAX_CURRENT = {1: 133, 2: 134}
WRITE_NVM = 94
NVM_KEY = 0xE22EAB7A
RESET_ENCODERS = 20
DRIVE_DUTY = 34


def _crc_table() -> list[int]:
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
        table.append(crc & 0xFFFF)
    return table


CRC_TABLE = _crc_table()


def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ CRC_TABLE[((crc >> 8) ^ byte) & 0xFF]
    return crc


class RoboClawError(Exception):
    pass


class RoboClaw:
    def __init__(self, port: str, baudrate: int = 115200, address: int = 0x80, timeout: float = 0.05, retries: int = 3):
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.timeout = timeout
        self.retries = retries
        self.retried = 0
        self._serial: serial.Serial | None = None
        self._lock = threading.Lock()

    def open(self) -> str:
        self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout, write_timeout=self.timeout)
        self._serial.reset_input_buffer()
        return self.read_firmware()

    def close(self):
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def _exchange(self, command: int, args: bytes, read: int | None) -> bytes:
        if self._serial is None:
            raise RoboClawError("RoboClaw port is closed")
        packet = bytes([self.address, command]) + args
        packet += struct.pack(">H", crc16(packet))
        last_error: RoboClawError | None = None
        with self._lock:
            for attempt in range(self.retries):
                if attempt:
                    self.retried += 1
                    time.sleep(0.002)
                    self._serial.reset_input_buffer()
                self._serial.write(packet)
                if read is None:
                    if self._serial.read(1) == b"\xff":
                        return b""
                    last_error = RoboClawError(f"Missing ack for command {command}")
                    continue
                response = self._serial.read(read + 2)
                if len(response) != read + 2:
                    last_error = RoboClawError(f"Short response for command {command}")
                    continue
                expected = crc16(bytes([self.address, command]) + response[:-2])
                if struct.unpack(">H", response[-2:])[0] != expected:
                    last_error = RoboClawError(f"CRC mismatch for command {command}")
                    continue
                return response[:-2]
        assert last_error is not None
        raise last_error

    def read_firmware(self) -> str:
        if self._serial is None:
            raise RoboClawError("RoboClaw port is closed")
        packet = bytes([self.address, READ_FIRMWARE])
        with self._lock:
            self._serial.reset_input_buffer()
            self._serial.write(packet + struct.pack(">H", crc16(packet)))
            text = bytearray()
            while (byte := self._serial.read(1)) not in (b"", b"\0"):
                text += byte
            crc = self._serial.read(2)
        if len(crc) != 2 or struct.unpack(">H", crc)[0] != crc16(packet + bytes(text) + b"\0"):
            raise RoboClawError("Invalid firmware response")
        return text.decode(errors="replace").strip()

    def drive(self, left: float, right: float):
        duty = [int(max(min(v, 1.0), -1.0) * DUTY_MAX) for v in (left, right)]
        self._exchange(DRIVE_DUTY, struct.pack(">hh", *duty), None)

    def set_serial_timeout(self, seconds: float):
        self._exchange(SET_SERIAL_TIMEOUT, bytes([max(0, min(255, round(seconds * 10)))]), None)

    def reset_encoders(self):
        self._exchange(RESET_ENCODERS, b"", None)

    def read_encoder_modes(self) -> tuple[int, int]:
        left, right = self._exchange(READ_ENCODER_MODES, b"", 2)
        return left, right

    def read_serial_timeout(self) -> float:
        return self._exchange(READ_SERIAL_TIMEOUT, b"", 1)[0] / 10.0

    def read_main_battery_limits(self) -> tuple[float, float]:
        low, high = struct.unpack(">HH", self._exchange(READ_MAIN_BATTERY_LIMITS, b"", 4))
        return low / 10.0, high / 10.0

    def set_main_battery_limits(self, low: float, high: float):
        self._exchange(SET_MAIN_BATTERY_LIMITS, struct.pack(">HH", round(low * 10), round(high * 10)), None)

    def read_pin_modes(self) -> tuple[int, int, int]:
        s3, s4, s5 = self._exchange(READ_PIN_MODES, b"", 3)
        return s3, s4, s5

    def set_pin_modes(self, s3: int, s4: int, s5: int):
        self._exchange(SET_PIN_MODES, bytes([s3, s4, s5]), None)

    def read_max_current(self, motor: int) -> float:
        high, _ = struct.unpack(">ii", self._exchange(READ_MAX_CURRENT[motor], b"", 8))
        return high / 100.0

    def set_max_current(self, motor: int, amps: float):
        self._exchange(SET_MAX_CURRENT[motor], struct.pack(">II", round(amps * 100), 0), None)

    def read_pwm_mode(self) -> int:
        return self._exchange(READ_PWM_MODE, b"", 1)[0]

    def read_config(self) -> int:
        (config,) = struct.unpack(">H", self._exchange(READ_CONFIG, b"", 2))
        return config

    def read_main_battery(self) -> float:
        (supply,) = struct.unpack(">H", self._exchange(READ_MAIN_BATTERY, b"", 2))
        return supply / 10.0

    def write_nvm(self) -> str:
        try:
            self._exchange(WRITE_NVM, struct.pack(">I", NVM_KEY), None)
            return "with key"
        except RoboClawError:
            self._exchange(WRITE_NVM, b"", None)
            return "without key"

    def read_encoders(self) -> dict:
        left_count, right_count = struct.unpack(">ii", self._exchange(READ_ENCODERS, b"", 8))
        left_speed, right_speed = struct.unpack(">ii", self._exchange(READ_SPEEDS, b"", 8))
        left_average, right_average = struct.unpack(">ii", self._exchange(READ_AVERAGE_SPEEDS, b"", 8))
        return {
            "left": {"count": left_count, "speed": left_speed, "average_speed": left_average},
            "right": {"count": right_count, "speed": right_speed, "average_speed": right_average},
        }

    def read_motion(self) -> dict:
        left_pwm, right_pwm = struct.unpack(">hh", self._exchange(READ_PWMS, b"", 4))
        left_current, right_current = struct.unpack(">hh", self._exchange(READ_CURRENTS, b"", 4))
        left_speed, right_speed = struct.unpack(">ii", self._exchange(READ_SPEEDS, b"", 8))
        left_encoder, right_encoder = struct.unpack(">ii", self._exchange(READ_ENCODERS, b"", 8))
        (supply,) = struct.unpack(">H", self._exchange(READ_MAIN_BATTERY, b"", 2))
        return {
            "left": {"pwm": left_pwm / DUTY_MAX, "current": left_current / 100.0, "speed": left_speed, "encoder": left_encoder},
            "right": {"pwm": right_pwm / DUTY_MAX, "current": right_current / 100.0, "speed": right_speed, "encoder": right_encoder},
            "supply_voltage": supply / 10.0,
        }

    def read_board(self) -> dict:
        (temperature,) = struct.unpack(">H", self._exchange(READ_TEMPERATURE, b"", 2))
        (status,) = struct.unpack(">I", self._exchange(READ_STATUS, b"", 4))
        return {"temperature": temperature / 10.0, "status": status}
