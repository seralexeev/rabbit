import struct
import time
from typing import Optional, Tuple

import serial


class RoboClaw:
    """RoboClaw motor controller interface.

    This class provides a Python interface for communicating with RoboClaw motor controllers
    via serial communication. It supports various motor control commands and sensor readings.
    """

    MAX_DUTY_CYCLE = 32767
    """Maximum duty cycle value for the motor, representing 100% speed."""

    MIN_DUTY_CYCLE = -32768
    """Minimum duty cycle value for the motor, representing -100% speed."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        address: int = 0x80,
        timeout: float = 0.1,
        retry_count: int = 3,
    ):
        """Initialize RoboClaw controller.

        Args:
            port: Serial port path (e.g., '/dev/ttyTHS1', 'COM3').
            baudrate: Communication baudrate. Defaults to 115200.
            address: RoboClaw device address. Defaults to 0x80.
            timeout: Serial communication timeout in seconds. Defaults to 0.1.
            retry_count: Number of retry attempts for failed commands. Defaults to 3.
        """
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.timeout = timeout
        self.retry_count = retry_count
        self._serial: Optional[serial.Serial] = None

    def open(self):
        """Open serial connection to RoboClaw controller."""
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
            inter_byte_timeout=self.timeout,
        )
        time.sleep(0.1)

    def close(self):
        """Close serial connection to RoboClaw controller."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            self._serial = None

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def _crc16(self, data: bytes) -> int:
        """Calculate CRC16 checksum for data validation.

        RoboClaw uses a CRC (Cyclic Redundancy Check) to validate each packet it receives.
        This is more complex than a simple checksum but prevents errors that could otherwise
        cause unexpected actions to execute on the RoboClaw.

        Args:
            data: Byte data to calculate CRC for.

        Returns:
            CRC16 checksum value.
        """
        crc = 0
        for byte in data:
            crc = crc ^ (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF

        return crc

    def _get_response_crc(self, command: int, response: bytes) -> int:
        """Calculate CRC16 checksum for received data validation.

        The CRC16 calculation can also be used to validate received data from the RoboClaw.
        The CRC16 value should be calculated using the sent Address and Command byte as well
        as all the data received back from the RoboClaw except the two CRC16 bytes.
        The value calculated will match the CRC16 sent by the RoboClaw if there are no errors
        in the data sent or received.

        Args:
            command: Command byte that was sent.
            response: Response bytes received from RoboClaw.

        Returns:
            CRC16 checksum value for validation.

        Raises:
            ValueError: If response is too short (less than 2 bytes).
        """
        if len(response) < 2:
            raise ValueError(
                f"Response too short: expected at least 2 bytes, got {len(response)}"
            )

        validation_packet = bytearray([self.address, command])
        validation_packet.extend(response[:-2])

        return self._crc16(validation_packet)

    def _send_command(self, command: int, read_bytes: int, args: bytes = b"") -> bytes:
        """Send command to RoboClaw and read response.

        Args:
            command: Command byte to send.
            read_bytes: Number of bytes to read in response.
            args: Additional command arguments. Defaults to empty bytes.

        Returns:
            Response bytes from RoboClaw.

        Raises:
            RuntimeError: If serial port is not open, response length is invalid,
                         or command fails after retry attempts.
        """
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("Serial port not open")

        packet = bytearray([self.address, command])
        packet.extend(args)
        packet.extend(struct.pack(">H", self._crc16(packet)))

        attempt = 0
        while attempt < self.retry_count:
            try:
                self._serial.reset_input_buffer()
                self._serial.write(packet)
                response = self._serial.read(read_bytes)
                if len(response) != read_bytes:
                    raise RuntimeError(
                        f"Invalid response length: expected {read_bytes}, got {len(response)}"
                    )

                return response
            except Exception as e:
                attempt += 1
                if attempt < self.retry_count:
                    time.sleep(0.1)
                    continue
                raise RuntimeError(f"Failed to send command: {e}")

        # This should never be reached, but added for type checker
        raise RuntimeError("Command failed after all retry attempts")

    def _send_command_ack(self, cmd: int, args: bytes = b""):
        """Send command and wait for 0xFF acknowledgment.

        Args:
            cmd: Command byte to send.
            args: Additional command arguments. Defaults to empty bytes.

        Raises:
            RuntimeError: If acknowledgment is not received or is invalid.
        """
        response = self._send_command(cmd, 1, args)

        if len(response) != 1 or response[0] != 0xFF:
            raise RuntimeError(
                f"Invalid response: expected 0xFF, got {response[0]:02X}"
            )

    def _send_command_crc(
        self, cmd: int, response_size: int, args: bytes = b""
    ) -> bytes:
        """Send command and validate response CRC.

        Args:
            cmd: Command byte to send.
            response_size: Expected response size including CRC bytes.
            args: Additional command arguments. Defaults to empty bytes.

        Returns:
            Response bytes without CRC.

        Raises:
            RuntimeError: If CRC validation fails.
        """
        response = self._send_command(cmd, response_size, args)
        crc = struct.unpack(">H", response[-2:])[0]
        control_crc = self._get_response_crc(cmd, response)

        if crc != control_crc:
            raise RuntimeError(
                f"CRC mismatch: received {crc:04X}, expected {control_crc:04X}"
            )

        return response[:-2]

    def _get_duty_cycle(self, percentage: int) -> int:
        """Convert percentage to signed duty cycle value.

        The duty cycle is used to control the speed of the motor without a quadrature encoder.
        The range is -32768 to +32767, where 0 is stop, -32768 is full reverse,
        and +32767 is full forward.

        Args:
            percentage: Speed percentage (-100 to 100).

        Returns:
            Duty cycle value in range -32768 to +32767.
        """
        return int(
            max(
                self.MIN_DUTY_CYCLE,
                min(self.MAX_DUTY_CYCLE, percentage * (self.MAX_DUTY_CYCLE / 100.0)),
            )
        )

    def drive_forward_m1(self, speed: int):
        """Drive M1 motor forward.

        Command: 0 - Drive Forward M1

        Drive M1 motor forward at specified speed.

        Protocol:
            Send: [Address, 0, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=stop, 127=full speed).
        """

        self._send_command_ack(0, struct.pack(">B", speed))

    def drive_backwards_m1(self, speed: int):
        """Drive M1 motor backward.

        Command: 1 - Drive Backwards M1

        Drive M1 motor backward at specified speed.

        Protocol:
            Send: [Address, 1, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=stop, 127=full speed).
        """

        self._send_command_ack(1, struct.pack(">B", speed))

    def set_minimum_main_voltage(self, voltage: int):
        """Set minimum main battery voltage.

        Command: 2 - Set Minimum Main Voltage

        Set minimum main battery voltage cut-off threshold.

        Protocol:
            Send: [Address, 2, Voltage, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            voltage: Voltage value in range 0-140 (formula: (V-6)*5).
        """

        self._send_command_ack(2, struct.pack(">B", voltage))

    def set_maximum_main_voltage(self, voltage: int):
        """Set maximum main battery voltage.

        Command: 3 - Set Maximum Main Voltage

        Set maximum main battery voltage cut-off threshold.

        Protocol:
            Send: [Address, 3, Voltage, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            voltage: Voltage value in range 30-175 (formula: V*5.12).
        """

        self._send_command_ack(3, struct.pack(">B", voltage))

    def drive_forward_m2(self, speed: int):
        """Drive M2 motor forward.

        Command: 4 - Drive Forward M2

        Drive M2 motor forward at specified speed.

        Protocol:
            Send: [Address, 4, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=stop, 127=full speed).
        """

        self._send_command_ack(4, struct.pack(">B", speed))

    def drive_backwards_m2(self, speed: int):
        """Drive M2 motor backward.

        Command: 5 - Drive Backwards M2

        Drive M2 motor backward at specified speed.

        Protocol:
            Send: [Address, 5, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=stop, 127=full speed).
        """

        self._send_command_ack(5, struct.pack(">B", speed))

    def drive_m1_7bit(self, speed: int):
        """Drive M1 motor using 7-bit speed control.

        Command: 6 - Drive M1 (7 Bit)

        Drive M1 motor using 7-bit bidirectional speed control.

        Protocol:
            Send: [Address, 6, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=full reverse, 64=stop, 127=full forward).
        """

        self._send_command_ack(6, struct.pack(">B", speed))

    def drive_m2_7bit(self, speed: int):
        """Drive M2 motor using 7-bit speed control.

        Command: 7 - Drive M2 (7 Bit)

        Drive M2 motor using 7-bit bidirectional speed control.

        Protocol:
            Send: [Address, 7, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=full reverse, 64=stop, 127=full forward).
        """

        self._send_command_ack(7, struct.pack(">B", speed))

    def drive_forward_mixed(self, speed: int):
        """Drive forward using mixed mode.

        Command: 8 - Drive Forward (Mixed)

        Drive forward using mixed mode (steering mode).

        Protocol:
            Send: [Address, 8, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=stop, 127=full forward).
        """

        self._send_command_ack(8, struct.pack(">B", speed))

    def drive_backwards_mixed(self, speed: int):
        """Drive backward using mixed mode.

        Command: 9 - Drive Backwards (Mixed)

        Drive backward using mixed mode (steering mode).

        Protocol:
            Send: [Address, 9, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=stop, 127=full reverse).
        """

        self._send_command_ack(9, struct.pack(">B", speed))

    def turn_right_mixed(self, speed: int):
        """Turn right using mixed mode.

        Command: 10 - Turn Right (Mixed)

        Turn right using mixed mode (steering mode).

        Protocol:
            Send: [Address, 10, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=stop, 127=full speed turn).
        """

        self._send_command_ack(10, struct.pack(">B", speed))

    def turn_left_mixed(self, speed: int):
        """Turn left using mixed mode.

        Command: 11 - Turn Left (Mixed)

        Turn left using mixed mode (steering mode).

        Protocol:
            Send: [Address, 11, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=stop, 127=full speed turn).
        """

        self._send_command_ack(11, struct.pack(">B", speed))

    def drive_forward_backward_7bit(self, speed: int):
        """Drive forward/backward using 7-bit mixed mode.

        Command: 12 - Drive Forward/Backward (7 Bit)

        Drive forward/backward using 7-bit mixed mode control.

        Protocol:
            Send: [Address, 12, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=full backward, 64=stop, 127=full forward).
        """

        self._send_command_ack(12, struct.pack(">B", speed))

    def turn_left_right_7bit(self, speed: int):
        """Turn left/right using 7-bit mixed mode.

        Command: 13 - Turn Left/Right (7 Bit)

        Turn left/right using 7-bit mixed mode control.

        Protocol:
            Send: [Address, 13, Speed, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in range 0-127 (0=full left, 64=stop, 127=full right).
        """

        self._send_command_ack(13, struct.pack(">B", speed))

    def set_serial_timeout(self, timeout: int):
        """Set serial timeout.

        Command: 14 - Set Serial Timeout

        Set serial timeout in 100ms increments.

        Protocol:
            Send: [Address, 14, Timeout, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            timeout: Timeout value in range 0-255 (value * 100ms).
        """

        self._send_command_ack(14, struct.pack(">B", timeout))

    def read_serial_timeout(self) -> int:
        """Read serial timeout.

        Command: 15 - Read Serial Timeout

        Read serial timeout setting.

        Protocol:
            Send: [Address, 15]
            Receive: [Timeout, CRC(2 bytes)]

        Returns:
            Timeout value in 100ms increments.
        """

        response = self._send_command_crc(15, 3)
        return response[0]

    def read_encoder_m1(self) -> Tuple[int, int]:
        """Read M1 encoder count.

        Command: 16 - Read Encoder M1

        Read M1 encoder count and status.

        Protocol:
            Send: [Address, 16]
            Receive: [Count(4 bytes), Status, CRC(2 bytes)]

        Returns:
            Tuple of (count, status) where:
            - count: Encoder count value
            - status: Direction indicator (0 = forward, 1 = backward)
        """

        response = self._send_command_crc(16, 7)
        count = struct.unpack(">i", response[:4])[0]
        status = response[4]

        return count, status

    def read_encoder_m2(self) -> Tuple[int, int]:
        """Read M2 encoder count.

        Command: 17 - Read Encoder M2

        Read M2 encoder count and status.

        Protocol:
            Send: [Address, 17]
            Receive: [Count(4 bytes), Status, CRC(2 bytes)]

        Returns:
            Tuple of (count, status) where:
            - count: Encoder count value
            - status: Direction indicator (0 = forward, 1 = backward)
        """

        response = self._send_command_crc(17, 7)
        count = struct.unpack(">i", response[:4])[0]
        status = response[4]

        return count, status

    def reset_encoders(self):
        """Reset both encoder counts.

        Command: 20 - Reset Encoders

        Reset both M1 and M2 encoder counters to zero.

        Protocol:
            Send: [Address, 20]
            Receive: [0xFF]
        """

        self._send_command_ack(20)

    def set_encoder_m1_value(self, value: int):
        """Set M1 encoder count value.

        Command: 22 - Set Encoder M1 Value

        Set M1 encoder count to specified value.

        Protocol:
            Send: [Address, 22, Value(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            value: Encoder count value to set.
        """

        self._send_command_ack(22, struct.pack(">i", value))

    def set_encoder_m2_value(self, value: int):
        """Set M2 encoder count value.

        Command: 23 - Set Encoder M2 Value

        Set M2 encoder count to specified value.

        Protocol:
            Send: [Address, 23, Value(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            value: Encoder count value to set.
        """

        self._send_command_ack(23, struct.pack(">i", value))

    def read_main_battery_voltage(self) -> float:
        """Read main battery voltage.

        Command: 24 - Read Main Battery Voltage

        Read main battery voltage.

        Protocol:
            Send: [Address, 24]
            Receive: [Voltage(2 bytes), CRC(2 bytes)]

        Returns:
            Voltage in volts.
        """

        response = self._send_command_crc(24, 4)
        return struct.unpack(">H", response)[0] / 10.0

    def read_logic_battery_voltage(self) -> float:
        """Read logic battery voltage.

        Command: 25 - Read Logic Battery Voltage

        Read logic battery voltage.

        Protocol:
            Send: [Address, 25]
            Receive: [Voltage(2 bytes), CRC(2 bytes)]

        Returns:
            Voltage in volts.
        """

        response = self._send_command_crc(25, 4)
        return struct.unpack(">H", response)[0] / 10.0

    def set_minimum_logic_voltage(self, voltage: int):
        """Set minimum logic battery voltage.

        Command: 26 - Set Min Logic Voltage

        Set minimum logic battery voltage cut-off threshold.

        Protocol:
            Send: [Address, 26, Voltage, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            voltage: Voltage value.
        """

        self._send_command_ack(26, struct.pack(">B", voltage))

    def set_maximum_logic_voltage(self, voltage: int):
        """Set maximum logic battery voltage.

        Command: 27 - Set Max Logic Voltage

        Set maximum logic battery voltage cut-off threshold.

        Protocol:
            Send: [Address, 27, Voltage, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            voltage: Voltage value.
        """

        self._send_command_ack(27, struct.pack(">B", voltage))

    def set_velocity_pid_m1(self, d: int, p: int, i: int, qpps: int):
        """Set M1 velocity PID parameters.

        Command: 28 - Set Velocity PID M1

        Set M1 velocity PID parameters.

        Protocol:
            Send: [Address, 28, D(4 bytes), P(4 bytes), I(4 bytes), QPPS(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            d: Derivative parameter.
            p: Proportional parameter.
            i: Integral parameter.
            qpps: Quadrature pulses per second.
        """

        args = struct.pack(">iiii", d, p, i, qpps)
        self._send_command_ack(28, args)

    def set_velocity_pid_m2(self, d: int, p: int, i: int, qpps: int):
        """Set M2 velocity PID parameters.

        Command: 29 - Set Velocity PID M2

        Set M2 velocity PID parameters.

        Protocol:
            Send: [Address, 29, D(4 bytes), P(4 bytes), I(4 bytes), QPPS(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            d: Derivative parameter.
            p: Proportional parameter.
            i: Integral parameter.
            qpps: Quadrature pulses per second.
        """

        args = struct.pack(">iiii", d, p, i, qpps)
        self._send_command_ack(29, args)

    def read_raw_speed_m1(self) -> Tuple[int, int]:
        """Read M1 raw speed.

        Command: 30 - Read Raw Speed M1

        Read M1 raw speed value.

        Protocol:
            Send: [Address, 30]
            Receive: [Speed(4 bytes), Status, CRC(2 bytes)]

        Returns:
            Tuple of (speed, status) where:
            - speed: Raw speed value
            - status: Direction indicator (0 = forward, 1 = backward)
        """

        response = self._send_command_crc(30, 7)
        speed = struct.unpack(">i", response[:4])[0]
        status = response[4]

        return speed, status

    def read_raw_speed_m2(self) -> Tuple[int, int]:
        """Read M2 raw speed.

        Command: 31 - Read Raw Speed M2

        Read M2 raw speed value.

        Protocol:
            Send: [Address, 31]
            Receive: [Speed(4 bytes), Status, CRC(2 bytes)]

        Returns:
            Tuple of (speed, status) where:
            - speed: Raw speed value
            - status: Direction indicator (0 = forward, 1 = backward)
        """

        response = self._send_command_crc(31, 7)
        speed = struct.unpack(">i", response[:4])[0]
        status = response[4]

        return speed, status

    def drive_m1_m2_with_signed_duty_cycle(self, duty_m1: int, duty_m2: int):
        """Drive M1 and M2 motors using signed duty cycle.

        Command: 34 - Drive M1/M2 With Signed Duty Cycle

        Drive both M1 and M2 motors using signed duty cycle values.

        Protocol:
            Send: [Address, 34, DutyM1(2 bytes), DutyM2(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            duty_m1: M1 duty cycle value in range -32767 to +32767.
            duty_m2: M2 duty cycle value in range -32767 to +32767.
        """

        args = struct.pack(">hh", duty_m1, duty_m2)
        self._send_command_ack(34, args)

    def drive_m1_with_signed_speed(self, speed: int):
        """Drive M1 motor using signed speed.

        Command: 35 - Drive M1 Speed

        Drive M1 motor using signed speed value.

        Protocol:
            Send: [Address, 35, Speed(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in QPPS (Quadrature Pulses Per Second).
        """

        self._send_command_ack(35, struct.pack(">i", speed))

    def drive_m2_with_signed_speed(self, speed: int):
        """Drive M2 motor using signed speed.

        Command: 36 - Drive M2 Speed

        Drive M2 motor using signed speed value.

        Protocol:
            Send: [Address, 36, Speed(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in QPPS (Quadrature Pulses Per Second).
        """

        self._send_command_ack(36, struct.pack(">i", speed))

    def drive_m1_m2_with_signed_speed(self, speed_m1: int, speed_m2: int):
        """Drive M1 and M2 motors using signed speed.

        Command: 37 - Drive M1/M2 Speed

        Drive both M1 and M2 motors using signed speed values.

        Protocol:
            Send: [Address, 37, SpeedM1(4 bytes), SpeedM2(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed_m1: M1 speed value in QPPS.
            speed_m2: M2 speed value in QPPS.
        """

        args = struct.pack(">ii", speed_m1, speed_m2)
        self._send_command_ack(37, args)

    def drive_m1_with_signed_speed_and_acceleration(self, accel: int, speed: int):
        """Drive M1 motor using signed speed and acceleration.

        Command: 38 - Drive M1 Speed+Accel

        Drive M1 motor using signed speed and acceleration values.

        Protocol:
            Send: [Address, 38, Accel(4 bytes), Speed(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value in QPPS per second.
            speed: Speed value in QPPS.
        """

        args = struct.pack(">ii", accel, speed)
        self._send_command_ack(38, args)

    def drive_m2_with_signed_speed_and_acceleration(self, accel: int, speed: int):
        """Drive M2 motor using signed speed and acceleration.

        Command: 39 - Drive M2 Speed+Accel

        Drive M2 motor using signed speed and acceleration values.

        Protocol:
            Send: [Address, 39, Accel(4 bytes), Speed(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value in QPPS per second.
            speed: Speed value in QPPS.
        """

        args = struct.pack(">ii", accel, speed)
        self._send_command_ack(39, args)

    def drive_m1_m2_with_signed_speed_and_acceleration(self, accel: int, speed_m1: int, speed_m2: int):
        """Drive M1 and M2 motors using signed speed and shared acceleration.

        Command: 40 - Drive M1/M2 Speed+Accel

        Drive both M1 and M2 motors using signed speed and shared acceleration values.

        Protocol:
            Send: [Address, 40, Accel(4 bytes), SpeedM1(4 bytes), SpeedM2(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value in QPPS per second.
            speed_m1: M1 speed value in QPPS.
            speed_m2: M2 speed value in QPPS.
        """

        args = struct.pack(">iii", accel, speed_m1, speed_m2)
        self._send_command_ack(40, args)

    def buffered_drive_m1_with_signed_speed_and_distance(self, speed: int, distance: int, buffer: int):
        """Drive M1 motor using signed speed and distance (buffered).

        Command: 41 - Buffered M1 Speed+Distance

        Drive M1 motor using signed speed and distance values with buffering.

        Protocol:
            Send: [Address, 41, Speed(4 bytes), Distance(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in QPPS.
            distance: Distance value in encoder counts.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiB", speed, distance, buffer)
        self._send_command_ack(41, args)

    def buffered_drive_m2_with_signed_speed_and_distance(self, speed: int, distance: int, buffer: int):
        """Drive M2 motor using signed speed and distance (buffered).

        Command: 42 - Buffered M2 Speed+Distance

        Drive M2 motor using signed speed and distance values with buffering.

        Protocol:
            Send: [Address, 42, Speed(4 bytes), Distance(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value in QPPS.
            distance: Distance value in encoder counts.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiB", speed, distance, buffer)
        self._send_command_ack(42, args)

    def buffered_drive_m1_m2_with_signed_speed_and_distance(self, speed_m1: int, distance_m1: int, speed_m2: int, distance_m2: int, buffer: int):
        """Drive M1 and M2 motors using signed speed and distance (buffered).

        Command: 43 - Buffered M1/M2 Speed+Distance

        Drive both M1 and M2 motors using signed speed and distance values with buffering.

        Protocol:
            Send: [Address, 43, SpeedM1(4 bytes), DistanceM1(4 bytes), SpeedM2(4 bytes), DistanceM2(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed_m1: M1 speed value in QPPS.
            distance_m1: M1 distance value in encoder counts.
            speed_m2: M2 speed value in QPPS.
            distance_m2: M2 distance value in encoder counts.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiiiB", speed_m1, distance_m1, speed_m2, distance_m2, buffer)
        self._send_command_ack(43, args)

    def buffered_drive_m1_with_signed_speed_accel_and_distance(self, accel: int, speed: int, distance: int, buffer: int):
        """Drive M1 motor using signed speed, acceleration, and distance (buffered).

        Command: 44 - Buffered M1 Speed+Accel+Distance

        Drive M1 motor using signed speed, acceleration, and distance values with buffering.

        Protocol:
            Send: [Address, 44, Accel(4 bytes), Speed(4 bytes), Distance(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value in QPPS per second.
            speed: Speed value in QPPS.
            distance: Distance value in encoder counts.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiiB", accel, speed, distance, buffer)
        self._send_command_ack(44, args)

    def buffered_drive_m2_with_signed_speed_accel_and_distance(self, accel: int, speed: int, distance: int, buffer: int):
        """Drive M2 motor using signed speed, acceleration, and distance (buffered).

        Command: 45 - Buffered M2 Speed+Accel+Distance

        Drive M2 motor using signed speed, acceleration, and distance values with buffering.

        Protocol:
            Send: [Address, 45, Accel(4 bytes), Speed(4 bytes), Distance(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value in QPPS per second.
            speed: Speed value in QPPS.
            distance: Distance value in encoder counts.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiiB", accel, speed, distance, buffer)
        self._send_command_ack(45, args)

    def buffered_drive_m1_m2_with_signed_speed_accel_and_distance(self, accel: int, speed_m1: int, distance_m1: int, speed_m2: int, distance_m2: int, buffer: int):
        """Drive M1 and M2 motors using signed speed, acceleration, and distance (buffered).

        Command: 46 - Buffered M1/M2 Speed+Accel+Distance

        Drive both M1 and M2 motors using signed speed, acceleration, and distance values with buffering.

        Protocol:
            Send: [Address, 46, Accel(4 bytes), SpeedM1(4 bytes), DistanceM1(4 bytes), SpeedM2(4 bytes), DistanceM2(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value in QPPS per second.
            speed_m1: M1 speed value in QPPS.
            distance_m1: M1 distance value in encoder counts.
            speed_m2: M2 speed value in QPPS.
            distance_m2: M2 distance value in encoder counts.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiiiiB", accel, speed_m1, distance_m1, speed_m2, distance_m2, buffer)
        self._send_command_ack(46, args)

    def read_buffer_length(self) -> Tuple[int, int]:
        """Read command buffer lengths.

        Command: 47 - Read Buffer Length

        Read the current command buffer lengths for both motors.

        Protocol:
            Send: [Address, 47]
            Receive: [BufferM1, BufferM2, CRC(2 bytes)]

        Returns:
            Tuple of (buffer_m1, buffer_m2) where:
            - buffer_m1: M1 buffer length
            - buffer_m2: M2 buffer length
        """

        response = self._send_command_crc(47, 4)
        buffer_m1 = response[0]
        buffer_m2 = response[1]

        return buffer_m1, buffer_m2

    def read_motor_pwms(self) -> Tuple[int, int]:
        """Read motor PWM values.

        Command: 48 - Read Motor PWMs

        Read current PWM values for both motors.

        Protocol:
            Send: [Address, 48]
            Receive: [M1PWM(2 bytes), M2PWM(2 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (m1_pwm, m2_pwm) where:
            - m1_pwm: M1 PWM value (±32767)
            - m2_pwm: M2 PWM value (±32767)
        """

        response = self._send_command_crc(48, 6)
        m1_pwm = struct.unpack(">h", response[:2])[0]
        m2_pwm = struct.unpack(">h", response[2:4])[0]

        return m1_pwm, m2_pwm

    def read_motor_currents(self) -> Tuple[float, float]:
        """Read motor current values.

        Command: 49 - Read Motor Currents

        Read current values for both motors.

        Protocol:
            Send: [Address, 49]
            Receive: [M1Current(2 bytes), M2Current(2 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (m1_current, m2_current) where:
            - m1_current: M1 current in amperes
            - m2_current: M2 current in amperes
        """

        response = self._send_command_crc(49, 6)
        m1_current = struct.unpack(">h", response[:2])[0] / 100.0
        m2_current = struct.unpack(">h", response[2:4])[0] / 100.0

        return m1_current, m2_current

    def drive_m1_m2_with_individual_signed_speed_and_acceleration(self, accel_m1: int, speed_m1: int, accel_m2: int, speed_m2: int):
        """Drive M1 and M2 motors using individual signed speed and acceleration.

        Command: 50 - Drive M1/M2 Individual Accel

        Drive both M1 and M2 motors using individual signed speed and acceleration values.

        Protocol:
            Send: [Address, 50, AccelM1(4 bytes), SpeedM1(4 bytes), AccelM2(4 bytes), SpeedM2(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel_m1: M1 acceleration value in QPPS per second.
            speed_m1: M1 speed value in QPPS.
            accel_m2: M2 acceleration value in QPPS per second.
            speed_m2: M2 speed value in QPPS.
        """

        args = struct.pack(">iiii", accel_m1, speed_m1, accel_m2, speed_m2)
        self._send_command_ack(50, args)

    def buffered_drive_m1_m2_with_individual_signed_speed_accel_and_distance(self, accel_m1: int, speed_m1: int, distance_m1: int, accel_m2: int, speed_m2: int, distance_m2: int, buffer: int):
        """Drive M1 and M2 motors using individual signed speed, acceleration, and distance (buffered).

        Command: 51 - Buffered M1/M2 Individual Accel+Distance

        Drive both M1 and M2 motors using individual signed speed, acceleration, and distance values with buffering.

        Protocol:
            Send: [Address, 51, AccelM1(4 bytes), SpeedM1(4 bytes), DistanceM1(4 bytes), AccelM2(4 bytes), SpeedM2(4 bytes), DistanceM2(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel_m1: M1 acceleration value in QPPS per second.
            speed_m1: M1 speed value in QPPS.
            distance_m1: M1 distance value in encoder counts.
            accel_m2: M2 acceleration value in QPPS per second.
            speed_m2: M2 speed value in QPPS.
            distance_m2: M2 distance value in encoder counts.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiiiiiB", accel_m1, speed_m1, distance_m1, accel_m2, speed_m2, distance_m2, buffer)
        self._send_command_ack(51, args)

    def drive_m1_with_signed_duty_cycle_and_acceleration(self, duty: int, accel: int):
        """Drive M1 motor using signed duty cycle and acceleration.

        Command: 52 - Drive M1 Duty+Accel

        Drive M1 motor using signed duty cycle and acceleration values.

        Protocol:
            Send: [Address, 52, Duty(2 bytes), Accel(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            duty: Duty cycle value in range -32767 to +32767.
            accel: Acceleration value.
        """

        args = struct.pack(">hh", duty, accel)
        self._send_command_ack(52, args)

    def drive_m2_with_signed_duty_cycle_and_acceleration(self, duty: int, accel: int):
        """Drive M2 motor using signed duty cycle and acceleration.

        Command: 53 - Drive M2 Duty+Accel

        Drive M2 motor using signed duty cycle and acceleration values.

        Protocol:
            Send: [Address, 53, Duty(2 bytes), Accel(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            duty: Duty cycle value in range -32767 to +32767.
            accel: Acceleration value.
        """

        args = struct.pack(">hh", duty, accel)
        self._send_command_ack(53, args)

    def drive_m1_m2_with_signed_duty_cycle_and_acceleration(self, duty_m1: int, accel_m1: int, duty_m2: int, accel_m2: int):
        """Drive M1 and M2 motors using signed duty cycle and acceleration.

        Command: 54 - Drive M1/M2 Duty+Accel

        Drive both M1 and M2 motors using signed duty cycle and acceleration values.

        Protocol:
            Send: [Address, 54, DutyM1(2 bytes), AccelM1(4 bytes), DutyM2(2 bytes), AccelM2(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            duty_m1: M1 duty cycle value in range -32767 to +32767.
            accel_m1: M1 acceleration value.
            duty_m2: M2 duty cycle value in range -32767 to +32767.
            accel_m2: M2 acceleration value.
        """

        args = struct.pack(">hihi", duty_m1, accel_m1, duty_m2, accel_m2)
        self._send_command_ack(54, args)

    def read_velocity_pid_m1(self) -> Tuple[int, int, int, int]:
        """Read M1 velocity PID parameters.

        Command: 55 - Read Velocity PID M1

        Read M1 velocity PID parameters.

        Protocol:
            Send: [Address, 55]
            Receive: [P(4 bytes), I(4 bytes), D(4 bytes), QPPS(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (p, i, d, qpps) where:
            - p: Proportional parameter
            - i: Integral parameter
            - d: Derivative parameter
            - qpps: Quadrature pulses per second
        """

        response = self._send_command_crc(55, 18)
        p = struct.unpack(">i", response[:4])[0]
        i = struct.unpack(">i", response[4:8])[0]
        d = struct.unpack(">i", response[8:12])[0]
        qpps = struct.unpack(">i", response[12:16])[0]

        return p, i, d, qpps

    def read_velocity_pid_m2(self) -> Tuple[int, int, int, int]:
        """Read M2 velocity PID parameters.

        Command: 56 - Read Velocity PID M2

        Read M2 velocity PID parameters.

        Protocol:
            Send: [Address, 56]
            Receive: [P(4 bytes), I(4 bytes), D(4 bytes), QPPS(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (p, i, d, qpps) where:
            - p: Proportional parameter
            - i: Integral parameter
            - d: Derivative parameter
            - qpps: Quadrature pulses per second
        """

        response = self._send_command_crc(56, 18)
        p = struct.unpack(">i", response[:4])[0]
        i = struct.unpack(">i", response[4:8])[0]
        d = struct.unpack(">i", response[8:12])[0]
        qpps = struct.unpack(">i", response[12:16])[0]

        return p, i, d, qpps

    def set_main_battery_voltages(self, min_voltage: int, max_voltage: int):
        """Set main battery voltage limits.

        Command: 57 - Set Main Battery Voltages

        Set main battery voltage limits.

        Protocol:
            Send: [Address, 57, Min(2 bytes), Max(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            min_voltage: Minimum voltage (×0.1V).
            max_voltage: Maximum voltage (×0.1V).
        """

        args = struct.pack(">HH", min_voltage, max_voltage)
        self._send_command_ack(57, args)

    def set_logic_battery_voltages(self, min_voltage: int, max_voltage: int):
        """Set logic battery voltage limits.

        Command: 58 - Set Logic Battery Voltages

        Set logic battery voltage limits.

        Protocol:
            Send: [Address, 58, Min(2 bytes), Max(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            min_voltage: Minimum voltage (×0.1V).
            max_voltage: Maximum voltage (×0.1V).
        """

        args = struct.pack(">HH", min_voltage, max_voltage)
        self._send_command_ack(58, args)

    def read_main_battery_settings(self) -> Tuple[int, int]:
        """Read main battery voltage settings.

        Command: 59 - Read Main Battery Settings

        Read main battery voltage settings.

        Protocol:
            Send: [Address, 59]
            Receive: [Min(2 bytes), Max(2 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (min_voltage, max_voltage) where:
            - min_voltage: Minimum voltage (×0.1V)
            - max_voltage: Maximum voltage (×0.1V)
        """

        response = self._send_command_crc(59, 6)
        min_voltage = struct.unpack(">H", response[:2])[0]
        max_voltage = struct.unpack(">H", response[2:4])[0]

        return min_voltage, max_voltage

    def read_logic_battery_settings(self) -> Tuple[int, int]:
        """Read logic battery voltage settings.

        Command: 60 - Read Logic Battery Settings

        Read logic battery voltage settings.

        Protocol:
            Send: [Address, 60]
            Receive: [Min(2 bytes), Max(2 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (min_voltage, max_voltage) where:
            - min_voltage: Minimum voltage (×0.1V)
            - max_voltage: Maximum voltage (×0.1V)
        """

        response = self._send_command_crc(60, 6)
        min_voltage = struct.unpack(">H", response[:2])[0]
        max_voltage = struct.unpack(">H", response[2:4])[0]

        return min_voltage, max_voltage

    def set_position_pid_m1(self, d: int, p: int, i: int, max_i: int, deadzone: int, min_pos: int, max_pos: int):
        """Set M1 position PID parameters.

        Command: 61 - Set Position PID M1

        Set M1 position PID parameters.

        Protocol:
            Send: [Address, 61, D(4 bytes), P(4 bytes), I(4 bytes), MaxI(4 bytes), Deadzone(4 bytes), MinPos(4 bytes), MaxPos(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            d: Derivative parameter.
            p: Proportional parameter.
            i: Integral parameter.
            max_i: Maximum integral value.
            deadzone: Deadzone value.
            min_pos: Minimum position.
            max_pos: Maximum position.
        """

        args = struct.pack(">iiiiiii", d, p, i, max_i, deadzone, min_pos, max_pos)
        self._send_command_ack(61, args)

    def set_position_pid_m2(self, d: int, p: int, i: int, max_i: int, deadzone: int, min_pos: int, max_pos: int):
        """Set M2 position PID parameters.

        Command: 62 - Set Position PID M2

        Set M2 position PID parameters.

        Protocol:
            Send: [Address, 62, D(4 bytes), P(4 bytes), I(4 bytes), MaxI(4 bytes), Deadzone(4 bytes), MinPos(4 bytes), MaxPos(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            d: Derivative parameter.
            p: Proportional parameter.
            i: Integral parameter.
            max_i: Maximum integral value.
            deadzone: Deadzone value.
            min_pos: Minimum position.
            max_pos: Maximum position.
        """

        args = struct.pack(">iiiiiii", d, p, i, max_i, deadzone, min_pos, max_pos)
        self._send_command_ack(62, args)

    def read_position_pid_m1(self) -> Tuple[int, int, int, int, int, int, int]:
        """Read M1 position PID parameters.

        Command: 63 - Read Position PID M1

        Read M1 position PID parameters.

        Protocol:
            Send: [Address, 63]
            Receive: [P(4 bytes), I(4 bytes), D(4 bytes), MaxI(4 bytes), Deadzone(4 bytes), MinPos(4 bytes), MaxPos(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (p, i, d, max_i, deadzone, min_pos, max_pos) where:
            - p: Proportional parameter
            - i: Integral parameter
            - d: Derivative parameter
            - max_i: Maximum integral value
            - deadzone: Deadzone value
            - min_pos: Minimum position
            - max_pos: Maximum position
        """

        response = self._send_command_crc(63, 30)
        p = struct.unpack(">i", response[:4])[0]
        i = struct.unpack(">i", response[4:8])[0]
        d = struct.unpack(">i", response[8:12])[0]
        max_i = struct.unpack(">i", response[12:16])[0]
        deadzone = struct.unpack(">i", response[16:20])[0]
        min_pos = struct.unpack(">i", response[20:24])[0]
        max_pos = struct.unpack(">i", response[24:28])[0]

        return p, i, d, max_i, deadzone, min_pos, max_pos

    def read_position_pid_m2(self) -> Tuple[int, int, int, int, int, int, int]:
        """Read M2 position PID parameters.

        Command: 64 - Read Position PID M2

        Read M2 position PID parameters.

        Protocol:
            Send: [Address, 64]
            Receive: [P(4 bytes), I(4 bytes), D(4 bytes), MaxI(4 bytes), Deadzone(4 bytes), MinPos(4 bytes), MaxPos(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (p, i, d, max_i, deadzone, min_pos, max_pos) where:
            - p: Proportional parameter
            - i: Integral parameter
            - d: Derivative parameter
            - max_i: Maximum integral value
            - deadzone: Deadzone value
            - min_pos: Minimum position
            - max_pos: Maximum position
        """

        response = self._send_command_crc(64, 30)
        p = struct.unpack(">i", response[:4])[0]
        i = struct.unpack(">i", response[4:8])[0]
        d = struct.unpack(">i", response[8:12])[0]
        max_i = struct.unpack(">i", response[12:16])[0]
        deadzone = struct.unpack(">i", response[16:20])[0]
        min_pos = struct.unpack(">i", response[20:24])[0]
        max_pos = struct.unpack(">i", response[24:28])[0]

        return p, i, d, max_i, deadzone, min_pos, max_pos

    def buffered_move_m1_to_position(self, accel: int, speed: int, deccel: int, position: int, buffer: int):
        """Move M1 motor to position (buffered).

        Command: 65 - Buffered M1 Position

        Move M1 motor to specified position with buffering.

        Protocol:
            Send: [Address, 65, Accel(4 bytes), Speed(4 bytes), Deccel(4 bytes), Position(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value.
            speed: Speed value.
            deccel: Deceleration value.
            position: Target position.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiiiB", accel, speed, deccel, position, buffer)
        self._send_command_ack(65, args)

    def buffered_move_m2_to_position(self, accel: int, speed: int, deccel: int, position: int, buffer: int):
        """Move M2 motor to position (buffered).

        Command: 66 - Buffered M2 Position

        Move M2 motor to specified position with buffering.

        Protocol:
            Send: [Address, 66, Accel(4 bytes), Speed(4 bytes), Deccel(4 bytes), Position(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value.
            speed: Speed value.
            deccel: Deceleration value.
            position: Target position.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiiiB", accel, speed, deccel, position, buffer)
        self._send_command_ack(66, args)

    def buffered_move_m1_m2_to_position(self, accel_m1: int, speed_m1: int, deccel_m1: int, pos_m1: int, accel_m2: int, speed_m2: int, deccel_m2: int, pos_m2: int, buffer: int):
        """Move M1 and M2 motors to positions (buffered).

        Command: 67 - Buffered M1/M2 Position

        Move both M1 and M2 motors to specified positions with buffering.

        Protocol:
            Send: [Address, 67, AccelM1(4 bytes), SpeedM1(4 bytes), DeccelM1(4 bytes), PosM1(4 bytes), AccelM2(4 bytes), SpeedM2(4 bytes), DeccelM2(4 bytes), PosM2(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel_m1: M1 acceleration value.
            speed_m1: M1 speed value.
            deccel_m1: M1 deceleration value.
            pos_m1: M1 target position.
            accel_m2: M2 acceleration value.
            speed_m2: M2 speed value.
            deccel_m2: M2 deceleration value.
            pos_m2: M2 target position.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiiiiiiiB", accel_m1, speed_m1, deccel_m1, pos_m1, accel_m2, speed_m2, deccel_m2, pos_m2, buffer)
        self._send_command_ack(67, args)

    def set_m1_default_duty_acceleration(self, accel: int):
        """Set M1 default duty acceleration.

        Command: 68 - Set M1 Default Duty Accel

        Set M1 default duty acceleration value.

        Protocol:
            Send: [Address, 68, Accel(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value.
        """

        self._send_command_ack(68, struct.pack(">i", accel))

    def set_m2_default_duty_acceleration(self, accel: int):
        """Set M2 default duty acceleration.

        Command: 69 - Set M2 Default Duty Accel

        Set M2 default duty acceleration value.

        Protocol:
            Send: [Address, 69, Accel(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            accel: Acceleration value.
        """

        self._send_command_ack(69, struct.pack(">i", accel))

    def set_m1_default_speed(self, speed: int):
        """Set M1 default speed.

        Command: 70 - Set M1 Default Speed

        Set M1 default speed value.

        Protocol:
            Send: [Address, 70, Speed(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value.
        """

        self._send_command_ack(70, struct.pack(">h", speed))

    def set_m2_default_speed(self, speed: int):
        """Set M2 default speed.

        Command: 71 - Set M2 Default Speed

        Set M2 default speed value.

        Protocol:
            Send: [Address, 71, Speed(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value.
        """

        self._send_command_ack(71, struct.pack(">h", speed))

    def read_default_speeds(self) -> Tuple[int, int]:
        """Read default speeds.

        Command: 72 - Read Default Speeds

        Read default speeds for both motors.

        Protocol:
            Send: [Address, 72]
            Receive: [M1Speed(2 bytes), M2Speed(2 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (m1_speed, m2_speed) where:
            - m1_speed: M1 default speed
            - m2_speed: M2 default speed
        """

        response = self._send_command_crc(72, 6)
        m1_speed = struct.unpack(">h", response[:2])[0]
        m2_speed = struct.unpack(">h", response[2:4])[0]

        return m1_speed, m2_speed

    def set_s3_s4_s5_modes(self, s3_mode: int, s4_mode: int, s5_mode: int):
        """Set S3, S4, S5 pin modes.

        Command: 74 - Set S3/S4/S5 Modes

        Set signal pin modes for S3, S4, and S5.

        Protocol:
            Send: [Address, 74, S3mode, S4mode, S5mode, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            s3_mode: S3 pin mode.
            s4_mode: S4 pin mode.
            s5_mode: S5 pin mode.
        """

        args = struct.pack(">BBB", s3_mode, s4_mode, s5_mode)
        self._send_command_ack(74, args)

    def read_s3_s4_s5_modes(self) -> Tuple[int, int, int]:
        """Read S3, S4, S5 pin modes.

        Command: 75 - Read S3/S4/S5 Modes

        Read signal pin modes for S3, S4, and S5.

        Protocol:
            Send: [Address, 75]
            Receive: [S3mode, S4mode, S5mode, CRC(2 bytes)]

        Returns:
            Tuple of (s3_mode, s4_mode, s5_mode) where:
            - s3_mode: S3 pin mode
            - s4_mode: S4 pin mode
            - s5_mode: S5 pin mode
        """

        response = self._send_command_crc(75, 5)
        s3_mode = response[0]
        s4_mode = response[1]
        s5_mode = response[2]

        return s3_mode, s4_mode, s5_mode

    def set_rc_analog_deadband(self, reverse: int, forward: int):
        """Set RC/Analog deadband.

        Command: 76 - Set RC/Analog Deadband

        Set RC/Analog deadband percentages.

        Protocol:
            Send: [Address, 76, Reverse, Forward, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            reverse: Reverse deadband percentage.
            forward: Forward deadband percentage.
        """

        args = struct.pack(">BB", reverse, forward)
        self._send_command_ack(76, args)

    def read_rc_analog_deadband(self) -> Tuple[int, int]:
        """Read RC/Analog deadband.

        Command: 77 - Read RC/Analog Deadband

        Read RC/Analog deadband percentages.

        Protocol:
            Send: [Address, 77]
            Receive: [Reverse, Forward, CRC(2 bytes)]

        Returns:
            Tuple of (reverse, forward) where:
            - reverse: Reverse deadband percentage
            - forward: Forward deadband percentage
        """

        response = self._send_command_crc(77, 4)
        reverse = response[0]
        forward = response[1]

        return reverse, forward

    def read_encoder_counters(self) -> Tuple[int, int]:
        """Read both encoder counters.

        Command: 78 - Read Encoder Counters

        Read encoder counters for both motors.

        Protocol:
            Send: [Address, 78]
            Receive: [Enc1(4 bytes), Enc2(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (enc1_count, enc2_count) where:
            - enc1_count: Encoder 1 count
            - enc2_count: Encoder 2 count
        """

        response = self._send_command_crc(78, 10)
        enc1_count = struct.unpack(">i", response[:4])[0]
        enc2_count = struct.unpack(">i", response[4:8])[0]

        return enc1_count, enc2_count

    def read_instantaneous_speeds(self) -> Tuple[int, int]:
        """Read instantaneous speeds.

        Command: 79 - Read Instantaneous Speeds

        Read instantaneous speeds for both motors.

        Protocol:
            Send: [Address, 79]
            Receive: [Speed1(4 bytes), Speed2(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (speed1, speed2) where:
            - speed1: Motor 1 instantaneous speed
            - speed2: Motor 2 instantaneous speed
        """

        response = self._send_command_crc(79, 10)
        speed1 = struct.unpack(">i", response[:4])[0]
        speed2 = struct.unpack(">i", response[4:8])[0]

        return speed1, speed2

    def restore_defaults(self):
        """Restore factory defaults.

        Command: 80 - Restore Defaults

        Reset all settings to factory defaults.

        Protocol:
            Send: [Address, 80]
            Receive: [0xFF]
        """

        self._send_command_ack(80)

    def read_default_duty_accelerations(self) -> Tuple[int, int]:
        """Read default duty accelerations.

        Command: 81 - Read Default Duty Accels

        Read default duty accelerations for both motors.

        Protocol:
            Send: [Address, 81]
            Receive: [M1Accel(4 bytes), M2Accel(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (m1_accel, m2_accel) where:
            - m1_accel: M1 default duty acceleration
            - m2_accel: M2 default duty acceleration
        """

        response = self._send_command_crc(81, 10)
        m1_accel = struct.unpack(">i", response[:4])[0]
        m2_accel = struct.unpack(">i", response[4:8])[0]

        return m1_accel, m2_accel

    def read_status(self) -> int:
        """Read unit status.

        Command: 90 - Read Status

        Read unit status flags.

        Protocol:
            Send: [Address, 90]
            Receive: [Status, CRC(2 bytes)]

        Returns:
            Status flags value.
        """

        response = self._send_command_crc(90, 3)
        return response[0]

    def read_encoder_modes(self) -> Tuple[int, int]:
        """Read encoder modes.

        Command: 91 - Read Encoder Modes

        Read encoder modes for both motors.

        Protocol:
            Send: [Address, 91]
            Receive: [Enc1Mode, Enc2Mode, CRC(2 bytes)]

        Returns:
            Tuple of (enc1_mode, enc2_mode) where:
            - enc1_mode: Encoder 1 mode
            - enc2_mode: Encoder 2 mode
        """

        response = self._send_command_crc(91, 4)
        enc1_mode = response[0]
        enc2_mode = response[1]

        return enc1_mode, enc2_mode

    def set_m1_encoder_mode(self, mode: int):
        """Set M1 encoder mode.

        Command: 92 - Set M1 Encoder Mode

        Set M1 encoder mode.

        Protocol:
            Send: [Address, 92, Mode, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            mode: Encoder mode value.
        """

        self._send_command_ack(92, struct.pack(">B", mode))

    def set_m2_encoder_mode(self, mode: int):
        """Set M2 encoder mode.

        Command: 93 - Set M2 Encoder Mode

        Set M2 encoder mode.

        Protocol:
            Send: [Address, 93, Mode, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            mode: Encoder mode value.
        """

        self._send_command_ack(93, struct.pack(">B", mode))

    def write_settings_to_eeprom(self):
        """Write settings to EEPROM.

        Command: 94 - Write Settings to EEPROM

        Save current settings to EEPROM.

        Protocol:
            Send: [Address, 94]
            Receive: [0xFF]
        """

        self._send_command_ack(94)

    def read_settings_from_eeprom(self):
        """Read settings from EEPROM.

        Command: 95 - Read Settings from EEPROM

        Load settings from EEPROM.

        Protocol:
            Send: [Address, 95]
            Receive: [0xFF]
        """

        self._send_command_ack(95)

    def set_standard_config(self, config: int):
        """Set standard configuration.

        Command: 98 - Set Standard Config

        Set standard configuration bits.

        Protocol:
            Send: [Address, 98, Config(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            config: Configuration value.
        """

        self._send_command_ack(98, struct.pack(">H", config))

    def read_standard_config(self) -> int:
        """Read standard configuration.

        Command: 99 - Read Standard Config

        Read standard configuration bits.

        Protocol:
            Send: [Address, 99]
            Receive: [Config(2 bytes), CRC(2 bytes)]

        Returns:
            Configuration value.
        """

        response = self._send_command_crc(99, 4)
        return struct.unpack(">H", response)[0]

    def set_ctrl_modes(self, ctrl1_mode: int, ctrl2_mode: int):
        """Set CTRL pin modes.

        Command: 100 - Set CTRL Modes

        Set CTRL pin modes.

        Protocol:
            Send: [Address, 100, CTRL1Mode, CTRL2Mode, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            ctrl1_mode: CTRL1 pin mode.
            ctrl2_mode: CTRL2 pin mode.
        """

        args = struct.pack(">BB", ctrl1_mode, ctrl2_mode)
        self._send_command_ack(100, args)

    def read_ctrl_modes(self) -> Tuple[int, int]:
        """Read CTRL pin modes.

        Command: 101 - Read CTRL Modes

        Read CTRL pin modes.

        Protocol:
            Send: [Address, 101]
            Receive: [CTRL1Mode, CTRL2Mode, CRC(2 bytes)]

        Returns:
            Tuple of (ctrl1_mode, ctrl2_mode) where:
            - ctrl1_mode: CTRL1 pin mode
            - ctrl2_mode: CTRL2 pin mode
        """

        response = self._send_command_crc(101, 4)
        ctrl1_mode = response[0]
        ctrl2_mode = response[1]

        return ctrl1_mode, ctrl2_mode

    def set_ctrl1(self, value: int):
        """Set CTRL1 output value.

        Command: 102 - Set CTRL1

        Set CTRL1 output value.

        Protocol:
            Send: [Address, 102, Value(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            value: CTRL1 output value.
        """

        self._send_command_ack(102, struct.pack(">H", value))

    def set_ctrl2(self, value: int):
        """Set CTRL2 output value.

        Command: 103 - Set CTRL2

        Set CTRL2 output value.

        Protocol:
            Send: [Address, 103, Value(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            value: CTRL2 output value.
        """

        self._send_command_ack(103, struct.pack(">H", value))

    def read_ctrl_settings(self) -> Tuple[int, int]:
        """Read CTRL output values.

        Command: 104 - Read CTRL Settings

        Read CTRL output values.

        Protocol:
            Send: [Address, 104]
            Receive: [CTRL1(2 bytes), CTRL2(2 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (ctrl1_value, ctrl2_value) where:
            - ctrl1_value: CTRL1 output value
            - ctrl2_value: CTRL2 output value
        """

        response = self._send_command_crc(104, 6)
        ctrl1_value = struct.unpack(">H", response[:2])[0]
        ctrl2_value = struct.unpack(">H", response[2:4])[0]

        return ctrl1_value, ctrl2_value

    def set_auto_home_m1(self, percentage: int, timeout: int):
        """Set M1 auto-home settings.

        Command: 105 - Set Auto Home M1

        Set M1 auto-home settings.

        Protocol:
            Send: [Address, 105, Percentage(2 bytes), Timeout(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            percentage: Auto-home percentage.
            timeout: Auto-home timeout.
        """

        args = struct.pack(">Hi", percentage, timeout)
        self._send_command_ack(105, args)

    def set_auto_home_m2(self, percentage: int, timeout: int):
        """Set M2 auto-home settings.

        Command: 106 - Set Auto Home M2

        Set M2 auto-home settings.

        Protocol:
            Send: [Address, 106, Percentage(2 bytes), Timeout(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            percentage: Auto-home percentage.
            timeout: Auto-home timeout.
        """

        args = struct.pack(">Hi", percentage, timeout)
        self._send_command_ack(106, args)

    def read_auto_home_settings(self) -> Tuple[int, int]:
        """Read auto-home settings.

        Command: 107 - Read Auto Home Settings

        Read auto-home settings.

        Protocol:
            Send: [Address, 107]
            Receive: [Percentage(2 bytes), Timeout(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (percentage, timeout) where:
            - percentage: Auto-home percentage
            - timeout: Auto-home timeout
        """

        response = self._send_command_crc(107, 8)
        percentage = struct.unpack(">H", response[:2])[0]
        timeout = struct.unpack(">i", response[2:6])[0]

        return percentage, timeout

    def read_average_speeds(self) -> Tuple[int, int]:
        """Read average speeds.

        Command: 108 - Read Average Speeds

        Read average speeds for both motors.

        Protocol:
            Send: [Address, 108]
            Receive: [Speed1(4 bytes), Speed2(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (speed1, speed2) where:
            - speed1: Motor 1 average speed
            - speed2: Motor 2 average speed
        """

        response = self._send_command_crc(108, 10)
        speed1 = struct.unpack(">i", response[:4])[0]
        speed2 = struct.unpack(">i", response[4:8])[0]

        return speed1, speed2

    def set_speed_error_limits(self, m1_limit: int, m2_limit: int):
        """Set speed error limits.

        Command: 109 - Set Speed Error Limits

        Set speed error limits for both motors.

        Protocol:
            Send: [Address, 109, M1Limit(4 bytes), M2Limit(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            m1_limit: M1 speed error limit.
            m2_limit: M2 speed error limit.
        """

        args = struct.pack(">ii", m1_limit, m2_limit)
        self._send_command_ack(109, args)

    def read_speed_error_limits(self) -> Tuple[int, int]:
        """Read speed error limits.

        Command: 110 - Read Speed Error Limits

        Read speed error limits for both motors.

        Protocol:
            Send: [Address, 110]
            Receive: [M1Limit(4 bytes), M2Limit(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (m1_limit, m2_limit) where:
            - m1_limit: M1 speed error limit
            - m2_limit: M2 speed error limit
        """

        response = self._send_command_crc(110, 10)
        m1_limit = struct.unpack(">i", response[:4])[0]
        m2_limit = struct.unpack(">i", response[4:8])[0]

        return m1_limit, m2_limit

    def read_speed_errors(self) -> Tuple[int, int]:
        """Read current speed errors.

        Command: 111 - Read Speed Errors

        Read current speed errors for both motors.

        Protocol:
            Send: [Address, 111]
            Receive: [M1Error(4 bytes), M2Error(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (m1_error, m2_error) where:
            - m1_error: M1 speed error
            - m2_error: M2 speed error
        """

        response = self._send_command_crc(111, 10)
        m1_error = struct.unpack(">i", response[:4])[0]
        m2_error = struct.unpack(">i", response[4:8])[0]

        return m1_error, m2_error

    def set_position_error_limits(self, m1_limit: int, m2_limit: int):
        """Set position error limits.

        Command: 112 - Set Position Error Limits

        Set position error limits for both motors.

        Protocol:
            Send: [Address, 112, M1Limit(4 bytes), M2Limit(4 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            m1_limit: M1 position error limit.
            m2_limit: M2 position error limit.
        """

        args = struct.pack(">ii", m1_limit, m2_limit)
        self._send_command_ack(112, args)

    def read_position_error_limits(self) -> Tuple[int, int]:
        """Read position error limits.

        Command: 113 - Read Position Error Limits

        Read position error limits for both motors.

        Protocol:
            Send: [Address, 113]
            Receive: [M1Limit(4 bytes), M2Limit(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (m1_limit, m2_limit) where:
            - m1_limit: M1 position error limit
            - m2_limit: M2 position error limit
        """

        response = self._send_command_crc(113, 10)
        m1_limit = struct.unpack(">i", response[:4])[0]
        m2_limit = struct.unpack(">i", response[4:8])[0]

        return m1_limit, m2_limit

    def read_position_errors(self) -> Tuple[int, int]:
        """Read current position errors.

        Command: 114 - Read Position Errors

        Read current position errors for both motors.

        Protocol:
            Send: [Address, 114]
            Receive: [M1Error(4 bytes), M2Error(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (m1_error, m2_error) where:
            - m1_error: M1 position error
            - m2_error: M2 position error
        """

        response = self._send_command_crc(114, 10)
        m1_error = struct.unpack(">i", response[:4])[0]
        m2_error = struct.unpack(">i", response[4:8])[0]

        return m1_error, m2_error

    def set_battery_voltage_offsets(self, main_offset: int, logic_offset: int):
        """Set battery voltage offsets.

        Command: 115 - Set Battery Voltage Offsets

        Set battery voltage offsets.

        Protocol:
            Send: [Address, 115, MainOffset, LogicOffset, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            main_offset: Main battery voltage offset.
            logic_offset: Logic battery voltage offset.
        """

        args = struct.pack(">BB", main_offset, logic_offset)
        self._send_command_ack(115, args)

    def read_battery_voltage_offsets(self) -> Tuple[int, int]:
        """Read battery voltage offsets.

        Command: 116 - Read Battery Voltage Offsets

        Read battery voltage offsets.

        Protocol:
            Send: [Address, 116]
            Receive: [MainOffset, LogicOffset, CRC(2 bytes)]

        Returns:
            Tuple of (main_offset, logic_offset) where:
            - main_offset: Main battery voltage offset
            - logic_offset: Logic battery voltage offset
        """

        response = self._send_command_crc(116, 4)
        main_offset = response[0]
        logic_offset = response[1]

        return main_offset, logic_offset

    def set_current_blanking(self, m1_blanking: int, m2_blanking: int):
        """Set current blanking percentages.

        Command: 117 - Set Current Blanking

        Set current blanking percentages for both motors.

        Protocol:
            Send: [Address, 117, M1Blanking(2 bytes), M2Blanking(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            m1_blanking: M1 current blanking percentage.
            m2_blanking: M2 current blanking percentage.
        """

        args = struct.pack(">HH", m1_blanking, m2_blanking)
        self._send_command_ack(117, args)

    def read_current_blanking(self) -> Tuple[int, int]:
        """Read current blanking percentages.

        Command: 118 - Read Current Blanking

        Read current blanking percentages for both motors.

        Protocol:
            Send: [Address, 118]
            Receive: [M1Blanking(2 bytes), M2Blanking(2 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (m1_blanking, m2_blanking) where:
            - m1_blanking: M1 current blanking percentage
            - m2_blanking: M2 current blanking percentage
        """

        response = self._send_command_crc(118, 6)
        m1_blanking = struct.unpack(">H", response[:2])[0]
        m2_blanking = struct.unpack(">H", response[2:4])[0]

        return m1_blanking, m2_blanking

    def buffered_move_m1_to_position_simple(self, position: int, buffer: int):
        """Move M1 motor to position (simple buffered).

        Command: 119 - Buffered M1 Position (Simple)

        Move M1 motor to specified position using default speeds.

        Protocol:
            Send: [Address, 119, Position(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            position: Target position.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iB", position, buffer)
        self._send_command_ack(119, args)

    def buffered_move_m2_to_position_simple(self, position: int, buffer: int):
        """Move M2 motor to position (simple buffered).

        Command: 120 - Buffered M2 Position (Simple)

        Move M2 motor to specified position using default speeds.

        Protocol:
            Send: [Address, 120, Position(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            position: Target position.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iB", position, buffer)
        self._send_command_ack(120, args)

    def buffered_move_m1_m2_to_position_simple(self, pos_m1: int, pos_m2: int, buffer: int):
        """Move M1 and M2 motors to positions (simple buffered).

        Command: 121 - Buffered M1/M2 Position (Simple)

        Move both M1 and M2 motors to specified positions using default speeds.

        Protocol:
            Send: [Address, 121, PosM1(4 bytes), PosM2(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            pos_m1: M1 target position.
            pos_m2: M2 target position.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiB", pos_m1, pos_m2, buffer)
        self._send_command_ack(121, args)

    def buffered_move_m1_with_speed_to_position(self, speed: int, position: int, buffer: int):
        """Move M1 motor with speed to position (buffered).

        Command: 122 - Buffered M1 Speed+Position

        Move M1 motor with specified speed to position.

        Protocol:
            Send: [Address, 122, Speed(4 bytes), Position(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value.
            position: Target position.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiB", speed, position, buffer)
        self._send_command_ack(122, args)

    def buffered_move_m2_with_speed_to_position(self, speed: int, position: int, buffer: int):
        """Move M2 motor with speed to position (buffered).

        Command: 123 - Buffered M2 Speed+Position

        Move M2 motor with specified speed to position.

        Protocol:
            Send: [Address, 123, Speed(4 bytes), Position(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed: Speed value.
            position: Target position.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiB", speed, position, buffer)
        self._send_command_ack(123, args)

    def buffered_move_m1_m2_with_speed_to_position(self, speed_m1: int, pos_m1: int, speed_m2: int, pos_m2: int, buffer: int):
        """Move M1 and M2 motors with speed to positions (buffered).

        Command: 124 - Buffered M1/M2 Speed+Position

        Move both M1 and M2 motors with specified speeds to positions.

        Protocol:
            Send: [Address, 124, SpeedM1(4 bytes), PosM1(4 bytes), SpeedM2(4 bytes), PosM2(4 bytes), Buffer, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            speed_m1: M1 speed value.
            pos_m1: M1 target position.
            speed_m2: M2 speed value.
            pos_m2: M2 target position.
            buffer: Buffer mode (0=add to buffer, 1=execute immediately).
        """

        args = struct.pack(">iiiiB", speed_m1, pos_m1, speed_m2, pos_m2, buffer)
        self._send_command_ack(124, args)

    def set_m1_max_current(self, max_current: int):
        """Set M1 maximum current limit.

        Command: 133 - Set M1 Max Current

        Set M1 maximum current limit.

        Protocol:
            Send: [Address, 133, MaxCurrent(4 bytes), 0, 0, 0, 0, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            max_current: Maximum current limit.
        """

        args = struct.pack(">iBBBB", max_current, 0, 0, 0, 0)
        self._send_command_ack(133, args)

    def set_m2_max_current(self, max_current: int):
        """Set M2 maximum current limit.

        Command: 134 - Set M2 Max Current

        Set M2 maximum current limit.

        Protocol:
            Send: [Address, 134, MaxCurrent(4 bytes), 0, 0, 0, 0, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            max_current: Maximum current limit.
        """

        args = struct.pack(">iBBBB", max_current, 0, 0, 0, 0)
        self._send_command_ack(134, args)

    def read_m1_max_current(self) -> Tuple[int, int]:
        """Read M1 current limits.

        Command: 135 - Read M1 Max Current

        Read M1 maximum and minimum current limits.

        Protocol:
            Send: [Address, 135]
            Receive: [MaxCurrent(4 bytes), MinCurrent(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (max_current, min_current) where:
            - max_current: Maximum current limit
            - min_current: Minimum current limit
        """

        response = self._send_command_crc(135, 10)
        max_current = struct.unpack(">i", response[:4])[0]
        min_current = struct.unpack(">i", response[4:8])[0]

        return max_current, min_current

    def read_m2_max_current(self) -> Tuple[int, int]:
        """Read M2 current limits.

        Command: 136 - Read M2 Max Current

        Read M2 maximum and minimum current limits.

        Protocol:
            Send: [Address, 136]
            Receive: [MaxCurrent(4 bytes), MinCurrent(4 bytes), CRC(2 bytes)]

        Returns:
            Tuple of (max_current, min_current) where:
            - max_current: Maximum current limit
            - min_current: Minimum current limit
        """

        response = self._send_command_crc(136, 10)
        max_current = struct.unpack(">i", response[:4])[0]
        min_current = struct.unpack(">i", response[4:8])[0]

        return max_current, min_current

    def set_pwm_mode(self, mode: int):
        """Set PWM mode.

        Command: 148 - Set PWM Mode

        Set PWM mode.

        Protocol:
            Send: [Address, 148, Mode, CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            mode: PWM mode (0=Locked Antiphase, 1=Sign Magnitude).
        """

        self._send_command_ack(148, struct.pack(">B", mode))

    def read_pwm_mode(self) -> int:
        """Read PWM mode.

        Command: 149 - Read PWM Mode

        Read PWM mode.

        Protocol:
            Send: [Address, 149]
            Receive: [Mode, CRC(2 bytes)]

        Returns:
            PWM mode (0=Locked Antiphase, 1=Sign Magnitude).
        """

        response = self._send_command_crc(149, 3)
        return response[0]

    def write_user_eeprom(self, address: int, value: int):
        """Write to user EEPROM.

        Command: 252 - Write User EEPROM

        Write value to user EEPROM at specified address.

        Protocol:
            Send: [Address, 252, MemAddr, Value(2 bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            address: Memory address.
            value: Value to write.
        """

        args = struct.pack(">BH", address, value)
        self._send_command_ack(252, args)

    def read_user_eeprom(self, address: int) -> int:
        """Read from user EEPROM.

        Command: 253 - Read User EEPROM

        Read value from user EEPROM at specified address.

        Protocol:
            Send: [Address, 253, MemAddr]
            Receive: [Value(2 bytes), CRC(2 bytes)]

        Args:
            address: Memory address.

        Returns:
            Value read from EEPROM.
        """

        response = self._send_command_crc(253, 4, struct.pack(">B", address))
        return struct.unpack(">H", response)[0]


def main():
    """Demo function to test RoboClaw functionality."""
    with RoboClaw("/dev/ttyTHS1") as rc:
        

        while True:
            try:
                response = rc.drive_m1_m2_with_signed_duty_cycle(-32767, 32767)
                time.sleep(0.5)
            except KeyboardInterrupt:
                print("Demo interrupted by user.")
                break
            except Exception as e:
                print(f"An error occurred: {e}")
                break


if __name__ == "__main__":
    main()
