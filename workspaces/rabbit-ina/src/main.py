"""
INA4235 4-Channel Current/Voltage/Power Monitor
Jetson Orin Nano I2C Reader

Shunt resistor: 0.01 Ohm (10 mΩ)
Max current per channel: ~8.2A
"""

import smbus2 as smbus
import time
import struct


class INA4235:
    # I2C address (default with SW0=SW1=GND)
    DEFAULT_ADDRESS = 0x41

    # Register addresses
    REG_CONFIG1 = 0x00
    REG_CONFIG2 = 0x01
    REG_CALIBRATION_CH1 = 0x02
    REG_CALIBRATION_CH2 = 0x03
    REG_CALIBRATION_CH3 = 0x04
    REG_CALIBRATION_CH4 = 0x05

    REG_SHUNT_VOLTAGE_CH1 = 0x06
    REG_SHUNT_VOLTAGE_CH2 = 0x07
    REG_SHUNT_VOLTAGE_CH3 = 0x08
    REG_SHUNT_VOLTAGE_CH4 = 0x09

    REG_BUS_VOLTAGE_CH1 = 0x0A
    REG_BUS_VOLTAGE_CH2 = 0x0B
    REG_BUS_VOLTAGE_CH3 = 0x0C
    REG_BUS_VOLTAGE_CH4 = 0x0D

    REG_CURRENT_CH1 = 0x0E
    REG_CURRENT_CH2 = 0x0F
    REG_CURRENT_CH3 = 0x10
    REG_CURRENT_CH4 = 0x11

    REG_POWER_CH1 = 0x12
    REG_POWER_CH2 = 0x13
    REG_POWER_CH3 = 0x14
    REG_POWER_CH4 = 0x15

    def __init__(self, bus_num=1, address=DEFAULT_ADDRESS):
        """
        Initialize INA4235
        bus_num: I2C bus number (1 for pins 3,5 on Jetson)
        address: I2C address
        """
        self.bus = smbus.SMBus(bus_num)
        self.address = address
        self.shunt_resistance = 0.01  # 10 mΩ shunt resistors

        # Calibration values for current calculation
        self.current_lsb = 0.001  # 1mA per LSB
        self.cal_value = self._calculate_calibration()

        print(f"INA4235 initialized at address 0x{address:02X}")
        self._setup_device()

    def _calculate_calibration(self):
        """Calculate calibration register value"""
        # CAL = 0.00512 / (Current_LSB * R_shunt)
        cal = 0.00512 / (self.current_lsb * self.shunt_resistance)
        return int(cal)

    def _read_register(self, reg):
        """Read 16-bit register"""
        try:
            # Read 2 bytes (big endian)
            data = self.bus.read_i2c_block_data(self.address, reg, 2)
            return (data[0] << 8) | data[1]
        except Exception as e:
            print(f"Error reading register 0x{reg:02X}: {e}")
            return None

    def _write_register(self, reg, value):
        """Write 16-bit register"""
        try:
            # Write 2 bytes (big endian)
            data = [(value >> 8) & 0xFF, value & 0xFF]
            self.bus.write_i2c_block_data(self.address, reg, data)
        except Exception as e:
            print(f"Error writing register 0x{reg:02X}: {e}")

    def _signed_16bit(self, value):
        """Convert unsigned 16-bit to signed"""
        if value > 32767:
            return value - 65536
        return value

    def _setup_device(self):
        """Configure INA4235 for operation"""
        print("Setting up INA4235...")

        # CONFIG1: Continuous mode, all channels enabled
        # Default should be fine: 0x0000
        config1 = 0x0000
        self._write_register(self.REG_CONFIG1, config1)

        # CONFIG2: ±81.92mV range, default conversion times
        # Bit 4 (ADCRANGE): 0 = ±81.92mV, 1 = ±20.48mV
        config2 = 0x0000  # Use ±81.92mV range
        self._write_register(self.REG_CONFIG2, config2)

        # Set calibration for all channels
        print(f"Setting calibration value: {self.cal_value}")
        self._write_register(self.REG_CALIBRATION_CH1, self.cal_value)
        self._write_register(self.REG_CALIBRATION_CH2, self.cal_value)
        self._write_register(self.REG_CALIBRATION_CH3, self.cal_value)
        self._write_register(self.REG_CALIBRATION_CH4, self.cal_value)

        # Wait for first conversion
        time.sleep(0.1)
        print("Setup complete!")

    def read_shunt_voltage(self, channel):
        """Read shunt voltage in mV"""
        if channel < 1 or channel > 4:
            raise ValueError("Channel must be 1-4")

        reg = self.REG_SHUNT_VOLTAGE_CH1 + (channel - 1)
        raw = self._read_register(reg)

        if raw is None:
            return None

        # Convert to signed and apply LSB (2.5µV per LSB for ±81.92mV range)
        signed_raw = self._signed_16bit(raw)
        voltage_mv = signed_raw * 0.0025  # 2.5µV LSB in mV
        return voltage_mv

    def read_bus_voltage(self, channel):
        """Read bus voltage in V"""
        if channel < 1 or channel > 4:
            raise ValueError("Channel must be 1-4")

        reg = self.REG_BUS_VOLTAGE_CH1 + (channel - 1)
        raw = self._read_register(reg)

        if raw is None:
            return None

        # Bus voltage LSB is 1.6mV
        voltage_v = raw * 0.0016
        return voltage_v

    def read_current(self, channel):
        """Read current in A"""
        if channel < 1 or channel > 4:
            raise ValueError("Channel must be 1-4")

        reg = self.REG_CURRENT_CH1 + (channel - 1)
        raw = self._read_register(reg)

        if raw is None:
            return None

        # Convert to signed and apply current LSB
        signed_raw = self._signed_16bit(raw)
        current_a = signed_raw * self.current_lsb
        return current_a

    def read_power(self, channel):
        """Read power in W"""
        if channel < 1 or channel > 4:
            raise ValueError("Channel must be 1-4")

        reg = self.REG_POWER_CH1 + (channel - 1)
        raw = self._read_register(reg)

        if raw is None:
            return None

        # Power LSB = Current_LSB × 6.4 × Bus_Voltage_LSB
        # Power LSB = 0.001 × 6.4 × 1.6mV = 0.01024 W
        power_lsb = self.current_lsb * 6.4 * 0.0016
        power_w = raw * power_lsb
        return power_w

    def read_all_channels(self):
        """Read all measurements from all channels"""
        results = {}

        for ch in range(1, 5):
            shunt_mv = self.read_shunt_voltage(ch)
            bus_v = self.read_bus_voltage(ch)
            current_a = self.read_current(ch)
            power_w = self.read_power(ch)

            # Calculate current from shunt voltage as verification
            calculated_current = None
            if shunt_mv is not None:
                calculated_current = shunt_mv / 1000.0 / self.shunt_resistance

            results[f"ch{ch}"] = {
                "shunt_voltage_mv": shunt_mv,
                "bus_voltage_v": bus_v,
                "current_a": current_a,
                "current_calculated_a": calculated_current,
                "power_w": power_w,
            }

        return results

    def print_readings(self):
        """Print formatted readings"""
        data = self.read_all_channels()

        print("\n" + "=" * 80)
        print("INA4235 Readings")
        print("=" * 80)
        print(
            f"{'Ch':<3} {'Shunt(mV)':<12} {'Bus(V)':<10} {'Current(A)':<12} {'Calc I(A)':<12} {'Power(W)':<10}"
        )
        print("-" * 80)

        for ch in range(1, 5):
            ch_data = data[f"ch{ch}"]

            shunt_str = (
                f"{ch_data['shunt_voltage_mv']:.3f}"
                if ch_data["shunt_voltage_mv"] is not None
                else "ERROR"
            )
            bus_str = (
                f"{ch_data['bus_voltage_v']:.3f}"
                if ch_data["bus_voltage_v"] is not None
                else "ERROR"
            )
            current_str = (
                f"{ch_data['current_a']:.3f}"
                if ch_data["current_a"] is not None
                else "ERROR"
            )
            calc_str = (
                f"{ch_data['current_calculated_a']:.3f}"
                if ch_data["current_calculated_a"] is not None
                else "ERROR"
            )
            power_str = (
                f"{ch_data['power_w']:.3f}"
                if ch_data["power_w"] is not None
                else "ERROR"
            )

            print(
                f"{ch:<3} {shunt_str:<12} {bus_str:<10} {current_str:<12} {calc_str:<12} {power_str:<10}"
            )


def main():
    """Main function for testing"""
    try:
        print("INA4235 4-Channel Current Monitor")
        print("Shunt resistance: 0.01 Ohm per channel")
        print("Maximum current per channel: ~8.2A")
        print("-" * 50)

        # Initialize INA4235
        ina = INA4235(bus_num=1, address=0x40)

        print("\nStarting continuous monitoring...")
        print("Press Ctrl+C to stop")

        while True:
            ina.print_readings()
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
    except Exception as e:
        print(f"Error: {e}")
        print("\nTroubleshooting:")
        print("1. Check I2C connections")
        print("2. Verify I2C is enabled: sudo i2cdetect -y 1")
        print("3. Check address switches SW0/SW1")
        print("4. Verify 3.3V power and enable jumper")


if __name__ == "__main__":
    main()
