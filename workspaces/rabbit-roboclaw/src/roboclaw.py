import serial
import struct
import time
from typing import Optional, Tuple
from dataclasses import dataclass


# RoboClaw Command Constants
class RoboClawCommands:
    """RoboClaw command codes from official documentation"""

    # Motor Control - Legacy Commands
    M1_FORWARD = 0
    M1_BACKWARD = 1
    M2_FORWARD = 4
    M2_BACKWARD = 5

    # Motor Control - Duty Cycle Commands
    M1_DUTY = 32
    M2_DUTY = 33

    # Motor Control - Speed Commands
    M1_SPEED = 35
    M2_SPEED = 36

    # Encoder Reading Commands
    GET_M1_ENC = 16
    GET_M2_ENC = 17

    # Speed Reading Commands
    GET_M1_SPEED = 18
    GET_M2_SPEED = 19

    # Reset Commands
    RESET_ENC = 20

    # System Information Commands
    GET_VERSION = 21
    GET_MBATT = 24
    GET_LBATT = 25
    GET_CURRENTS = 49
    GET_TEMP = 82


@dataclass
class RoboClawStatus:
    """RoboClaw status data"""

    encoder_m1: Optional[int] = None
    encoder_m2: Optional[int] = None
    speed_m1: Optional[int] = None
    speed_m2: Optional[int] = None
    current_m1: Optional[int] = None  # mA
    current_m2: Optional[int] = None  # mA
    voltage: Optional[float] = None  # V
    temperature: Optional[float] = None  # °C


