# Body board rev C: firmware bring-up map

Date 2026-10-12 (Sydney). This is the reference to write the STM32 firmware and the Pi-side drivers from.

**Truth.** Every pin, net, strap and resistor value below was read from the routed board, `pcb/rabbit-body-c/rabbit-body-c.kicad_pcb` (2026-10-11 14:00), with KiCad pcbnew. Where an older document disagrees, the board wins.

**Datasheet pages** are PDF pages of the files in `datasheet/`. [mem] marks facts from the ST reference manual RM0440 or AN2606: both are not in the repo, because st.com refuses scripted downloads.

**Related documents.**
- Review that produced this map: `data/pcb-revc/review/round4-firmware.md`.
- Electrical acceptance tests: `docs/reports/2026-10-11-body-pcb-rev-c-bringup.md`.
- Spec: `docs/reports/2026-10-10-body-pcb-rev-c.md`.

Contents:
1. Power-up state without software
2. Raspberry Pi: boot configuration and GPIO
3. Pi I2C1: power control and monitoring
4. Pi I2C6: ToF
5. Pi UARTs, SPI0, PWM
6. Pi power sequencing and fault handling
7. STM32G474: clocks, pins, peripherals
8. STM32: motor drive and safety sequence
9. STM32: other subsystems
10. Pi ↔ STM32 link, flashing and recovery
11. Existing code that must change for rev C

---

## 1. Power-up state without software

Battery plugged in and button pressed; the Pi still booting or dead; the MCU in reset.

| Load / signal | State | Why (board) |
|---|---|---|
| +5V, +5V_MCU, +3V3_MCU, ADC_AVDD 2.5 V | on | LM61495 U4, TPS2121 U32, TLV75533 U15, REF3425 U33 |
| Pi (USB-C J53) | **on** | U87 EN is a 100 k/100 k divider from +5V, not on an expander |
| Jetson (XT30 J21) | **on** | TPS16630 U5 SHDN opens to 2.48-3.3 V (tps1663 p.9); Q7 is off while GPIO25 is low |
| Motor bus MOT_BUS | **off** | MOT_BUS_OFF has 100 k (RN6.1-8) to **+3V3_MCU** → Q31 pulls MOT_UVLO low |
| Lidars, fans, AUX/CAN 5 V, encoder 3.3 V, servo buck, servo eFuse, arm eFuse, ToF buck, spare VBAT | off | every EN line has 100 k to GND (RN1-RN6); expander pins are inputs at reset (pcal6524 p.7). Spare VBAT also has R186 10 k |
| DRV8243 bridges | asleep and Hi-Z | nSLEEP 4.7 k to GND (R94/R95); DRVOFF high, because ALIVE_DET is low until PC3 toggles |
| ITRIP | 2.41 A (LVL2) | ITRIP_SEL R1150 100 k pull-up → Q1101/Q1201 on → 8.25 k |
| CAN transceiver | standby | CAN_STB 10 k (R98) to +3V3_MCU |
| PCA9685 servo/fan PWM | outputs low (full off), oscillator asleep | pca9685 power-up state |
| E-stop loop | stop | ESTOP 10 k (R17) to GND; Pi GPIO16 power-on pull-down |

---

## 2. Raspberry Pi: boot configuration and GPIO

### 2.1 `/boot/firmware/config.txt` (replaces the rev B lines in `scripts/body-setup.sh`)

```
force_eeprom_read=0                      # no HAT-EEPROM probe on GPIO0/1 (BOOT0/NRST)
dtparam=i2c_arm=on,i2c_arm_baudrate=100000
dtoverlay=i2c6,pins_22_23,baudrate=400000
dtoverlay=spi0-0cs,no_miso               # SPI0 on GPIO10/11 only (keeps 7/8/9 free)
dtoverlay=disable-bt                     # UART0 (PL011) back on GPIO14/15 -> /dev/ttyAMA0
dtoverlay=uart3                          # GPIO4/5   lidar 1   (never ctsrts: would take 6/7)
dtoverlay=uart4                          # GPIO8/9   lidar 2
dtoverlay=uart5                          # GPIO12/13 lidar 3   (never ctsrts: would take 14/15)
dtoverlay=pwm,pin=18,func=2              # PWM0_0 ALT5 -> buzzer
dtparam=audio=off                        # analogue audio would use the PWM
dtoverlay=i2c-rtc,ds3231
dtoverlay=gpio-poweroff,gpiopin=17       # LM74800 latch off at the end of shutdown
dtparam=watchdog=on
gpio=16=op,dl                            # E-stop source low until rabbit-safety arms it
gpio=6=op,dl                             # expanders held in reset until rabbit-power runs
gpio=0-1=ip,pn                           # BOOT0/NRST: inputs, no pull, when idle
```

- `cmdline.txt`:
  - remove `console=serial0,115200`;
  - keep `pinctrl_bcm2835.persist_gpio_outputs=n`, so a dead process releases its outputs;
  - `systemctl disable hciuart`.
- `dtparam=spi=on` is not needed. If it is present, it must come **before** `spi0-0cs`, otherwise SPI0 claims GPIO7/8/9 (EXP_INT_N, UART4).
- Remove `i2c3,pins_4_5`, `i2c4,pins_6_7`, `i2c5,pins_10_11` (rev B ToF buses). On rev C those pins are UART3, EXP_RESET_N/EXP_INT_N and SPI0.
- Device names to check on the first boot (`ls -l /sys/class/tty/ttyAMA*`):
  - UART0 → `/dev/ttyAMA0`;
  - UART3/4/5 → by device-tree node fe201600 / fe201800 / fe201a00 [mem];
  - bind udev symlinks `rabbit-mcu`, `rabbit-lidar1..3` by `DEVPATH`, not by ttyAMA number.

### 2.2 J3 GPIO map

**ALT functions:** BCM2711 table 94, `datasheet/Raspberry Pi/bcm2711-peripherals.pdf` p.78-79. **Power-on pulls:** same table.

