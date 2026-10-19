# 2026-10-10 Body PCB rev C: spec, parts, netlist and placement

Offline. Spec (Russian): `reports/2026-10-10-body-pcb-rev-c.md`; project: `pcb/rabbit-body-c` (a copy of the rev B generator; rev B in `pcb/rabbit-body` untouched); per-IC data: `data/pcb-revc/ics/` (gitignored).

## Owner decisions

- RoboClaw removed; the board replaces the kit's deck-2 plate on the 50 mm standoffs; Pi 4 on M2.5 standoffs on the board, joined by a short 40-way ribbon that also powers it.
- Back to the kit's Hiwonder JGB37-520R30-12 motors; brushed H-bridges only.
- Jetson stays on deck 1 between the servo and the motors; it gets only power (XT30 on the board, owner's barrel-jack pigtail), talks to the Pi over Ethernet. Deck 3 is for the battery and the camera.
- The Pi runs all mechanics and power; the Jetson does perception and planning only. The Pi can switch every load.
- Lidars on Pi UART3/4/5 over the ribbon; ports: ToF 8, lidar 3, servo 8, CAN 1, fans 2; quality and precision over cost; two-sided assembly.

## Design

- Drive: 2 × TI DRV8243H (40 V, 84 mΩ, IPROPI, ITRIP 2.41 A default / 4.05 A selected by the STM32, DRVOFF from the rev B E-stop logic; brake = both inputs low). Motor bus behind an LM5069 hot-swap (slow ramp: the BSC010N04LS SOA allows only 0.33 A DC at 16.8 V), off until the Pi enables it.
- 18 × TPS259470L eFuses (each load), ILM read by 3 × ADS7128 (REF3425); 2 × PCAL6524 for EN/FLT, GPIO6 resets them (all loads off); 9 × INA238 on the rails (VBUS straight to the load-side sense tap: rev B's filter-resistor wiring added ~84 mA of phantom current).
- I2C1 (100 kHz until measured): ADS7128 0x10/11/17, TCA6416A 0x20, PCAL6524 0x22/23, INA238 0x40–0x4F (9), PCA9685 0x60, DS3231 0x68, TCA9548A 0x77.
- Motor connectors: JST PH-6 SMD on the bottom in the gap between the motors' rear ends (board X ±7, Y −84): over the motors only ~10.7 mm is left for the plug and the cable bend.

## Status

- 753 footprints (385 top, 368 bottom), 497 nets, 152 BOM lines, all in JLC stock; `check_netlist.py --board` OK; placement DRC 0 errors. Not routed: power routing from rev B no longer applies (`routing.py` is planes only).
- Thin stock (JLC, 2026-10-10): JST GH-6 85 (fell from 105 the same day), Würth 2×20 89, STM32G474 272, DRV8243 408. A JLCPCB project "Rabbit body board rev C" tracks these six parts (no purchase).
- Open: pads read from drawing labels (TPS62826, TPS2121, SK9822, DRV8243 mask), no 3D models for new footprints, bottom THT XT30s need a bottom THT step or hand soldering, outer copper 1 oz vs 2 oz assumed for DRV8243 thermals, Q47 (Pi power over the ribbon).

## Update: Pi power and assembly (same day)

- Pi 4 is powered through USB-C (owner): +5V → INA238 0x4C → U87 TPS259470L (3.3 A, EN pulled up to +5V17 so an expander reset cannot cut the Pi) → J53 USB4125 (Rp 10 kΩ) → short cable to the Pi's USB-C. Ribbon pins 2/4 are left open: two feeds would back-power each other.
- JLC assembles everything that can be assembled, including the bottom THT XT30s; the MMC5983MA magnetometer and the motor Micro-Fit connectors are fitted; 7 configuration alternatives stay DNP.
- 754 footprints, 154 BOM lines in stock for 2 boards, netlist OK, placement DRC 0 errors.

## Night of 10–11 October: vertical connectors, ToF brackets, xArm, reviews, 8 layers

- **Connectors perpendicular to the board** (owner): USB-C J50/J53 → GCT USB4115-03-C vertical, CAN J51 → JST BM04B-GHS-TBT, ToF → JST BM06B-GHS-TBT (1 in JLC stock: Global Sourcing), XT30 J20/J21 → AMASS XT30UPB-F on the bottom at the left edge (X −53.5), lidar ports → JST XH-5 (see below). Only the barrel pigtail stays sideways.
- **ToF on brackets under deck 2** instead of deck 1: 6 sensors (front, two front chamfers at ±50°, rear, two rear chamfers at ±135°). `cad/robot/tof_fov.py` casts the VL53L8CX 8 × 8 zones against the assembly with the front wheels steered ±30°: the side positions are 20–100 % blocked by wheels, gearboxes and steering links; the chosen six are clear (front chamfers lose 2/64 zones at full opposite lock). The board outline (`gen/outline_revc.py`) turns the four chamfers square to the sensors and pushes them out until the bracket flange clears the M4 standoffs by 1.5 mm. One printed bracket for all six (`cad/robot/parts/tof_mount.py`, MJF PA12, `cad/robot/print/`); footprint `ToF_Bracket_M2.5` carries the two holes and the flange keep-out. 6 ports (TOF7/8 electronics removed), the mux on the Pi's own I2C6.
- **xArm 1S on the board**: TPS259824L current-limiting eFuse (5 A, 2.2 ms blanking) from SERVO_RAW, TLV6700 overvoltage cut at 8.8 V, STM32 PB9 USART3 single-wire half-duplex → BSS138 → 5 V bus (390 Ω 1206, 9 V ESD), 2 × PH-3. MCU_ALIVE moved to PC3, VBUS_SENSE dropped.
- **Reviews and simulation**: round 1 (power, MCU/motor, Pi side, footprints, SPICE in `workspaces/bench/pcb-sim/`) and round 2 (script-assisted net-by-net audit in `workspaces/bench/pcb-audit/`, ToF carrier). Reports and the list of applied fixes: `data/pcb-revc/review/`. Real catches: XT30/XT60 polarity reversed against the footprints' chamfer, lidar connector didn't fit the C1 cable (XH2.54-5P, no motor line), battery plug-in could latch the board on (C26 to GND), arm without overvoltage cut, a stalled arm sagging the steering rail through the shared buck (the circuit-breaker eFuse let 2× ILIM through for 47–93 ms), ToF traffic saturating I2C1, motor bus "off by default" relying on the Pi's 3.3 V, PB9 overcurrent on a mis-plugged arm cable.
- **Layers**: 4 → 6 → 8. With In1/In4 GND and In2 VBUS on 6 layers the autorouter left ~350 connections on 3 signal layers; 8 layers: F/In2/In3/In5/B signals, In1/In6 GND (with the GND_MOT island), In4 VBUS. fastroute (Rust port of Freerouting) fans out in 25 s where Freerouting took 37 min.

## 11 October: simpler, bigger, re-floorplanned

- **Simplified (owner):** ToF ports straight on +3V3_TOF (the TPS62826 EN is the group switch), no per-port eFuses or their ADC (ADS7128 0x10); one eFuse for both encoders; INA238 only on battery (0x40), motor bus (0x41), servo (0x43) and 5 V total (0x47). 763 → 671 parts.
- **ZED 2i on deck 2:** two M3 × 5 mm standoffs, holes 36 mm apart (Stereolabs drawing, `datasheet/ZED/`, owner measured 36); the nose grows to Y 156.2 so the camera clears the front deck-3 standoffs by 2 mm; the LED row follows the edge.
- **Outline (`gen/outline_revc.py`):** rear chamfers 30 mm long (the 26 mm brackets fit like the front ones), tail to Y −158, tail and middle widened to ±70 up to Y 30 (9.8 mm to the rear wheels; the front zone is unchanged for the steering sweep).
- **Routing so far:** 8 layers with In5 split into MOT_BUS / SERVO_RAW / SERVO_PWR / +5V regions; battery chain 3 mm and 5–10 A nets 2 mm, outer layers only (2 oz); pours that trap other nets' pads are filled after routing. fastroute 0.1.13 (from 0.1.7) with `min_trace_width_um`, `neck_width_um`, cheaper vias and `min_passes`. Plateau 64–90 unrouted on the old floorplan; Fable's floorplan for the enlarged board is being compared.

## 11 October (day): JLC options, deeproute, routed to zero

- **JLC options (owner's account, quote form, nothing ordered):** 8 layers, 2.0 mm, Shengyi S1000-2M TG170, ENIG 2U", 2 oz outer / 1 oz inner, epoxy filled and capped vias (the only choice for 8 layers), 0.2 mm min via (adds a 4-wire Kelvin test), black mask, edge plating, 2D barcode serial: $441.88 for 5 bare boards, 10–11 days. Details in `docs/reports/2026-10-11-jlc-order.md`.
- **Edge plating:** GND copper reaches the outline (DRU rule), every other net stays 1.5 mm off it, 174 GND stitching vias every 5 mm, the ZED cutout is not plated (named area `zed_cutout` for the DRU only, a 0.5 mm `cutout_keepout` for the router).
- **Value swaps after the bring-up review** (`data/pcb-revc/review/bringup-risks-verify.md`): F1 15 A → 20 A (0451020.MRL, 14.7 A continuous at 40 °C), R45 47k → 220k (Q4 V_EB on a reversed 4S pack 10.5 → 4.8 V), lidar eFuse R_ILM 4.42k → 1.65k (C1 starts at 0.8 A). Arm + steering above the servo buck's minimum limit is accepted (they don't move together).
- **Router comparison on the same board and rules (KiCad DRC, project rules):** fastroute 0.1.13 at 0.15 mm (C3): 24 unconnected, 5 errors after ~1.5 h. deeproute (a new router from another session, `~/projects/deeproute-data`): v2 15/0 in ~4 min, then iterated with a power-width rule (outside its own pour a PWR_* track keeps its class width; necks only within 1 mm of a pad; single small-signal spurs allowed) to v19: 10/0.
- **In5 reshaped from deeproute's diagnostics:** +5V bands beside SERVO_RAW (lidar eFuse inputs, buzzer) joined to the nose region, a dedicated +5V_PI_USBC plane U87 → J53, a +5V_AUX plane to J58/J51, SERVO_PWR shrunk to the servo ports. ARM_PWR got its own class (1.2 mm; 2.0 mm for 4.45 A did not fit the arm block) and POSTFILL pours.
- **Finish by hand** (`gen/fixups.py` toolkit, `gen/dedupe_vias.py`): v19 + 57 merged same-net vias 0.04–0.2 mm apart (JLC hole-to-hole 0.25 mm), sense spurs to U4.5 / U6.5 / U10.9 / U10.10, HG on In3 moved and narrowed to 0.6 mm to free a via for LM74800 VS, BUZZER_PWM by a small grid A* over In2/In3/B. Result: **0 unconnected, 0 DRC errors**, `check_netlist --board` OK. Saved as `data/pcb-route/routed-8L-E19-hand.kicad_pcb`.
- **Power widths (deeproute's metric on the final board):** every PWR_* outside its own pour and > 1 mm from a pad is at class width except sense/gate/bootstrap spurs; one compromise: SERVO_RAW into U83.5 (steering eFuse IN) is 1.0 mm for 1.8 mm.
- **Review round 3** (`data/pcb-revc/review/round3-power-si.md`, `round3-dfm.md`), on the routed board:
  - power/SI: the router dropped one via wherever a pour meets a plane (15 A at R1 → In4 VBUS, 10 A at Q30 → In5 MOT_BUS, 10 A motor return at NT1, 11 A at the servo shunt, 9 A at the +5V shunt), the LM61495 PGND had no direct plane connection, SPARE_VBAT / JET_PWR ran 0.6 mm (1 oz inner) for 3.8 / 3.5 A. `gen/power_fix.py` adds 3–8 vias of the net's size per transition inside that net's plane region with a solid local pour, solid zone connections on J1.1 / NT1 and the buck power-stage GND pads, ~30 GND vias 0.6/0.3 at the bucks; SPARE_VBAT and JET_PWR got 1.2 / 1.5 mm F.Cu paths and via clusters at the eFuse outputs;
  - DFM: GND fills reached the unplated ZED cutout, 38 thermal holes were component holes (fill and cap not guaranteed), the USB-C pegs were 0.58 mm NPTH slots (JLC minimum 1.0), In2/In3 had 4 % copper against ~90 % on the planes (bow risk on a 2.0 mm structural deck), overlapping XT30 polarity marks. `gen/dfm_fix.py` fixes them (pour keepout 0.5 mm on all layers, holes → 0.5/0.3 vias, plated GND slots, GND fills on In2/In3, silk); `fab.py` names the plated-edge layer `*-Edge_Plating.gbr`.
  - Final: 0 unconnected, 0 DRC errors, `check_netlist --board` OK, all 158 BOM lines in JLC stock for 2 boards; fab outputs in `pcb/rabbit-body-c/fab/`, board copy `data/pcb-route/routed-8L-final.kicad_pcb`. The routed board is the artifact: `make.sh` would route it differently (deeproute + hand edits are not replayed).
