# ToF carrier (VL53L8CX), rev A

This is a 22 × 18 mm carrier for the ST VL53L8CX 8×8 multizone ToF sensor. It plugs into one ToF port of the body board (`pcb/rabbit-body-c`) with a 100 mm JST GH-6 cable, pin 1 to pin 1. Planned quantity: 10 boards, 6 used and 4 spares.

`gen/design.py` is the single source of truth for parts, nets and positions. Everything else is generated from it:

```
gen/make.sh                      # STEP model of the sensor, footprints, placement + pours, Freerouting, cleanup, fill, DRC
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
$PY gen/check_netlist.py --board # netlist and placement checks, board == design.py
python3 gen/stock.py 10          # JLC stock for 10 boards -> fab/stock.json, fab/rabbit-tof-revA-stock.csv
$PY gen/fab.py                   # Gerbers zip, JLC BOM + CPL, full BOM, board STEP
gen/render.sh                    # renders/front.png, back.png, iso_front.png, iso_back.png
```

Board frame: mm, origin at the board centre, X right, Y up, looking at the sensor (front) face. In KiCad the page position is x = 100 + X, y = 100 − Y.

## Sources

| Document | Where | Cited as |
|---|---|---|
| VL53L8CX datasheet DS14161 **Rev 12** (July 2025), from st.com | `data/datasheets/st/vl53l8cx-DS14161-rev12.pdf` (Rev 7 from LCSC alongside) | DS p.N |
| AN5897 Rev 2 "PCB thermal guidelines for the VL53L8 ToF sensor family" | read on st.com; the browser could not save the file | AN5897 p.N |
| TI LP5907 SNVS798Q | `data/datasheets/ti/lp5907.pdf` | LP5907 p.N |
| TI LSF0204 SLVSCP5H | `data/datasheets/ti/lsf0204.pdf` | LSF p.N |
| TI TPS25947 SLVSFC9C (the body board's port eFuse TPS259470L) | `data/datasheets/ti/tps25947.pdf` | TPS25947 p.N |
| JST GH catalogue | `data/datasheets/jst/GH-catalog.pdf` | — |

## Design decisions

### 1. Supplies: 3.3 V alone is not possible, so the board has a 1.8 V LDO

The brief asked for a single 3.3 V supply "if the datasheet allows". It does not:
- CORE_1V8 is a 1.8 V supply. IOVDD is 1.2 V or 1.8 V, and both have an **absolute maximum of 1.98 V** (DS p.20 table 11, p.4 table 1).
- Rev 12 has no internal-LDO or 3.3 V IOVDD option.
- The Rev 7 copy from LCSC says the same.

The supplies are therefore:
- **AVDD** comes from port pin 2 (the body board's switched, eFuse-limited 3.3 V).
- **CORE_1V8 and IOVDD** share one TI **LP5907MFX-1.8** (C92498). DS p.20 recommends one supply for both when IOVDD is 1.8 V.
- **Current:** CORE draws 50 mA typical and 80 mA max while ranging, plus 10 mA peaks (DS p.21 table 14). That gives 135 mW in the LDO at most.
- **Power-up slew (DS p.11 table 5):** after AVDD is stable, CORE_1V8 and IOVDD must rise at ≥ 0.012 V/µs. In the "start together" case AVDD also needs ≥ 0.001 V/µs.
- **The port ramp is too slow for "start together":** the body board's TPS259470L with CdVdt 2.2 nF ramps at 2000 / 2200 pF = 0.9 V/ms (TPS25947 eq. 4). With the IdVdt spread, the slowest case is 0.33 V/ms.
  - An LDO enabled with AVDD would therefore track AVDD in dropout at 0.0003–0.0009 V/µs, which violates the table.
- **Enable delay:** EN is delayed by **R1 100k / C6 1 µF**. The LP5907's internal 1 MΩ EN pull-down is included in the calculation.
  - `check_netlist.py` simulates the slowest port ramp, including a generous 10 µA hot reverse leakage of D1 that charges EN: AVDD reaches 3.13 V at 9.4 ms, and EN reaches VIH max (1.2 V) at 40 ms.
  - With the fastest EN threshold (VIL 0.4 V), EN still crosses after AVDD is up. This is the DS's "AVDD stable followed by CORE_1V8 and IOVDD" row. D1 is reverse-biased while the rail rises (EN < rail), so it does not change the sequence.
- **LDO start-up:** the LP5907 then starts in t_ON 80 µs typical / 150 µs max to 95 % (LP5907 p.6). That is about 0.021 V/µs typical.
  - If all of the 150 µs max were ramp, the average would be 0.011 V/µs. Most of t_ON is the internal delay, so this is listed as a bench check (V13).
- **Why not TPS7A20 or TLV755:** TPS7A2018 (750 µs) and TLV75518 (550 µs) start too slowly for the 0.012 V/µs rule.
- **Power-down and re-enable (review round 2, T-4):** the port eFuse has no output discharge, so without help the rail and C6 would decay only through leakage and the 1 MΩ (τ ≈ 1 s).
  - A quick re-enable would then find EN still high. The LDO would track AVDD up in dropout, which is too slow for DS p.11 table 5.
  - **R9** (10k, +3V3 to GND, 1.1 mW while on) bleeds the rail. The rail is about 12 µF (C1 + C4 here, plus the body board's 1 µF eFuse output cap), so τ = 0.12 s.
  - **D1** (Diodes BAT54WS-7-F, C124205; anode EN, cathode +3V3) pulls EN down with the rail.
  - `check_netlist.py` simulates the decay with a 0.15 V Schottky drop: EN falls below 0.35 V (VIL is 0.4 V) 350 ms after the port turns off. The LP5907 then discharges +1V8 through its 230 Ω (LP5907 p.3).
  - **A sensor reset by power-cycling the port must keep the port off for ≥ 0.8 s** (twice the computed time). V13 measures it.
- **Decoupling (DS p.8 fig. 5):**
  - **AVDD:** C1 is a 10 µF 0603 X5R. The DS asks for 4.7 µF; 10 µF keeps ≥ 4.7 µF effective at 3.3 V bias. It sits 1.8 mm from pin C4.
  - **CORE_1V8:** C2 100 nF, 1.4 mm from B7.
  - **IOVDD:** C3 100 nF, 1.3 mm from A3. It is tucked under the A row, and a `.kicad_dru` rule allows its courtyard overlap.
  - **LDO:** 1 µF on its input and on its output (LP5907 p.4).

### 2. Interface: I2C through a TI LSF0204

**Strapping (DS p.7 table 3, p.8 fig. 5, I2C mode):**
- SPI_I2C_N (C1) and NCS (C2) each have a 47k pull-down (R7, R8).
- MISO (C5) is not connected.
- RSVD1–3 (A6, A7, C6) and both GND pins go to GND.

**Pull-ups on the sensor side, all to 1.8 V (DS p.7):**
- SDA and SCL: 2.2k each (R2, R3).
- GPIO1 = INT: 47k (R4).
- LPn: 47k (R5).
- GPIO2 = SYNC: 47k (R6). SYNC is not used; DS Rev 11+ renamed A1/B1 to GPIO1/GPIO2.

**Level translation:** all digital pins must be driven at the IOVDD level (DS p.7 note), and the body board works at 3.3 V. A TI **LSF0204PWR** (C202288) translates SDA, SCL, INT and LPn (LSF p.13 fig. 10-1):
- Vref_A = 1.8 V and Vref_B = 3.3 V.
- EN is tied to Vref_A, so the switches stay off and isolate the 3.3 V side until the 1.8 V rail is up. The sensor is never back-powered through SDA/SCL.
- Because it is a pass-FET translator, both open-drain lines (SDA, SCL, INT) and the push-pull LPn drive from the body board's TCA6416A (through its 1k) pass through without direction control.

**No duplicate parts on the 3.3 V side.** The body board already has the 4.7k SDA/SCL and 10k INT pull-ups to the port's switched 3.3 V, the 1k in LPn and the ESD diodes.

**LPn has a pull-up, not a pull-down.** DS p.7 says LPn low disables I2C, and asks for a 47k pull-up to IOVDD when the pin is not driven.
- Each sensor has its own TCA9548A channel, so the shared 0x29 address never collides and the sensor should talk as soon as it is powered.
- While the TCA6416A pin is still an input after reset, R5 holds LPn high.
- The Pi can still drive LPn low through the translator to drop a sensor off the bus.
- A 47k pull-down would instead leave I2C off until the Pi drives LPn.

### 3. Land pattern (`gen/footprints.py`, `lib/rabbit_tof.pretty/ST_VL53L8CX_LGA-16_6.4x3.0mm`)

**Pads (DS p.37 fig. 33, "view through top of module"):**
- 14 pads, 0.500 × 0.515, at 0.750 pitch.
- The rows are 1.315 from the centre line to the outer pad edge, with a 0.200 gap to the thermal pad.
- Thermal pad B4: 2.316 × 1.200.
- B1/B7: 0.535 × 0.500, centred at ±2.6675.
- **A1 has ST's pin-1 tab** (fig. 33: 0.500 / 0.600 / 0.200): the pad is 0.600 wide over the 0.200 nearest the thermal pad, with the extra 0.100 on its outer (+X) side. Without the tab the pattern is 180° symmetric. A rotated placement would then pass the paste-overlay check and put AVDD on SDA (review round 2, T-1).
- **Assembly marks:** F.Fab has the package outline chamfered at A1 (bottom right) and the 2D-code square of the cap at C7 (top left; DS p.35: the code marks C7, not pin 1). The silk dot sits next to A1, below the projected exclusion cones, at (+5.2, +1.6).

**Pin map:** DS p.6 fig. 4 (bottom view), mirrored. In the top view A1 is bottom-right, C1 top-right, B1 right and B7 left. AN5897 p.4 fig. 2 shows the same.

**Thermal pad (AN5897 p.3–4, section 3 and fig. 3; changed in review round 2, T-2):**
- AN5897 gives a thermal budget of 35 °C/W board-to-ambient for 320 mW at 85 °C.
- AN5897 shows 8 vias in B4, one full paste rectangle and the pad repeated on the bottom with the mask open. The review found two problems with that here:
  - Paste wicks through open vias onto the back.
  - The back pad would leave a solder bump against the bracket face and tilt the sensor.
- **Now:**
  - **4 vias** (0.3 mm drill, 0.5 mm copper) sit in one row on the centre line at x = ±0.3 and ±0.9.
  - The vias are tented on the back: no bottom pad and no bottom mask opening. They stay open on the front, inside the pad.
  - The front paste is split into **4 windows of 1.108 × 0.32 mm**, clear of the via copper by ≥ 0.03 mm. That is **51 %** of the pad.
- **Why 4, not 8:** 8 vias at JLC's 2-layer minimum (0.3 / 0.5 mm) cover the whole 2.316 × 1.200 pad and leave no room for paste windows. Keeping 8 would need smaller vias or filled and capped vias, which JLC offers for 4+ layers.
- Both layers are GND pours. 9 stitching vias tie the front pour islands to the back.
- The thermal margin on the bracket is a bench check (review T-6, V13).

**Optics (DS p.31 fig. 26, p.33 fig. 29):**
- The Rx (SPAD) "optical centre" is 1.48 mm from the left package edge and 0.10 mm below the centre line, towards the A row. The VCSEL is 4.00 mm to its right.
- The Rx centre is placed at **(0, +4.0)**, as specified, so the package centre is at (+1.72, +4.10).
- F.Fab draws the apertures. Cmts.User draws the exclusion-cone sections at 3 mm (4.2 × 4.2 square, 57.6°).

**Keep-outs:**
- The cones start at the module top, 1.75 mm above the board.
- The tallest front part is the LP5907 SOT-23-5 at 1.45 mm, and every front part is below the module top (`check_netlist.py`). So nothing on the board can enter the cones.
- There is no silk on or around the module apart from the A1 dot, which is outside its courtyard and outside the cone projection.
- The module top must stay free of tape and conformal coat. If the reel has the liner option, remove the liner after assembly (DS p.32, p.36).

### 4. Mechanics and layout

**Board:**
- 22.0 × 18.0 × 1.6 mm, R1 corners, 2 layers, ENIG.
- Two M2 holes (2.2 mm NPTH) at (±8.5, +4.0). No part is within 2.8 mm of a hole centre, which clears an M2 head of d 3.8 mm.

**Front face:** the sensor, the LDO, the LSF0204 and the passives, all lower than the sensor.

**Back face:**
- Only J1, a JST GH-6 vertical, centred at (0, −4.0). The bracket window must clear its body: about 11.3 × 6 mm footprint, 4.25 mm tall.
- Nothing else protrudes: the 4 thermal vias are tented and there is no exposed pad.
- Silk: "RABBIT ToF L8CX", the pin names "1 GND … 6 LPn" over each contact, a triangle at pin 1, "CABLE 1:1", and "rev A github.com/seralexeev/rabbit".
- Seen from the back, pin 1 is on the right (front-view X −3.125).

**Port pinout (same as the body board):**

| Pin | Net |
|---|---|
| 1 | GND |
| 2 | +3V3 (AVDD) |
| 3 | SDA |
| 4 | SCL |
| 5 | INT |
| 6 | LPn |

The mounting tabs (MP) are GND.

**Cable (review round 2, T-7):** use a JST GH 1.25 mm 6-pin double-ended cable, **same direction (pin 1 to pin 1)**, 100 mm, 26 AWG. A reverse-direction GH cable, which is just as common, puts GND on LPn and 3.3 V on INT. The back silk says "CABLE 1:1".

**Routing:**
- The power feeds are hand-routed (`design.ROUTES`), all at 0.3 mm:
  - +3V3 from J1 up the back to C1/AVDD, with a branch to the LDO input;
  - +1V8 from the LDO to C2/CORE, with a branch to the SDA/SCL pull-ups R3/R2.
- Freerouting routes the rest at 0.15 mm, plus 0.3 mm on power and GND.
- The LSF0204 is rotated 270° so that its A pins 2–5 (INT, LPn, SDA, SCL) face sensor pins A1, A2, A4 and A5 in the same order.

**STEP:** `fab/rabbit-tof-revA.step` is in the board frame (origin at the board centre). Z = 0 is the back face, the board top is at 1.6, the sensor top at 3.37 and the connector reaches −4.29. Use it for the bracket check.

## Parts and stock (JLC, 2026-10-10, for 10 boards; `fab/rabbit-tof-revA-stock.csv`)

| Ref | Part | LCSC | JLC stock | Notes |
|---|---|---|---|---|
| U1 | ST VL53L8CXV0GC/1 | C7386355 | 2357 | extended, $10.19 |
| U2 | TI LP5907MFX-1.8/NOPB | C92498 | 30794 | extended |
| U3 | TI LSF0204PWR | C202288 | 10110 | extended |
| J1 | HCTL HC-GH-6PLT (GH-compatible vertical, JST BM06B land) | C3011957 | 4820 | extended, see below |
| C1 | 10 µF 10 V X5R 0603 (Samsung CL10A106KP8NNNC) | C19702 | 10.4 M | basic |
| C2, C3 | 100 nF X7R 0402 | C1525 | 24 M | basic |
| C4, C5, C6 | 1 µF 25 V X5R 0402 | C52923 | 7.3 M | basic |
| R1 | 100k 0402 | C25741 | 8.1 M | basic |
| R2, R3 | 2.2k 0402 | C25879 | 1.6 M | basic |
| R4–R8 | 47k 0402 | C25792 | 5.3 M | basic |
| R9 | 10k 0402 (rail bleed) | C25744 | 19.8 M | basic |
| D1 | Diodes BAT54WS-7-F, Schottky SOD-323 (EN discharge) | C124205 | 48.9 k | extended |

Totals: 12 BOM lines, 20 placements per board. 19 placements are on the top. J1 is on the bottom, so the order needs two-sided assembly.

**J1 sourcing (2026-10-11).** Genuine JST BM06B-GHS-TBT (C189892) had 1 in stock at JLC, so J1 is the HCTL HC-GH-6PLT (C3011957): 1.25 mm pitch, pads 0.6 mm, MP pads at ±4.975 mm like JST (HCTL drawing p.18), so the JST land `Connector_JST:JST_GH_BM06B-GHS-TBT_1x06-1MP_P1.25mm_Vertical` is kept. Mating with genuine JST GH cables is checked on arrival (M29 in `docs/open-issues.md`). The body board rev C uses the same part for J60-J65.

## Check results (2026-10-10)

| Check | Result |
|---|---|
| `check_netlist.py --board` | OK. 22 parts (20 SMT, 2 holes), 15 nets. It covers: DS strapping and supplies; decoupling within 2.5 mm; the LDO EN delay against the slowest port ramp (with D1 leakage); the EN discharge path (D1 + R9) and the resulting off-time; LSF0204 channel pairs; the port pinout; no 3.3 V-side resistors; the Rx centre at (0, 4.0); front heights below the sensor; only J1 on the back; screw-head clearance; and the board matches `design.py` pin for pin |
| DRC (`gen/drc_summary.py`, KiCad 10) | **0 violations, 0 unconnected**. Rules: 0.15 mm track/space (0.13 minimum), 0.3/0.6 mm vias, 0.3 mm copper to edge |
| Pours | GND on F.Cu (240 mm²) and B.Cu (304 mm²) |
| Back face | B.Mask opens only for J1 (no thermal pad, the vias are tented) |
| Stock | All lines in stock at JLC except J1 (see above) |

## Files

| Path | What |
|---|---|
| `rabbit-tof.kicad_pcb`, `.kicad_pro`, `.kicad_dru`, `fp-lib-table` | KiCad 10 project. The board is generated; edit `gen/design.py`, not the board |
| `gen/design.py` | Parts, nets, positions, hand routes, stitching vias, silk |
| `gen/footprints.py`, `gen/models.py`, `lib/`, `3d/vl53l8cx.step` | Sensor footprint and envelope model |
| `gen/build_board.py`, `gen/autoroute.py`, `gen/import_ses.py`, `gen/cleanup.py`, `gen/fill.sh`, `gen/make.sh` | Board build and routing (Freerouting 2.4.1 from `data/tools/`; work files in `data/pcb-route-tof/`) |
| `gen/check_netlist.py`, `gen/drc_summary.py`, `gen/stock.py`, `gen/fab.py`, `gen/render.sh` | Checks and outputs |
| `fab/rabbit-tof-revA-gerbers.zip` | Gerbers and drill files for JLCPCB. Origin is the bottom-left board corner |
| `fab/rabbit-tof-revA-bom-jlc.csv`, `fab/rabbit-tof-revA-cpl-jlc.csv` | JLC assembly BOM and CPL (top and bottom) |
| `fab/rabbit-tof-revA-bom-full.csv`, `fab/rabbit-tof-revA-stock.csv`, `fab/stock.json` | Full BOM with stock and price; stock of J1 alternatives |
| `fab/rabbit-tof-revA.step` | Board with parts, for the CAD bracket check |
| `renders/front.png`, `renders/back.png`, `renders/iso_front.png`, `renders/iso_back.png` | 3D renders. `back.png` is seen from behind |

## Order notes (JLCPCB)

- 2 layers, 1.6 mm, ENIG, green or black mask. Black mask lowers stray IR near the module. Quantity 10.
- Assembly: standard, both sides (J1 is on the bottom), "Confirm parts placement" on.
- **Pre-order J1** (genuine JST, Global Sourcing or consigned) before submitting (T-3).
- **Order remark to paste into the JLC order:** "U1 VL53L8CX: pin A1 (pin 1) is bottom-right in top view, at the pad with the small tab, next to the silk dot. The 2D code square on the cap is at the top-left (C7 corner, not pin 1). U3 LSF0204: pin 1 at the silk triangle (top-right). J1 (bottom side): contacts toward the board centre. Please confirm orientation before assembly."
- **Check in JLC's placement preview** and reject any view that differs:
  - U1 at rotation 0: A1 (the tabbed pad) is bottom-right in the front view, next to the silk dot. The 2D-code square of JLC's model must be at the top-left. The 2D code marks C7, not pin 1 (DS p.35).
  - U3 (TSSOP-14 at 270°, also 180° symmetric): pin 1 is top-right in the front view, next to the silk triangle and the library F.Fab chamfer.
  - J1 on the bottom (CPL rotation 0): its contacts face the board centre (front-view y −2.05; the MP tabs at y −5.4), and pin 1 is under the "1 GND" label. JLC's bottom-side rotations from KiCad are often 180° off.
  - D1: the cathode band is toward +3V3 (pad 1, bottom).
- VL53L8CX: MSL 3, reflow peak 240 °C recommended and 260 °C max, no-wash, dry reflow only (DS p.38–39). JLC's standard lead-free profile peaks at about 245 °C.

## Open items

| Item | Status |
|---|---|
| J1 sourcing | Genuine JST needs Global Sourcing or consignment. The look-alikes are unverified (see above) |
| 1.8 V rise slew (≥ 0.012 V/µs) and EN delay | By calculation only. Scope +1V8 and AVDD on the first board (V13) |
| Port power-cycle off time | ≥ 0.8 s (EN falls below VIL 350 ms after the port turns off, through D1 and R9). The ToF driver's reset path on the Pi must respect it (V13) |
| Mux and port order (review T-5) | Software rule: never select a TCA9548A channel whose port is off, and deselect the channel before switching a port off. Otherwise the Pi-side pull-ups back-feed the off port through the 4.7k pull-ups. The carrier itself stays isolated (LSF0204 Hi-Z with EN = 0) |
| Thermal (review T-6) | Bench check: 8×8 at 15 Hz continuous, on the bracket in the closed body, thermocouple on the cap. Above ~70 °C, slot the bracket face or lower the frame rate (V13) |
| AN5897 PDF | Read on st.com (pages 1, 3, 4). The download was blocked in the session, so it is not in `data/datasheets/st/` |
| Bracket | `cad/robot` bracket: window for J1 (≥ 11.5 × 6.5 mm, 4.3 mm deep), M2 holes at (±8.5, +4.0). The rest of the back is flat (tented vias, silk) |
| Driver | The zone order and orientation follow DS p.24 fig. 23. With the module's long axis along board X and A1 at the bottom-right, check the image orientation on the robot (V9) |
