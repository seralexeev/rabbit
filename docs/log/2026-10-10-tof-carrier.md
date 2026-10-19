# 2026-10-10: ToF carrier PCB (VL53L8CX), rev A

The project is `pcb/rabbit-tof/`. Its README holds the design decisions with datasheet page citations, the BOM with stock and the check results. The board is generated from `gen/design.py` the same way as `pcb/rabbit-body-c`.

## What was built

- **Board:** 22 × 18 × 1.6 mm, 2 layers, ENIG. M2 holes at (±8.5, +4.0). The VL53L8CX Rx optical centre is at (0, +4.0) on the front face.
- **Port:** a JST GH-6 vertical (BM06B-GHS-TBT) is the only part on the back. Its pinout matches the body board port: 1 GND, 2 +3V3, 3 SDA, 4 SCL, 5 INT, 6 LPn.
- **Checks:** routed with 2 hand-drawn power feeds plus Freerouting 2.4.1. DRC gives 0 violations and 0 unconnected. `check_netlist.py --board` passes.
- **Outputs:** Gerbers, JLC BOM and CPL, a STEP in the board frame, and front/back/iso renders.
- **Size:** 18 placements per board, 10 BOM lines. Planned order: 10 boards.

## Findings

- **The VL53L8CX cannot run from 3.3 V alone.** CORE_1V8 and IOVDD have an absolute maximum of 1.98 V in DS14161 Rev 12 (July 2025, p.20 table 11), and there is no LDO or 3.3 V IO option. The carrier therefore has:
  - an LP5907-1.8 for CORE and IOVDD;
  - an LSF0204 translating SDA, SCL, INT and LPn between 1.8 V and 3.3 V.
- **Power-up slew matters with the body board's soft-start eFuse.**
  - DS p.11 table 5 asks for ≥ 0.012 V/µs on CORE/IOVDD.
  - The TPS259470L port eFuse (CdVdt 2.2 nF) ramps the port at 0.33–1.7 V/ms. An LDO enabled with its input would track that ramp in dropout, which is too slow.
  - The fix is an RC on LDO EN (100k / 1 µF with the internal 1 MΩ): EN reaches 1.2 V at 51 ms on the slowest ramp, after AVDD reaches 3.13 V at 9.4 ms. Then the LP5907 starts in 80 µs typical.
  - TPS7A20 (750 µs start-up) and TLV755 (550 µs) were rejected for the same reason.
  - Side effect: **a port power-cycle reset needs ≥ 0.5 s off** so the EN capacitor discharges.
- **Thermal pad:** ST AN5897 (p.4, fig. 3) asks for 8 vias in the B4 thermal pad with the bottom mask open. Without them the pad is enclosed by the signal pads and cannot reach ground on a 2-layer board.
- **LPn has a 47k pull-up on the sensor side (DS default), not a pull-down.** Every sensor sits on its own TCA9548A channel, so it can talk as soon as the port is powered. The Pi can still drive LPn low.
- **JLC has 1 genuine JST BM06B-GHS-TBT (C189892).**
  - The body board rev C uses the same part, so both boards need JLC Global Sourcing or consigned JST.
  - GH look-alikes with stock exist but are unverified for land pattern and mating: HCTL HC-GH-6PLT C3011957 (4820), BOOMELE C2829264 and XUNPU C52037399. Raised as Q50.
- **Freerouting needs help:** it failed (1–2 unrouted) on the long +3V3 feed and the +1V8 feed until those were drawn in `design.ROUTES`.
  - Pull-ups placed in a row under the sensor's A row blocked the pad escape. They now sit beside the LSF0204, which is rotated so that its A pins face the sensor pins in the same order.

## Review round 2 (same day, `data/pcb-revc/review/round2-tof-carrier.md`)

- **T-1, pin-1 tab:** without its pin-1 tab, the VL53L8CX land pattern was 180° symmetric. A rotated placement would pass JLC's overlay and put AVDD on SDA.
  - A1 now has ST's tab (DS p.37 fig. 33: 0.600 wide over the 0.200 nearest the thermal pad).
  - F.Fab is chamfered at A1 and marks the 2D-code corner (C7). The silk dot moved outside the cone projection.
  - The README has an order remark for U1, U3 and J1 orientation.
- **T-2, thermal pad:** the 8 open vias with full paste and an exposed back pad would wick solder into a bump against the bracket.
  - Now 4 vias in one row, tented on the back with no bottom pad, and 4 paste windows covering 51 %.
  - 8 vias at 0.3 / 0.5 mm leave no room for windows in the 2.316 × 1.2 pad.
- **T-4, EN discharge:** added BAT54WS (EN to +3V3) and a 10k bleed on +3V3.
  - Simulated: EN falls below VIL 350 ms after the port turns off, so the off-time is ≥ 0.8 s.
  - Start-up with 10 µA diode leakage still has EN crossing after AVDD is up (VIH at 40 ms).
- **T-7, cable:** the cable must be same-direction (1:1). This is now in the README and on the back silk.
- **T-3, J1:** an ordering step (pre-order genuine JST into JLC).
- **T-5 / T-6:** a software rule and a bench check, both under V13.
- **Totals:** 20 placements on 12 BOM lines. DRC 0 / 0.