| J3 | GPIO | Net | Function / ALT | Dir | Power-on pull → state | Owner (software) |
|---|---|---|---|---|---|---|
| 3/5 | 2/3 | I2C1_SDA/SCL | I2C1 ALT0, 100 kHz, Pi 1.8 k pull-ups only | io | up | kernel i2c-1 |
| 15/16 | 22/23 | I2C6_SDA/SCL | I2C6 ALT5, 400 kHz, 2.2 k R892/R893 on board | io | down (pulled up on board) | kernel i2c-6 |
| 8/10 | 14/15 | MCU_RX/MCU_TX | UART0 TXD0/RXD0 ALT0 → STM32 USART2 (R10 100 Ω, R11 1 k) | out/in | down → idle low until UART0 is set up | `rabbit-mcu` (`/dev/ttyAMA0`) |
| 7/29 | 4/5 | GPIO4→LIDAR1_RX, LIDAR1_TX→GPIO5 | UART3 ALT4 (1 k R1011/R1012) | out/in | up | `rabbit-lidar` |
| 24/21 | 8/9 | LIDAR2 | UART4 ALT4 (R1021/R1022) | out/in | up / down | `rabbit-lidar` |
| 32/33 | 12/13 | LIDAR3 | UART5 ALT4 (R1031/R1032) | out/in | down | `rabbit-lidar` |
| 19/23 | 10/11 | LED_DI/LED_CI | SPI0 MOSI/SCLK ALT0 → 74AHCT1G125 U48/U49 → 5 V → 8 × SK9822 | out | down (+100 k R480/R481) | `rabbit-power` (status LEDs) |
| 12 | 18 | BUZZER_PWM | PWM0_0 ALT5 → R190 → AO3400A Q9 → PKLCS1212E4001 (4.0 kHz) | out | down (+R191 100 k) → silent | `rabbit-power` |
| 11 | 17 | PWR_OFF | gpio-poweroff: high at the end of shutdown → LM74800 latch off (R48, D9) | out | down → stays on | kernel |
| 22 | 25 | JETSON_OFF | GPIO out: **high = Jetson off** (R86 → Q7 → U5 SHDN) | out | down (+R87) → Jetson **on** | `rabbit-power` |
| 36 | 16 | ESTOP_RUN | GPIO out: high = may drive (R16 1 k → J52.1 → NC switch → ESTOP) | out | down → stop | `rabbit-safety` |
| 31 | 6 | EXP_RESET_N | GPIO out: low = PCAL6524 ×2 + TCA6416A in reset (all expander loads off) | out | up ~50 k against R371 10 k → 0.55 V = reset | `rabbit-power` |
| 26 | 7 | EXP_INT_N | GPIO in, falling/low: INT of U37, U38, U41 (open drain, R372 10 k) | in | up | `rabbit-power` (see §3.6) |
| 18 | 24 | PWR_ALERT_N | GPIO in, falling/low: ALERT of INA238 ×4 + ADS7128 ×2 (R373 10 k) | in | down (pulled up on board) | `rabbit-power` |
| 35 | 19 | TOF_MUX_RESET_N | GPIO out: low = TCA9548A reset (R891 10 k pull-up) | out | down vs 10 k up → 2.75 V = running | `rabbit-tof` or the kernel mux driver |
| 27 | 0 | MCU_BOOT0 | GPIO: high = STM32 system bootloader at next reset (R91 1 k, R90 10 k to GND) | in when idle | up ~50 k → BOOT0 ≈ 0.54 V = low | `rabbit-mcu` flasher |
| 28 | 1 | MCU_NRST | GPIO: drive low to reset the STM32 (R92 1 k, C87 100 nF) | in when idle | up | `rabbit-mcu` flasher |
| 37 | 26 | POWER_BTN | GPIO in: low = pressed (R28 10 k up, C10) | in | down (pulled up on board) | `rabbit-power` |
| 38/40 | 20/21 | BUMPER_FRONT/REAR | GPIO in: NC switch to GND, **high = bumper open/pressed** (R29/R30 4.7 k up, C11/C12); also to MCU PC13/PC14 via 1 k | in | down (pulled up on board) | `rabbit-safety` |
| 13 | 27 | BTN_LED | GPIO out: high = button LED on (R24 → Q3) | out | down (+R25 100 k) | `rabbit-power` |
| 1/17 | — | +3V3_PI | powers all Pi-side logic: INA238, ADS7128 DVDD, PCAL6524, TCA6416A, TCA9548A, PCA9685, DS3231 | | | |
| 2/4 | — | NC | the Pi takes 5 V through its USB-C from J53 | | | |

**Fail-safe on crash** (`persist_gpio_outputs=n`):
- GPIO16 falls to pull-down: E-stop.
- GPIO6 returns to its ~50 k pull-up against R371 10 k, which reads as low: the expanders reset and every switched load goes off, including the motor bus.
- GPIO25 falls to pull-down: the Jetson stays on.

---

## 3. Pi I2C1: power control and monitoring (100 kHz)

| Addr | Ref | Part | Purpose |
|---|---|---|---|
| 0x11 | U35 | ADS7128 | eFuse currents: lidars, steering, fans, AUX, encoders |
| 0x17 | U36 | ADS7128 | IMON Jetson / spare VBAT; ILM + FLT of Pi USB-C and arm |
| 0x20 | U41 | TCA6416A | ToF LPn (out) / INT (in) |
| 0x22 | U37 | PCAL6524 | load enables |
| 0x23 | U38 | PCAL6524 | FLT / PG inputs |
| 0x40 / 0x41 / 0x43 / 0x47 | U21 / U22 / U23 / U26 | INA238 | battery / motor bus / servo rail / +5V |
| 0x60 | U8 | PCA9685 | servo 0-7, fan PWM |
| 0x68 | U9 | DS3231 | RTC (kernel `rtc-ds1307` through `i2c-rtc`) |
| 0x70 | U8 | PCA9685 All Call (ACKs at power-up, pca9685 p.8) | **reserved**, never address |
| 0x00 | all | general call | never send SWRST (06h): it resets the PCA9685 and the expanders together |

### 3.1 PCAL6524 U37 @ 0x22: load enables (all outputs)

Pin n = bit P(n-1)/8_(n-1)%8 (pcal6524 p.6). Each line has a 100 k pull-down (pull-up on P2_4).

