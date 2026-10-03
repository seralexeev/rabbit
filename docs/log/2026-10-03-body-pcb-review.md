# 2026-10-03 Body PCB review before ordering

Offline. An independent review of the rev A body board (`pcb/rabbit-body/`, report `reports/2026-10-03-body-pcb.md`) against the wiring document, the datasheets and the vendor drawings, with fixes made in the generator. Russian report with every finding, its evidence and its fix: `reports/2026-10-03-body-pcb-review.md`. No robot, Forge or `cad/brackets/` code changed.

## Result

- No wrong connection found. Checked pin by pin:
  - INA4235: ball map (SBOSAB5 fig. 4-1, top view), address 0x41 (A1 = GND, A0 = VS, table 6-1), EN = VS, Kelvin pairs (IN+ on the source side of every shunt);
  - PCA9685 (A0–A5, OE, EXTCLK to GND); DS3231 (N.C. 5–12 to GND, VBAT, Keystone 3001 polarity); TPS73733 DCQ (1 IN, 2 OUT, 3 GND, 4 NR, 5 EN, tab GND); AO3400A gates;
  - all 40 Pi header pins against `-wiring.md`; Jetson J14-3/4/7 against SP-11324 table 3-4;
  - the three Pololu footprints against the bottom-view drawings and the labelled isometric views (psw03b, reg15b, reg24d): the mirroring is right;
  - standoff holes against `kit_plate.dxf` (0.000 mm); no body intersections in `rabbit-body.step`; heights fit the 45 mm to deck 3.
- Ordering blocker: PCA9685PW (LCSC C2678753) had 0 in stock and INA4235 (C33440856) 1, so JLC cannot assemble two boards without a pre-order or consigned parts (`open-issues.md` P15).

## Fixed in the generator

| Finding | Fix |
|---|---|
| No TVS across the switch input (Pololu asks for one; only the output had SMBJ20A) | D7 SMBJ20CA (C151921), bidirectional so a reversed battery is blocked by the switch instead of blowing F1 |
| ToF 3.3 V tracks 0.4 mm, mostly on the 0.5 oz In2: 0.72 Ω to the rear-right connector, while the Pololu VL53L8CX carrier needs VIN ≥ 3.2 V at up to 150 mA | `+3V3_TOF` at 1.0 mm: 0.31 Ω worst |
| 5 V to the lidar and the ToF LDO 1.0 mm on In2 (0.10 Ω) | new `PWR_5V` class at 1.5 mm: 0.058 Ω |
| Motor return star: 2 mm net tie and 4 × 0.4 mm vias for a 10 A fuse; the MOT_BAT neck 3.3 mm | 3.5 mm custom net tie, 3.5 mm tracks, 9 vias, 6.7 mm neck |
| `pcbnew.NewBoard` loads the existing `.kicad_pro`, so net class patterns piled up between runs (`+3V3_TOF` resolved to "PWR_LO,PWR_MID") and width changes in `design.py` did not reach the routing | `build_board.py` clears net classes and patterns first |
| ZED cable cut-out 7.8 × 13.8 mm, smaller than the kit slot (10.3 × 23.9) and a moulded USB-A plug | 11.1 × 18.0 mm; Q3/R24/R25 moved 3 mm forward. The grommet in `cad/brackets/zed_grommet.py` still has the old size |
| INA4235 paste 0.25 mm at 0.4 mm pitch (TI stencil: 0.21 mm) | paste margin −0.02 mm on the 16 balls |
| CR1220 holder LCSC number C238098 does not exist; stencil paste on its contact pad | number removed; no paste on SMD pads of parts JLC does not place |

After the fixes `gen/make.sh` gives DRC 0 violations and 0 unconnected, `check_netlist.py --board` matches `design.py` (117 parts, 91 nets), and `gen/fab.py` gives 22 BOM lines and 61 placements.

## Left to the owner

- Pre-order PCA9685 and INA4235; check the part rotations in JLC's placement preview (the CPL has no JLC rotation corrections: U3, U7, U8, U9, Q1–Q3, D1, D7, LEDs).
- 5 V to the Pi through the ribbon: about 0.1 V drop at 2.5 A, 1.25 A per IDC contact (Q3).
- The E-stop is fail-safe only with 1 kΩ S3→GND inside the connector at the RoboClaw; the 100 kΩ at GPIO16 on the board cannot beat RoboClaw's internal pull-up. Battery current through the #2813 module needs a solid wire through its 2.18 mm VIN/VOUT holes (Q26).
- XT60/XT30 polarity: pad 1 (chamfered end) is "+"; Amass does not draw it, so check the moulded mark before soldering (Q24). ZED plug size (Q25).

## Factory assembly and rev B

- Every THT part on the board is in LCSC stock, so JLC can hand-solder them at $0.0164 per joint (~$2.5 per board, $3.58 per order). Only the four Pololu modules stay manual. On-board replacements for rev B: LM61495RPHR (C2943584, 36 V 10 A) or TPS54560DDAR (C31966) instead of the D24V90F5/D36V50F modules, eFuses TPS259474 / TPS25982 instead of ATO holders (23–24 V limits), a discrete 40 V P-MOSFET latch instead of #2813 (Q27).
- For the rev B FOC board: define net classes from scratch, budget rails by path resistance, size the power star for phase currents with its own ground pour, TVS at every switched input and compare TVS clamp voltage with eFuse/driver limits, check LCSC stock before review, keep the E-stop pull to "stop" at the drive side, follow TI stencils for 0.4 mm WCSP, add 10 Ω INA input resistors and ToF pull-up footprints.
