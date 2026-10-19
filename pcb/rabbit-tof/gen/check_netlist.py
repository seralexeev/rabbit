"""Netlist and placement checks in place of ERC (the netlist is code, not a schematic):
- every net has at least two pins, and every unconnected pad is declared `nc` in design.py;
- VL53L8CX pins per DS14161 Rev 12 p.7 table 3 / p.8 fig. 5 (I2C): supplies, straps (2.2k SDA/SCL, 47k INT/SYNC/LPn
  pull-ups to IOVDD, 47k SPI_I2C_N/NCS pull-downs), RSVD to GND, MISO open; decoupling 4.7 uF AVDD, 100 nF CORE and
  IOVDD within 2.5 mm of their pins (DS p.8 note: as close as possible);
- 1.8 V rail: LP5907 IN +3V3, OUT +1V8 with >= 1 uF on both, EN delayed by an RC; the EN delay is checked against the
  slowest AVDD ramp from the body board's TPS259470L (CdVdt 2.2 nF, SLVSFC9C eq. 4 and IdVdt 0.81..3.82 uA p.10);
- LSF0204: Vref_A / EN on +1V8, Vref_B on +3V3, each A pin and B pin carry the same signal (X_1V8 <-> X);
- port: JST GH-6 pinout of the body board (1 GND, 2 +3V3, 3 SDA, 4 SCL, 5 INT, 6 LPN); no pull-ups on the 3.3 V side
  (the body board has them), no pull-down on LPn (DS: 47k pull-up on the sensor side);
- placement: Rx optical centre at design.OPTICAL, only J1 on the back, front parts no taller than the sensor, nothing
  under the M2 screw heads (d 3.8 mm + 0.3 mm);
- with --board: the board matches design.py pin for pin (needs KiCad's Python)."""
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design  # noqa: E402

errors = 0


def err(*a):
    global errors
    errors += 1
    print("ERROR:", *a)


by = {p["ref"]: p for p in design.PARTS}
pins = defaultdict(list)
for p in design.PARTS:
    for pad, net in p["pins"].items():
        pins[net].append(f'{p["ref"]}.{pad}')
print(f"{len(design.PARTS)} parts ({sum(p['bom'] == 'smt' for p in design.PARTS)} SMT), {len(pins)} nets")
for n, v in sorted(pins.items()):
    if len(v) < 2:
        err("single-pin net:", n, v)


def two_pin(value=None, fp_kind=None):
    for p in design.PARTS:
        if set(p["pins"]) == {"1", "2"} and (value is None or p["value"] == value) and \
                (fp_kind is None or fp_kind in p["fp"]):
            yield p


def between(a, b, value=None, kind=None):
    return [p for p in two_pin(value, kind) if set(p["pins"].values()) == {a, b}]


def dist(ref_a, ref_b_xy):
    ax, ay = by[ref_a]["at"]
    return math.hypot(ax - ref_b_xy[0], ay - ref_b_xy[1])


def pad_xy(ref, pad):
    """Board-frame position of a VL53L8CX pad (footprint frame: y down, columns 1..7 right to left)."""
    import footprints as F
    x0, y0 = by[ref]["at"]
    col = int(pad[1]) - 1
    lx = {"A": 2.25 - 0.75 * col, "C": 2.25 - 0.75 * col}.get(pad[0])
    ly = {"A": F.ROW_Y, "C": -F.ROW_Y}.get(pad[0])
    if pad == "B1":
        lx, ly = F.SIDE_X, 0.0
    if pad == "B7":
        lx, ly = -F.SIDE_X, 0.0
    return x0 + lx, y0 - ly


# ---------------------------------------------------------------- sensor
u1 = by["U1"]["pins"]
want = {"A3": "+1V8", "B7": "+1V8", "C4": "+3V3", "C3": "GND", "C7": "GND", "B4": "GND", "A6": "GND", "A7": "GND",
        "C6": "GND"}
for pad, net in want.items():
    if u1.get(pad) != net:
        err(f"U1.{pad} must be on {net}, is {u1.get(pad)}")
if "C5" in u1 or "C5" not in by["U1"]["nc"]:
    err("U1.C5 (MISO) must be left open in I2C mode (DS p.7)")
straps = [("SDA_1V8", "A4", "+1V8", "2.2k"), ("SCL_1V8", "A5", "+1V8", "2.2k"), ("INT_1V8", "A1", "+1V8", "47k"),
          ("LPN_1V8", "A2", "+1V8", "47k"), ("SYNC_1V8", "B1", "+1V8", "47k"), ("SPI_I2C_N", "C1", "GND", "47k"),
          ("NCS", "C2", "GND", "47k")]
