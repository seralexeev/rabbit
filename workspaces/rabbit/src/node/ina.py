import asyncio

from lib.node import RabbitNode
from smbus2 import SMBus

I2C_BUS = 7
INA_ADDR = 0x41

R_SHUNT = 0.01  # Ом
CURRENT_LSB = 0.001  # 1 мА/LSB
LSB_VBUS = 1.6e-3  # В/LSB

BUS_VOLT_REGS = {1: 0x01, 2: 0x09, 3: 0x11, 4: 0x19}
CURRENT_REGS = {1: 0x02, 2: 0x0A, 3: 0x12, 4: 0x1A}
CALIB_REGS = {1: 0x05, 2: 0x0D, 3: 0x15, 4: 0x1D}


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
        await self.task(self.publish_metrics)

    def _write_calibration(self):
        shunt_cal = int(0.00512 / (CURRENT_LSB * R_SHUNT))
        cal_swapped = swap_bytes(shunt_cal)
        for reg in CALIB_REGS.values():
            self.bus.write_word_data(INA_ADDR, reg, cal_swapped)
        print(f"✅ Written SHUNT_CAL={shunt_cal} to calibration registers")

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
        while True:
            try:
                for ch in range(1, 5):
                    voltage = self.read_bus_voltage(ch)
                    current = self.read_current(ch)
                    power = voltage * current
                    print(
                        f"CH{ch}: VBUS = {voltage:.3f} V, I = {current:.3f} A, P = {power:.3f} W"
                    )
                print("-" * 50)
            except Exception as e:
                print(f"⚠️ Error reading INA4235: {e}")
            await asyncio.sleep(1)

    async def close(self):
        await super().close()
        self.bus.close()
        print("🧹 SMBus closed")


if __name__ == "__main__":
    Node().run_node()
