#!/usr/bin/env python3
import time
from smbus2 import SMBus

# Параметры I2C
I2C_BUS    = 7        # ваша шина I²C
INA_ADDR   = 0x41     # адрес INA4235
# Адреса регистров Bus Voltage для каналов 1–4
BUS_VOLT_REGS = {
    1: 0x01,  # BUS_VOLTAGE_CH1
    2: 0x09,  # BUS_VOLTAGE_CH2
    3: 0x11,  # BUS_VOLTAGE_CH3
    4: 0x19,  # BUS_VOLTAGE_CH4
}

# LSB = 1.6 mV
LSB_VBUS = 1.6e-3  # V

def read_bus_voltage(bus, addr, reg):
    raw = bus.read_word_data(addr, reg)
    # поменять порядок байт (little-endian → big-endian)
    raw_swapped = ((raw & 0xFF) << 8) | (raw >> 8)
    # все 16 бит содержат значение VBUS
    return raw_swapped * LSB_VBUS

def main():
    with SMBus(I2C_BUS) as bus:
        print(f"Чтение напряжения по каналам 1–4 на I2C/{I2C_BUS}, addr=0x{INA_ADDR:02X}")
        try:
            while True:
                for ch, reg in BUS_VOLT_REGS.items():
                    v = read_bus_voltage(bus, INA_ADDR, reg)
                    print(f"VBUS{ch} = {v:.3f} В")
                print("-" * 30)
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("Прерывание пользователем, выход.")

if __name__ == "__main__":
    main()
