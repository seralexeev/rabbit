# Body board rev C: bring-up and acceptance test plan

Date 2026-10-11. Status: plan for the assembled boards from JLCPCB (not ordered yet; routing is in progress). Nothing
here was run on hardware.

## 0. Scope, sources and rules

**Source of truth.** `pcb/rabbit-body-c/gen/design.py` with `gen/placement.json` (netlist, values, refs). The spec
`docs/reports/2026-10-10-body-pcb-rev-c.md` is partly stale (9 INA238, 8 ToF eFuses, TPS2553, PH-6 lidar ports); where
it disagrees with `design.py`, `design.py` wins. Other sources, cited in the steps as short tags:

| Tag | File |
|---|---|
| `design.py` | `pcb/rabbit-body-c/gen/design.py` (block comments and part values) |
| sim `<n>-<test>` | `data/pcb-revc/sim/results.md`, decks in `workspaces/bench/pcb-sim/` (ngspice, 2026-10-10) |
| S-n | `data/pcb-revc/review/round1-sim.md` |
| P-n, R-n, M-n, F-n | `data/pcb-revc/review/round1-power.md`, `round1-pi.md`, `round1-mcu-motor.md`, `round1-footprints.md` |
| A-n | `data/pcb-revc/review/round2-audit.md` (script `workspaces/bench/pcb-audit/audit.py`) |
| `rail_resistance.py` | `workspaces/bench/pcb-bringup/rail_resistance.py` (new: unpowered resistances from the netlist, step B1.4) |
| `<part> p.N` | the datasheet PDF in `datasheet/<Maker>/`, page N of the PDF |
| [calc] | worked out for this plan from the cited values; [mem] = from memory, not checked against a PDF here |

Datasheets used: `datasheet/TI/tps25947.pdf` (SLVSFC9C), `lm74800.pdf` (SNOSDD8), `lm61495.pdf` (SNVSBZ4A),
`lm5069.pdf` (SNVS452G), `tps1663.pdf` (SLVSET9G), `drv8243-q1.pdf` (SLVSG23E), `ina238.pdf` (SLYS025B), `ads7128.pdf`,
`tca9548a.pdf`, `tps62826.pdf`, `tps2121.pdf`, `ref34.pdf`, `tlv755p.pdf`; `datasheet/NXP/pcal6524.pdf`, `pca9685.pdf`;
`datasheet/Slamtec/rplidar-c1-datasheet.pdf`; `datasheet/TDK/icm42688p.pdf`; `datasheet/Opsco/sk9822-ec20.pdf`;
`datasheet/Littelfuse/littelfuse-0451.pdf`; `datasheet/JST/jst-gh.pdf`.

**Rules for every step.**
- Robot motion (AGENTS.md): every motor, servo and arm test runs with the board on the bench, or with the robot on a
  stand and the wheels off the floor, and only after the owner says in that session that motion is fine.
- Power comes from a current-limited bench supply through an XT60 pigtail until step B6.4. Raise the limit only when
  the step says so. One change at a time; if a value is out of range, stop and record it.
- ESD: wrist strap and mat. The bottom side carries the DRV8243s, eFuses, ADCs and expanders: lay the board on
  standoffs, never flat on the bench.
- Each board gets a serial (marker on the silk, e.g. `C-01`). Results go to `data/pcb-revc/bringup/<serial>/results.md`
  (gitignored `/data/`), one row per step ID (B1.1 ...), with the measured value, the instrument and the pass/fail.
  Once the Pi runs, every step also leaves the Forge records listed in section 7.
- Test IDs: B1 incoming, B2 first power, B3 MCU, B4 Pi side, B5 servo and arm, B6 thermal and current, B7 observability.

## Reference tables

### Rails

| Rail | Source | Nominal (range) | Source of value | Test point | On by default (no Pi) |
|---|---|---|---|---|---|
| BAT_F | XT60 J1 through F1 15 A | battery 12.0-16.8 V | spec §3 | TP29 `BAT` | yes (always, when plugged) |
| VBUS_RAW / VBUS | LM74800 U10 + Q1/Q2, soft latch | = BAT_F − I × ~5 mΩ | `design.py` | TP20 `VBUS` | after a button press |
| MOT_BUS | LM5069 U30 + Q30, F2 10 A | = VBUS; UVLO on 11.58 V (10.94-12.22), off 10.58 V, OVLO 19.94 V | sim 5-rails | TP27 `VMOT` | **no** (MOT_BUS_OFF pulled up to +3V3_MCU) |
| +5V | LM61495 U4, 100k/24k | 5.167 V (5.033-5.303) | sim 5-rails | TP21 `5V` | yes (EN 100k/22k: starts at 7.0 V) |
| +5V_MCU | TPS2121 U32: IN1 = +5V (priority), IN2 = USB VBUS | ≈ +5V or USB VBUS | `design.py` | TP5 `5VM` | yes |
| +3V3_MCU | TLV75533 U15 (SOT-23-5) | 3.30 V (±1 %: 3.27-3.33) | tlv755p p.5 | TP1 `3V3M` | yes |
| ADC_AVDD | REF3425 U33 | 2.500 V ±0.05 % (2.49875-2.50125) | ref34 p.6 | TP31 `REF` | yes |
| +3V3_PI | Raspberry Pi 3.3 V via J3 pins 1/17 | 3.3 V | Pi | TP30 `3V3P` | **no** (only with the Pi) |
| SERVO_RAW | LM61495 U6, F4 10 A | 6.000 V (5.940-6.060); 7.399 V (7.325-7.473) with SERVO_7V4 | sim 5-rails | TP23 `SRVR` | no (SERVO_BUCK_EN) |
| SERVO_PWR | eFuse U83 | = SERVO_RAW | | TP22 `SRV` | no (SERVO_EN) |
| ARM_PWR | eFuse U88 | = SERVO_RAW | | none (J80/J81 pin 2) | no (ARM_EN) |
| +3V3_TOF | TPS62826 U31, 115k/25.5k 0.1 % | 3.306 V (3.273-3.339) | sim 5-rails | TP24 `3V3T` | no (TOF3V3_EN) |
| JET_PWR | TPS16630 U5 | = VBUS; UVLO 9.36 V, OVP 19.2 V, I_OL 3.53 A (3.28-3.78) | sim 5-rails | TP33 `JET` | **yes** (SHDN internal pull-up; Pi GPIO25 high turns it off) |
| SPARE_VBAT | TPS16630 U7 | = VBUS; I_OL 3.83 A (3.56-4.10), latch-off | sim 5-rails | TP34 `VBA` | no (SPAREBAT_EN) |
| +5V_PI_USBC | TPS259470A U87 | = +5V | `design.py` | none (J53 VBUS) | **yes** (EN = +5V/2 through R879/R878) |
| +5V_AUX, FANn_5V, LIDARn_5V, ENC_3V3 | TPS259470L U86, U84/U85, U80-U82, U78 | = rail | | TP32 `5VA` (AUX only) | no |

TP numbers: TP20-TP35 are created in this order in `design.py` (VBUS, 5V, SRV, SRVR, 3V3T, GND, GND, VMOT, GNDM, BAT,
3V3P, REF, 5VA, JET, VBA, MOTF); TP1 3V3M, TP2 DRVOFF, TP3 ESTOP, TP4 SRC (TPS2121 ST), TP5 5VM, TP6/TP7 SDA6/SCL6,
TP8 INT (EXP_INT_N), TP9 ALERT (PWR_ALERT_N), TP10/TP11 LED DO/CO.

### Switched loads (Pi side)

PCAL6524 U37 (0x22) drives the enables, U38 (0x23) reads FLT/PG (`design.py` EN_PORT/FLT_PORT; pins 1-24 = P0_0..P2_7).
TPS259470L: R_ILM = 3334 / I_LIM (tps25947 p.32 eq.7), table rows p.9; G_IMON 182 µA/A (165-200, p.10), so
V_ILM = I × 182 µA/A × R_ILM and V_ILM ≈ 0.607 V at I_LIM for every cell [calc]; t_ITIMER = 1.51 V × C / 1.8 µA
(p.10, p.32 eq.8). The ILM node feeds the ADS7128 through 10 kΩ + 1 nF (`design.py`); ADS7128 reference = ADC_AVDD
2.5 V, 12 bit, 0.61 mV/LSB.

| Load | eFuse | Out net → connector | R_ILM | I_LIM min/typ/max (A) | ITIMER | IMON (V/A) | ADC channel | EN bit (0x22) | FLT bit (0x23) |
|---|---|---|---|---|---|---|---|---|---|
| Lidar 1/2/3 | U80/U81/U82 | LIDARn_5V → J71/J72/J73 pin 1 | 1.65k (was 4.42k) | ~2.02 A typ (3334 / 1650) | 10 nF: 8.4 ms (5.1-14.5) | 0.300 V/A | 0x11 AIN0/1/2 | P1_0/1/2 | P1_0/1/2 |
| Steering servo | U83 | SERVO_PWR → J22-J29 pin 2 | 549 | 5.400 / 6.068 / 6.600 (p.9) | 22 nF: 18.5 ms (11.3-31.9) | 0.0999 | 0x11 AIN3 | P1_3 (SERVO_EN) | P1_3 |
| Fan 1/2 | U84/U85 | FANn_5V → J55/J56 pin 2 | 6.65k | 0.425 / 0.500 / 0.575 (p.9) | 10 nF: 8.4 ms | 1.210 | 0x11 AIN4/5 | P1_6/7 | P1_6/7 |
| Spare 5 V + CAN pin 1 | U86 | +5V_AUX → J58 pin 1, J51 pin 1 | 1.65k | 1.800 / 2.028 / 2.200 (p.9) | 10 nF: 8.4 ms | 0.300 | 0x11 AIN6 | P2_0 | P2_0 |
| Encoders L+R | U78 | ENC_3V3 → J41/J42 pin 2 | 6.65k | 0.425 / 0.500 / 0.575 (p.9) | 1 nF: 0.84 ms (0.5-1.5) | 1.210 | 0x11 AIN7 | P2_1 | P2_1 |
| xArm | U88 | ARM_PWR → J80/J81 pin 2 | 750 | 3.960 / 4.452 / 4.840 (p.9) | 22 nF: 18.5 ms (11.3-31.9) | 0.1365 | 0x17 AIN5; FLT on 0x17 AIN6 (GPIO) | P0_6 (ARM_EN) | — |
| Pi USB-C | U87 (TPS259470**A**, auto-retry 110 ms, p.11) | +5V_PI_USBC → J53 VBUS | 887 | 3.76 typ (eq.7, no table row; ~3.4-4.1 est.) | 10 nF: 8.4 ms | 0.161 | 0x17 AIN3; FLT on 0x17 AIN4 (GPIO) | fixed on | — |
| Jetson | U5 TPS16630, auto-retry | JET_PWR → J21 (XT30) | R_ILIM 5.1k | 3.28 / 3.53 / 3.78 (sim 5-rails) | — | 0.279 (27.9 µA/A × 10k, tps1663 p.9) | 0x17 AIN1 | GPIO25 high = off | P2_4 |
| Spare VBAT | U7 TPS16630, latch-off | SPARE_VBAT → J20 (XT30) | 4.7k | 3.56 / 3.83 / 4.10 | — | 0.279 | 0x17 AIN2 | P2_3 | P2_3 |
| Servo buck | U6 LM61495 | SERVO_RAW | — | low-side limit 9.8 / 11.5 / 12.9 (lm61495 p.7) | — | INA238 0x43 | — | P1_4 (SERVO_BUCK_EN), P1_5 (SERVO_7V4) | P1_4 (PG) |
| ToF rail | U31 TPS62826 | +3V3_TOF → J60-J65 pin 2 | — | HS limit 3.7 / 4.3 / 5.0 (tps62826 p.6), hiccup | — | **none** | — | P2_5 | P2_6 (PG) |
| Motor bus | U30 LM5069 | MOT_BUS | — | 9.7 / 11.0 / 12.3 (55 mV / 5 mΩ, sim 5-rails) | 22 nF fault timer 1.04 ms | INA238 0x41 | — | P2_4 (MOT_BUS_OFF, low = on) | P2_5 (PG) |
| +5V buck | U4 | +5V | — | 9.8 / 11.5 / 12.9 | — | INA238 0x47 | — | always on | P1_5 (5V_PG) |