| Bit | Net | Load | Active | Notes |
|---|---|---|---|---|
| P0_0..P0_5, P0_7 | EXP_OUT_SPAREn | — | — | 100 k to GND; drive 0 |
| **P0_6** | ARM_EN | U88 TPS259470L → ARM_PWR → J80/J81 (xArm) | high | needs SERVO_RAW up (servo buck on) |
| **P1_0 / P1_1 / P1_2** | LIDAR1/2/3_EN | U80/U81/U82 → J71/J72/J73 | high | stagger by ≥ 0.5 s: the C1 start current is ~0.8 A each |
| **P1_3** | SERVO_EN | U83 → SERVO_PWR → J22-J29 pin 2 | high | after SERVO_BUCK_PG |
| **P1_4** | SERVO_BUCK_EN | U6 LM61495 EN → SERVO_RAW | high | |
| **P1_5** | SERVO_7V4 | Q601 → FB6_SEL: 6.0 V (0) / 7.4 V (1) | high = 7.4 V | |
| **P1_6 / P1_7** | FAN1/2_EN | U84/U85 → J55/J56 | high | |
| **P2_0** | AUX_EN | U86 → +5V_AUX → J58 and CAN J51 pin 1 | high | |
| **P2_1** | ENC_EN | U78 → ENC_3V3 → J41/J42 pin 2 | high | **needs +3V3_TOF** (P2_5) |
| P2_2, P2_6, P2_7 | spares | — | — | drive 0 |
| **P2_3** | SPAREBAT_EN | U7 TPS16630 SHDN → J20 (XT30) | high | also R186 10 k to GND |
| **P2_4** | MOT_BUS_OFF | Q31 → LM5069 U30 UVLO | **high = OFF** | pull-up to +3V3_MCU |
| **P2_5** | TOF3V3_EN | U31 TPS62826 → +3V3_TOF (6 ToF ports + U78) | high | |

**Init (output port registers reset to FFh, pcal6524 p.12):**
1. Drive GPIO6 high.
2. Write the **output** registers first: port 0 = 0x00, port 1 = 0x00, port 2 = **0x10** (MOT_BUS_OFF = 1).
3. Then write configuration port 0/1/2 = 0x00 (all outputs).
4. Leave output-drive and pull settings at their defaults (push-pull, internal pulls disabled; the board has the pulls).

With the Linux `gpio-pca953x` driver (`compatible = "nxp,pcal6524"`), request each line with its initial value and the driver keeps this order.

### 3.2 PCAL6524 U38 @ 0x23: faults and power-good (all inputs, 10 k pull-ups to +3V3_PI)

| Bit | Net | Source | Meaning |
|---|---|---|---|
| P0_0..P0_7 | EXP_IN_SPARE3..8, 1, 2 | — | pulled high; mask |
| P1_0 / P1_1 / P1_2 | LIDAR1/2/3_FLT | U80-U82 FLT | **low = fault** (latched off; clear with EN low → high, tps25947 p.38) |
| P1_3 | SERVO_FLT | U83 | low = fault, latched |
| P1_4 | SERVO_BUCK_PG | U6 PG | high = SERVO_RAW in regulation |
| P1_5 | 5V_PG | U4 PG | high = +5V good |
| P1_6 / P1_7 | FAN1/2_FLT | U84/U85 | low = fault, latched |
| P2_0 | AUX_FLT | U86 | low = fault, latched |
| P2_1 | ENC_FLT | U78 | low = fault, latched |
| P2_2 | EXP_IN_SPARE9 | — | mask |
| P2_3 | SPAREBAT_FLT | U7 FLT | low = fault; latch-off (MODE open, tps1663 p.26): clear by toggling SPAREBAT_EN |
| P2_4 | JET_FLT | U5 FLT | low = fault; auto-retry (MODE = GND) |
| P2_5 | MOT_BUS_PG | U30 PGD | high = motor bus up |
| P2_6 | TOF3V3_PG | U31 PG | high = +3V3_TOF good |
| P2_7 | RTC_INT_N | U9 INT/SQW | low = RTC alarm |

**Init:**
- Configuration stays FFh (inputs).
- Enable the **input latch** on every FLT bit, so a short FLT pulse is held until read.
- Interrupt mask: unmask the FLT, PG and RTC bits; keep the spares masked (reset value FFh = all masked, pcal6524 p.12).
- Read the interrupt status registers to clear.

Note: OVLO cuts on the servo/arm eFuses do not assert FLT (bring-up §9 item 6). Infer them from INA238 0x43 VBUS.

### 3.3 ADS7128 U35 @ 0x11 and U36 @ 0x17

**Common settings.**
- AVDD = REF3425 2.500 V, so 1 LSB = 0.610 mV at 12 bits.
- DVDD = +3V3_PI.
- Every input comes from the ILM/IMON node through 10 k + 1 nF.
- Opcodes (ads7128 p.27): read 0x10, write 0x08, set bit 0x18, clear bit 0x20.
- ALERT is open drain by default and wired-OR on PWR_ALERT_N.

**Current conversions.**
- TPS25947 ILM: I = V / (182 µA/A × R_ILM) (tps25947 p.10, gain 165-200 µA/A).
- TPS16630 IMON: I = V / (27.9 µA/A × 10 k) (tps1663 p.24).

| Dev | AIN (pin) | Net | Mode | Scale (V/A) | I_LIM typ | Full scale |
|---|---|---|---|---|---|---|
| 0x11 | 0 (15) / 1 (16) / 2 (1) | LIDAR1/2/3_IMON | analog | **0.300** (R_ILM 1.65 k) | 2.02 A | 8.3 A |
| 0x11 | 3 (2) | SERVO_IMON | analog | 0.0999 (549 Ω) | 6.07 A | 25 A |
| 0x11 | 4 (3) / 5 (4) | FAN1/2_IMON | analog | 1.210 (6.65 k) | 0.50 A | 2.07 A |
| 0x11 | 6 (5) | AUX_IMON | analog | 0.300 (1.65 k) | 2.02 A | 8.3 A |
| 0x11 | 7 (6) | ENC_IMON | analog | 1.210 (6.65 k) | 0.50 A | 2.07 A |
| 0x17 | 0 (15) | — | NC: leave out of the sequence | | | |
| 0x17 | 1 (16) | JET_IMON | analog | 0.279 | 3.53 A (R_ILIM 5.1 k) | 8.96 A |
| 0x17 | 2 (1) | SPAREBAT_IMON | analog | 0.279 | 3.83 A | 8.96 A |
| 0x17 | 3 (2) | USB_PI_IMON | analog | 0.161 (887 Ω) | 3.76 A | 15.5 A |
| 0x17 | 4 (3) | USB_PI_FLT | **GPIO in** (10 k up to 2.5 V; VIH 0.7 × AVDD = 1.75 V, ads7128 p.6) | low = fault (U87 auto-retries after ~110 ms) | | |
| 0x17 | 5 (4) | ARM_IMON | analog | 0.1365 (750 Ω) | 4.45 A | 18.3 A |
| 0x17 | 6 (5) | ARM_FLT | **GPIO in** | low = fault, latched | | |
| 0x17 | 7 (6) | — | NC | | | |

The lidar scale is 0.300 V/A on the board (design.py line 787). The spec §3 table and the bring-up report still show 4.42 k / 0.804 V/A. Use the board value.

