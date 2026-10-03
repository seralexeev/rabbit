import asyncio
import os

import numpy as np
from lib.ina4235 import CLIP_FRACTION, channel_calibrations, is_clipped
from lib.node import RabbitNode
from smbus2 import SMBus

I2C_BUS = int(os.environ.get("I2C_BUS", "7"))
INA_ADDR = 0x41

LSB_VBUS = 1.6e-3  # V/LSB

SHUNT_VOLT_REGS = {1: 0x00, 2: 0x08, 3: 0x10, 4: 0x18}
BUS_VOLT_REGS = {1: 0x01, 2: 0x09, 3: 0x11, 4: 0x19}
CURRENT_REGS = {1: 0x02, 2: 0x0A, 3: 0x12, 4: 0x1A}
CALIB_REGS = {1: 0x05, 2: 0x0D, 3: 0x15, 4: 0x1D}
CONFIG1_REG = 0x20
CHANNELS = {1: "battery", 2: "rail_6v"}
ACTIVE_CHANNELS = sum(1 << (ch - 1) for ch in CHANNELS)
CONFIG1 = (ACTIVE_CHANNELS << 12) | (0b001 << 9) | (0b011 << 6) | (0b011 << 3) | 0b111

BATTERY_CELLS = 4
CELL_VOLTAGE = np.array([3.30, 3.55, 3.65, 3.70, 3.74, 3.79, 3.85, 3.92, 4.00, 4.10, 4.20])
CELL_CHARGE_PCT = np.array([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100])

INA_SUBJECT = "rabbit.ina"
PUBLISH_INTERVAL = 0.02


def swap_bytes(val: int) -> int:
    return ((val & 0xFF) << 8) | (val >> 8)


def twos_complement(val: int, bits: int = 16) -> int:
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val


class Node(RabbitNode):
    def __init__(self):
        super().__init__("ina4235")
        self.calibrations = channel_calibrations(CHANNELS, os.environ.get("INA_SHUNT_OHMS"), os.environ.get("INA_MAX_CURRENT_A"))
        self.bus = SMBus(I2C_BUS)
        self.errors = 0

    async def init(self):
        self._write_calibration()
        self.set_interval(self.publish_metrics, PUBLISH_INTERVAL, max_parallel=1)

    def _write_calibration(self):
        self.bus.write_word_data(INA_ADDR, CONFIG1_REG, swap_bytes(CONFIG1))
        fields = {}
        for ch, cal in self.calibrations.items():
            self.bus.write_word_data(INA_ADDR, CALIB_REGS[ch], swap_bytes(cal.shunt_cal))
            fields |= {
                f"ch{ch}_name": CHANNELS[ch],
                f"ch{ch}_shunt_ohms": cal.shunt_ohms,
                f"ch{ch}_max_current_a": cal.max_current_a,
                f"ch{ch}_full_scale_a": cal.full_scale_a,
                f"ch{ch}_clip_a": cal.clip_a,
                f"ch{ch}_current_lsb_a": cal.current_lsb_a,
                f"ch{ch}_shunt_cal": cal.shunt_cal,
            }
        summary = ", ".join(f"ch{ch} {CHANNELS[ch]} {cal.shunt_ohms * 1000:g} mOhm SHUNT_CAL={cal.shunt_cal} LSB={cal.current_lsb_a * 1000:g} mA" for ch, cal in self.calibrations.items())
        self.event(
            "power.calibrated",
            "INA4235 shunts calibrated",
            message=f"Written CONFIG1={CONFIG1:#06x}; {summary}",
            config1=CONFIG1,
            clip_fraction=CLIP_FRACTION,
            **fields,
        )

    def _read_word(self, reg: int) -> int:
        raw = self.bus.read_word_data(INA_ADDR, reg)
        return swap_bytes(raw)

    def read_bus_voltage(self, ch: int) -> float:
        raw = self._read_word(BUS_VOLT_REGS[ch])
        return raw * LSB_VBUS

    def read_signed(self, reg: int) -> int:
        return twos_complement(self._read_word(reg))

    def read_channels(self) -> list[dict]:
        channels = []
        for ch, name in CHANNELS.items():
            voltage = self.read_bus_voltage(ch)
            shunt_raw = self.read_signed(SHUNT_VOLT_REGS[ch])
            current_raw = self.read_signed(CURRENT_REGS[ch])
            current = current_raw * self.calibrations[ch].current_lsb_a
            channels.append(
                {
                    "ch": ch,
                    "name": name,
                    "voltage": round(voltage, 3),
                    "current": round(current, 3),
                    "power": round(voltage * current, 3),
                    "clipped": is_clipped(shunt_raw, current_raw),
                }
            )
        return channels

    async def publish_metrics(self):
        try:
            channels = await asyncio.to_thread(self.read_channels)
        except OSError as e:
            self.errors += 1
            self.logger.error(f"Error reading INA4235: {e}")
            return

        battery = channels[0]
        charge = np.interp(battery["voltage"] / BATTERY_CELLS, CELL_VOLTAGE, CELL_CHARGE_PCT)
        await self.publish_json(
            INA_SUBJECT,
            {
                "channels": channels,
                "battery_charge_pct": round(float(charge), 1),
                "errors": self.errors,
            },
        )

    async def close(self):
        await super().close()
        self.bus.close()


if __name__ == "__main__":
    Node().run_node()