0x23 P2_7 = RTC_INT_N. Unused 0x22/0x23 lines are named EXP_OUT_SPARE*/EXP_IN_SPARE*.

### I2C

- **Pi I2C1** (J3 pins 3/5, 100 kHz, only the Pi's 1.8 kΩ pull-ups): exactly **0x11, 0x17** (ADS7128), **0x20**
  (TCA6416A), **0x22, 0x23** (PCAL6524), **0x40, 0x41, 0x43, 0x47** (INA238 battery, motor bus, servo, 5 V),
  **0x60** (PCA9685), **0x68** (DS3231), **0x70** (PCA9685 All Call, ACKs from power-up: pca9685 p.8). 12 addresses.
  Source: `design.py` straps; `i2c_address_map.json` agrees on the addresses (its text for 0x11/0x17 is stale).
- **Pi I2C6** (GPIO22/23, J3 pins 15/16, `dtoverlay=i2c6,pins_22_23`, 2.2 kΩ R892/R893 on the board): **0x77**
  (TCA9548A) only; ToF sensors at 0x29 appear only behind a selected channel.
- **STM32 I2C3** (PC8/PC9, 2.2 kΩ): 0x48, 0x49 (TMP117), 0x30 (MMC5983MA, assembled).

### INA238 calibration (ina238 p.30 eq.1: SHUNT_CAL = 819.2·10⁶ × CURRENT_LSB × R_SHUNT, ×4 for ADCRANGE = 1)

| Addr | Ref | Shunt | IN+/IN− and VBUS pin | ADCRANGE (full scale) | CURRENT_LSB | SHUNT_CAL |
|---|---|---|---|---|---|---|
| 0x40 | U21 | R1 2 mΩ 1 % WSLP2512 | VBUS_RAW → VBUS; VBUS pin = VBUS | 1 (±40.96 mV = 20.5 A) | 1 mA | 6554 (0x199A) |
| 0x41 | U22 | R3 5 mΩ 1 % (shared with the LM5069) | MOT_F → MOT_SNS_D; VBUS pin = MOT_BUS | 0 (±163.84 mV = 32.8 A) | 1 mA | 4096 (0x1000) |
| 0x43 | U23 | R2 5 mΩ 1 % | SERVO_BUCK → SERVO_RAW; VBUS pin = SERVO_RAW | 0 | 1 mA | 4096 |
| 0x47 | U26 | R6 5 mΩ 1 % | +5V_BUCK → +5V; VBUS pin = +5V | 0 | 1 mA | 4096 |

Expected accuracy before trimming: shunt 1 % + INA238 gain 0.1 % (ina238 p.5) ≈ ±1.1 % plus offset; VBUS ±0.1 %
± 5 mV (p.5). MANUFACTURER_ID (0x3E) = 0x5449, DEVICE_ID (0x3F) = 0x2381 (ina238 p.28).

---

## 1. Incoming inspection (no power)

**B1.1 Paperwork.** JLC DFM/AOI report and X-ray images (order X-ray for the parts below). BOM against the board:
the DNP parts are exactly R1106, R1206 (DRV8243 MODE 0R), Q1102, Q1202, R1151 (second ITRIP line), R423, R424 (IMU
CLKIN link) (`design.py` bom="dnp"). The MMC5983MA U43, C431, C432 **are** fitted (C33). J20/J21 (XT30, bottom THT)
are soldered (F-7). The CR1220 cell is not supplied (BT1 "cell not included").

**B1.2 Visual / AOI / X-ray points.** Under a microscope, 10-20×:
- Bottom-terminated parts with exposed pads (X-ray for voids and bridges): U11, U12 DRV8243 (VQFN-HR-14, bottom);
  U4, U6 LM61495 (VQFN-HR-16); U31 TPS62826 (VSON-HR 1.5 × 1.5, bottom); the 11 eFuses U78, U80-U88 (RPW0010A
  2 × 2 mm, bottom except U83/U88); U10 LM74800 (WSON-12); U32 TPS2121 (VQFN-HR-12); U35, U36 ADS7128 (WQFN-16);
  U37, U38 PCAL6524 (QFN-32 on the KiCad land, not NXP's: check side fillets on all 32 pins, `design.py` PCAL note);
  U40 TCA9548A, U41 TCA6416A; U44, U45 TMP117; U46 TCAN1044AV; U5, U7 TPS16630 (HTSSOP-20 PowerPAD).
- LGA (X-ray only): U42 ICM-42688-P (LGA-14), U43 MMC5983MA (LGA-16).
- U1 STM32G474 LQFP-64: bridges between 0.5 mm pins.
- D89 TPD1E10B09 (X1SON-2, 1.0 × 0.6 mm on the custom land F-9): not tombstoned or tilted.
- J41, J42 PH-6 SMD on the bottom: both mounting tabs soldered (the motor cable pulls on them).
- J60-J65 GH-6 (HCTL HC-GH-6PLT, bottom): mate a genuine JST GH-6 housing once per board; latch must click and hold
  (GH-compatibility with genuine JST plugs was not checked, Q50).
- Polymer capacitors and the XAL1010 inductors L4/L6 upright, no lifted pins; shunts R1, R2, R3, R6 Kelvin pads
  fully wetted (the INA238 gain depends on them).
- No flux residue under U35/U36 (ADC inputs at 10 kΩ / 1 nF) and around the 0.1 % dividers.

**B1.3 Polarity and orientation.** Check each part against its silk mark and the render
`pcb/rabbit-body-c/renders/{top,bottom}_labelled.png`.

| Part | Rule | Source |
|---|---|---|
| J1 XT60 (top) | pad 1 = GND at the chamfered end (silk "−" at pad 1), pad 2 = BAT_IN (flat end, "+") | `design.py` J1, F-2, A-audit XT table |
| J20, J21 XT30UPB-F (bottom, mate from below) | pad 1 = GND at the chamfered end ("−"), pad 2 = SPARE_VBAT / JET_PWR | F-1, M26 |
| J50, J53 USB-C vertical | both GCT USB4115; J53 is power only (data pins open) | `design.py` |
| J3 2×20 Würth box header | key notch matches the silk; pin 1 square pad. Pins 2 and 4 are **not connected** (B1.4) | `design.py` PI_PINS |
| J41, J42 PH-6 (bottom) | 1 Mx_OUT2, 2 ENC_3V3, 3 ENC_x_A, 4 ENC_x_B, 5 GND, 6 Mx_OUT1 | `design.py`, M-2 |
| J80, J81 PH-3 | 1 GND, 2 ARM_PWR, 3 ARM_SIG (silk "ARM − + S") | `design.py`, M25 |
| J71-J73 XH-5 | 1 LIDARn_5V, 2 LIDARn_TX (lidar out), 3 LIDARn_RX (lidar in), 4 GND, 5 NC | `design.py`, rplidar-c1 p.12 |
| J60-J65 GH-6 (bottom) | 1 GND, 2 +3V3_TOF, 3 SDA, 4 SCL, 5 INT, 6 LPn | `design.py` |
| J52 XH-4 E-stop | 1 ESTOP_A (Pi GPIO16 via 1k), 2 ESTOP, 3 ESTOP2_SRC (+3V3_MCU via 1k), 4 ESTOP2_M | `design.py` |
| J15 XH-5 button | 1 BTN_ON, 2 GND, 3 POWER_BTN, 4 +5V, 5 BTN_LED_K | `design.py` |
| J13, J14 XH-2 bumpers | 1 BUMPER, 2 GND | `design.py` |
| J55, J56 KK-254 fans | 1 GND, 2 FANn_5V, 3 TACH, 4 PWM (5 V fans only) | `design.py` |
| J58 XH-2 | 1 +5V_AUX, 2 GND | `design.py` |
| J51 GH-4 CAN | 1 +5V_AUX, 2 CANH, 3 CANL, 4 GND | `design.py` |
| J22-J29 1×3 servo | 1 PWM, 2 SERVO_PWR, 3 GND | `design.py` |
| J47 TC2030 | 1 +3V3_MCU (VTref), 2 SWDIO, 3 NRST, 4 SWCLK, 5 GND, 6 NC | `design.py` |
| C30, C33, C887, C1103, C1203 (220 µF 35 V), C835, C836 (470 µF 25 V) polymers | stripe/bevel = pin 2 = GND / GND_MOT | `design.py` |
| D1, D13 SMBJ20A (VBUS), D10 (MOT_BUS → GND_MOT), D14, D15 (JET_PWR, SPARE_VBAT) | cathode band on the rail | `design.py` tvs() |
| D7 SMBJ20CA (BAT_F) | bidirectional, no polarity | |
| D31, D831 B540C; D88, D801, D811, D821, D841, D851 B340A | cathode band on MOT_BUS / SERVO_PWR / ARM_PWR / LIDARn_5V / FANn_5V | `design.py` |
| D8 BZT52C8V2 (cathode VBUS_RAW), D11 BZT52C12, D9, D30 1N4148WS, D90 BAT54WS (cathode ARM_PWR) | band = pin 1 | `design.py`, A-audit D90 |
| D12, D1105, D1205 BAT54S; Q-parts (SOT-23) | pin 1 dot | |
| D2-D6, D93 red LEDs | cathode (pin 1) to GND | `design.py` led() |
| LED1-LED8 SK9822-EC20 | pin 1 corner mark | sk9822 |
| BT1 CR1220 holder | "+" up | Keystone 3000 |
| ICs | pin 1 dot against the silk dot, all 60 | |

**B1.4 Resistance to GND before any power.** Meter in Ω mode, black lead on TP25/TP26 `GND`, red on the rail. Caps
charge from the meter, so wait until the reading stops rising (VBUS: τ ≈ 12 kΩ × ~0.5 mF ≈ 6 s). Expected values are
the resistor network only (`rail_resistance.py`): a real reading may be lower where IC inputs conduct, never much
higher.

| Net (where) | Expected (settles to) | Fail if |
|---|---|---|
| BAT_F (TP29, J1 pin 2) | open, > 1 MΩ (LM74800 off, Q4 off) | < 100 kΩ |
| VBUS = VBUS_RAW = MOT_F = BODY_IN = STEER_IN (TP20, TP35) | 12.4 kΩ (EN, UVLO, OVP and OVLO dividers) | < 5 kΩ |
| MOT_BUS (TP27) | 32.6 kΩ (R63/R64, brake dividers) | < 10 kΩ |
| BRK_VCC (U17 pin 8) | 32.7 kΩ | < 10 kΩ |
| +5V (TP21) | 15.1 kΩ (FB 124k, OVLO 50.2k, TPS2121 PR1 30k, R879/R878) | < 5 kΩ |
| USB_VBUS (J50 VBUS) | 15.1 kΩ (R150/R151, CP2, OV2) | < 5 kΩ |
| +3V3_MCU (TP1), +3V3_MCU_A, +3V3_IMU | 10.0 kΩ (two 10k + NTC 10k at 25 °C to GND_MOT); MCU_A/IMU are behind 10 Ω | < 3 kΩ |
| +3V3_TOF (TP24) | 26.9 kΩ (FB 140.5k, OVLO 33.2k) | < 10 kΩ |
| SERVO_RAW (TP23) | 45.0 kΩ (FB 120k, OVLO 71.9k) | < 15 kΩ |
| ARM_PWR (J80 pin 2) | 4.7 kΩ (bleed R890) | < 3 kΩ |
| +5V_MCU, +3V3_PI (TP30), ADC_AVDD (TP31), SERVO_PWR (TP22), ARM_5V, JET_PWR (TP33), SPARE_VBAT (TP34), +5V_AUX (TP32), +5V_PI_USBC, ENC_3V3, FAN1/2_5V, LIDAR1/2/3_5V | open (> 1 MΩ, IC leakage, LEDs below their knee) | < 100 kΩ |
| GND_MOT (TP28) to GND | < 0.2 Ω (NT1 star; cannot be measured apart from the copper) | > 1 Ω |

Then rail to rail. Any pair below 100 Ω is a short, except the designed 10 Ω pairs (+3V3_MCU/+3V3_MCU_A R100,
+3V3_MCU/+3V3_IMU R421) and the same-node groups above. Measure at least: VBUS–MOT_BUS, VBUS–+5V, VBUS–SERVO_RAW,
VBUS–JET_PWR, VBUS–SPARE_VBAT, MOT_BUS–+5V, SERVO_RAW–SERVO_PWR, SERVO_RAW–ARM_PWR, SERVO_PWR–+5V, ARM_PWR–+5V,
+5V–+3V3_MCU, +5V–+3V3_TOF, +5V–+3V3_PI, +3V3_MCU–+3V3_PI, +3V3_TOF–+3V3_PI. Expected: about the sum of the two
values to GND (e.g. VBUS–+5V ≈ 27 kΩ) [calc].

Also:
- J3 pins 2 and 4 to anything: open (`design.py` PI_PINS has no pin 2/4; R-15, C32).
- Motor outputs ML_OUT1/2, MR_OUT1/2 (J41/J42 pins 6/1) to GND_MOT and to MOT_BUS: > 100 kΩ (DRV8243 unpowered).
- ESTOP (TP3) to GND: 10 kΩ (R17). EXP_RESET_N (J3 pin 31) to GND: 10 kΩ (R371). MCU_BOOT0 to GND: 10 kΩ (R90).
- I2C1 SDA/SCL (J3 pins 3/5) to GND: open (no board pull-ups on I2C1; S-6). I2C6 (TP6/TP7) to +3V3_PI (TP30): 2.2 kΩ.

**B1.5 Before first power.** Fit a CR1220 in BT1 (DS3231 VBAT must not float: R-7). Check the button LED of the
owner's button on its own (5 V through a 220 Ω test resistor, then without): J15 sinks BTN_LED_K through Q3 with no
series resistor on the board, so the button must have one inside. Pre-wire the pigtails in B8.2 (shopping list).

## 2. First power: bench supply, nothing plugged

Setup: bench supply into J1 through an XT60 pigtail, 12.0 V, **limit 100 mA**. Nothing else connected: no Pi, no J53
cable, no J21 Jetson, no motors, servos, arm, lidars, ToF, fans, USB. DMM on TP20 (VBUS). Scope: CH1 BAT_F (TP29),
CH2 VBUS_RAW/VBUS (TP20), CH3 +5V (TP21), CH4 MOT_BUS (TP27).

What is on by design with no Pi (+3V3_PI absent, so both PCAL6524 are unpowered and their 100 kΩ arrays hold every
EN low; `design.py` PCAL block): VBUS, +5V, +5V_MCU, +3V3_MCU, ADC_AVDD, **JET_PWR** (TPS16630 SHDN has an internal
pull-up; only Pi GPIO25 turns it off) and **+5V_PI_USBC** (U87 EN tied to +5V). Off: MOT_BUS, SERVO_RAW/PWR, ARM_PWR,
+3V3_TOF, ENC_3V3, LIDARn_5V, FANn_5V, +5V_AUX, SPARE_VBAT.

| Step | Action | Expected | Source |
|---|---|---|---|
| B2.1 | Supply on, **no button press** | VBUS_RAW < 1 V; supply current < 10 µA (LM74800 shutdown 2.87 µA typ / 5 µA max + TVS leakage; Q4 off; C26 blocks DC) | lm74800 p.5 I(SHDN); `design.py` latch |
| B2.2 | Short J15 pins 1-2 for 1 s (the supply is current-limited, so VBUS ramps slowly; the sim latches with 150 ms) | latched: VBUS ≈ 12.0 V; LM_EN 3.57 V at 12 V; D5 (VBUS) and D2 (+5V) lit, D4 (JET) lit | sim 1-latch cycle_12.0V |
| B2.3 | Read the supply current, raise the limit to 500 mA | 10-25 mA at 12 V [calc: LM74800 0.4 mA, dividers 1 mA, D5 1 mA, LM5069 disabled 0.48 mA, D4 2.2 mA, TPS16630 on ~0.5 mA, 5 V side ~18 mA (D2 3.4 mA, SK9822 8 × ~1 mA, blank STM32 bootloader, REF3425)]. Record as the board's baseline | lm5069 p.5, sk9822 p.6, ref34 p.1 |
| B2.4 | Rails, DMM | +5V 5.033-5.303 V (5.167 typ); +5V_MCU ≈ +5V − 0.05 V; +3V3_MCU 3.27-3.33 V; +3V3_MCU_A ≈ +3V3_MCU; ADC_AVDD 2.49875-2.50125 V; JET_PWR ≈ VBUS; +5V_PI_USBC ≈ +5V; MOT_BUS < 0.5 V; SERVO_RAW, +3V3_TOF, SPARE_VBAT, +5V_AUX < 0.1 V | sim 5-rails; tlv755p p.5; ref34 p.6 |
| B2.5 | Control nodes, DMM | MOT_BUS_OFF ≈ 3.3 V (pulled up to +3V3_MCU), MOT_UVLO < 0.1 V (Q31 on); DRVOFF (TP2) ≈ 3.3 V (ESTOP low without the Pi); ESTOP (TP3) 0 V; ITRIP_SEL (U1 pin 33) 3.3 V (R1150 pull-up, 2.41 A level); DRV_x_NSLEEP 0 V (R94/R95); EXP_RESET_N 0 V; MCU_BOOT0 0 V | `design.py`; A-audit MOT_BUS_OFF |
| B2.6 | Step 12.0 → 14.8 → 16.8 V | rails unchanged; current falls with voltage (buck); MOT_BUS stays < 0.5 V | |
| B2.7 | **Power-up waveform.** Limit 2 A, button held, switch the supply output on at 16.8 V (scope single shot, 20 ms/div) | VBUS_RAW ramps at ~1.17 V/ms (0.83-1.6) set by C23 47 nF and I_HGATE 55 µA (39-75); inrush ≈ 0.6 A into ~520 µF of VBUS caps [calc]. +5V starts when VBUS passes 7.0 V (6.44-7.57). MOT_BUS never rises above 0.5 V (P-4/R-2 fix). DRVOFF stays high | lm74800 p.6 I(HGATE), p.16 eq.2; sim 5-rails U4 EN |
| B2.8 | **Brown-out.** From 14.8 V, ramp down at ~0.1 V/s to 8.0 V, then back up to 16.8 V | JET_PWR off at TPS16630 UVLO (falling below 9.36 V by the hysteresis); latch drops between 8.4 and 10.0 V of supply (D8 8.2 V + EN 1.132 V × 267k/220k ≈ 9.6 V; soft zener knee lowers it, P-13); +5V follows down; **after recovery the board stays off** (C26 to BAT_F) | sim 1-latch dip cases and S-1 fix; tps1663 p.8 |
| B2.9 | **Over-voltage.** Latched at 16.8 V, ramp up at 0.1 V/s, **stop at 20.0 V** (SMBJ20A/CA break down at 22.2 V min) | JET_PWR off at 19.2 V (18.82-19.58, TPS16630 OVP); VBUS_RAW cut at 19.70 V (19.12-20.27, LM74800 OV); after the cut VBUS_RAW decays, the latch drops and the board stays off until a press (inferred from the circuit, not simulated) | sim 5-rails; lm74800 p.5 V(OVR) |
| B2.10 | **Hot-plug** with the real battery (or the supply output pre-enabled and an XT60 plugged by hand), 10 times at 12-16.8 V | VBUS_RAW stays < 1 V every time (no turn-on without a press) | sim 1-latch plugin_*_fixC26, S-1 |
| B2.11 | **Off by the Pi line.** Latched at 14.8 V, drive J3 pin 11 (GPIO17) to 3.3 V through 1 kΩ from a lab source | VBUS_RAW < 1 V within 1.58-1.62 s, no re-latch; C25/R49 keep Q5 on ~1 s after the drive is removed | sim 1-latch cycle_*; `design.py` latch comment |
| B2.12 | **Reverse polarity.** Swap the leads, limit 50 mA. Every board: −5 V. First board only: then −12 V and −16.8 V (see risk 11: above ~8.5 V reverse, Q4's emitter-base junction is driven past its 5 V rating) | at −5 V: < 0.15 mA; at −16.8 V: < 0.35 mA (LM74800 I(A) reverse ≤ 112 µA, plus 0.1-0.2 mA from GND through Q5's body diode, R45, Q4's collector-base junction and R43 to BAT_F [calc]); all rails 0 V. Then forward again at 12 V: B2.2-B2.4 values unchanged, the button still latches | lm74800 p.4 (A to GND −65 V; EN may go to V(A)), p.5 I(REV) |
| B2.13 | 10 min latched at 16.8 V, thermal camera snapshot | nothing above ambient + 10 K; hottest: D2/D4/D5 LEDs, U4 | |

## 3. MCU

Power the board from the bench at 14.8 V unless the step says USB only.

**B3.1 SWD.** Tag-Connect TC2030-CTX-NL (+ retaining clip; J47 is the no-legs footprint) to an ST-LINK V3 or J-Link,
probe set to **not** power the target (VTref = +3V3_MCU from the board). Connect under reset. Expected: DBGMCU IDCODE
DEV_ID 0x469 (STM32G47x/48x) [mem, RM0440]; flash 512 KB. Read option bytes: keep nSWBOOT0 = 1 (BOOT0 from the pin,
`stm32_pinmap.md` pin 61). Flash the bring-up firmware (test build of the motor firmware with a test command set).

**B3.2 Clocks.** HSE 8 MHz Y1 (C88/C89 18 pF). Output MCO on PA8 (DRV_L_IN1; DRV8243 L stays asleep, nSLEEP low)
and measure 8.000 MHz ± 50 ppm (crystal tolerance: check the C367183 listing). PLL to 170 MHz; toggle PC3 (MCU_ALIVE)
from a timer at 10.000 kHz and measure it: error < 0.01 %. FDCAN needs the HSE (`stm32_pinmap.md` pin 5).

**B3.3 USB-C (J50) and the source mux.**
- Board unpowered, laptop on J50 (through a USB isolator): +5V_MCU ≈ 5 V, +3V3_MCU 3.3 V, USB_VBUS_DET (U1 pin 20)
  = VBUS × 33/55 = 3.0 V at 5.0 V (3.15 V at 5.25 V, TT pin limit 4.0 V); record the TP4 (TPS2121 ST, 10k to
  +3V3_MCU) level here and again on board power: the two must differ (tps2121 p.4); laptop
  current < 150 mA [est.]. TPS2121 current limit 1.5 A (1-2 A). Source: `design.py` USB block; tps2121 p.8.
- CDC device enumerates (bring-up firmware). DFU: the system bootloader needs BOOT0 high, which only Pi GPIO0 can
  drive (no button): enter it from firmware or with the Pi in B4 (stm32 p.21 lists DFU over USB).
- With USB connected, latch the board at 14.8 V: TPS2121 switches to IN1 (+5V above the PR1 threshold 3.18 V,
  3.03-3.30) within 100 µs (tps2121 p.7 t_SW); the MCU must **not** reset (read RCC_CSR reset flags: no POR/BOR/PIN).
  Turn the board off: switch back to USB without a reset.

**B3.4 MCU housekeeping.** TMP117 0x48/0x49 on I2C3 read room temperature within ±1 °C of a reference
(±0.1 °C spec, `design.py`). ICM-42688-P on SPI3 (21.25 MHz): WHO_AM_I (0x75) = 0x47 (icm42688p p.87); gravity
9.81 m/s² ±2 % on the vertical axis at rest. MMC5983MA 0x30 answers (product ID register; fitted, C33). NTC_L/NTC_R
(PA0/PA1) read 1.65 V ± 0.1 V at 25 °C (10k/10k). VMOT_SENSE (PC2) = MOT_BUS/11. BRK_SENSE (PC5) 0 V.
Encoder inputs: set PWR_CR3.UCPD1_DBDIS = 1 first (PB4/PB6 carry the UCPD dead-battery Rd while PA9/PA10 are high,
`stm32_pinmap.md` pins 43/44).

**B3.5 DRVOFF watchdog (no motor power needed).** ESTOP must be high: plug a shorting plug into J52 (1-2, 3-4) and
drive J3 pin 36 (GPIO16 net) to 3.3 V from a lab source (or use the Pi, B4). Scope: CH1 PC3 (MCU_ALIVE), CH2 C14B
(ALIVE_DET, no TP), CH3 TP2 DRVOFF, CH4 TP3 ESTOP. Expected (sim 2-watchdog, all corners):

| Case | Expected |
|---|---|
| Toggle PC3 at 10 kHz (the firmware rate, S-5) | ALIVE_DET 2.58-3.00 V; DRVOFF goes low 1.1-1.2 ms after toggling starts |
| Toggle at 1 kHz | ALIVE_DET 2.27-2.87 V; release after 2.0-3.0 ms (VT+ max 2.04 V: only 0.23 V margin at the worst corner) |
| Stop the toggle low / high | DRVOFF high after 6.0-11.3 ms / 13.7-23.0 ms (limit ≤ 50 ms, IWDG) |
| Frequency sweep 10 kHz → 50 Hz | release still happens down to 100-300 Hz (S-5, known: the hardware guarantees "stuck pin → DRVOFF", not a frequency floor). Record the measured floor |
| ESTOP opened while toggling | TIM1/TIM8 BKIN zero the PWM at once (PA8/PA9/PC6/PC7 low within µs, logic analyser); DRVOFF high after 208-278 ms (100k × 2.2 µF into the Schmitt NAND) |
| Power-up | DRVOFF high for ≥ 200 ms after +3V3_MCU rises (209 ms in sim) |
| PA4 (DRVOFF_MON) | firmware reads the same level as TP2 in every case above (R19 10k readback, M-3) |

**B3.6 E-stop, two channels.** The owner's 2-channel NC mushroom button on J52; GPIO16 driven high as in B3.5.
- Both closed: ESTOP ≈ 3.3 V × 10k/11k = 3.0 V; PC15 (ESTOP2_M) ≈ 3.0 V.
- Open channel 1 only: ESTOP < 0.1 V, BKIN brake, DRVOFF high after 208-278 ms; firmware reports a channel mismatch.
- Open channel 2 only: PC15 < 0.1 V; firmware stops (both DRV inputs 0/0) and reports the mismatch; DRVOFF follows
  only if firmware stops MCU_ALIVE (document which).
- Short J52 pin 1 to GND: GPIO16 sources 3.3 mA through R16 1k (R-4 fix), the Pi pin survives.

**B3.7 Motors in the air (DRV8243).** Preconditions: owner's OK (AGENTS.md), motors on the bench or wheels off the
floor; the Pi from B4 is running (the motor bus and the encoder supply are enabled through the 0x22 expander);
supply 14.8 V (the LM5069 UVLO turns on at 11.58 V typ but **12.22 V max**: at 12.0 V the motor bus may stay off,
sim 5-rails), limit 3 A.

1. **Kit cable pin 1 (M-2) before plugging.** On a kit motor with its cable, with a meter on the cable's board-end
   housing: the two cavities with ~3.75 Ω between them are the motor (cavities 1 and 6; JGB37-520 winding, spec §4).
   Diode mode, red on the cavity next to M2 (must be cavity 2, VCC) and black on cavity 5 (GND): an IC junction reads
   about 0.5-0.7 V one way only. If VCC turns out to be cavity 5, **do not plug**: the encoder would get 3.3 V on its
   GND pin. Photograph and record the result against `datasheet/JGB37-520R30-12/hiwonder-JGB37-520R-encoder-pinout.jpg`.
2. **Encoder supply.** TOF3V3_EN then ENC_EN on (U78 is fed from +3V3_TOF, so the ToF buck must be on): ENC_3V3 at
   J41/J42 pin 2 ≈ +3V3_TOF (3.27-3.34 V), pin 5 GND. Plug both motors. ENC_IMON (0x11 AIN7) ≈ 1.21 V/A × encoder current
   (~20 mA total, spec §4) ≈ 0.02-0.05 V. Turn each wheel one revolution by hand: 1320 counts per wheel revolution
   (11 pulses × 4 edges × 30:1, spec §4), sign per side recorded.
3. **Motor bus.** Pi writes 0x22 P2_4 low (output register first, then direction: R-12). MOT_BUS ramps after the
   insertion delay 16 ms (22 nF × 4 V / 5.5 µA, 11-29 ms) at ~0.16 V/ms (I_GATE 16 µA, 10-22, into C303 100 nF), so
   67-150 ms to 14.8 V, inrush ≈ 0.07 A into ~460 µF [calc]; MOT_BUS_PG (0x23 P2_5) high; INA238 0x41 VBUS = MOT_BUS
   within 0.1 % ± 5 mV. Source: lm5069 p.5 (I_GATE), p.6 (insertion current); `design.py` LM5069 block.
4. **Wake handshake.** nSLEEP high: nFAULT (PB1/PB2) goes low to acknowledge the wake-up; send an nSLEEP low pulse of
   25-35 µs (longer than t_RESET 5-20 µs, shorter than t_SLEEP 40-120 µs): nFAULT returns high, driver in STANDBY
   (drv8243 p.11-12, p.22).
5. **Run.** 20 kHz PWM, duty limited to 12 V / VBUS (spec §4), both directions, each side. No-load current 0.4-1 A
   (`design.py` motor connector comment). IPROPI (PC0/PC1) = 0.489 V/A (1.5 kΩ × 1/3070, drv8243 p.16); sampled in the high-side on
   time it must match the INA238 0x41 current divided by the duty within ±20 % at 0.2-0.8 A and ±5 % at 0.8-4.3 A
   (drv8243 p.16 A_ERR); zero-load offset ≤ 15 µA × 1.5 kΩ = 22 mV (≈ 46 mA).
6. **ITRIP level.** ITRIP_SEL high (default): IPROPI chops at 1.06-1.30 V = 2.17-2.66 A (LVL2); PB11 low: 1.78-2.18 V
   = 3.64-4.46 A (LVL3) (drv8243 p.16 V_ITRIP; `design.py` ladder 8.25k / 21.95k). Stall test in B6.2.
7. **Fault latch.** Optional, at 14.8 V / 3 A limit: short Mx_OUT1 to GND_MOT on the PH pigtail for < 1 s. Expected:
   OCP within 4.5-7.3 µs (p.16 t_OCP), nFAULT low and **latched** (DIAG 100k = LVL5 latch, `design.py`); cleared only
   by the nSLEEP reset pulse.
8. **Brake chopper.** With the motor bus on, raise the supply to 17.9 V for **≤ 200 ms**, then back to 16.8 V. Brake
   on at 17.67 V, off at 17.18 V (`gen/calc.py`); BRK_SENSE (PC5) high while on; 4 × 39 Ω take 1.8 A = 8 W, four
   times their 2 W rating (A-9): never hold it.

## 4. Pi side

**B4.1 Pi image and `config.txt`** (from `data/pcb-revc/ics/pi_pinmap.md`): `dtparam=i2c_arm=on,i2c_arm_baudrate=100000`;
`dtoverlay=i2c6,pins_22_23,baudrate=400000`; `dtoverlay=uart3`, `uart4`, `uart5`; `dtoverlay=disable-bt` (UART0 on
GPIO14/15 to the MCU, no serial console); `dtparam=spi=on` + `dtoverlay=spi0-0cs,no_miso` (frees GPIO7/8/9);
`dtoverlay=pwm,pin=18,func=2`, `dtparam=audio=off`; `dtoverlay=gpio-poweroff,gpiopin=17`; `force_eeprom_read=0`
(GPIO0/1 are BOOT0/NRST); `gpio=0-1=ip,pn`, `gpio=6=op,dl` (expanders held in reset: every load off until the power
node runs), `gpio=16=op,dl` (E-stop = stop until safety runs). `cmdline.txt`: `pinctrl_bcm2835.persist_gpio_outputs=n`
(P17). Check with `pinctrl get 0-27`.

**B4.2 Ribbon and power order.** Pin 1 marks at both ends. With everything unpowered, measure the Pi's own pin 2
(5 V) to Pi GND with the ribbon on: it must read the Pi's normal value, not < 1 Ω (a reversed socket puts Pi 5 V on
board pin 39 = GND: R-9). Power order for B4: board first (bench, 14.8 V), then the Pi from its **own** USB-C supply
(J53 unplugged until B4.12); off in reverse. Scope MCU_NRST during the Pi boot: no low pulse (force_eeprom_read=0).

**B4.3 I2C1 scan.** `i2cdetect -y -r 1` lists exactly the 12 addresses of the I2C reference table. Missing or extra =
stop. INA238s: MANUFACTURER_ID 0x5449, DEVICE_ID 0x2381. Scope J3 pin 3/5 at 100 kHz: rise (30-70 %) < 1000 ns;
sim 4-i2c gave 355-432 ns with 18 devices, so expect less with 12; VOL < 0.4 V (S-6). Do not raise the bus to
400 kHz (S-6).

**B4.4 I2C6 and the ToF mux.** `ls /dev/i2c-*` (the overlay's bus number), `i2cdetect -y -r <bus>`: only 0x77. The
control register reads 0x00 (all channels off at power-up and after a reset: tca9548a p.1, p.12). Pulse GPIO19 low
(TOF_MUX_RESET_N): still 0x00. Scope TP6/TP7 at 400 kHz with one ToF carrier selected: rise ≤ 300 ns (Fast-mode);
sim 4-i2c tof_port had 253 ns port side and 317 ns Pi side, so this is marginal: if > 300 ns, run I2C6 at 100-200 kHz.

**B4.5 Expander walk (PCAL6524 0x22 / 0x23) with ADC readback.** Release EXP_RESET_N (GPIO6 high). For 0x22 write
the output registers to 0 **before** setting the direction registers to output (outputs reset to FFh: R-12). Enable
input latching and interrupts on 0x23; EXP_INT_N = GPIO7 (TP8). Configure both ADS7128 for manual reads without
averaging (averaging stretches SCL: R-13), ALERT open drain (default, ads7128 p.19), U36 AIN4/AIN6 as digital inputs
(USB_PI_FLT, ARM_FLT, pulled up to ADC_AVDD). Then for each row of the switched-load table, with nothing plugged:

1. EN high → the output net ramps at SR = 2000 / C_dVdt[pF] V/ms (tps25947 p.30 eq.4): 2.2 nF → 0.91 V/ms, so
   +5V loads in ~5.5 ms and ENC_3V3 in ~3.6 ms; 4.7 nF (servo, arm) → 0.43 V/ms, 7.4 V in ~17 ms. FLT stays high;
   IMON reading < 10 LSB (6 mV).
2. Read both 0x23 ports and the ADC flags: only that load changed; the INT line fired once and cleared on read.
3. EN low → output falls. With nothing plugged only the 1 µF C_OUT and leakage remain, so it may decay slowly:
   record the time to < 0.5 V (ARM_PWR has the R890 bleed, B5.3).
4. GPIO6 low (expander reset) with three loads on → all three off within 1 ms, EN lines low (100k arrays).

Dependencies: ENC needs TOF3V3_EN; SERVO_EN and ARM_EN need SERVO_BUCK_EN; nothing switches JET_PWR except GPIO25
(high = off: check JET_PWR < 0.1 V and back on when GPIO25 goes low).

**B4.6 eFuse current limits with the electronic load.** For each TPS259470L cell (lidars, steering, fans, AUX,
encoders, arm, Pi USB-C) and each TPS16630, pigtail into the connector in the load table; e-load in CC mode, its
voltage sense at the connector.

| Step | Load | Expected | Source |
|---|---|---|---|
| a | 0.5 × I_LIM min | V_OUT = V_IN − I × R_ON (28 mΩ typ, 45 mΩ max hot); IMON = I × 182 µA/A × R_ILM within ±10 % (G_IMON 165-200); INA238 of the parent rail rises by the same current | tps25947 p.9 R_ON, p.10 G_IMON |
| b | Ramp slowly to I_LIM max + 10 % | the output holds until I_LIM (inside the min/max of the table), then current limits; **FLT goes low after t_ITIMER** (persistent overcurrent, not latched), V_ILM ≈ 0.61 V; the e-load collapses the output, foldback below V_OUT 1.9 V lowers the limit; then thermal shutdown (154 °C) **latches** the L parts off (FLT stays low) | tps25947 p.31-32, p.38 table 7-3, p.10 V_FB, T_SD |
| c | Re-enable | EN low (< V_SD 0.45 V) then high clears the latch and FLT | tps25947 p.38 |
| d | Step 0 → 1.5 × I_LIM typ for 2 ms, then 0 | passes (shorter than t_ITIMER), no FLT | p.31 |
| e | Hard short (e-load short mode or a MOSFET across the pigtail) | scalable fast trip at 2.01 × I_LIM (p.10), response 500 ns for > 3 × I_LIM (p.11), then current limit; FLT high for the short itself (table 7-3: "circuit breaker followed by current limit"), low after t_ITIMER of limiting | p.10 ISC gain, p.11 t_SC, p.38 |
| f | During b and e | the parent rail stays in regulation: +5V ≥ 5.03 V, +3V3_TOF ≥ 3.27 V, SERVO_RAW inside its band; no other FLT bit changes; the Pi does not reset | sim 5-rails |
| g | U87 (Pi USB-C, Pi on its own PSU): 2.0 and 3.0 A for 1 min, then 4.5 A | no trip at 3.0 A; at 4.5 A it limits near 3.76 A, USB_PI_FLT low, then **auto-retries every 110 ms** (TPS259470A) | tps25947 p.11 t_RST; P-6 |
| h | TPS16630 U7 (spare, XT30 J20): 3.0 A, then 4.5 A | no trip at 3.0 A; limit 3.56-4.10 A, SPAREBAT_FLT low, **latched** until SPAREBAT_EN toggles; fast trip 2 × I_OL | sim 5-rails; tps1663 p.8-9 |
| i | TPS16630 U5 (Jetson, J21): 3.0 A, then 4.0 A | limit 3.28-3.78 A, JET_FLT low, **auto-retry** (MODE = GND) | tps1663 p.9 (MODE) |

IMON check points (V at the ADS7128 pin, typical): lidar 0.4 A → 0.322 V; fan 0.3 A → 0.363 V; AUX 1.5 A → 0.450 V;
encoders 0.3 A → 0.363 V; steering 4 A → 0.400 V; arm 3 A → 0.410 V; Pi 2.5 A → 0.403 V; Jetson 2 A → 0.558 V
[calc from the load table].

Record per cell: I_LIM measured, t_ITIMER measured, IMON gain (V/A), FLT timing. Pass: I_LIM inside the table's
min-max, t_ITIMER inside the sim range, IMON gain inside 165-200 µA/A × R_ILM.

**B4.7 INA238 calibration against a reference load.** Write CONFIG (ADCRANGE per the INA table) and SHUNT_CAL; set the
ADC to 1052 µs conversion, 16 averages for calibration. Reference: the e-load's readback and a DMM in series on its
10 A range.

| INA | Load path | Points |
|---|---|---|
| 0x40 battery | e-load on J20 (spare VBAT, SPAREBAT_EN on) | 0.5, 1, 2, 3.5 A; later 14 A in B6.3 |
| 0x41 motor bus | one bridge static at 100 % (OUT1 high, OUT2 low) into the e-load on the PH pigtail pins 6/1 (≤ 2 A: PH contact rating) | 0.5, 1, 2 A; also gives the IPROPI gain |
| 0x43 servo | e-load on three servo headers in parallel (pins 2/3) | 0.5, 2, 5 A |
| 0x47 +5V | e-load on J58 (AUX, ≤ 1.8 A) plus one lidar port | 0.5, 1, 2 A |

Subtract the board's own idle current (reading at 0 A). Pass: error ≤ ±1.2 % of reading + 5 mA before trimming. Trim
SHUNT_CAL by the measured gain (store per board serial). VBUS readings against the DMM at the test point: ±0.1 %
± 5 mV (ina238 p.5).

**B4.8 Lidars (J71-J73).** Before plugging: confirm on the stock C1 cable which end of the XH-5 housing is pin 1
(red = VCC on pin 1, yellow TX 2, green RX 3, black GND 4: rplidar-c1 p.12; the pin-1 end is UNVERIFIED, A-audit).
LIDARn_EN on, nothing plugged: pin 1 = +5V, pin 4 GND. Plug a C1, then:
- Start current: scope LIDARn_5V and LIDARn_FLT while enabling. The C1 needs 800 mA typ to start (rplidar-c1 p.13)
  and the eFuse limits at 0.671-0.822 A after an 8.4 ms (5.1-14.5) blanking time: watch for FLT going low and a
  slow or failed spin-up (design risk, section 9).
- Running: 230-260 mA (p.13) → IMON 0.185-0.209 V; LIDARn_5V ≥ 4.8 V and ≤ 5.2 V (p.12-13: the +5V rail is
  5.03-5.30 V worst case, A-8: record the real value).
- UART at 460800 baud on `/dev/ttyAMA*` (map with `dmesg | grep ttyAMA`): `lidar.connected` with sample_hz 5000,
  10 ± 0.5 Hz scans, ≥ 450 points (V8).
- Back-power: EN off with the C1 plugged and the UART open: LIDARn_5V must stay < 1 V (Pi TX idles high through 1 kΩ,
  R-5; ~2.8 mA, A-audit). If not, firmware drives the TX pin low while the port is off.

**B4.9 ToF ports (J60-J65)** with a ToF carrier (`pcb/rabbit-tof`, its own checks in V13) and a 1:1 GH-6 cable.
- TOF3V3_EN on: +3V3_TOF 3.273-3.339 V, TOF3V3_PG (0x23 P2_6) high (PG at 94-98 % of nominal: tps62826 p.5).
- Only then select a mux channel; deselect (write 0x00) **before** TOF3V3_EN goes low (R-11, V13: a selected channel
  on a dead rail ties SDA/SCL to it through 4.7 kΩ).
- Per port n: TCA6416A (0x20) P0_(n−1) output high (LPn) → 0x29 appears behind channel n−1; LPn low → it disappears.
  INT from the sensor reaches TCA6416A P1_(n−1) and EXP_INT_N.
- Selecting spare channels 6/7: empty, bus idle high (RN40), no hang.
- There is **no current readback for the ToF rail** (INA238 0x4F and ADS7128 0x10 removed 2026-10-11): record the
  +5V change on INA 0x47 as the only proxy.

**B4.10 SK9822 LEDs.** `/dev/spidev0.0` at 1 MHz: start frame (32 zero bits), 8 frames 0xE0|brightness, B, G, R, end
frame. All 8 light in order; TP10/TP11 (LED_DOUT/COUT) carry data after LED8. LED_DI_5V / LED_CI_5V swing to ~5 V
(SK9822 V_IH 3.4 V: sk9822 p.6; AHCT1G125 buffers). During Pi boot they stay dark (100 kΩ pull-downs R480/R481).
Full white: INA 0x47 rises by ≤ 8 × 54 mA ≈ 0.43 A (18 mA per colour version, sk9822 p.3).

**B4.11 Buzzer, RTC, fans, buttons, bumpers.**
- Buzzer: PWM0 on GPIO18 at 4 kHz, 50 % → tone (PKLCS1212E4001 resonant at 4 kHz).
- RTC: DS3231 0x68: set time, power the whole board off for 1 h, time kept (CR1220 fitted, B1.5); BT1 + to GND
  3.0 V; RTC_INT_N (0x23 P2_7) toggles with a 1 Hz alarm.
- Fans: FANn_EN on → FANn_5V ≈ +5V; PWM from PCA9685 ch 11/12 through 2N7002K (inverted in firmware); tach on the
  **MCU** (PA15, PB3, TIM2), not the Pi: speed changes with PWM; IMON 1.21 V/A (fan current ~0.1-0.3 A).
- Button: J15 BTN_ON latches (B2.2); POWER_BTN (GPIO26) low while pressed; GPIO27 lights the button LED through Q3.
- Bumpers: GPIO20/21 and PC13/PC14 both see a press (4.7 kΩ to +3V3_PI, 1 kΩ to the MCU).

**B4.12 Pi on the board's USB-C (J53) and U87.** Before the Pi: a USB-C plug breakout with 5.1 kΩ Rd on CC: CC
reads 5.17 V × 5.1/15.1 = 1.75 V (10 kΩ Rp = 3.0 A advertisement, `design.py` R531/R532) [calc]; VBUS = +5V. Then
the Pi on J53 through a short (≤ 0.3 m, 3 A) cable, its own PSU removed. Run `stress-ng --cpu 4` plus the USB loads
(Wi-Fi adapter, storage) for 30 min: `vcgencmd get_throttled` = 0x0, Pi 5 V at its GPIO pin 2 ≥ 4.9 V; U87 IMON
(0.161 V/A) and INA 0x47 agree on the Pi's current within 5 %. `sudo poweroff`: the whole board turns off ~1.6 s after
the Pi halts (GPIO17, B2.11).

## 5. Servo rail and xArm

Supply 14.8 V, limit 15 A. Pi running.

**B5.1 Servo buck.** SERVO_BUCK_EN (0x22 P1_4) on, SERVO_7V4 low: SERVO_RAW 5.940-6.060 V; SERVO_BUCK_PG (0x23 P1_4)
high 1.2-3.75 ms after regulation (lm61495 p.8 t_RESET_ACT; RESET threshold 94 % of FB, p.7). SERVO_7V4 high:
7.325-7.473 V (sim 5-rails). Switch 6.0 ↔ 7.4 V with a 1 A load: no overshoot above 8.506 V (the U83/U88 OVLO
minimum) and no FLT.

**B5.2 Steering eFuse U83.** SERVO_EN on: SERVO_PWR = SERVO_RAW − I × R_ON. Run B4.6 a-f on three servo headers in
parallel: I_LIM 5.400-6.600 A, t_ITIMER 11.3-31.9 ms, IMON 0.0999 V/A (0x11 AIN3). Then the real steering servo:
current at rest and during a full-lock sweep from INA 0x43.

**B5.3 Arm eFuse U88.** Before the arm: **M25** — on the stock xArm cable, beep from the servo's "−" pin to each cavity
of the board-end PH-3 housing: it must land on board pin 1 (GND), "+" on pin 2, "S" on pin 3. If not, do not plug.
ARM_EN (0x22 P0_6) on: ARM_PWR = SERVO_RAW; ARM_5V 4.9-5.1 V (TLV76050); ARM_SIG idles at ~5 V (R888 to ARM_5V).
ARM_EN off: ARM_PWR < 1 V within ~2.5 s (R890 4.7k × ~264 µF, τ 1.2 s; A-5). Load test on **both** PH-3 ports in
parallel (PH contacts are 2 A each): I_LIM 3.960-4.840 A, t_ITIMER 11.3-31.9 ms, IMON 0.1365 V/A (0x17 AIN5),
ARM_FLT on 0x17 AIN6.

**B5.4 Steering stays in regulation while the arm overloads (S-2).** Two e-loads: steering 2 A CC on servo headers,
arm on J80+J81 in transient mode. SERVO_RAW at 7.4 V. Scope SERVO_PWR (TP22), SERVO_RAW (TP23), ARM_PWR.

| Arm step | Expected | Source |
|---|---|---|
| 0 → 4 A (below I_LIM min) | steady, SERVO_PWR ≥ 7.3 V | |
| 0 → 6 A for 200 ms | passes for t_ITIMER (11.3-31.9 ms), then limited at 3.96-4.84 A, ARM_FLT low; buck total ≤ 8 A < 9.8 A min limit, so SERVO_PWR stays ≥ 6.66 V (90 % of 7.4 V) | tps25947 p.31-32; lm61495 p.7 |
| 0 → 8.5 A for 200 ms (above I_LIM max 4.84 A, below 2 × I_LIM typ 8.9 A) | **the case that failed in S-2**: arm + steering ≈ 10.5 A ≥ the buck's 9.8 A minimum limit, for up to t_ITIMER. Pass criterion of the sim: SERVO_PWR ≥ 6.66 V; sim S-2 with the old TPS25982 model gave 7.26 V typical and 4.82 V for 93 ms at the worst corners. The TPS259470L with C884 22 nF was **not simulated** (A-2): this measurement decides C884 (round 1 recommended 4.7 nF → 2.2 ms) | S-2, A-2; lm61495 p.7 |
| 0 → 15 A (above 3 × I_LIM max = 14.5 A) | fast trip within 500 ns, then current limit; SERVO_PWR dips < 1 ms | tps25947 p.10-11 |

Repeat the 8.5 A case at 6.0 V. Record SERVO_PWR minimum and the time below 90 %.

**B5.5 OVLO 8.63 V (shared by U83 and U88).** Servo buck **off**, board at 14.8 V (VBUS must stay above the injected
voltage, or the LM61495 high-side body diode back-feeds VBUS). A second supply, 100 mA limit, into TP23 (SERVO_RAW);
SERVO_EN and ARM_EN on; ramp 6 → 9.0 V. Expected: SERVO_PWR and ARM_PWR cut at 8.506-8.793 V within 1.2 µs, back on
below ~7.84 V (sim 5-rails; tps25947 p.11 t_OVLO). **FLT does not assert on OVLO** (tps25947 p.38 table 7-3): the
firmware has to see it from INA 0x43 VBUS > 8.5 V with IMON at zero.

**B5.6 xArm bus (PB9, USART3 single-wire half-duplex, 115200 8N1).** Logic analyser on PB9 (ARM_UART_M) and ARM_SIG,
scope on ARM_SIG. With no servo: MCU sends `55 55 01 03 1C DF` (POS_READ, ID 1, `xarm_bus.md`): bus low ≤ 0.12 V
(0.05 V solved, A-1), high 4.99 V, rise 10-90 % < 1.7 µs (0.89 µs sim 3-xarm; τ 4.7 kΩ × ~150 pF = 0.7 µs, A-1).
Plug one arm servo (torque is off at power-up, `xarm_bus.md` LOAD_OR_UNLOAD): reply frame decoded; PB9 low ≤ 0.63 V
(A-1, VIL 0.99 V), high 3.3 V; the firmware's echo compare reports no mismatch over 1000 frames. Then the whole arm:
ID_READ per servo, SERVO_VIN_READ within ±0.2 V of ARM_PWR. With ARM_EN off, USART3 RX and TX are disabled (PB9 reads
~0.5 V then: A-4, M-6).

## 6. Thermal and current

Thermal camera at each high-current path. Mark reference spots with black tape (ε ≈ 0.95) on shiny parts (fuses,
shunts, connectors). Still air, 20-25 °C ambient, board on its standoffs in the chassis position (top up); bottom
parts (DRV8243, eFuses) need a second camera position from below. Soak 10 min per point unless the step limits time.
Pass: every part ≤ 85 °C case at 25 °C ambient, copper ΔT ≤ 20 K at the narrowest neck (the IPC-2221 budget
`gen/power_check.py` uses), no FLT/nFAULT/PG change that the step does not expect.

**B6.1 `gen/power_check.py` comparison.** Run it on the final routed board before ordering and copy its table here.
Each net in its CURRENT table (BAT chain 14 A, 10 A nets, ML/MR_OUT 4.1 A, ARM_PWR 5.7 A, SW4/+5V_BUCK 8 A) must show
capacity ≥ the test current. The run of 2026-10-11 on the unfinished routing still flags 16 nets "UNDERSIZED (before
pours)": BAT_F, VBUS_RAW, SW_MID, MOT_F, MOT_BUS, ML/MR_OUT1/2, SERVO_BUCK, SERVO_RAW, SERVO_PWR, STEER_IN, SW6,
+5V_BUCK, ARM_PWR (0.10 mm stubs, pours not filled). In B6.2-B6.3 aim the camera at the necks it reports.

**B6.2 Motors stalled at ITRIP.** Owner's OK; wheels clamped. 14.8 V and 16.8 V.

| Case | Duration | Expected | Hot spots |
|---|---|---|---|
| Both motors stalled, ITRIP 2.41 A (default) | 60 s | chop current 2.17-2.66 A on IPROPI; DRV8243 conduction ≈ 2.41² × 84 mΩ ≈ 0.5 W → +17 K at 34.2 K/W (DC, 2 oz board) to +24 K at 48.4 K/W (JEDEC) [calc]; nFAULT high | U11/U12 (bottom), J41/J42 PH contacts (2 A each), R3, Q30, F2 |
| Both stalled, ITRIP 4.05 A (PB11 low) | **≤ 10 s** | chop 3.64-4.46 A; 4.8 A for 10 s / 3.5 A DC is the DRV8243 VQFN capability at 85 °C ambient (drv8243 p.18 table 6-1); DRV8243 ≈ 1.4 W → +24 K after 10 s at 17.5 K/W; PH contacts carry 2× their rating (F-11): watch J41/J42 | same |

**B6.3 Battery path at 14 A (M28).** Supply ≥ 15 A (or the real battery for B6.4). Build 14 A on INA 0x40 from: Jetson
XT30 e-load 3.0 A (below its 3.28 A minimum limit), spare XT30 3.5 A, servo rail 6 A + arm 4 A at 7.4 V (≈ 5.6 A from
VBUS at 90 % [calc]), +5V 3-4 A (Pi + lidars + AUX ≈ 1.4 A from VBUS), plus motors at 2.41 A ITRIP if needed. Hold
10 min. Expected dissipation [calc]:

| Part | At its test current | Note |
|---|---|---|
| F1 NANO2 15 A | 3.7 mΩ cold × 14² ≈ 0.73 W | 25 % standard derating = 11.25 A continuous (littelfuse-0451 p.2-3): **14 A is above it** (P-10) |
| J1 XT60 | contact resistance only | |
| Q1/Q2 BSC010N04LS | 14² × 1.5 mΩ (hot) ≈ 0.29 W each | `gen/calc.py` |
| R1 2 mΩ 3 W | 0.39 W | |
| F2/F4 10 A, F3 8 A | ~0.5 W at 10 A [mem: NANO2 10 A ~5 mΩ] | |
| U6/L6 servo buck at 10 A, 7.4 V | ~6 W loss at 88 % [calc] | TMP117 0x49 reads the area |
| U83 at 6 A, U88 at 4.45 A | 6² × 28-45 mΩ ≈ 1.0-1.6 W; 4.45² × 45 mΩ ≈ 0.9 W | tps25947 p.9 R_ON |
| U5/U7 TPS16630 at 3.5 A | 3.5² × 31 mΩ ≈ 0.38 W → +12 K | `gen/calc.py` |
| R2/R6 5 mΩ 1 W at 10 A | 0.5 W | |
| NT1 star, In4 VBUS plane, GND_MOT island | ΔT ≤ 20 K | `gen/routing.py` |

**B6.4 Real battery (M28).** On the robot, owner's OK. V-mount pack (14 A continuous by its label): start both motors
and move the arm at the same time from rest, 10 times. Record INA 0x40 peak current and the VBUS minimum. Pass: the
BMS never cuts out; VBUS stays above the LM5069 UVLO-off 10.58 V and the latch hold (~9.6 V); firmware's power budget
throttles the arm first, then the motors to ITRIP 2.4 A, from ~12 A on INA 0x40 (M28 plan).

## 7. Observability (AGENTS.md: every test must be answerable from Forge alone)

Nothing below exists yet: the rev C power node, the motor firmware and its Pi bridge are to be written. The names
follow `docs/reports/2026-10-03-observability.md` (event `<area>.<what>`, `reason`, severity, numbers in `values` with
the unit in the key, text in `labels`, `boot_id` and `instance_id` on every event, `every_s` on anything that can
repeat). Bring-up adds one label to every event of a test run: `test_id` (e.g. `B4.6-LIDAR1-b`) and `board_serial`,
set in the node's log context by the bring-up script, plus a `bringup.step` event (`test_id`, `result`, measured
value) per step, so each test's window can be cut out by SQL.

| Record | Kind | Fields | Tests |
|---|---|---|---|
| `node.start` of the power and motor nodes | event (existing) | snapshot + `board_rev` "C", `board_serial`, MCU firmware hash, INA/ADC config | all |
| `power.calibrated` | event (name exists in `node/ina.py`) | per INA238: `addr`, `shunt_ohms`, `adcrange`, `current_lsb_a`, `shunt_cal`, `gain_correction`; per ADS7128 channel: `r_ilm_ohms`, `imon_v_per_a` | B4.7, B4.6 |
| `rabbit.power.board` (new subject → Forge table) | periodic state, 10 Hz | 4 × INA238 `bus_v`, `current_a`, `power_w`, `die_c`; 13 ADS7128 currents `<load>_a`; EN bitmask, FLT/PG bitmask, ADC_AVDD check; `vbus_min_v` since last sample | B2-B6 |
| `power.load_switched` | event | `load`, `on`, `reason` (`bringup`, `pi request`, `fault recovery`, `shutdown`), `source`, `rail_v`, `current_a` before/after, `inrush_peak_a` | B4.5, B4.6, B5 |
| `power.load_fault` | event, warning/error | `load`, `kind` (`flt`, `pg_lost`, `imon_at_limit`, `ovlo_suspected`, `retrying`), `current_a`, `ilim_a`, `rail_v`, `latched`, `duration_ms` | B4.6, B4.8, B5.2-B5.5 |
| `power.load_fault_cleared` | event | `load`, `how` (EN toggle, auto-retry), `off_s` | B4.6 c |
| `power.rail_out_of_range` | event, `every_s` 5 | `rail`, `value_v`, `min_v`, `max_v` | B2.8, B2.9, B4.12, B5.1, B5.5 |
| `power.motor_bus_switched` | event | `on`, `reason`, `vbus_v`, `mot_bus_v`, `ramp_ms`, `pg` | B3.7 |
| `power.shutdown` | event | `reason` (button, low battery, request), `vbus_v`, GPIO17 asserted | B2.11, B4.12 |
| `power.battery_low` / `power.state_changed` | events (exist in `lib/power_supervisor.py`) | `battery_v` from INA 0x40 | B2.8, B6.4 |
| `motors.mcu_reset` | event | RCC_CSR flags (POR, BOR, PIN, IWDG, SW), firmware hash, uptime | B3.3, B4.2 |
| `motors.drvoff_changed` | event | `level`, `cause` (`estop`, `alive_lost`, `firmware`), `alive_hz`, from PA4 | B3.5, B3.6 |
| `motors.estop_changed` | event | `ch1`, `ch2`, `mismatch_ms` | B3.6 |
| `motors.driver_fault` | event | `side`, `nfault`, `latched`, `ipropi_a`, `ntc_c`, `vmot_v` | B3.7.7, B6.2 |
| `motors.itrip_changed` | event | `level_a` 2.41/4.05, `reason` | B3.7.6, B6.2 |
| `motors.brake` | event, `every_s` 1 | `on_ms`, `mot_bus_peak_v` | B3.7.8 |
| `rabbit.motors.state` (new) | periodic, 50 Hz | duty, `ipropi_a` L/R, encoder counts, `vmot_v`, `ntc_c` L/R, TMP117 0x48/0x49, DRVOFF, ESTOP bits | B3.7, B6.2 |
| `arm.bus_error` | event, `every_s` 5 | `kind` (echo mismatch, timeout, checksum), `servo_id` | B5.6 |
| `tof.mux_refused` | event | `channel`, `reason` "rail off" | B4.9 |
| `lidar.connected` | event (exists, V8) | `sample_hz`, `port` | B4.8 |

Check per test with SQL over Forge, for example: every `power.load_fault` row of `test_id = 'B4.6-LIDAR1-b'` has
`values['current_a']` within 5 % of the e-load setpoint and `labels['kind'] = 'imon_at_limit'` then `'flt'`. A step is
not passed until its records are there. The simulator does not model the rev C board yet: add a stub of
`rabbit.power.board` and the fault events to `rabbit-sim` so the pipeline is tested before the boards arrive.

## 8. Checklist (one page)

| ID | Check | Pass | Done |
|---|---|---|---|
| B1.1 | JLC report, X-ray, DNP = R1106 R1206 Q1102 Q1202 R1151 R423 R424; U43 fitted | matches | ☐ |
| B1.2 | Microscope: QFN/LGA/LQFP joints, D89, PH/GH tabs, GH mates with genuine JST | no defects | ☐ |
| B1.3 | Polarity: XT60/XT30 pad 1 = GND, polymers, TVS/Schottky bands, LEDs, J3 key, CR1220 | all correct | ☐ |
| B1.4 | Rail to GND (VBUS 12.4k, MOT_BUS 32.6k, +5V 15.1k, 3V3_MCU 10.0k, 3V3_TOF 26.9k, SERVO_RAW 45.0k, ARM_PWR 4.7k, rest open); rail pairs > 100 Ω; J3 pins 2/4 open | in range | ☐ |
| B1.5 | CR1220 fitted; button LED has its own resistor | yes | ☐ |
| B2.1 | Off-state at 12 V, no press | < 10 µA, VBUS 0 V | ☐ |
| B2.2-4 | Press: latch; idle 10-25 mA; +5V 5.03-5.30, 3V3_MCU 3.27-3.33, REF 2.4988-2.5013; JET_PWR and J53 VBUS on; MOT_BUS off | in range | ☐ |
| B2.7 | Power-up: VBUS ~1.2 V/ms, MOT_BUS < 0.5 V, DRVOFF high | yes | ☐ |
| B2.8 | Brown-out: latch drops 8.4-10.0 V, stays off on recovery | yes | ☐ |
| B2.9 | OV: JET off 19.2 V, VBUS_RAW off 19.7 V (max 20.0 V applied) | in range | ☐ |
| B2.10 | Hot-plug ×10: no turn-on | VBUS_RAW < 1 V | ☐ |
| B2.11 | GPIO17 off | < 1.62 s | ☐ |
| B2.12 | Reverse −5 V (all), −16.8 V (first board) | < 0.15 / < 0.35 mA, latch still works | ☐ |
| B3.1-2 | SWD, DEV_ID 0x469; HSE 8 MHz ± 50 ppm; 170 MHz | OK | ☐ |
| B3.3 | USB-only power, VBUS_DET 3.0 V, CDC; source switch without MCU reset | OK | ☐ |
| B3.4 | TMP117 ×2, IMU WHO_AM_I 0x47, MMC5983MA, NTCs 1.65 V | OK | ☐ |
| B3.5 | DRVOFF: 10 kHz release 1.1-1.2 ms; stop → 6-23 ms; E-stop → 208-278 ms; floor 100-300 Hz recorded | in range | ☐ |
| B3.6 | E-stop both channels, mismatch reported | OK | ☐ |
| B3.7 | M-2 cable check; ENC_3V3 3.3 V; 1320 counts/rev; motor bus ramp 67-150 ms; wake handshake; IPROPI 0.489 V/A; ITRIP 2.17-2.66 / 3.64-4.46 A; fault latch; brake 17.67/17.18 V | in range | ☐ |
| B4.1-2 | config.txt; ribbon not reversed; no NRST pulse at Pi boot | OK | ☐ |
| B4.3 | I2C1 = 0x11 0x17 0x20 0x22 0x23 0x40 0x41 0x43 0x47 0x60 0x68 0x70; rise < 1 µs at 100 kHz | exact | ☐ |
| B4.4 | I2C6 = 0x77 only; rise ≤ 300 ns at 400 kHz or slow the bus | OK | ☐ |
| B4.5 | Every EN bit switches only its load; FLT/INT/ADC agree; GPIO6 resets all | OK | ☐ |
| B4.6 | Each eFuse: I_LIM in table range, ITIMER in sim range, IMON gain 165-200 µA/A × R_ILM, latch/retry behaviour; parent rail holds | per cell | ☐ |
| B4.7 | INA238 ×4 within ±1.2 % + 5 mA; SHUNT_CAL trimmed and stored | OK | ☐ |
| B4.8 | Lidar pin 1; start without FLT; 230-260 mA; 4.8-5.2 V; scans; no back-power | OK | ☐ |
| B4.9 | ToF: 3V3_TOF 3.27-3.34, PG; 0x29 per port; LPn/INT; select only when powered | OK | ☐ |
| B4.10-11 | LEDs, buzzer, RTC holds time, fans + tach, button, bumpers | OK | ☐ |
| B4.12 | Pi on J53: throttled 0x0, ≥ 4.9 V, U87 IMON = INA 0x47 ± 5 %; poweroff kills the board | OK | ☐ |
| B5.1 | Servo 5.94-6.06 / 7.33-7.47 V, PG, no overshoot past 8.5 V | OK | ☐ |
| B5.2-3 | U83 5.40-6.60 A; M25 cable check; U88 3.96-4.84 A; ARM_PWR bleed | OK | ☐ |
| B5.4 | Arm 6 A / 8.5 A / 15 A steps with 2 A steering: SERVO_PWR ≥ 6.66 V (record min and time) | measured | ☐ |
| B5.5 | OVLO 8.51-8.79 V both branches; firmware sees it without FLT | OK | ☐ |
| B5.6 | xArm bus levels, echo, 1000 frames clean, IDs 1-6 | OK | ☐ |
| B6.1 | power_check.py clean on the routed board | no UNDERSIZED | ☐ |
| B6.2 | Stall 2.41 A 60 s, 4.05 A ≤ 10 s: ≤ 85 °C, no nFAULT | OK | ☐ |
| B6.3 | 14 A for 10 min: ≤ 85 °C parts, ≤ 20 K copper, F1 recorded | OK | ☐ |
| B6.4 | Real battery: motors + arm start ×10, no BMS cut | OK | ☐ |
| B7 | Every step's Forge records present (section 7 table) | SQL checks pass | ☐ |

## 9. Design risks noticed while writing this plan (not fixed)

1. **Arm eFuse blanking time.** U88 is now a TPS259470L with C884 22 nF: between I_LIM and 2 × I_LIM (up to 8.9-9.7 A)
   it passes current for 11.3-31.9 ms before limiting (tps25947 p.31-32). Arm 8.5 A + steering 2-6 A exceeds the
   servo buck's 9.8 A minimum limit, the S-2 failure mode. Round 1 asked for 4.7 nF; the `design.py` comment cites
   "sim S-2" for the new part, but S-2 simulated the TPS25982, not this one (A-2). B5.4 measures it.
2. **Lidar start current vs eFuse.** RPLIDAR C1 start current is 800 mA typical (rplidar-c1 p.13); the lidar eFuses
   limit at 0.671-0.822 A after 5-15 ms. The C1 may start slowly, assert FLT, or cycle. B4.8 measures it.
3. **F1 at 14 A.** NANO2 15 A has a 25 % standard derating (11.25 A continuous, littelfuse-0451 p.3) and 3.7 mΩ
   (p.2); the 14 A battery budget (M28) is above it (P-10 still open).
4. **ToF rail has no per-port protection and no current readback.** A shorted ToF cable draws up to the TPS62826 limit
   3.7-5.0 A (tps62826 p.6) through a GH contact rated 1 A (jst-gh p.1) until hiccup, and takes down the encoder
   supply (U78 is fed from +3V3_TOF), so odometry drops with the ToF rail. Forge cannot see ToF current at all
   (INA238 0x4F removed), against the observability rule.
5. **Encoders depend on the ToF buck.** ENC_3V3 needs TOF3V3_EN; turning the ToF rail off for power saving or a fault
   also blinds the motor controller.
6. **OVLO is silent on FLT.** A servo-rail overvoltage cut does not assert FLT or ARM_FLT (tps25947 p.38): only the
   INA 0x43 voltage shows it. Firmware must infer it.
7. **PH contacts.** J80/J81 carry the arm at a 4.45 A limit (and up to ~9 A for the blanking time) over JST PH contacts
   rated 2 A each (2 ports in parallel = 4 A); J41/J42 at ITRIP 4.05 A (F-11, known).
8. **Jetson output is on by default** (TPS16630 SHDN internal pull-up; GPIO25 must go high to turn it off), unlike
   every other load "off until the Pi enables it". By design from rev B; worth stating in the spec.
9. **Motor bus at a 12 V battery.** LM5069 UVLO rising is 11.58 V typ, 12.22 V max: a 4S pack near empty (12 V) may
   never enable the motor bus on some boards.
10. **No DFU entry without the Pi.** BOOT0 is driven only by Pi GPIO0 (10 kΩ pull-down); a laptop-only recovery over
   J50 needs a firmware jump to the bootloader or SWD.
11. **Reverse battery stresses Q4.** With BAT_F negative, Q5's body diode clamps LM_EN at about −0.6 V, so current
   flows GND → Q5 body diode → R45 47k → Q4 collector-base (forward) → R43 100k → BAT_F. R43's drop reverse-biases
   Q4's emitter-base junction by ~7 V at −12 V and ~10 V at −16.8 V [calc], past the MMBT3906's 5 V V_EBO: it
   avalanches at ~0.1-0.2 mA. Probably not destructive, but outside the rating and it can lower Q4's gain (the
   button latch). The LM74800 itself is fine (A to −65 V, EN down to V(A): lm74800 p.4).