**Init:**
1. GENERAL_CFG: calibrate.
2. PIN_CFG: 0x50 on 0x17 (AIN4 and AIN6 as GPIO). GPIO_CFG: inputs.
3. OSR_CFG: averaging 16.
4. SEQUENCE_CFG: auto-sequence over the analog channels.
5. ALERT_CH_SEL and thresholds: only if hardware alerts are wanted. Polling at 10-20 Hz is enough for telemetry; the eFuses protect themselves.

### 3.4 INA238 ×4

**Settings for all four** (ina238 p.21 register map):
- CONFIG.ADCRANGE as in the table.
- ADC_CONFIG: keep FB68h (continuous bus + shunt + temperature, 1052 µs each) or set AVG = 16.
- SHUNT_CAL = 819.2·10⁶ × CURRENT_LSB × R_SHUNT, ×4 when ADCRANGE = 1 (ina238 p.30).
- VBUS LSB = 3.125 mV.
- Check MANUFACTURER_ID 0x5449.
- Limits are off at reset, so ALERT stays quiet until programmed.

| Addr | Ref | Shunt | VBUS pin | ADCRANGE | CURRENT_LSB | SHUNT_CAL | Suggested alerts (DIAG_ALRT ALATCH = 1) |
|---|---|---|---|---|---|---|---|
| 0x40 | U21 | R1 2 mΩ | VBUS | 1 (±40.96 mV = 20.5 A) | 1 mA | 6554 | BUVL 12.4 V (4S low), SOVL 12 A (M28 budget) |
| 0x41 | U22 | R3 5 mΩ (shared with LM5069) | MOT_BUS | 0 (±163.84 mV) | 1 mA | 4096 | SOVL 9 A |
| 0x43 | U23 | R2 5 mΩ | SERVO_RAW | 0 | 1 mA | 4096 | BOVL 8.3 V (precedes the 8.63 V eFuse OVLO), SOVL 9 A |
| 0x47 | U26 | R6 5 mΩ | +5V | 0 (8 A × 5 mΩ = 40 mV, too close to the ADCRANGE 1 full scale) | 1 mA | 4096 | BOVL 5.35 V, BUVL 4.9 V |

Linux has an `ina238` hwmon driver (`ti,ina238`, `shunt-resistor` in µΩ) [mem]. Userspace SMBus is equally fine. Do not mix the two on one device.

### 3.5 PCA9685 U8 @ 0x60

**Channel map.**
- LED0-LED7 (pins 6-13) → R3000-R3007 → servo headers J22-J29 pin 1. Header order: **1 S, 2 SERVO_PWR, 3 GND**.
- Servo 0 can instead take STM32 PA7 (TIM17_CH1) through JP3 (default bridged 1-2 = PCA).
- LED11 (pin 18) → Q55 → J55 pin 4 (fan 1 PWM); LED12 (pin 19) → Q56 → J56 pin 4.
- LED8-10 and LED13-15 are not connected.
- OE pin 23 is tied to GND, so the outputs are always enabled.

**Init:**
1. MODE1 reset value: SLEEP = 1, ALLCALL = 1.
2. PRE_SCALE = round(25 MHz / (4096 × 50 Hz)) − 1 = **121** (50 Hz), written while asleep.
3. MODE1: AI = 1, SLEEP = 0. Wait 500 µs. Then set RESTART.
4. Leave MODE2 OUTDRV = 1 (totem-pole).

**Fans.**
- One prescaler serves all 16 outputs (pca9685 p.2), so the fans get the servo frequency, not 25 kHz.
- The 2N7002K inverts: fan duty = 1 − PCA duty. Full-off on LED11/12 means full speed.
- If a fan misbehaves at 50 Hz on the bench, run it on/off through FAN_EN.

**Before SERVO_EN or SERVO_BUCK_EN goes low**, write ALL_LED_OFF (or SLEEP). Otherwise the PCA9685 keeps feeding the unpowered servos through their signal pins (open P27).

### 3.6 Interrupt lines

**GPIO24 PWR_ALERT_N** (INA238, ADS7128):
- on a falling edge, read DIAG_ALRT of the four INA238s and the event flags of the two ADS7128s;
- with ALATCH = 1 the line stays low until read.

**GPIO7 EXP_INT_N** (PCAL6524 ×2 + TCA6416A U41):
- The TCA6416A has **no interrupt mask** (tca6416a p.19, p.21). Each ToF INT edge on P1_0..P1_5 pulls this line, about 90-360 times a second.
- Until U41 INT is moved off this line (round 4 R-1), handle GPIO7 like this:
  - read **only U38's interrupt status**, at most every 20 ms (U38 latches its inputs, so nothing is lost);
  - treat a low level that lasts more than 5 ms as "PCAL event pending";
  - never read U41 from this handler.
- ToF data-ready is polled over I2C6, so the ToF INT lines are not needed.

---

## 4. Pi I2C6: ToF (400 kHz)

**Topology.**
- TCA9548A U40 at **0x77**; RESET = GPIO19.
- Channel n = port J6n = sensor TOFn+1, every sensor at 0x29:

| Mux ch | Port | Sensor (`gen/tof.json`) | LPn (U41 0x20) | INT (U41) |
|---|---|---|---|---|
| 0 | J60 | front, yaw 0° | P0_0 | P1_0 |
| 1 | J61 | front_l, −50° | P0_1 | P1_1 |
| 2 | J62 | front_r, +50° | P0_2 | P1_2 |
| 3 | J63 | rear, 180° | P0_3 | P1_3 |
| 4 | J64 | rear_l, −135° | P0_4 | P1_4 |
| 5 | J65 | rear_r, +135° | P0_5 | P1_5 |
| 6, 7 | — | 10 k pull-ups (RN40), unused | | |

**Cable and carrier.**
- Port pinout: 1 GND, 2 +3V3_TOF, 3 SDA, 4 SCL, 5 INT, 6 LPn.
- That matches `pcb/rabbit-tof` J1. Its LSF0204 translates to the sensor's 1.8 V, so the sensor is not back-powered while the rail is off.

**TCA6416A U41 init.**
- Output port 0 = 0x3F (LPn high = I2C enabled; the reset value is FFh anyway), configuration port 0 = 0xC0, port 1 = 0xFF.
- P0_6/P0_7 and P1_6/P1_7 are spares with 100 k pull-downs.
- Reset is shared with the PCAL6524s (GPIO6).

**Sensor bring-up.**
1. TOF3V3_EN (0x22 P2_5) on.
2. Wait for TOF3V3_PG (0x23 P2_6).
3. Release the mux reset (GPIO19 high).
4. For each channel: select it (write 1 << ch to 0x77), load the VL53L8CX firmware (~84 kB at 400 kHz, roughly 2-3 s per sensor), then deselect (write 0x00).
5. Read frames round-robin, polling data-ready.