for net, pad, rail, val in straps:
    if u1.get(pad) != net:
        err(f"U1.{pad} must be {net}")
    rs = between(net, rail, val)
    if len(rs) != 1:
        err(f"{net}: want exactly one {val} to {rail}, found {[r['ref'] for r in rs]}")
for rail, pad, val, lim in (("+3V3", "C4", "10uF", 2.5), ("+1V8", "B7", "100nF", 2.5), ("+1V8", "A3", "100nF", 2.5)):
    cs = [c for c in between(rail, "GND", val) if dist(c["ref"], pad_xy("U1", pad)) <= lim]
    if not cs:
        err(f"no {val} on {rail} within {lim} mm of U1.{pad}")
    else:
        print(f"U1.{pad} {rail}: {cs[0]['ref']} {val} at {dist(cs[0]['ref'], pad_xy('U1', pad)):.2f} mm")

# ---------------------------------------------------------------- 1.8 V LDO and its EN delay
u2 = by["U2"]["pins"]
if (u2.get("1"), u2.get("2"), u2.get("5")) != ("+3V3", "GND", "+1V8"):
    err("U2 LP5907 pins: 1 IN +3V3, 2 GND, 5 OUT +1V8")
for rail in ("+3V3", "+1V8"):
    if not [c for c in between(rail, "GND") if c["value"] in ("1uF", "10uF") and dist(c["ref"], by["U2"]["at"]) < 3.5]:
        err(f"LP5907 needs >= 1 uF on {rail} next to it (SNVS798Q p.4)")
en = u2.get("3")
r_up = between("+3V3", en, "100k")
c_en = between(en, "GND", "1uF")
d_en = [p for p in design.PARTS if p["fp"].endswith("D_SOD-323") and p["pins"] == {"1": "+3V3", "2": en}]
bleed = between("+3V3", "GND", "10k")
if not (r_up and c_en):
    err("LP5907 EN must be an RC from +3V3 (100k) to GND (1 uF)")
elif not (d_en and bleed):
    err("EN needs a Schottky to +3V3 (anode EN = pad 2, cathode +3V3 = pad 1) and a 10k bleed on +3V3 (review T-4)")
else:
    R, C, RPD, RB = 100e3, 1e-6, 1e6, 10e3   # LP5907 internal EN pull-down 1 MOhm (SNVS798Q 6.3.1)
    VIH, VIL = 1.2, 0.4                     # SNVS798Q p.6 (max / min)
    ILEAK = 10e-6                           # BAT54WS reverse leakage, generous hot value at 3.3 V (2 uA at 25 V, 25 C)
    sr_min = 2000 / 2200 * 0.81 / 2.21      # V/ms: SLVSFC9C eq. 4 with 2.2 nF, scaled by IdVdt min / typ
    dt, t, v_en, t_avdd, t_on = 1e-6, 0.0, 0.0, None, None
    while t < 0.3:
        v_in = min(3.3, sr_min * 1e3 * t)
        if t_avdd is None and v_in >= 3.13:
            t_avdd = t
        leak = ILEAK * min(1.0, max(0.0, v_in - v_en) / 3.3)
        v_en += dt * ((v_in - v_en) / R - v_en / RPD + leak) / C
        t += dt
        if v_en >= VIL and t_avdd is None:
            err(f"EN may pass VIL {VIL} V at {t * 1e3:.1f} ms, before AVDD reaches 3.13 V")
            break
        if v_en >= VIH:
            t_on = t
            break
    print(f"power-up: AVDD (slowest ramp {sr_min:.2f} V/ms) reaches 3.13 V at {t_avdd * 1e3:.1f} ms; EN reaches VIH max "
          f"{VIH} V at {t_on * 1e3:.1f} ms with {ILEAK * 1e6:.0f} uA diode leakage; then 1.8 V reaches 95 % in t_ON 80 us typ"
          f" / 150 us max (DS needs >= 0.012 V/us: 0.021 typ, 0.011 if all of t_ON max were ramp; scope it, V13)")
    # power-down: port eFuse off, no load but R9; rail C = carrier caps on +3V3 + the body board's 1 uF eFuse output cap
    c_rail = sum({"10uF": 10e-6, "1uF": 1e-6, "100nF": 0.1e-6}[c["value"]] for c in between("+3V3", "GND") if c["ref"].startswith("C")) + 1e-6
    v_rail, v_en, t, VF = 3.3, 3.3, 0.0, 0.15   # Schottky drop at uA currents (BAT54WS VF curve, ~0.1-0.2 V)
    dt = 1e-5
    while v_en > VIL - 0.05 and t < 5:
        i_d = max(0.0, (v_en - v_rail - VF)) / 50.0          # diode on: ~50 Ohm dynamic resistance
        v_en += dt * (-(v_en - v_rail) / R - v_en / RPD - i_d) / C
        v_rail += dt * (-v_rail / RB + i_d) / c_rail
        t += dt
    print(f"power-down: rail {c_rail * 1e6:.1f} uF x {RB / 1e3:.0f}k; EN below {VIL - 0.05:.2f} V after {t * 1e3:.0f} ms "
          f"-> keep a port off >= {max(0.5, round(t * 2 + 0.05, 1))} s before re-enabling it")

