# Rabbit Power & I/O Board (v1)

## Purpose

Replace the current wiring nest (Evemodel distribution block, Adafruit PCA9685 breakout,
INA4235EVM, loose regulator wiring, Dupont jumpers to the Jetson header) with a single
board that distributes battery power, measures it, drives servos, and breaks out the
Jetson UART to the RoboClaw.

Firmware compatibility is a hard requirement: `node/steering.py`, `node/ina.py` and
`node/roboclaw.py` must keep working with at most a calibration-constant change.

---

## Current hardware (as found)

Sources: `docs/whiteboard.excalidraw`, node sources, `README.md`, datasheets in `datasheet/`.
The Jetson was offline during research, so nothing below was re-verified on the robot.

Power (whiteboard):

```
Gens Ace 4S HV LiPo 15.2V 7500mAh (13.2–17.4V)
 └─ XY-CD63L low-voltage disconnect (30A)
     └─ Evemodel distribution block
         ├─ Pololu D36V50F12 (12V 4.5A) → Jetson Orin Nano Super
         ├─ Pololu D36V50F12 (12V 4.5A) → RoboClaw 2x30A → 2× Pololu 37D 70:1 12V (5.5A stall each)
         ├─ Pololu D24V22F12 (12V 2.4A) → Teltonika TRB246
         ├─ Pololu D24V90F5  (5V 9A)    → (was RPi 4, now unused?)
         └─ Pololu D36V50F6  (6V 5.5A)  → PCA9685 V+ → A50BHL steering servo (3.6A @ 6V)
```

Signals (code):

| Device | Bus | Address / port | Source |
|---|---|---|---|
| PCA9685, steering on ch0, 50 Hz | I2C bus 7 = J12 pins 3/5 | `0x40` | `node/steering.py` |
| INA4235, 4 ch, R_SHUNT 10 mΩ | I2C bus 7 | `0x41` (A1=GND, A0=VS) | `node/ina.py` |
| RoboClaw, packet serial 115200 | `/dev/ttyTHS1` = J12 pins 8 (TX) / 10 (RX) | `0x80` | `node/roboclaw.py` |
| ZED 2i | USB | – | `node/zed.py` |

Jetson J12 facts (carrier spec SP-11324-001 §3.3): all signals 3.3V; I2C already has
2.2 kΩ pull-ups on the carrier; 3.3V pins 1/17 are limited to 0.1 A; 5V pins 2/4 to 0.5 A.
RoboClaw S1/S2 are 5V tolerant, output 3.3V → no level shifting needed.

---

## Board architecture

```
XT60 in ──F1 30A── Rsh1 2mΩ (INA ch1 BAT) ──┬── F2 20A ── Rsh2 2mΩ (INA ch2 MOTOR) ── XT60 → RoboClaw
                                            ├── F3 7.5A ─ U: D36V50F12 ── Rsh3 10mΩ (INA ch3 JETSON) ── XT30 → Jetson DC jack
                                            ├── F4 7.5A ─ U: D36V50F6 ─── Rsh4 10mΩ (INA ch4 SERVO) ─── servo V+ rail
                                            ├── F5 3A ─── U: D24V22F12 ─────────────────────────────── XT30 → TRB246
                                            └── F6 7.5A ─ U: D36V50F6/F7.5 (DNP) ──────────────────── 2-pin terminal → ARM

Jetson J12 (2x20 IDC ribbon) ── 3V3, GND, SDA, SCL, TX, RX, GPIO
   ├─ INA4235 (DSBGA-16, VS = 3V3, addr 0x41)
   ├─ PCA9685 (TSSOP-28, VCC = 3V3, addr 0x40, OE → GND via 0Ω / optional GPIO) → 16× servo headers (PWM, V+ 6V, GND)
   └─ RoboClaw S1 (Jetson TX), S2 (Jetson RX) — 2× 3-pin servo-style headers, +5V pin NC
```

Design decisions:

1. **Keep Pololu regulators as plug-in modules** on 0.1" female headers. Designing three
   3–5 A buck converters from scratch is the riskiest part of any power board and gives
   nothing here; modules are proven and swappable. Footprints come from Pololu's drawings.
