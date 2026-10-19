"""Rabbit ToF carrier (VL53L8CX), revision A: parts, nets and placement (the netlist source of truth).

One board per ToF port of the body board (pcb/rabbit-body-c, JST GH-6 port: 1 GND, 2 switched 3.3 V, 3 SDA, 4 SCL,
5 INT, 6 LPn; the body board has the 4.7k SDA/SCL and 10k INT pull-ups to the port's 3.3 V, 1k in series with LPn from
a TCA6416A output, and the ESD diodes).

Datasheets (data/datasheets/):
- st/vl53l8cx-DS14161-rev12.pdf (DS14161 Rev 12, July 2025), cited as DS p.N;
- st AN5897 Rev 2 (PCB thermal guidelines, read on st.com: p.4 section 3 and figure 3);
- ti/lp5907.pdf (SNVS798Q), ti/lsf0204.pdf (SLVSCP5H), ti/tps25947.pdf (SLVSFC9C, the body board's port eFuse).

Supplies (DS p.4 table 1, p.11, p.20 tables 11-12): AVDD 3.3 V, CORE_1V8 1.8 V and IOVDD 1.2/1.8 V with an absolute
maximum of 1.98 V on CORE_1V8 and IOVDD, so the sensor cannot run from 3.3 V alone. AVDD comes from the port, CORE_1V8
and IOVDD share one LP5907 1.8 V LDO (DS p.20 note: same supply recommended), and a TI LSF0204 translates SDA, SCL,
INT and LPn between 1.8 V (A side) and 3.3 V (B side).

Board frame: mm, origin at the board centre, X right, Y up, looking at the sensor (front) face. `rot` is the KiCad
orientation; side "B" parts are flipped about their own Y axis, `at` stays in the front-view frame.
"""

REV = "A"
W, H = 22.0, 18.0
CORNER_R = 1.0
HOLES = [(-8.5, 4.0), (8.5, 4.0)]
OPTICAL = (0.0, 4.0)
RX_OFFSET = (-1.72, 0.10)   # Rx (SPAD) optical centre from the package centre, KiCad frame (y down): DS p.31 fig. 26
SENSOR_AT = (OPTICAL[0] - RX_OFFSET[0], OPTICAL[1] + RX_OFFSET[1])
SENSOR_H = 1.75             # DS p.31 fig. 26 (1.750 +-0.050)

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
GH6 = "Connector_JST:JST_GH_BM06B-GHS-TBT_1x06-1MP_P1.25mm_Vertical"
L8 = "rabbit_tof:ST_VL53L8CX_LGA-16_6.4x3.0mm"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
SOD323 = "Diode_SMD:D_SOD-323"
TSSOP14 = "Package_SO:TSSOP-14_4.4x5mm_P0.65mm"
HOLE = "MountingHole:MountingHole_2.2mm_M2"

LCSC_R = {"2.2k": "C25879", "10k": "C25744", "47k": "C25792", "100k": "C25741"}
LCSC_C = {"100nF": "C1525", "1uF": "C52923", "10uF": "C19702"}

PARTS = []
USED = set()


def part(ref, fp, value, at, rot=0, pins=None, bom="smt", lcsc=None, mpn=None, side="F", nc=()):
    """nc: pads deliberately left unconnected (checked by check_netlist.py)."""
    assert ref not in USED, f"duplicate ref {ref}"
    USED.add(ref)
    PARTS.append(dict(ref=ref, fp=fp, value=value, at=(round(at[0], 3), round(at[1], 3)), rot=rot % 360,
                      pins=pins or {}, bom=bom, lcsc=lcsc, mpn=mpn or value, side=side, nc=list(nc)))


def res(ref, value, at, a, b, rot=0):
    part(ref, R0402, value, at, rot, {"1": a, "2": b}, "smt", LCSC_R[value], f"0402 {value} 1%")


def cap(ref, value, at, a, b, rot=0, fp=C0402, mpn=None):
    part(ref, fp, value, at, rot, {"1": a, "2": b}, "smt", LCSC_C[value], mpn or f"{fp.split('_')[1]} {value} X5R/X7R")


def at(dx, dy):
    """Offset from the sensor package centre (board frame)."""
    return (SENSOR_AT[0] + dx, SENSOR_AT[1] + dy)


