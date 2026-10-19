# Body board rev C: netlist, placement, routing

Status 2026-10-11: netlist and two-sided placement done (floorplan of 2026-10-11 in `gen/placement.json`); routing on 8 layers in progress (autorouter plateau 27-29 unrouted connections, the rest is being finished by hand).
- The approved spec is `docs/reports/2026-10-10-body-pcb-rev-c.md` (Russian). Its §11a decisions and the "10-11 October" section override older data.
- The per-IC source tables are `data/pcb-revc/ics/*.json` (gitignored); reviews and the applied fixes are in `data/pcb-revc/review/`.
- The generator `gen/design.py` is the single source of truth for parts, nets and default positions; `gen/placement.json` (263 overrides, applied at the end of `design.py`) moves parts to the 2026-10-11 floorplan.
- History: `docs/log/2026-10-10-body-pcb-rev-c.md`.

```
python3 gen/footprints.py                       # custom footprints -> lib/rabbit_body.pretty
python3 gen/outline_revc.py                     # outline.json + the corner ToF poses in tof.json (from kit_outline.json)
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
$PY gen/build_board.py --no-route               # placement only (without --no-route: + planes and pours, gen/routing.py)
gen/make.sh                                     # full run: build, fill, fastroute/Freerouting, cleanup, DRC (SES=... reuses a route)
python3 gen/check_netlist.py [--board]          # netlist checks (--board needs $PY)
$PY gen/drc_summary.py                          # kicad-cli DRC -> fab/drc.json
$PY gen/power_check.py                          # copper width and vias of the high-current nets after routing
python3 gen/stock.py [boards]                   # JLC stock of every BOM line (default 2 boards) -> fab/stock.json + csv
PLOTPY=<python with matplotlib> gen/render.sh   # renders/top, bottom (seen from below), iso, *_labelled
```

## Board