**Recovery.**
- Per sensor: pulse its LPn low, then re-init.
- Whole mux: GPIO19 low.
- **Do not cycle TOF3V3_EN while the motors are enabled.** +3V3_TOF also feeds the encoder eFuse U78, so cycling it blinds odometry (round 4 R-3).
- Before turning +3V3_TOF off, write 0x00 to the mux. A selected channel with its 4.7 k pull-ups to a dead rail would drag I2C6 down.

**Kernel option.**
- A device-tree overlay with `i2c-mux-pca954x` (`compatible = "nxp,pca9548"`, `reg = <0x77>`, `reset-gpios = <&gpio 19 GPIO_ACTIVE_LOW>`, `i2c-mux-idle-disconnect`) under i2c6 gives one `/dev/i2c-N` per port.
- With that, the existing `rabbit-tof` model of one bus per sensor keeps working; only the `Mount.bus` numbers change.

---

## 5. Pi UARTs, SPI0, PWM

| Device | Pins | Port | Settings |
|---|---|---|---|
| STM32 | GPIO14/15 | UART0 PL011 `/dev/ttyAMA0` | 1 Mbaud 8N1 suggested (PL011 and USART2 both support it). Idle line low during Pi boot (GPIO14 power-on pull-down): the MCU must tolerate a break |
| Lidar 1 | GPIO4/5 | UART3 | 460800 8N1 (`lib/rplidar.py`) |
| Lidar 2 | GPIO8/9 | UART4 | 460800 8N1 |
| Lidar 3 | GPIO12/13 | UART5 | 460800 8N1 |
| SK9822 ×8 | GPIO10/11 | SPI0 `/dev/spidev0.0` (check it exists with `spi0-0cs`) | mode 0, ≤ 4 MHz. Frame: 4 × 0x00, then per LED [0xE0 \| brightness(0-31), B, G, R], then 4 × 0x00 + ≥ 4 extra clock bytes. Through 74AHCT1G125 at 5 V |
| Buzzer | GPIO18 | `/sys/class/pwm/pwmchip0/pwm0` | period 250 000 ns (4.0 kHz resonance of PKLCS1212E4001), duty 50 % = on, disable = off |

**Lidar connector J71-J73** (RPLIDAR C1 XH2.54-5P, rplidar-c1 p.12): 1 VCC 5 V, 2 TX (lidar out → Pi RX), 3 RX (lidar in ← Pi TX, max 3.5 V), 4 GND, 5 empty.

While a lidar is off, its idle-high Pi TX feeds it ≤ 2.7 mA through 1 k. This is harmless. To avoid it, set that TX pin to input while LIDARn_EN = 0.

---

## 6. Pi power sequencing and fault handling (`rabbit-power`)

**Start**, after the Pi has booted. GPIO6 is low, GPIO16 is low and the Jetson is already on.

1. GPIO6 high. Initialise U37 (§3.1, output registers first), U38 (§3.2), U41 (§4), INA238 ×4 (§3.4), ADS7128 ×2 (§3.3), PCA9685 (§3.5: asleep, outputs off).
2. Read INA238 0x40 VBUS. If it is below 12.4 V, do not enable the motor bus (LM5069 UVLO is 11.58 V typ / 12.22 V max).
3. **Sensors:**
   1. TOF3V3_EN.
   2. Wait for TOF3V3_PG.
   3. ENC_EN; check ENC_FLT and ADS 0x11 AIN7.
   4. LIDAR1/2/3_EN, 0.5 s apart; check FLT and ILM.
   5. FAN1/2_EN.
4. **Servos and arm:**
   1. SERVO_BUCK_EN.
   2. Wait for SERVO_BUCK_PG.
   3. SERVO_7V4 if wanted, then wait 5 ms.
   4. Wake the PCA9685 with the outputs still off.
   5. SERVO_EN; then ARM_EN when the arm is in use.
5. **Motors:**
   1. MOT_BUS_OFF = 0.
   2. Wait for MOT_BUS_PG (0x23 P2_5).
   3. Tell the STM32 "bus up".
   4. `rabbit-safety` drives GPIO16 high when its checks pass.
   5. The STM32 does the DRV8243 handshake (§8).
6. AUX_EN / SPAREBAT_EN on request.

**Faults** (an EXP_INT_N or PWR_ALERT_N event, or polling):

| Part | Behaviour | Clearing / response |
|---|---|---|
| TPS259470L (lidar, servo, fan, AUX, encoders, arm) | latch off | EN low ≥ 10 ms, then high (tps25947 p.38). Log the ILM value before clearing. Retry at most N times |
| TPS259470A (Pi) | auto-retries by itself | log only |
| TPS16630 Jetson | auto-retries (MODE = GND) | log only |
| TPS16630 spare VBAT | latch off (MODE open) | clear by toggling SPAREBAT_EN |
| LM61495 servo buck PG low | | turn SERVO_EN/ARM_EN off and the PCA9685 outputs off |
| LM5069 PG low with MOT_BUS_OFF = 0 | | tell the STM32, set ESTOP_RUN low |

**Shutdown:**
1. Stop drive; MOT_BUS_OFF = 1; GPIO16 low.
2. PCA9685 ALL_LED_OFF + SLEEP; SERVO_EN/ARM_EN/SERVO_BUCK_EN off; lidars and ToF off.
3. Jetson: graceful shutdown over the network, then GPIO25 high.
4. `systemctl poweroff`: gpio-poweroff drives GPIO17 high and the LM74800 latch drops all power.

---

## 7. STM32G474RET6 (U1): clocks, pins, peripherals

### 7.1 Clocks [CubeMX]

- **SYSCLK 170 MHz** from HSE 8 MHz (Y1, 18 pF C88/C89): PLLM /2, N ×85, R /2, boost mode, 4 flash wait states [mem].
- **FDCAN kernel clock:** HSE (8 MHz exact) or PLLQ.
- **USB:** HSI48 with CRS synced to USB SOF.
- **RTC:** none. VBAT is tied to +3V3_MCU; LSE pins PC14/PC15 are GPIO.
- **Keep VREFBUF off.** VREF+ = VDDA (R100 10 Ω from +3V3_MCU, C83/C85/C86).

### 7.2 Pin configuration

**Sources.** AF numbers: DS12288 table 13 p.73-76. ADC channels: table 12 p.57-61. All were checked against the board netlist.