12. **I2C6 at 400 kHz is marginal**: 317 ns Pi-side rise in sim 4-i2c against 300 ns for Fast-mode.
13. **Routing not yet current-safe**: `power_check.py` (2026-10-11) flags 16 power nets with 0.10 mm segments; must be
   clean before the order (B6.1).
14. **Stale documents that would mislead bring-up firmware:** `design.py` comments still mention +5V17, INA238
   0x4C/0x4D/0x4F, "+5V_LIDAR behind INA238 #8", "8 ToF + 2 encoder eFuses", "VBUS sense for the MCU (PC3)" and
   "Pi USB-C (3.3 A, 1k)"; `i2c_address_map.json` describes 0x11/0x17 channels from before the simplification;
   `data/pcb-revc/sim/results.md` predates the TPS259470L arm eFuse, the ToF eFuse removal and the 12-device I2C1;
   `stm32_pinmap.md` gives 5.1 kΩ nFAULT pull-ups where `design.py` has 10 kΩ (R1103/R1203); spec §3 still lists
   TPS2553 and 9 INA238.

## 10. Bench equipment (shopping list)

What the owner already has is unknown: fill in the last column before ordering. Quality makers per the hardware rule
(AGENTS.md).

| Item | Why (steps) | Suggested model | Have? |
|---|---|---|---|
| Programmable DC supply, ≥ 20 V / 20 A, fast CC, OVP, logging, two channels to parallel or to inject SERVO_RAW | B2, B5.5, B6.3 | Keysight E36233A (2 × 30 V / 20 A, 400 W) or R&S NGP802 | ? |
| Low-current precision supply (µA readback, battery simulation) | B2.1 off-state, B2.12 reverse | R&S NGM202 (2 × 20 V / 6 A) | ? |
| Electronic DC load ≥ 350 W, 60 A, CC/CR/short, transient mode (µs steps), remote sense | B4.6, B4.7, B5, B6.3 | Keysight EL34143A; a second load (or Keysight EL34243A dual) for B5.4 steering + arm | ? |
| Thermal camera for PCBs (close focus, ≥ 320 × 240) | B2.13, B6 | FLIR ETS320 (bench PCB system) or FLIR E54 with close-up lens | ? |
| Tag-Connect cable + clip + SWD probe | B3.1 | TC2030-CTX-NL-STDC14 + TC2030-CLIP-3PACK + ST STLINK-V3SET (or TC2030-CTX-NL + ARM20-CTX for a SEGGER J-Link PLUS) | ? |
| Logic analyser with analog channels and I2C/SPI/UART decoders | B3.5, B4.3-4.10, B5.6 | Saleae Logic Pro 8 | ? |
| Oscilloscope, 4 ch, ≥ 200 MHz, 10-12 bit | B2.7-B2.11, B3.5, B4.6, B5.4 | R&S RTB2004 or Keysight DSOX3024G | ? |
| DC current probe, ≥ 30 A | B4.6 e, B5.4, B3.7 | matched to the scope (R&S RT-ZC20B or Keysight N2783B) | ? |
| Handheld and bench DMM (µA, 10 A, 4-wire) | B1.4, B2, B4.7 | Fluke 87V; Keysight 34465A | ? |
| USB isolator (scope/laptop ground during motor tests) | B3.3, B3.7 | Intona 7055-C | ? |
| Pigtails and breakouts | throughout | XT60/XT30 12 AWG leads; JST PH-6, PH-3, XH-5, XH-4, XH-2, GH-6, KK-4 crimped leads; USB-C plug breakout with a 5.1 kΩ Rd option; three 1×3 servo leads; 3 A ≤ 0.3 m USB-C cable | ? |
| Misc | | CR1220 cell; Raspberry Pi 27 W USB-C PSU; ESD mat and strap; black tape for emissivity | ? |