- Outline (`gen/outline_revc.py` -> `gen/outline.json`): X -70..70, Y -158..156.2 (board frame: origin at the deck centre, +Y = robot front, top view). The kit plate grown on 2026-10-11 (owner): the tail goes to Y -158 and the board is ±70 wide from the tail to Y 30 (9.8 mm to the rear wheels' inner faces); the front keeps the kit's waist for the steering sweep; the nose goes to Y 156.2 so the ZED 2i (43.1 mm deep, front face on the edge) clears the front deck-3 standoffs by 2 mm. The four corner chamfers are turned square to the ToF brackets: front ±50°, rear ±135°, rear chamfers 30 mm long.
- Holes: 4 × M4 deck standoffs (±38.09, -121.89 / 107.64), 2 × M3 (±55.26, 84.95), 2 × M3 for the ZED 2i on 5 mm standoffs (±18, 134.9; holes 36 mm apart), 6 ToF bracket footprints `ToF_Bracket_M2.5` (two M2.5 holes, flange and screw-head keep-outs), the ZED USB cable cutout 11.1 × 18 mm.
- Stack (`gen/routing.py`, `gen/autoroute.py`): 8 layers. Signals on F.Cu, In2.Cu, In3.Cu and B.Cu; In1 and In6 are GND planes with a GND_MOT island under the motor block (joins GND only at the star tie NT1 next to the battery connector); In4 is one VBUS plane over the whole board; In5 is a split power plane: MOT_BUS over the drive, SERVO_RAW and SERVO_PWR over the servo/arm block, +3V3_MCU under the MCU, +5V everywhere else. The router treats In1/In4/In5/In6 as power layers (vias only). The battery chain (3 mm) and the 5-10 A nets (2 mm) run on the outer layers only; 2 oz outer copper is assumed. Local pours that would trap other nets' pads are filled after routing.
- 667 footprints: 411 on the top, 256 on the bottom. 613 assembled placements (361 top, 252 bottom; 589 SMT, 24 THT), 46 mechanical or copper-only, 1 module (the Pi), 7 DNP. 159 BOM lines (unique LCSC numbers), 47 ICs, 433 nets.
- DNP: the PH/EN MODE 0R R1106/R1206; the second ITRIP line Q1102/Q1202 and R1151; the IMU CLKIN link R423/R424. Everything else, including the MMC5983MA and the bottom THT XT30s, is assembled by JLC (owner, 2026-10-10).
- Stock (`gen/stock.py`, 2026-10-11, 2 boards): all 159 lines in JLC stock with at least 3× the need, so one JLC order with no Global Sourcing. Thinnest: Würth 2×20 C7433390 (89), PCA9685 (157), RT0603 549 Ω 0.1 % (224), STM32G474 (248), TPS259470A (331), EEHZK1E471P (404), DRV8243 (408).

## Blocks and placement (after `placement.json`)

| Where | Top | Bottom |
|---|---|---|
| Rear right, X 34..58, Y -112..-34 | Power entry (rev B): XT60 J1, F1 15 A, LM74800 latch, 2 mΩ battery shunt + INA238 0x40, VBUS bulk; motor-bus F2, 5 mΩ shunt shared by the LM5069 and INA238 0x41, BSC010N04LS, LM5069-1 | — |
| Rear centre, Y -120..-77 | 2 × 220 µF MOT_BUS bulk at the drivers; brake chopper (rev B); D10 TVS; D31 B540C freewheel diode | DRV8243H L/R at (-20.5 / 25.5, -83) with straps, ITRIP ladder, IPROPI and NTC; motor PH-6 J41/J42 at (∓7, -84) between the motors' rear ends with an empty ≥ 8 mm band for the OUT pours; TMP117 0x48; ToF ports J63-J65 (Y -110..-112) |
| Tail, Y -158..-120 | STM32G474 at (-13, -135) with crystal, LDO, TC2030, the E-stop NAND/ALIVE logic, IPROPI clamps; USB-C J50 + TPS2121 + USBLC6 at the rear edge right of the rear ToF bracket; CAN (TCAN1044AV, GH-4 J51, split termination) at the rear-left edge; rear bumper J14 | — |
| Left strip, X -70..-40 | E-stop XH-4, fan 2, spare 5 V XH-2, Pi power USB-C J53, fan 1 | Jetson and spare-VBAT TPS16630 (U5, U7), TVS; XT30 J21/J20 at X -65, Y -35/-48 (bottom, mating downward) |
| Y -57..-33 | IMU at (-14, -46) | — |
| Middle, Y -30..25 | Raspberry Pi 4 on 4 × M2.5 at (13, -4); no top parts under it | eFuse row under the Pi at Y -2 (fans ×2, spare 5 V, Pi USB-C) and the encoder eFuse U78 (28, 3); PCAL6524 0x22/0x23 (U37/U38) with their arrays; TCA9548A (0, 14) and TCA6416A (12, 14); ADS7128 U35 (43, 8) / U36 (43, -8) + REF3425; OVLO dividers |
| Front, Y 26..69 | Pi 2×20 header at Y 30.2 next to the Pi's own header; 5.17 V buck + INA238 0x47 and the servo buck 6.0/7.4 V + INA238 0x43; F3/F4; VBUS polymer; TMP117 0x49 between the bucks | TPS62826 3.3 V ToF rail |
| Front, Y 69..156 | Lidar XH-5 ×3, RTC + CR1220, buzzer, button, xArm block (TPS259470L U88, TLV76050, BSS138 shifter, 220 µF, PH-3 ×2), steering eFuse U83 + B540C + 2 × 470 µF, PCA9685 0x60, 8 servo headers, front bumper, MMC5983MA, ZED 2i standoffs, SK9822 ×8 along the front edge with the AHCT buffers | Lidar eFuses ×3, lidar UART resistors and ESD; ToF ports J60-J62 |

Layer rules:
- Tall parts only on the top: inductors, polymers, THT headers.
- `check_netlist.py` checks bottom heights: at most 8 mm over the motors (Y -60..-130), at most 10 mm elsewhere; nothing on the top under the Pi.
- Floorplan rules (`data/pcb-revc/review/floorplan-2026-10-11.md`): ≥ 2 mm free ring around 0.5 mm QFNs, 3 mm around the LQFP-64, no logic-GND parts over GND_MOT.

Renders: `renders/top_labelled.png`, `renders/bottom_labelled.png` (seen from below, so mirrored), `renders/top.png`, `renders/bottom.png`, `renders/iso.png`; re-render after routing.

## What changed against the first rev C netlist (10-11 October)

- Vertical connectors only (owner): USB-C J50/J53 GCT USB4115-03-C, CAN GH-4 JST BM04B-GHS-TBT, ToF GH-6 HCTL HC-GH-6PLT (C3011957, GH-compatible on the JST BM06B land; genuine JST had 1 in JLC stock), XT30 AMASS XT30UPB-F on the bottom, lidar JST B5B-XH-A.
- ToF: 6 ports, one per printed bracket under deck 2 (front, front ±50°, rear, rear ±135°; `gen/tof.json`, field of view checked in `cad/robot/tof_fov.py`), all on +3V3_TOF (the TPS62826 EN is the group switch); the TCA9548A is alone on the Pi's I2C6 (GPIO22/23, J3 pins 15/16, 2.2 k pull-ups); mux channels 6/7 and TCA6416A P06/P07/P16/P17 are tied off.
- Simplified (owner, 2026-10-11): no per-port ToF eFuses and no ADS7128 0x10; one eFuse U78 for both encoders; INA238 only on battery 0x40, motor bus 0x41, servo 0x43, 5 V total 0x47. 763 parts before, 667 now.
- xArm 1S bus on the board: TPS259470L U88 (active current limit, R_ILM 750 Ω = 4.45 A) from SERVO_RAW, OVLO on the steering eFuse's divider (61.9k/10k = 8.63 V); STM32 PB9 USART3_TX AF7 single-wire half-duplex -> BSS138 -> 5 V bus (390 Ω 1206, TPD1E10B09), 2 × PH-3; ARM_PWR bleed 4.7 kΩ. The round-1 TLV6700 cut and the TPS259824L (0 at JLC) are gone.
- MCU: MCU_ALIVE PC3 (pin 11), PB9 = arm UART, PA6 = USB VBUS detect, PA4 reads DRVOFF through 10 kΩ, nSLEEP pull-downs 4.7 kΩ, IMU CLKIN held low by 100 kΩ.
- Pi power through USB-C J53: U87 is the auto-retry TPS259470A (R_ILM 887 Ω = 3.76 A), EN 100k/100k from +5V (2.6 V), not on the expander; Rp 10 kΩ (3.0 A); ribbon pins 2/4 open.
- Polarity: XT60 J1 and XT30 J20/J21 pad 1 = GND at the chamfered end ('-'), pad 2 = '+' (round 1 F-1/F-2).
- MOT_BUS_OFF (0x22 P2_4) pulled up to +3V3_MCU, not +3V3_PI: the motor bus stays off when the Pi is dead or unplugged (round 1 P-4).
- C26 (button debounce) to BAT_F: plugging the battery in no longer latches the board on (round 1 P-2).
- Series resistors to the Pi (E-stop, UART0 RX, lidar UARTs) 100 Ω -> 1 kΩ (back-powering).
- Board grown and re-floorplanned for routing; ZED 2i on two M3 standoffs on the board.

## Kept from rev B

- The LM74800 switch and latch, F1, the battery path, NT1 (star ground) and the brake chopper.
- The LM61495 buck block.
- The STM32 core: crystal, decoupling, BOOT0/NRST from the Pi, LDO.
- The E-stop NAND/ALIVE logic driving DRVOFF.
- RTC, button and bumpers.

## Removed against rev B

- DRV8316, the BLDC phase, Hall and encoder connectors; the RoboClaw fallback (JP1, JP2, J48, J49).
- TPS73733, the rev B ToF wiring and the Jetson UART; the INA226s; the DRV8316 footprint.

## Custom footprints (`gen/footprints.py`)

| Footprint | Part | Note |
|---|---|---|
| `TI_RXY0014A_VQFN-HR-14_3x4.5mm` | DRV8243 | 4 thermal vias in the GND bar; mask polygons approximated |
| `TI_RPW0010A_VQFN-HR-10_2x2mm` | TPS259470L/A | — |
| `TI_DMQ0006A_VSON-HR-6_1.5x1.5mm` | TPS62826 | pads from drawing labels |
| `TI_RUX0012A_VQFN-HR-12_2x2.5mm` | TPS2121 | pads from drawing labels |
| `TI_DPY0002A_X1SON-2` | TPD1E10B09 | pads 0.3 × 0.5 at ±0.35 (TI p.19) |
| `LED_SK9822-EC20_2x2mm` | SK9822-EC20 | partly illegible drawing |
| `ToF_Bracket_M2.5` | ToF bracket | holes, flange keep-out under the board, screw heads on top |
| rev B: `TI_RPH0016B`, `TI_DRR0012E`, NANO2 fuse, Kelvin 2512 shunt, NetTie, Pi standoffs | | |

PCAL6524 uses the KiCad `QFN-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm`, close to but not the NXP HUQFN32 land.

## Deviations from the JSON files and substitutions

1. **Battery shunt.** Vishay WSLP25122L000FEA (2512, 2 mΩ, 3 W, C2090981) instead of the WSLP2726: same value, fits the rev B Kelvin land.
2. **ITRIP default 2.41 A.** Series ladder 8.25k / 13.7k / 25.5k; ITRIP_SEL is pulled up (R1150 to +3V3_MCU), so 2.41 A applies by default and in MCU reset; the STM32 drives PB11 low for 4.05 A; with R1111/R1211 removed and PB11 low, 4.73 A. `drv8243.json` synced on 2026-10-11.
3. **Motor bus off by default.** MOT_BUS_OFF (0x22 P2_4) has its pull-up (RN array) to +3V3_MCU; Q31 holds the LM5069 UVLO low until the Pi drives the line low.
4. **Expander reset.** `EXP_RESET_N` (GPIO6, 10 kΩ pull-down) resets both PCAL6524s and the TCA6416A: every switched load stays off until the Pi drives it high. The TCA9548A has its own reset (GPIO19, 10 kΩ pull-up).
5. **STM32 PA6** is `USB_VBUS_DET` (22k/33k). TPS2121 ST goes to a test point (no MCU pin left).
6. **ILM readback** through 10 kΩ at the eFuse, 1 nF only at the ADS7128 input (§11a).
7. **Pi USB-C eFuse U87** (Q47 -> C32): TPS259470A auto-retry, R_ILM 887 Ω; 0x23 is full, so its FLT and current go to ADS7128 0x17 AIN4 (as GPIO, pulled up to ADC_AVDD) and AIN3. The arm eFuse U88 uses AIN5 (current) and AIN6 (FLT) the same way.
8. **ToF rail enable** from 0x22 P2_5 with a pull-down; PG to 0x23 P2_6.
9. **TCAN1044AV VCC** from +5V_MCU, so CAN works on USB power alone. CAN connector pin 1 = +5V_AUX (spare 5 V eFuse).
10. **SK9822 supply** straight from +5V.
11. **Servo bulk** 2 × Panasonic EEHZK1E471P (470 µF 25 V, C242138).
12. **TPS16630.** Jetson: MODE = GND (auto-retry), 5.1k = 3.53 A, SHDN through Q7 from GPIO25. Spare output: latch-off, 4.7k = 3.83 A, SHDN 10 kΩ pull-down. Their currents come from the TPS16630 IMON pins (ADS7128 0x17 AIN1/AIN2); the separate INA238 0x44/0x45 and shunts are gone.
13. **Fan PWM** through a 2N7002K (fans pull PWM up to 5 V): inverted in firmware.
14. **LM5069 freewheel diode** B540C on the GND_MOT island at the bulk capacitors.

## Open issues and what could not be verified

Tracked in `docs/open-issues.md` (Q49 layers, M25-M27 and M29-M30 cable and connector checks, P24-P28). In short:

- **Mechanical:** room for the mated PH plug in the gap between the motors; XT30 tails and pigtail bend at the left edge (M27); HCTL GH-6 mating with genuine GHR housings (M29).
- **Footprints:** DRV8243 mask polygons approximated; TPS62826, TPS2121, SK9822 pads from drawing labels; XT30 drill 1.8 mm vs AMASS 1.9 mm; no 3D models for the new footprints; `rabbit-body-c.kicad_dru` still names the old USB4105 for J50.
- **Pinouts:** TPD4E05U06 pins from memory; PESD2CANFD24V unchecked; pin 1 of the kit motor cable, the C1 lidar cable and the xArm cable to be checked with a meter; XT polarity on the moulded housings.
- **Electrical:** DRV8243 thermals assume 2 oz outer copper and via-stitched pads; ILM readback below 0.5 A unspecified; BSC010N04LS SOA margin under the LM5069 small; ITRIP live switching with a FET ladder untested; +5V worst case 5.30 V vs the C1's 5.2 V (P26); SERVO_RAW unclamped after a buck high-side short (P25); brake resistors 4 × their rating while on (P24); PCA9685 can phantom-power unpowered servos (P27, firmware).
- **Stale text in the generator** (not netlist): `design.py` docstring and comments (9 INA238, 8 ToF, ADS7128 ×3, "+5V17", "56k Rp", PCAL INT on GPIO22, VBUS sense on PC3), the bottom silk "4L 1.6 mm" and the `routing.py` docstring ("In5 signals") (P28).