| Pin | Port | Net | Mode / AF | Pull | Function, default and notes |
|---|---|---|---|---|---|
| 1 | VBAT | +3V3_MCU | | | |
| 2 | PC13 | BUMP_F_M | input, EXTI13 | none (4.7 k to +3V3_PI on board) | high = front bumper open/pressed; reads low if the Pi is unpowered |
| 3 | PC14 | BUMP_R_M | input, EXTI14 | none | rear bumper |
| 4 | PC15 | ESTOP2_M | input, EXTI15 | none (R161 10 k to GND) | E-stop channel 2: high = closed (run) |
| 5/6 | PF0/PF1 | OSC_IN/OUT | HSE | | 8 MHz crystal |
| 7 | NRST | MCU_NRST | | | Pi GPIO1 via 1 k; TC2030 pin 3; C87 100 nF |
| 8 | PC0 | IPROPI_L_M | analog ADC1_IN6 | | 0.489 V/A (1.5 k / 3070 A/A), clamped by BAT54S D1105; injected, triggered by TIM1 CC4 |
| 9 | PC1 | IPROPI_R_M | analog ADC2_IN7 | | same, D1205; injected, triggered by TIM8 CC4 |
| 10 | PC2 | VMOT_SENSE | analog ADC1_IN8 | | ×11 (R63 100 k / R64 10 k): 3.3 V = 36.3 V |
| 11 | PC3 | MCU_ALIVE | GPIO push-pull out | | ≥ 1 kHz square wave **from the main loop**; never TIM1_CH4 |
| 12 | PA0 | NTC_L | analog ADC1_IN1 | | 10 k (R1112) to +3V3_MCU, NTC RT11 10 k to GND_MOT |
| 13 | PA1 | NTC_R | analog ADC2_IN2 | | R1212, RT12 |
| 14 | PA2 | MCU_TX | AF7 USART2_TX | | → Pi GPIO15 (R11 1 k) |
| 17 | PA3 | MCU_RX | AF7 USART2_RX | pull-up | ← Pi GPIO14 (R10 100 Ω) |
| 18 | PA4 | DRVOFF_MON | input, EXTI4 | none | reads DRVOFF through R19 10 k: high = bridges Hi-Z (hardware) |
| 19 | PA5 | MCU_LED | GPIO out | | R93 1 k → D93 |
| 20 | PA6 | USB_VBUS_DET | input, EXTI6 | none | R150 22 k / R151 33 k: 5 V → 3.0 V. Connect or disconnect the D+ pull-up on its edges |
| 21 | PA7 | SERVO_MCU | AF1 TIM17_CH1 or input | | 50 Hz steering, only if JP3 is moved to 2-3; otherwise input |
| 22 | PC4 | IMU_CS | GPIO out, high | (R422 10 k up) | ICM-42688-P CS |
| 23 | PC5 | BRK_SENSE | **analog ADC2_IN11 only** | | brake gate × 33/133 (R61/R62). Detect edges with the ADC2 AWD1 interrupt; EXTI cannot work on an analog pin [mem] |
| 24 | PB0 | IMU_INT1 | input, EXTI0 | pull-up, or set INT1 push-pull in the IMU | data ready |
| 25 | PB1 | DRV_L_NFAULT | input, EXTI1 falling | none (R1103 10 k) | ignore while VMOT < 11 V |
| 26 | PB2 | DRV_R_NFAULT | input, EXTI2 falling | none (R1203 10 k) | same |
| 28/29 | VREF+/VDDA | +3V3_MCU_A | | | |
| 30 | PB10 | ESTOP | AF12 TIM1_BKIN | none (R17 10 k to GND) | active low. Also readable from IDR. EXTI10 is allowed |
| 33 | PB11 | ITRIP_SEL | GPIO open-drain out, or input | (R1150 100 k up) | released = 2.41 A (LVL2); low = 4.05 A (LVL3) |
| 34 | PB12 | CAN_RX | AF9 FDCAN2_RX | | |
| 35 | PB13 | CAN_TX | AF9 FDCAN2_TX | | |
| 36 | PB14 | DRV_L_NSLEEP | GPIO out, low | (R94 4.7 k down) | wake and reset pulse |
| 37 | PB15 | CAN_STB | GPIO out | (R98 10 k up) | high = standby; drive low for normal mode |
| 38/39 | PC6/PC7 | DRV_R_IN1/IN2 | AF4 TIM8_CH1/CH2 | | |
| 40/41 | PC8/PC9 | I2C3_SCL/SDA | AF8 open-drain | (R96/R97 2.2 k) | 400 kHz |
| 42/43 | PA8/PA9 | DRV_L_IN1/IN2 | AF6 TIM1_CH1/CH2 | | PA9 is UCPD1_DBCC1 |
| 44 | PA10 | DRV_R_NSLEEP | GPIO out, low | (R95 4.7 k down) | PA10 is UCPD1_DBCC2 |
| 45/46 | PA11/PA12 | USB_DM/DP | USB FS | | DFU / CDC; USBLC6 U47; J50 Rd 5.1 k |
| 49/50 | PA13/PA14 | SWDIO/SWCLK | AF0 | | TC2030 J47 (no SWO); never reassign |
| 51 | PA15 | FAN1_TACH_M | AF1 TIM2_CH1 | (R142 10 k up, R140 1 k) | input capture |
| 52-54 | PC10/PC11/PC12 | SPI3 SCK/MISO/MOSI | AF6 | | IMU, mode 3, ≤ 24 MHz |
| 55 | PD2 | ESTOP | AF4 TIM8_BKIN | | **no EXTI** (EXTI2 belongs to PB2) |
| 56 | PB3 | FAN2_TACH_M | AF1 TIM2_CH2 | (R143, R141) | |
| 57/58 | PB4/PB5 | ENC_R_A/B | AF2 TIM3_CH1/CH2 | pull-up (optional) | 22 Ω series; PB4 is NJTRST at reset |
| 59/60 | PB6/PB7 | ENC_L_A/B | AF2 TIM4_CH1/CH2 | pull-up (optional) | |
| 61 | PB8-BOOT0 | MCU_BOOT0 | leave as input | | R90 10 k down, Pi GPIO0 via 1 k; keep nSWBOOT0 = 1 |
| 62 | PB9 | ARM_UART_M | AF7 USART3_TX, **open drain**, HDSEL | none (R887 4.7 k up) | xArm bus through Q88 BSS138 to 5 V |

EXTI lines used: 0, 1, 2, 4, 6, 13, 14, 15 (10 optional). Each line has one port only (RM0440 EXTI mux [mem]).

### 7.3 Timers