# ---------------------------------------------------------------- sensor (DS p.7 table 3, p.8 fig. 5: I2C mode)
part("U1", L8, "VL53L8CX", SENSOR_AT, 0,
     {"A1": "INT_1V8",      # GPIO1 = INT, open drain, 47k to IOVDD (R4)
      "A2": "LPN_1V8",      # LPn, 47k to IOVDD (R5); driven low through the LSF0204 to disable I2C
      "A3": "+1V8",         # IOVDD
      "A4": "SDA_1V8",      # 2.2k to IOVDD (R2)
      "A5": "SCL_1V8",      # 2.2k to IOVDD (R3)
      "A6": "GND", "A7": "GND", "C6": "GND",   # RSVD1..3: connect to ground
      "B1": "SYNC_1V8",     # GPIO2 = SYNC input, open drain, 47k to IOVDD (R6), unused
      "B4": "GND",          # thermal pad
      "B7": "+1V8",         # CORE_1V8
      "C1": "SPI_I2C_N",    # 47k to GND selects I2C (R7)
      "C2": "NCS",          # I2C: 47k to GND (R8)
      "C3": "GND", "C4": "+3V3", "C7": "GND"},
     "smt", "C7386355", "ST VL53L8CXV0GC/1", nc=["C5"])   # C5 MISO: I2C, do not connect
cap("C1", "10uF", at(-0.82, 2.65), "+3V3", "GND", 0, fp=C0603, mpn="Samsung CL10A106KP8NNNC 10uF 10V X5R 0603")
cap("C2", "100nF", at(-4.05, 0.0), "+1V8", "GND", 90)     # CORE_1V8 (B7)
cap("C3", "100nF", at(0.75, -2.4), "GND", "+1V8", 90)     # IOVDD (A3), courtyard overlap allowed in the .kicad_dru
res("R7", "47k", at(2.53, 2.75), "SPI_I2C_N", "GND", 90)
res("R8", "47k", at(1.28, 2.75), "NCS", "GND", 90)
res("R6", "47k", (6.4, 1.2), "SYNC_1V8", "+1V8", 0)
res("R4", "47k", (6.2, -1.6), "INT_1V8", "+1V8", 90)
res("R5", "47k", (7.3, -1.6), "LPN_1V8", "+1V8", 90)
res("R2", "2.2k", (-1.0, -1.6), "SDA_1V8", "+1V8", 90)
res("R3", "2.2k", (-2.1, -1.6), "SCL_1V8", "+1V8", 90)

# ---------------------------------------------------------------- 1.8 V: LP5907MFX-1.8 (SNVS798Q, DBV: 1 IN, 2 GND,
# 3 EN, 4 N/C, 5 OUT; CIN and COUT >= 1 uF p.4). EN is delayed by R1/C6 (with the internal 1 MOhm pull-down):
# CORE_1V8 and IOVDD start only after AVDD has settled (DS p.11 table 5, row "AVDD stable followed by CORE_1V8 and
# IOVDD": >= 0.012 V/us on 1V8, none on AVDD), then rise in t_ON 80 us typ / 150 us max (LP5907 p.6).
part("U2", SOT23_5, "LP5907-1.8", (-6.0, -4.2), 0,
     {"1": "+3V3", "2": "GND", "3": "LDO_EN", "5": "+1V8"}, "smt", "C92498", "TI LP5907MFX-1.8/NOPB", nc=["4"])
cap("C4", "1uF", (-8.6, -4.2), "GND", "+3V3", 90)
cap("C5", "1uF", (-3.4, -4.2), "GND", "+1V8", 90)
res("R1", "100k", (-6.95, -7.0), "+3V3", "LDO_EN", 0)
cap("C6", "1uF", (-5.0, -7.0), "LDO_EN", "GND", 0)
# EN discharge when the port drops (review round 2, T-4): the port eFuse has no output discharge, so without these the
# rail and C6 decay only through leakage and the 1 MOhm (tau ~1 s) and a quick re-enable would find EN still high (LDO
# tracking AVDD in dropout, too slow for DS p.11 table 5). R9 bleeds the port rail (10k x ~12 uF incl. the body board's
# 1 uF: tau 0.12 s, 1.1 mW on), D1 (Schottky, anode EN, cathode +3V3) pulls EN down with it. D1 is reverse-biased while
# the rail is up; its leakage only speeds the EN ramp a little (checked in check_netlist.py).
part("D1", SOD323, "BAT54WS", (-9.0, -7.2), 90, {"1": "+3V3", "2": "LDO_EN"}, "smt", "C124205",
     "Diodes BAT54WS-7-F Schottky 30 V SOD-323 (pad 1 cathode)")