2. **INA4235 on board** (JLCPCB C33440856, DSBGA-16, stocked) → requires JLCPCB PCBA
   for that part; not hand-solderable. Same address as today, so `ina.py` keeps working.
3. **Shunt values change** for ch1/ch2: 10 mΩ × 81.92 mV range caps a channel at 8.2 A,
   which is below battery total and motor stall. Use 2 mΩ Kelvin 2512 on ch1/ch2 (41 A range),
   keep 10 mΩ on ch3/ch4. `ina.py` needs per-channel `R_SHUNT` (small code change).
4. **PCA9685 logic at 3.3V** from J12 pin 1 (PCA9685 + INA4235 ≪ 0.1 A), so I2C needs no
   level shifting. Series 220 Ω on PWM outputs like the Adafruit board.
5. **Blade fuses** (mini ATO) per branch; XT60/XT30 keyed connectors, no active reverse-polarity
   protection in v1 (XT60 is keyed; ideal-diode controller would add cost and heat at 30 A).
6. **Low-voltage disconnect stays external** (XY-CD63L) in v1. INA ch1 bus voltage + ALERT
   gives software visibility; hardware LVD can move on board in v2.
7. **Stackup**: 4-layer, 2 oz outer copper, battery/motor paths as polygon pours on
   top+bottom with via stitching; inner layers GND + 3V3/signals.
8. Size target ~100 × 80 mm, 4× M3 holes for acrylic plate standoffs. Rail LEDs on 12V/6V/3V3.

---

## Decisions (confirmed by owner)

- **RoboClaw is fed directly from the battery** (it accepts 6–34 V), through F2 + Rsh2.
  Motor voltage/current must be capped in RoboClaw config (max duty ≈ 12 / 17.4 V at full
  charge, per-channel current limit) — do this before first power-up on the new board.
- **5V 9A module (D24V90F5) is dropped.** Nothing on the robot uses it now.
- **xArm control is out of scope for v1.** The board only gets an unmeasured, fused socket
  for a second 6–7.5 V Pololu module + 2-pin terminal (`ARM`), populated later.
  LX-15D/LX-225 are serial-bus servos, so PCA9685 cannot drive them anyway.
- TCA9548A (datasheet in repo) is not needed with two devices on the bus.

---

## Implementation notes

- Project: `pcb/rabbit-board/`, project libs in `pcb/rabbit-board/lib/` (`rabbit.kicad_sym`,
  `rabbit.pretty`): INA4235 symbol + TI YBJ DSBGA-16 footprint (0.4 mm pitch, 0.23 mm NSMD pads),
  Pololu D36V50Fx / D24V22Fx symbols + footprints taken from Pololu dimension drawings
  (top/component-side view; D36V50Fx columns VOUT, GND, GND, VIN, VRP, EN/PG).
- INA4235 inner balls are escaped with diagonal traces only (EN B3 → VS A4, A0 C2 → EN B3,
  A1 C3 → GND B4); ALERT (B2) is left unconnected so no via-in-pad is needed.
- Shunt Kelvin pins: `Device:R_Shunt` pins 1/4 = current, 2/3 = sense; WSK2512 footprint pads match.
- 8 servo channels populated (PCA9685 LED0–7 → 220 Ω → 1x03 headers: SIG, +6V, GND).
- THT parts (XT60/XT30, fuse holders, terminals, IDC header, pin headers, Pololu modules) are
  hand-soldered; SMD parts carry `LCSC` fields for JLCPCB assembly.

## Implementation steps

1. Create KiCad project `pcb/rabbit-board/` (Konnect `create_project`).
2. Schematic, hierarchical: `power` (input, fuses, shunts, module sockets, outputs),
   `monitor` (INA4235), `servo` (PCA9685 + headers), `jetson` (J12 IDC, RoboClaw headers).
3. Assign footprints + LCSC part numbers; custom footprints for Pololu modules.
4. ERC clean.
5. PCB: outline, mounting holes, placement (power path along one edge), pours, routing.
6. DRC clean against JLCPCB 4-layer rules; export Gerbers, BOM, CPL.
7. Software: per-channel `R_SHUNT` in `node/ina.py`.
