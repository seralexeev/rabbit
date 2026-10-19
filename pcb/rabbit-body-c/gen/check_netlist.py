"""Netlist checks in place of ERC (the netlist is code, not a schematic):
- every net has at least two pins (DNP footprints count: they keep the copper);
- every IC power, ground and bus pin is on a net (per part value, pins from data/pcb-revc/ics/*.json);
- DRV8243 VM on MOT_BUS and GND on GND_MOT; star ground: no part touches both GND and GND_MOT except the net tie NT1;
- every TPS259470L EN is a PCAL6524 0x22 output with a pull-down, every FLT a 0x23 input with a pull-up;
- I2C addresses are unique on the Pi's I2C1 and I2C6 (ToF mux only) and on the STM32's I2C3 (straps decoded per datasheet tables);
- with --board: the board matches design.py pin for pin."""
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


pins = defaultdict(list)
for p in design.PARTS:
    for pad, net in p["pins"].items():
        pins[net].append(f'{p["ref"]}.{pad}')
smt = sum(p["bom"] == "smt" for p in design.PARTS)
tht = sum(p["bom"] == "tht" for p in design.PARTS)
print(f"{len(design.PARTS)} parts ({smt} SMT, {tht} THT, "
      f"{sum(p['bom'] == 'dnp' for p in design.PARTS)} DNP), {len(pins)} nets")
for n, v in sorted(pins.items()):
    if len(v) < 2:
        err("single-pin net:", n, v)

by = {p["ref"]: p for p in design.PARTS}
R = lambda a, b: [str(i) for i in range(a, b + 1)]  # noqa: E731
MUST = {   # value -> pins that must be on a net
    "STM32G474RET6": ["1", "15", "16", "27", "28", "29", "31", "32", "47", "48", "63", "64", "7", "49", "50", "30",
                      "55", "5", "6", "61"],
    "LM61495": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "11", "12", "13", "14", "15", "16"],
    "TPS16630": ["1", "2", "3", "6", "7", "8", "9", "10", "11", "13", "14", "15", "18", "19", "20", "21"],
    "LM74800": R(1, 12), "TLV75533": ["1", "2", "3", "5"], "SN74LVC1G132": R(1, 5), "LM393": ["1", "2", "3", "4", "8"],
    "TL431": R(1, 3), "INA238": R(1, 10), "DRV8243H": R(1, 14), "TPS259470L": ["1", "2", "4", "5", "6", "7", "8", "9",
                                                                              "10"],
    "TPS259470A": ["1", "2", "4", "5", "6", "7", "8", "9", "10"],
    "LM5069-1": R(1, 10), "TPS62826": R(1, 6), "TPS2121": R(1, 12), "REF3425": R(1, 6),
    "ADS7128": ["7", "8", "9", "10", "12", "13", "14", "17"], "PCAL6524": R(1, 33), "TCA9548A": R(1, 25),
    "TCA6416A": R(1, 25), "ICM-42688-P": R(1, 14), "TMP117 0x48": ["1", "2", "4", "5", "6"],
    "TMP117 0x49": ["1", "2", "4", "5", "6"], "TCAN1044AV": R(1, 9), "PCA9685PW": ["14", "23", "24", "25", "26", "27",
                                                                                  "28"],
    "DS3231SN": ["2", "13", "14", "15", "16"], "USBLC6-2SC6": R(1, 6), "74AHCT1G125": R(1, 5), "SK9822-EC20": R(1, 6),
    "MMC5983MA": ["1", "2", "4", "9", "11", "13", "16"],
    "TLV76050": R(1, 3), "BSS138": R(1, 3),
}
seen_vals = set()
for p in design.PARTS:
    need = MUST.get(p["value"])
    if need is None:
        continue
    seen_vals.add(p["value"])
    miss = [x for x in need if x not in p["pins"]]
    if miss:
        err("unconnected power/bus pin:", p["ref"], p["value"], miss)
for v in MUST:
    if v not in seen_vals:
        err("no part with value", v)

for p in design.PARTS:
    if p["value"] == "DRV8243H":
        if p["pins"]["4"] != "MOT_BUS" or p["pins"]["6"] != "GND_MOT":
            err(p["ref"], "VM/GND", p["pins"]["4"], p["pins"]["6"])
    if p["value"] == "STM32G474RET6":
        for pad in ("1", "16", "32", "48", "64"):
            if p["pins"][pad] != "+3V3_MCU":
                err("MCU VDD", pad, p["pins"][pad])