res("R9", "10k", (-9.6, -4.2), "+3V3", "GND", 270)

# ---------------------------------------------------------------- LSF0204PWR (SLVSCP5H p.5 table 6-1, PW: 1 Vref_A,
# 2..5 A1..A4, 6/9 NC, 7 GND, 8 EN, 10..13 B4..B1, 14 Vref_B). Vref_A = 1.8 V, Vref_B = 3.3 V, EN = Vref_A (p.13
# fig. 10-1; EN is referenced to Vref_A, so the switches stay off until the 1.8 V rail is up). Rotated so that the A
# pins 2..5 (INT, LPn, SDA, SCL) face the sensor's A row in the same order; the pull-ups sit beside it.
part("U3", TSSOP14, "LSF0204", (2.4, -3.8), 270,
     {"1": "+1V8", "2": "INT_1V8", "3": "LPN_1V8", "4": "SDA_1V8", "5": "SCL_1V8", "7": "GND", "8": "+1V8",
      "10": "SCL", "11": "SDA", "12": "LPN", "13": "INT", "14": "+3V3"},
     "smt", "C202288", "TI LSF0204PWR", nc=["6", "9"])

# ---------------------------------------------------------------- port: JST GH-6 vertical on the back (body board
# pinout). The only part on the back: the bracket behind the board has a window for it.
part("J1", GH6, "GH-6", (0.0, -4.0), 180,
     {"1": "GND", "2": "+3V3", "3": "SDA", "4": "SCL", "5": "INT", "6": "LPN", "MP": "GND"},
     "smt", "C3011957", "HCTL HC-GH-6PLT (GH-compatible, JST BM06B land; JLC stock)", side="B")

for i, (x, y) in enumerate(HOLES):
    part(f"H{i + 1}", HOLE, "M2", (x, y), 0, bom="none")

SILK = [  # (text, X, Y, size, side)
    ("RABBIT ToF L8CX", 0.0, 6.6, 1.0, "B"),
    ("rev A  github.com/seralexeev/rabbit", 0.0, -8.0, 0.7, "B"),
    ("CABLE 1:1", -6.6, 2.0, 0.6, "B"),     # same-direction GH-6 cable, pin 1 to pin 1 (review round 2, T-7)
]
POWER = ["+3V3", "+1V8", "GND"]
# hand-routed before the autorouter (net, layer, points, width; a point may be "REF.PAD"): the AVDD feed from J1 pin 2
# straight up the back to C1 / U1 C4, its branch to the LDO input, and the LDO output to the CORE_1V8 decoupler C2
ROUTES = [("+3V3", "B.Cu", ["J1.2", (-1.875, 6.75)], 0.3),
          ("+3V3", "F.Cu", [(-1.875, 6.75), "C1.1"], 0.3),
          ("+3V3", "B.Cu", [(-1.875, -0.6), (-6.0, -0.6)], 0.3),
          ("+3V3", "F.Cu", [(-6.0, -0.6), (-7.14, -1.74), "U2.1"], 0.3),
          ("+1V8", "F.Cu", ["U2.5", (-3.2, -1.6), (-3.2, -1.12), (-3.2, 3.0), "C2.1"], 0.3),
          ("+1V8", "F.Cu", [(-3.2, -1.12), "R3.2", "R2.2"], 0.3)]
ROUTE_VIAS = [("+3V3", (-1.875, 6.75)), ("+3V3", (-6.0, -0.6))]
# GND stitching vias (front pour islands -> back pour), placed before routing
STITCH = [(-5.0, 1.0), (-4.6, 3.0), (-9.6, 0.0), (-9.6, 7.6), (-1.6, 7.9), (9.6, 7.6), (9.6, 0.0), (9.6, -6.6),
          (6.5, -6.9)]