# ---------------------------------------------------------------- translator
u3 = by["U3"]["pins"]
if (u3.get("1"), u3.get("8"), u3.get("14"), u3.get("7")) != ("+1V8", "+1V8", "+3V3", "GND"):
    err("U3 LSF0204: 1 Vref_A and 8 EN on +1V8, 14 Vref_B on +3V3, 7 GND")
for a, b_ in (("2", "13"), ("3", "12"), ("4", "11"), ("5", "10")):
    na, nb = u3.get(a), u3.get(b_)
    if not na or na != f"{nb}_1V8":
        err(f"U3 channel A{int(a) - 1}/B{int(a) - 1}: {na} <-> {nb}")
print("LSF0204 channels:", ", ".join(f"{u3[a]} <-> {u3[b_]}" for a, b_ in (("2", "13"), ("3", "12"), ("4", "11"),
                                                                          ("5", "10"))))

# ---------------------------------------------------------------- port
j1 = by["J1"]
if j1["pins"] != {"1": "GND", "2": "+3V3", "3": "SDA", "4": "SCL", "5": "INT", "6": "LPN", "MP": "GND"}:
    err("J1 pinout differs from the body board port", j1["pins"])
for net in ("SDA", "SCL", "INT", "LPN"):
    rs = [p for p in two_pin() if net in p["pins"].values()]
    if rs:
        err(f"{net} (3.3 V side) must have no resistor here (pull-ups / series R are on the body board): {rs}")

# ---------------------------------------------------------------- placement
rx = (by["U1"]["at"][0] + design.RX_OFFSET[0], by["U1"]["at"][1] - design.RX_OFFSET[1])
if math.hypot(rx[0] - design.OPTICAL[0], rx[1] - design.OPTICAL[1]) > 1e-3:
    err("Rx optical centre at", rx, "want", design.OPTICAL)
print(f"Rx optical centre at ({rx[0]:.3f}, {rx[1]:.3f}), package centre at {by['U1']['at']}")
HEIGHT = {"VL53L8CX": 1.75, "SOD-323": 1.1, "C_0402": 0.55, "R_0402": 0.4, "C_0603": 0.9, "SOT-23-5": 1.45, "TSSOP-14": 1.2,
          "MountingHole": 0.0, "JST_GH": 4.25}
for p in design.PARTS:
    h = next((v for k, v in HEIGHT.items() if k in p["fp"] or k == p["value"]), None)
    if h is None:
        err("no height on record:", p["ref"], p["fp"])
    elif p["side"] == "F" and p["ref"] != "U1" and h >= design.SENSOR_H:
        err(f"{p['ref']} ({h} mm) is not lower than the sensor ({design.SENSOR_H} mm)")
    if p["side"] == "B" and p["ref"] != "J1":
        err("only J1 may be on the back (bracket side):", p["ref"])
    for hx, hy in design.HOLES:
        if p["bom"] != "none" and math.hypot(p["at"][0] - hx, p["at"][1] - hy) < 1.9 + 0.3 + 0.6:
            err(f"{p['ref']} under the M2 screw head at ({hx}, {hy})")
print("heights: tallest front part besides U1:",
      max((v, p["ref"]) for p in design.PARTS if p["side"] == "F" and p["ref"] != "U1"
          for k, v in HEIGHT.items() if k in p["fp"]))

if "--board" in sys.argv:
    import pcbnew
    b = pcbnew.LoadBoard(str(HERE.parent / "rabbit-tof.kicad_pcb"))
    diff = 0
    for fp in b.GetFootprints():
        p = by.get(fp.GetReference())
        for pad in fp.Pads():
            if not pad.GetNumber():
                continue
            want_n = p["pins"].get(pad.GetNumber(), "") if p else ""
            if pad.GetNetname() != want_n:
                print("board/design mismatch", fp.GetReference(), pad.GetNumber(), pad.GetNetname(), want_n)
                diff += 1
            if not want_n and p and pad.GetNumber() not in p["nc"] and p["bom"] != "none":
                print("undeclared open pad", fp.GetReference(), pad.GetNumber())
                diff += 1
    print("board matches design.py" if not diff else f"{diff} mismatches")
    errors += diff
print("netlist OK" if not errors else f"{errors} errors")
sys.exit(1 if errors else 0)