| Timer | Use | Configuration |
|---|---|---|
| TIM1 | motor L | PWM 20 kHz, CH1 = IN1, CH2 = IN2. CH4 is internal (no pin), for ADC1 injected trigger (JEXTSEL = TIM1_CC4 [mem]). BDTR: BKE = 1, BKP = 0 (low = break), BKF filter ≥ 8 samples, OSSI = 1, OSSR = 1, OIS1 = OIS2 = 0, AOE = 0 |
| TIM8 | motor R | same, PC6/PC7, BKIN on PD2; CH4 → ADC2 injected (TIM8_CC4 [mem]) |
| TIM3 | encoder R | encoder mode 3 (×4), IC filter, ARR 0xFFFF; read and unwrap at ≥ 100 Hz |
| TIM4 | encoder L | same |
| TIM2 | fan tachs | 32-bit free-running, input capture on CH1/CH2 with filter. Typical fan: 2 pulses per revolution |
| TIM17 | steering option | 50 Hz PWM on PA7, only with JP3 on 2-3 |
| TIM6 / TIM7 | control loop / scheduler | free |
| TIM5, TIM15, TIM16, TIM20 | free | no pins needed |

**Encoder scale:** 11 pulses per motor revolution × 4 × 30 (gear ratio) = **1320 counts per wheel revolution**. The left and right signs are mirrored: calibrate both the motor sign and the A/B sign on the bench.

### 7.4 ADC

| ADC | Injected (per PWM period) | Regular scan (DMA) |
|---|---|---|
| ADC1 | IN6 IPROPI_L, triggered by TIM1_CC4 at mid on-time | IN8 VMOT_SENSE, IN1 NTC_L, VREFINT, TS |
| ADC2 | IN7 IPROPI_R, triggered by TIM8_CC4 | IN2 NTC_R, IN11 BRK_SENSE (AWD1 window for brake on/off) |

**Measurement notes.**
- IPROPI sees only the high-side current. It is valid during both on-time and the 0/0 high-side brake (drv8243 p.34).
- Current: I = V_ADC / 0.489 V/A.
- Duty limit for the 12 V motor: duty_max = 12 V / VMOT.

### 7.5 Other peripherals

| Peripheral | Pins | Device | Settings |
|---|---|---|---|
| USART2 | PA2/PA3 | Pi UART0 | 1 Mbaud 8N1, DMA RX with idle-line detection. Link watchdog: no valid frame for 100 ms → MOE = 0 on both timers |
| USART3 | PB9 | xArm bus (6 Hiwonder servos, IDs 1-6) | 115200 8N1, HDSEL = 1, LINEN/CLKEN/SCEN/IREN = 0. RE = 0 while ARM_EN is off. Drop the echo of own frames. Frame `55 55 ID LEN CMD … CHK` (`data/pcb-revc/ics/xarm_bus.md`) |
| SPI3 | PC10-PC12, CS PC4 | ICM-42688-P (U42) | mode 3, 170 MHz / 8 = 21.25 MHz. WHO_AM_I (0x75) = 0x47. Init: soft reset (DEVICE_CONFIG = 0x01), wait 1 ms; INTF_CONFIG0 UI_SIFS_CFG = disable I2C; INT_CONFIG: INT1 push-pull, active high or low as wired to EXTI0; INT_SOURCE0 UI_DRDY_INT1_EN; PWR_MGMT0 gyro + accel low-noise; ODR/FS in GYRO_CONFIG0/ACCEL_CONFIG0. Pin 9 has 100 k to GND: leave PIN9_FUNCTION = INT2 unused (R423 to the DS3231 32 kHz output is DNP) |
| I2C3 | PC8/PC9 | TMP117 0x48 (U44, at the DRV8243s) and 0x49 (U45, at the bucks); MMC5983MA 0x30 (U43) | 400 kHz. TMP117: temperature register 0x00 = 7.8125 m°C/LSB, device ID 0x0F = 0x0117. MMC5983MA: product ID register 0x2F = 0x30, SET/RESET before each measurement; INT pin not wired (poll). ALERT pins are not wired |
| FDCAN2 | PB12/PB13 | TCAN1044AV U46 (VCC +5V_MCU, VIO +3V3_MCU) | PB15 low = normal. The bus 5 V on J51 pin 1 is +5V_AUX (Pi 0x22 P2_0). Termination by solder jumpers JP461/JP462 (open) |
| USB | PA11/PA12 | J50 USB-C, device | CDC for logs and commands; DFU through a jump to system memory (0x1FFF0000 [mem]). Self-powered: follow PA6 VBUS |

**IRQ priority** (highest first):
1. TIM1_BRK / TIM8_BRK;
2. ADC1_2 (injected end of conversion, current loop);
3. EXTI1/EXTI2 (nFAULT) and EXTI4 (DRVOFF_MON);
4. USART2 DMA and idle-line;
5. EXTI0 (IMU);
6. FDCAN2, USART3, USB;
7. EXTI13/14/15 (bumpers, E-stop channel 2: telemetry only, because the hardware loop does the stopping).

---

## 8. STM32: motor drive and safety sequence

**Hardware chain, which works without firmware.**
- E-stop open or Pi GPIO16 low → ESTOP low → TIM1/TIM8 break at once.
- Both timer outputs then go to 0/0, which is the DRV8243 high-side brake (drv8243 p.34).
- After R18 100 k × C18 2.2 µF ≈ 0.24 s, U16 sets DRVOFF high, which puts the bridges in Hi-Z.
- If the main loop stops toggling PC3, ALIVE_DET decays (τ 10 ms) and DRVOFF goes high after about 10 ms.

**Boot sequence:**
1. **First instruction after clocks:** PWR_CR3.UCPD_DBDIS = 1. This removes the dead-battery 5.1 k Rd from PB6/PB4 (encoder A lines) that PA9/PA10 would enable (DS12288 table 12 note 5).
2. GPIO safe state:
   - PB14 and PA10 (nSLEEP) low;
   - PB11 released (2.41 A);
   - PC4 high;
   - PB15 high;
   - timer pins in AF with MOE = 0.
3. Start ADCs (calibrate first) and TIM1/TIM8 with MOE = 0. Start the PC3 toggle in the main loop.
4. Wait for the Pi link. Report: ESTOP (PB10 IDR), ESTOP2 (PC15), DRVOFF_MON, VMOT, temperatures, bumpers.

