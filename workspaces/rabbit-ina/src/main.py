#!/usr/bin/env python3
import time
from smbus2 import SMBus

# ====== Параметры I²C ======
I2C_BUS  = 7         # ваша шина I²C
INA_ADDR = 0x41      # адрес INA4235

# ====== Шунт и LSB ======
R_SHUNT     = 0.01   # Ω, внешний шунт (например 10 mΩ)
CURRENT_LSB = 0.001  # A/LSB (1 mA)

# ====== Адреса регистров ======
BUS_VOLT_REGS = {1: 0x01, 2: 0x09, 3: 0x11, 4: 0x19}
CURRENT_REGS  = {1: 0x02, 2: 0x0A, 3: 0x12, 4: 0x1A}
CALIB_REGS    = {1: 0x05, 2: 0x0D, 3: 0x15, 4: 0x1D}

LSB_VBUS = 1.6e-3    # V/LSB для Bus Voltage

def swap_bytes(val: int) -> int:
    """Малый и большой байты меняются местами (little→big endian)."""
    return ((val & 0xFF) << 8) | (val >> 8)

def write_calibration(bus: SMBus):
    """Записываем SHUNT_CAL = 0.00512/(CURRENT_LSB*R_SHUNT) во все каналы."""
    shunt_cal = int(0.00512 / (CURRENT_LSB * R_SHUNT))
    cal_swapped = swap_bytes(shunt_cal)
    for reg in CALIB_REGS.values():
        bus.write_word_data(INA_ADDR, reg, cal_swapped)
    print(f"Written SHUNT_CAL={shunt_cal} to calibration registers")

def read_word(bus: SMBus, reg: int) -> int:
    """Чтение 16-битного регистра с учётом порядка байт."""
    raw = bus.read_word_data(INA_ADDR, reg)
    return swap_bytes(raw)

def twos_complement(val: int, bits: int = 16) -> int:
    """Преобразование 16-битного two’s-complement в signed int."""
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val

def read_bus_voltage(bus: SMBus, ch: int) -> float:
    """Напряжение шины [В] для канала ch."""
    raw = read_word(bus, BUS_VOLT_REGS[ch])
    return raw * LSB_VBUS

def read_current(bus: SMBus, ch: int) -> float:
    """Ток [А] для канала ch."""
    raw = read_word(bus, CURRENT_REGS[ch])
    signed = twos_complement(raw)
    return signed * CURRENT_LSB

def main():
    with SMBus(I2C_BUS) as bus:
        write_calibration(bus)
        print(f"Start reading on I2C/{I2C_BUS} addr=0x{INA_ADDR:02X}")
        try:
            while True:
                for ch in range(1, 5):
                    voltage = read_bus_voltage(bus, ch)
                    current = read_current(bus, ch)
                    power = voltage * current
                    print(f"CH{ch}: VBUS = {voltage:.3f} V, I = {current:.3f} A, P = {power:.3f} W")
                print("-" * 50)
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("Stopped by user.")

if __name__ == "__main__":
    main()
