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

    def read_firmware_version(self) -> str:
        """Read RoboClaw firmware version.

        Command: 21 - Read Firmware Version

        Read RoboClaw firmware version. Returns up to 48 bytes (depending on the RoboClaw model)
        and is terminated by a line feed character and a null character.

        Protocol:
            Send: [Address, 21]
            Receive: ["RoboClaw 10.2A v4.1.11", 10, 0, CRC(2 bytes)]

        The command will return up to 48 bytes. The return string includes the product name and
        firmware version. The return string is terminated with a line feed (10) and null (0) character.

        Returns:
            Firmware version string.
        """

        response = self._send_command_crc(21, 48)
        version = ""
        for byte in response:
            if byte == 10:
                break
            version += chr(byte)

        return version

    def drive_m1_with_signed_duty_cycle(self, duty: int):
        """Drive M1 motor using signed duty cycle.

        Command: 32 - Drive M1 With Signed Duty Cycle

        Drive M1 using a duty cycle value. The duty cycle is used to control the speed
        of the motor without a quadrature encoder.

        Protocol:
            Send: [Address, 32, Duty(2 Bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            duty: Duty cycle value in range -32767 to +32767 (±100% duty).
        """

        self._send_command_ack(32, struct.pack(">h", duty))

    def drive_m2_with_signed_duty_cycle(self, duty: int):
        """Drive M2 motor using signed duty cycle.

        Command: 33 - Drive M2 With Signed Duty Cycle

        Drive M2 using a duty cycle value. The duty cycle is used to control the speed
        of the motor without a quadrature encoder.

        Protocol:
            Send: [Address, 33, Duty(2 Bytes), CRC(2 bytes)]
            Receive: [0xFF]

        Args:
            duty: Duty cycle value in range -32767 to +32767 (±100% duty).
        """

        self._send_command_ack(33, struct.pack(">h", duty))

    def read_temperature(self) -> float:
        """Read board temperature.

        Command: 82 - Read Temperature

        Read the board temperature. Value returned is in 10ths of degrees.

        Protocol:
            Send: [Address, 82]
            Receive: [Temperature(2 bytes), CRC(2 bytes)]

        Returns:
            Temperature in degrees Celsius.
        """

        response = self._send_command_crc(82, 4)
        return struct.unpack(">h", response)[0] / 10.0

    def read_temperature_2(self) -> float:
        """Read second board temperature.

        Command: 83 - Read Temperature 2

        Read the second board temperature (only on supported units).
        Value returned is in 10ths of degrees.

        Protocol:
            Send: [Address, 83]
            Receive: [Temperature(2 bytes), CRC(2 bytes)]

        Returns:
            Temperature in degrees Celsius.
        """

        response = self._send_command_crc(83, 4)
        return struct.unpack(">h", response)[0] / 10.0

    def read_encoder_speed_m1(self) -> Tuple[int, int]:
        """Read M1 encoder speed.

        Command: 18 - Read Encoder Speed M1

        Read M1 counter speed. Returned value is in pulses per second.
        RoboClaw keeps track of how many pulses received per second for both encoder channels.

        Protocol:
            Send: [Address, 18]
            Receive: [Speed(4 bytes), Status, CRC(2 bytes)]

        Returns:
            Tuple of (speed, status) where:
            - speed: Speed in pulses per second
            - status: Direction indicator (0 = forward, 1 = backward)
        """

        response = self._send_command_crc(18, 7)
        speed = struct.unpack(">i", response[:4])[0]
        status = response[4]

        return speed, status

    def read_encoder_speed_m2(self) -> Tuple[int, int]:
        """Read M2 encoder speed.

        Command: 19 - Read Encoder Speed M2

        Read M2 counter speed. Returned value is in pulses per second.
        RoboClaw keeps track of how many pulses received per second for both encoder channels.

        Protocol:
            Send: [Address, 19]
            Receive: [Speed(4 bytes), Status, CRC(2 bytes)]

        Returns:
            Tuple of (speed, status) where:
            - speed: Speed in pulses per second
            - status: Direction indicator (0 = forward, 1 = backward)
        """

        response = self._send_command_crc(19, 7)
        speed = struct.unpack(">i", response[:4])[0]
        status = response[4]

        return speed, status


def main():
    """Demo function to test RoboClaw functionality."""
    with RoboClaw("/dev/ttyTHS1") as rc:
        response = rc.read_firmware_version()
        print(f"Response from command 21: {response}")

        while True:
            try:
                speed, status = rc.read_encoder_speed_m1()
                print(f"Encoder Speed: {speed} pulses/sec, Status: {status}")
                time.sleep(0.5)
            except KeyboardInterrupt:
                print("Demo interrupted by user.")
                break
            except Exception as e:
                print(f"An error occurred: {e}")
                break


if __name__ == "__main__":
    main()