**Arming** (on a Pi command, once VMOT > 11 V and ESTOP and ESTOP2 have been high for more than 0.3 s):
1. nSLEEP high (tWAKEUP ≤ 10 µs).
2. Wait for nFAULT low, which is the wake acknowledgement (tCOM ≤ 400 µs).
3. **Reset pulse**: nSLEEP low for **30 µs** (it must be > 20 µs, the tRESET filter, and < 40 µs, the tSLEEP filter; drv8243 p.11). Use a one-pulse timer or interrupts off.
4. nFAULT goes high = STANDBY. Wait tREADY 1 ms (p.12).
5. Check DRVOFF_MON low: ALIVE is good and ESTOP_DLY is high.
6. Set MOE = 1 on TIM1/TIM8, with 0 duty.

The same handshake runs after every MOT_BUS power-up (the VM POR asserts nFAULT, p.22).

**Running.**
- PWM mode (MODE pin Hi-Z, R1106 DNP):

  | IN1 / IN2 | Bridge |
  |---|---|
  | 1 / 0 | forward |
  | 0 / 1 | reverse |
  | 0 / 0 | high-side brake (also the off-phase) |
  | 1 / 1 | Hi-Z (coast) |

- Forward is PWM on CH1 with CH2 forced low; reverse is PWM on CH2 with CH1 forced low.
- Duty is limited to 12 V / VMOT.
- Stall budget: ITRIP at 2.41 A by default. Pull PB11 low for 4.05 A only on a Pi command and within the thermal budget (TMP117 0x48, NTC_L/NTC_R).
- PH contacts on J41/J42 carry ≤ 2 A each (F-11).

**Faults.**

| Event | Response |
|---|---|
| nFAULT falling with VMOT > 11 V | MOE = 0, report it, then one reset pulse to clear (p.22). Repeated faults stay disabled until the Pi commands |
| DRVOFF_MON high while armed | hardware stop: report the cause (ESTOP_DLY or ALIVE) |
| Link lost for 100 ms | MOE = 0 |
| ESTOP falling | break interrupt: report; AOE = 0 keeps it disarmed |

**Motor connector J41 (L) / J42 (R)**, JST PH-6, read against the Hiwonder pinout:
- 1 OUTx2, 2 ENC_3V3, 3 A, 4 B, 5 GND, 6 OUTx1.
- Encoder power ENC_3V3 comes from U78 on **+3V3_TOF**. It needs Pi 0x22 P2_5 **and** P2_1. Report "encoder supply missing" when the counts stop while the motors draw current.

---

## 9. STM32: other subsystems

| Subsystem | Pins | What firmware does |
|---|---|---|
| Fans | PA15, PB3 (tach only; PWM and power belong to the Pi) | measure rpm, report to the Pi; 0 rpm while FANn_EN is on means fault |
| Bumpers | PC13/PC14 | report edges with timestamps; the Pi's `rabbit-safety` decides |
| E-stop channel 2 | PC15 (fed from +3V3_MCU through R160 1 k and the second NC contact) | plausibility against ESTOP: a mismatch for more than 50 ms is a wiring fault, refuse to arm |
| Brake chopper | PC5 analog | AWD1 on ADC2 IN11: time and duty of brake activity (regen energy) |
| xArm | PB9 | §7.5. `MOVE_STOP` on E-stop; only the Pi removes arm power |
| IMU + magnetometer | SPI3 + EXTI0, I2C3 | timestamp samples with the same clock as the encoders; stream to the Pi for the EKF |
| Temperatures | I2C3 TMP117 ×2, NTC ×2 | 1-10 Hz; derate ITRIP and duty with temperature |
| CAN | FDCAN2 | future modules; disabled until PB15 is driven low |
| LED | PA5 | heartbeat and fault code |

---

## 10. Pi ↔ STM32 link, flashing and recovery

- **Link:** `/dev/ttyAMA0` ↔ USART2. Framed binary protocol with CRC. The Pi sends set-points and a heartbeat at ≥ 50 Hz. The STM32 sends a state frame:
  - encoder counts, IPROPI;
  - VMOT, temperatures;
  - ESTOP, ESTOP2, DRVOFF_MON, nFAULT;
  - bumpers, tach, IMU;
  - arm bus counters.

  Every field and every rejected command goes to Forge with a reason (AGENTS observability rule).
- **Flashing from the Pi** (system bootloader on USART2 [AN2606 mem]):
  1. GPIO0 high.
  2. GPIO1 low for ≥ 1 ms (C87 100 nF × R92 1 k: τ 0.1 ms), then release GPIO1 to input.
  3. `stm32flash -b 115200 -w fw.bin -v /dev/ttyAMA0`.
  4. GPIO0 to input (R90 pulls BOOT0 low).
  5. Pulse GPIO1 again.
- **The STM32 is only reset by GPIO1 when it is driven low.** Keep GPIO1 as an input otherwise: a push-pull high would fight the MCU's own reset pulse.
- **In bootloader mode the motors are safe:** nSLEEP is pulled down (4.7 k) and DRVOFF is high (no ALIVE).
- **Laptop recovery:** USB-C J50 + a firmware command that jumps to the bootloader (DFU), or SWD on TC2030 J47. BOOT0 cannot be raised without the Pi (bring-up §9 item 10).

---

## 11. Existing code that must change for rev C

| File | Rev B assumption | Rev C |
|---|---|---|
| `scripts/body-setup.sh` | i2c3 on 4/5, i2c4 on 6/7, i2c5 on 10/11, I2C1 at 400 kHz, no uart3 | config in §2.1 |
| `workspaces/rabbit/src/lib/hardware.py` `PINS` | TOF_PWR_OFF = 18, STATUS_LED = 19, SWITCH_OFF = 17 | 18 is the buzzer (PWM, kernel), 19 is TOF_MUX_RESET_N, 17 is gpio-poweroff (do not request). Add EXP_RESET_N = 6, EXP_INT_N = 7, MCU_BOOT0 = 0, MCU_NRST = 1 |
| `node/steering.py` | PCA9685 at 0x40 | 0x60 (**0x40 is now the battery INA238**) |
| `node/tof.py`, `lib/tof.py` | one sensor per bus, power cycle on GPIO18 | mux channels (§4), LPn reset, TOF3V3_EN via 0x22 P2_5 only with the motors disabled |
| `node/ina.py` | INA4235, bus 7 (Jetson) | INA238 ×4 + ADS7128 ×2 on I2C1 (§3.3-3.4) |
| `node/roboclaw.py` | RoboClaw packet protocol | STM32 protocol (§10) |
| `node/lidar.py`, `body.env` | one lidar, `/dev/ttyAMA4` | three lidars on UART3/4/5 by udev name |
| `node/power.py` | STATUS_LED / BTN_LED GPIOs | BTN_LED = 27; status on SK9822 SPI0; buzzer PWM; expander and eFuse sequencing (§6) |