class RoboClaw:
    """Minimal RoboClaw driver for Ackerman robots - following official documentation exactly"""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        address: int = 0x80,
        timeout: float = 0.1,
        retries: int = 3,
    ):
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.timeout = timeout
        self.retries = retries
        self._serial: Optional[serial.Serial] = None

    def _crc16(self, data: bytes) -> int:
        """Calculate CRC16 exactly as in RoboClaw documentation"""
        crc = 0
        for byte in data:
            crc = crc ^ (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    def open(self) -> bool:
        """Open serial connection"""
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                inter_byte_timeout=self.timeout,
            )
            time.sleep(0.1)
            return True
        except Exception as e:
            print(f"Error opening port: {e}")
            return False

    def close(self):
        """Close serial connection"""
        if self._serial and self._serial.is_open:
            self._serial.close()
            self._serial = None

    def _write_command(self, cmd: int, *args) -> bool:
        """Send write command and wait for 0xFF acknowledgment"""
        if not self._serial or not self._serial.is_open:
            return False

        # Build packet according to documentation
        packet = bytearray([self.address, cmd])

        # Add arguments based on command
        for arg in args:
            if isinstance(arg, int):
                if -128 <= arg <= 127:
                    packet.append(arg & 0xFF)
                elif -32768 <= arg <= 32767:
                    packet.extend(struct.pack(">h", arg))
                else:
                    packet.extend(struct.pack(">i", arg))

        # Add CRC
        crc = self._crc16(packet)
        packet.extend(struct.pack(">H", crc))

        # Send with retries
        for _ in range(self.retries):
            try:
                self._serial.reset_input_buffer()
                self._serial.write(packet)

                # Wait for 0xFF acknowledgment
                ack = self._serial.read(1)
                if ack and ack[0] == 0xFF:
                    return True
            except:
                continue

        return False

    def _read_command(self, cmd: int, format_str: str) -> Optional[Tuple]:
        """Send read command and return parsed response"""
        if not self._serial or not self._serial.is_open:
            return None

        for _ in range(self.retries):
            try:
                self._serial.reset_input_buffer()

                # Send command
                packet = bytearray([self.address, cmd])
                crc = self._crc16(packet)
                packet.extend(struct.pack(">H", crc))
                self._serial.write(packet)

                # Read response
                data_size = struct.calcsize(format_str)
                response = self._serial.read(data_size + 2)  # +2 for CRC

                if len(response) >= data_size + 2:
                    data = response[:-2]
                    received_crc = struct.unpack(">H", response[-2:])[0]

                    # Verify CRC - only on received data, not including address/cmd
                    calculated_crc = self._crc16(bytearray([self.address, cmd]) + data)

                    if calculated_crc == received_crc:
                        return struct.unpack(format_str, data)

            except:
                continue

        return None

    # === MOTOR CONTROL ===

    def set_motor_pwm(self, motor: int, pwm: float) -> bool:
        """Set motor PWM duty cycle: motor=1|2, pwm=-100.0 to 100.0"""
        # Convert percentage to RoboClaw duty value (-32767 to 32767)
        duty = int(max(-32767, min(32767, pwm * 327.67)))

        cmd = RoboClawCommands.M1_DUTY if motor == 1 else RoboClawCommands.M2_DUTY
        return self._write_command(cmd, duty)

    def set_motor_pwm_legacy(self, motor: int, pwm: float) -> bool:
        """Set motor PWM using legacy commands (0-127 range)"""
        if pwm >= 0:
            # Forward commands
            cmd = RoboClawCommands.M1_FORWARD if motor == 1 else RoboClawCommands.M2_FORWARD
            value = int(min(127, pwm * 1.27))  # Convert 0-100% to 0-127
        else:
            # Backward commands
            cmd = RoboClawCommands.M1_BACKWARD if motor == 1 else RoboClawCommands.M2_BACKWARD
            value = int(min(127, abs(pwm) * 1.27))  # Convert 0-100% to 0-127

        return self._write_command(cmd, value)

    def set_motor_speed(self, motor: int, speed: int) -> bool:
        """Set motor speed in QPPS (requires configured encoders and PID)"""
        cmd = RoboClawCommands.M1_SPEED if motor == 1 else RoboClawCommands.M2_SPEED
        return self._write_command(cmd, speed)

    def stop_motors(self) -> bool:
        """Stop both motors"""
        return self.set_motor_pwm(1, 0) and self.set_motor_pwm(2, 0)

    # === READING FUNCTIONS ===

    def read_encoder(self, motor: int) -> Optional[int]:
        """Read encoder count for specified motor"""
        cmd = RoboClawCommands.GET_M1_ENC if motor == 1 else RoboClawCommands.GET_M2_ENC
        result = self._read_command(cmd, ">IB")  # 4 bytes value + 1 byte status
        return result[0] if result else None

    def read_speed(self, motor: int) -> Optional[int]:
        """Read motor speed in QPPS"""
        cmd = RoboClawCommands.GET_M1_SPEED if motor == 1 else RoboClawCommands.GET_M2_SPEED
        result = self._read_command(cmd, ">iB")  # signed 4 bytes + 1 byte status
        return result[0] if result else None

    def read_currents(self) -> Optional[Tuple[int, int]]:
        """Read both motor currents in milliamps"""
        result = self._read_command(RoboClawCommands.GET_CURRENTS, ">HH")
        if result:
            # Current values are in 10mA units, convert to mA
            return (result[0] * 10, result[1] * 10)
        return None

    def read_main_voltage(self) -> Optional[float]:
        """Read main battery voltage in volts"""
        result = self._read_command(RoboClawCommands.GET_MBATT, ">H")
        return result[0] / 10.0 if result else None

    def read_logic_voltage(self) -> Optional[float]:
        """Read logic battery voltage in volts"""
        result = self._read_command(RoboClawCommands.GET_LBATT, ">H")
        return result[0] / 10.0 if result else None

    def read_temperature(self) -> Optional[float]:
        """Read board temperature in Celsius"""
        result = self._read_command(RoboClawCommands.GET_TEMP, ">H")
        return result[0] / 10.0 if result else None

    def read_version(self) -> Optional[str]:
        """Read firmware version string"""
        if not self._serial or not self._serial.is_open:
            return None

        for _ in range(self.retries):
            try:
                self._serial.reset_input_buffer()

                # Send command
                packet = bytearray([self.address, RoboClawCommands.GET_VERSION])
                crc = self._crc16(packet)
                packet.extend(struct.pack(">H", crc))
                self._serial.write(packet)

                # Read version string (up to 48 characters)
                version = b""
                for _ in range(48):
                    byte = self._serial.read(1)
                    if not byte or byte[0] == 0:  # Null terminator
                        break
                    version += byte

                # Read and verify CRC
                crc_bytes = self._serial.read(2)
                if len(crc_bytes) == 2:
                    received_crc = struct.unpack(">H", crc_bytes)[0]
                    # For version command, CRC includes the version string
                    check_data = bytearray([self.address, RoboClawCommands.GET_VERSION]) + version + b"\x00"
                    if self._crc16(check_data) == received_crc:
                        return version.decode("ascii", errors="ignore")

            except:
                continue

        return None

    def reset_encoders(self) -> bool:
        """Reset both encoder counts to zero"""
        return self._write_command(RoboClawCommands.RESET_ENC)

    # === ACKERMAN ROBOT HELPERS ===

    def set_drive_speed(self, speed: float) -> bool:
        """Set speed for both rear drive motors"""
        return self.set_motor_pwm(1, speed) and self.set_motor_pwm(2, speed)

    def move_forward(self, speed: float = 50.0) -> bool:
        """Move forward at specified speed percentage"""
        return self.set_drive_speed(speed)

    def move_backward(self, speed: float = 50.0) -> bool:
        """Move backward at specified speed percentage"""
        return self.set_drive_speed(-speed)

    def stop(self) -> bool:
        """Emergency stop - alias for stop_motors()"""
        return self.stop_motors()

    # === STATUS AND DIAGNOSTICS ===

    def get_status(self) -> RoboClawStatus:
        """Get complete system status"""
        currents = self.read_currents()
        return RoboClawStatus(
            encoder_m1=self.read_encoder(1),
            encoder_m2=self.read_encoder(2),
            speed_m1=self.read_speed(1),
            speed_m2=self.read_speed(2),
            current_m1=currents[0] if currents else None,
            current_m2=currents[1] if currents else None,
            voltage=self.read_main_voltage(),
            temperature=self.read_temperature(),
        )

    # === CONTEXT MANAGER ===

    def __enter__(self):
        if not self.open():
            raise RuntimeError(f"Failed to open {self.port}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# === USAGE EXAMPLE ===


def demo():
    """Demonstration following official examples"""

    with RoboClaw("/dev/ttyTHS1") as rc:
        # Test connection
        version = rc.read_version()
        if not version:
            print("Failed to read version - check connection!")
            return

        print(f"RoboClaw version: {version}")

        # Read initial status
        status = rc.get_status()
        print(f"Main voltage: {status.voltage}V")
        print(f"Temperature: {status.temperature}°C")
        print(f"Encoders: M1={status.encoder_m1}, M2={status.encoder_m2}")

        # Test movements
        print("Moving forward 30%...")
        rc.move_forward(30)
        time.sleep(2)

        print("Moving backward 30%...")
        rc.move_backward(30)
        time.sleep(2)

        print("Stopping...")
        rc.stop()

        # Individual motor control
        print("Left motor 50%, right motor 30%...")
        rc.set_motor_pwm(1, 50)  # Left rear motor
        rc.set_motor_pwm(2, 30)  # Right rear motor
        time.sleep(2)

        print("Final stop")
        rc.stop()

        # Final status
        final_status = rc.get_status()
        print(
            f"Final encoders: M1={final_status.encoder_m1}, M2={final_status.encoder_m2}"
        )


if __name__ == "__main__":
    demo()