for p in design.PARTS:
    s = set(p["pins"].values())
    if {"GND", "GND_MOT"} <= s and p["ref"] != "NT1":
        err("star ground broken by", p["ref"], p["pins"])
mot = sorted(p["ref"] for p in design.PARTS if "GND_MOT" in p["pins"].values())
print("on GND_MOT:", " ".join(mot))

# eFuse control: EN on the 0x22 expander with a pull-down, FLT on 0x23 with a pull-up (or an ADC GPIO)
en_out = {n for p in design.PARTS if p["value"] == "PCAL6524" and p["pins"]["26"] == "GND" for n in p["pins"].values()}
flt_in = {n for p in design.PARTS if p["value"] == "PCAL6524" and p["pins"]["26"] == "+3V3_PI"
          for n in p["pins"].values()}
pulled = defaultdict(set)
for p in design.PARTS:
    if p["fp"] in (design.RARRAY, design.R0603):
        ps = p["pins"]
        pairs = [(ps.get(str(k)), ps.get(str(9 - k))) for k in range(1, 5)] if p["fp"] == design.RARRAY else \
            [(ps.get("1"), ps.get("2"))]
        for a, b in pairs:
            for x, y in ((a, b), (b, a)):
                if y in ("GND", "+3V3_PI", "+3V3_MCU", "ADC_AVDD"):
                    pulled[x].add(y)
for p in design.PARTS:
    if p["value"] not in ("TPS259470L", "TPS259470A"):
        continue
    en, flt = p["pins"]["1"], p["pins"]["4"]
    if p["ref"] == "U87":   # Pi USB-C power: always on with the board (EN pulled up), never on the expander
        if en in en_out or not any(q["fp"] in (design.R0603, design.R0402) and set(q["pins"].values()) == {en, "+5V"}
                                   for q in design.PARTS):
            err("U87 EN must be pulled up to +5V and not on the expander:", en)
    elif en not in en_out or "GND" not in pulled[en]:
        err(p["ref"], "EN not an 0x22 output with pull-down:", en)
    if not ((flt in flt_in and "+3V3_PI" in pulled[flt]) or "ADC_AVDD" in pulled[flt]):
        err(p["ref"], "FLT not pulled up to a monitored input:", flt)
if "+3V3_MCU" not in pulled["MOT_BUS_OFF"] or "MOT_BUS_OFF" not in en_out:
    err("MOT_BUS_OFF must be an 0x22 output pulled up (motor bus off by default)")

# I2C addresses
strap = {"GND": 0, "+3V3_PI": 1, "+3V3_MCU": 1, "I2C1_SDA": 2, "I2C1_SCL": 3, "I2C3_SDA": 2, "I2C3_SCL": 3}
bus = defaultdict(lambda: defaultdict(list))
res_on = defaultdict(list)
for p in design.PARTS:
    if p["fp"] in (design.R0603,):
        res_on[p["pins"]["1"]].append(p)
        res_on[p["pins"]["2"]].append(p)
for p in design.PARTS:
    v, ps = p["value"], p["pins"]
    if v == "INA238":
        bus["I2C1"][0x40 | strap[ps["1"]] << 2 | strap[ps["2"]]].append(p["ref"])
    elif v == "ADS7128":
        a = ps.get("11")
        rs = [r for r in res_on.get(a, []) if r["bom"] != "dnp"] if a else []
        if not rs:
            addr = 0x10
        else:
            other = [n for n in rs[0]["pins"].values() if n != a][0]
            addr = {("GND", "11k"): 0x11, ("GND", "33k"): 0x12, ("GND", "100k"): 0x13}.get((other, rs[0]["value"]))
            if other.endswith("_DECAP"):
                addr = {"0": 0x17, "11k": 0x16, "33k": 0x15, "100k": 0x14}[rs[0]["value"]]
        bus["I2C1"][addr].append(p["ref"])
    elif v == "PCAL6524":
        bus["I2C1"][{"I2C1_SCL": 0x20, "I2C1_SDA": 0x21, "GND": 0x22, "+3V3_PI": 0x23}[ps["26"]]].append(p["ref"])
    elif v == "TCA6416A":
        bus["I2C1"][0x20 | strap[ps["18"]]].append(p["ref"])
    elif v == "TCA9548A":
        bus["I2C6" if ps["19"] == "I2C6_SCL" else "I2C1"][0x70 | strap[ps["18"]] << 2 | strap[ps["23"]] << 1 |
                                                         strap[ps["22"]]].append(p["ref"])
    elif v == "PCA9685PW":
        a = sum(strap[ps[pin]] << bit for bit, pin in enumerate(("1", "2", "3", "4", "5", "24")))
        bus["I2C1"][0x40 | a].append(p["ref"])
        bus["I2C1"][0x70].append(p["ref"] + " (All Call)")
    elif v == "DS3231SN":
        bus["I2C1"][0x68].append(p["ref"])
    elif v.startswith("TMP117"):
        bus["I2C3"][{"GND": 0x48, "+3V3_MCU": 0x49, "I2C3_SDA": 0x4A, "I2C3_SCL": 0x4B}[ps["4"]]].append(p["ref"])
    elif v == "MMC5983MA":
        bus["I2C3"][0x30].append(p["ref"])
