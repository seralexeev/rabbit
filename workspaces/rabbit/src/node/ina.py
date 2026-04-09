import json

from lib.node import RabbitNode
from smbus2 import SMBus

I2C_BUS = 7
INA_ADDR = 0x41

R_SHUNT = 0.01  # Ohm
CURRENT_LSB = 0.001  # 1 mA/LSB
LSB_VBUS = 1.6e-3  # V/LSB

BUS_VOLT_REGS = {1: 0x01, 2: 0x09, 3: 0x11, 4: 0x19}
CURRENT_REGS = {1: 0x02, 2: 0x0A, 3: 0x12, 4: 0x1A}
CALIB_REGS = {1: 0x05, 2: 0x0D, 3: 0x15, 4: 0x1D}

INA_SUBJECT = "rabbit.ina"
PUBLISH_INTERVAL = 1.0


def swap_bytes(val: int) -> int:
    return ((val & 0xFF) << 8) | (val >> 8)


def twos_complement(val: int, bits: int = 16) -> int:
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val


class Node(RabbitNode):
    def __init__(self):
        super().__init__("ina4235")
        self.bus = SMBus(I2C_BUS)

    async def init(self):
        self._write_calibration()
        self.set_interval(self.publish_metrics, PUBLISH_INTERVAL)

    def _write_calibration(self):
        shunt_cal = int(0.00512 / (CURRENT_LSB * R_SHUNT))
        cal_swapped = swap_bytes(shunt_cal)
        for reg in CALIB_REGS.values():
            self.bus.write_word_data(INA_ADDR, reg, cal_swapped)
        self.logger.info(f"Written SHUNT_CAL={shunt_cal} to calibration registers")

    def _read_word(self, reg: int) -> int:
        raw = self.bus.read_word_data(INA_ADDR, reg)
        return swap_bytes(raw)

    def read_bus_voltage(self, ch: int) -> float:
        raw = self._read_word(BUS_VOLT_REGS[ch])
        return raw * LSB_VBUS

    def read_current(self, ch: int) -> float:
        raw = self._read_word(CURRENT_REGS[ch])
        signed = twos_complement(raw)
        return signed * CURRENT_LSB

    async def publish_metrics(self):
        channels = []
        for ch in range(1, 5):
            try:
                voltage = self.read_bus_voltage(ch)
                current = self.read_current(ch)
                channels.append(
                    {
                        "ch": ch,
                        "voltage": round(voltage, 3),
                        "current": round(current, 3),
                        "power": round(voltage * current, 3),
                    }
                )
            except Exception as e:
                self.logger.error(f"Error reading CH{ch}: {e}")

        payload = json.dumps({"channels": channels}).encode()
        await self.nc.publish(INA_SUBJECT, payload)

    async def close(self):
        await super().close()
        self.bus.close()


if __name__ == "__main__":
    Node().run_node()