for b, addrs in sorted(bus.items()):
    for a, refs in sorted(addrs.items()):
        print(f"{b} 0x{a:02x}: {' '.join(refs)}")
        if len(refs) > 1:
            err("I2C address clash", b, hex(a), refs)
want = {0x11, 0x17, 0x20, 0x22, 0x23, 0x40, 0x41, 0x43, 0x47, 0x60, 0x68, 0x70}
if set(bus["I2C6"]) != {0x77}:
    err("I2C6 must carry only the ToF mux 0x77:", bus["I2C6"])
if set(bus["I2C1"]) != want:
    err("I2C1 map differs from i2c_address_map.json:", sorted(hex(a) for a in set(bus["I2C1"]) ^ want))

# heights (spec section 2): bottom parts <= 8 mm over the motors (Y -60..-130), <= 10 mm elsewhere; nothing on the top
# under the Pi (its standoffs leave ~6 mm, the Pi's own bottom parts need the rest). Body heights above the board (mm)
# from the package drawings, rounded up.
HEIGHT = {"Fiducial": 0.0, "R_0603": 0.6, "C_0603": 0.9, "C_0805": 1.4, "C_1210": 2.7, "R_1206": 0.7, "R_Array": 0.6, "SOT-23": 1.2,
          "D_SMA": 2.4, "D_SMB": 2.6, "MSOP-10": 1.1, "HTSSOP-20": 1.2, "QFN-32": 0.6, "WQFN": 0.8, "VQFN": 1.0,
          "USON-10": 0.6, "WSON-6": 0.8, "VSON-8": 1.0, "VQFN-HR": 1.0, "VSON-HR": 1.0, "XxL4020": 2.1,
          "LED_0603": 0.8, "JST_GH_SM06B": 4.3, "JST_GH_BM06B": 4.25, "D_SOD-323": 1.1, "JST_PH_B6B-PH-SM4": 6.0, "XT30PW-F": 5.6, "XT30UPB-F": 11.2, "R_Shunt": 1.2}
for p in design.PARTS:
    if p["side"] != "B":
        continue
    h = next((v for k, v in HEIGHT.items() if k in p["fp"]), None)
    lim = 8.0 if -130.0 <= p["at"][1] <= -60.0 else 10.0
    if abs(p["at"][0]) > 50.0 and p["at"][1] > -60.0:
        lim = 12.0   # deck edge between the wheels, outboard of the Jetson: room down to deck 1 (cad/robot)
    if h is None:
        err("bottom part with no height on record:", p["ref"], p["fp"])
    elif h > lim:
        err(f"bottom part too tall: {p['ref']} {h} mm > {lim} mm at Y {p['at'][1]}")
pi = by["MOD1"]["at"]
for p in design.PARTS:
    x, y = p["at"]
    if p["side"] == "F" and p["ref"] != "MOD1" and pi[0] - 42.5 < x < pi[0] + 42.5 and pi[1] - 28 < y < pi[1] + 28:
        err("top part under the Raspberry Pi:", p["ref"])
print("bottom side:", sum(p["side"] == "B" for p in design.PARTS), "parts, heights within limits;",
      "top side:", sum(p["side"] == "F" for p in design.PARTS), "parts")

if "--board" in sys.argv:
    import pcbnew
    b = pcbnew.LoadBoard(str(HERE.parent / "rabbit-body-c.kicad_pcb"))
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
    print("board matches design.py" if not diff else f"{diff} mismatches")
    errors += diff
print("netlist OK" if not errors else f"{errors} errors")
sys.exit(1 if errors else 0)
