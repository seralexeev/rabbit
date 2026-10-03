"""Rabbit 2.0 body board, revision B: parts, nets and placement (the netlist source of truth).

Rev A (git: f36dd87) carried Pololu modules, a RoboClaw and ATO fuses. Rev B puts everything on the board as parts
JLCPCB assembles: an LM74800 ideal-diode power switch with a soft latch, SMD fuses, eFuses, two LM61495 bucks,
an STM32G474 + 2 x DRV8316 BLDC drive with a hardware brake chopper, and INA226 monitors.
Design notes and datasheet pages: docs/reports/2026-10-03-body-pcb-rev-b.md; numbers: gen/calc.py.

Board frame: mm, origin at the deck centre, +X = robot right, +Y = robot front, top view. `rot` is the KiCad
footprint orientation in degrees. `bom`: "smt" / "tht" = assembled by JLCPCB from LCSC stock, "hand" = soldered by
the owner, "module" = existing module on standoffs, "none" = mechanical or copper only.
Grounds: GND is the logic ground; GND_MOT is the motor power ground (DRV8316 PGND/AGND, bulk caps, brake chopper)
and joins GND only at the star NT1 next to the battery connector.
"""

REV = "B"
K = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/"

R0603 = "Resistor_SMD:R_0603_1608Metric"
R0402 = "Resistor_SMD:R_0402_1005Metric"
R0805 = "Resistor_SMD:R_0805_2012Metric"
R2512 = "Resistor_SMD:R_2512_6332Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"
CPOLY = "Capacitor_SMD:CP_Elec_8x10.5"
LED0603 = "LED_SMD:LED_0603_1608Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
SOD123 = "Diode_SMD:D_SOD-123"
SOD323 = "Diode_SMD:D_SOD-323"
SMB = "Diode_SMD:D_SMB"
TDSON = "Package_TO_SOT_SMD:TDSON-8-1"
FUSE = "rabbit_body:Fuse_Littelfuse_NANO2_451_2410"
SHUNT = "rabbit_body:R_Shunt_2512_Kelvin"
DRV_FP = "rabbit_body:TI_RGF0040E_VQFN-40_5x7mm_P0.5mm_EP3.7x5.7mm"
BUCK_FP = "rabbit_body:TI_RPH0016B_VQFN-HR-16_3.5x4.5mm"
EFUSE_FP = "Package_SO:HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP3.4x6.5mm_Mask2.96x2.96mm_ThermalVias"
INA_FP = "Package_SO:MSOP-10_3x3mm_P0.5mm"
JP3 = "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm_NumberLabels"

LCSC_R = {"39k": "C23153", "0": "C21189", "10": "C22859", "22": "C23345", "100": "C22775", "220": "C22962", "330": "C23138",
          "1k": "C21190", "1.5k": "C22843", "4.7k": "C23162", "4.99k": "C23046", "5.1k": "C23186", "10k": "C25804",
          "22k": "C31850", "24k": "C23352", "20k": "C4184", "33k": "C4216", "47k": "C25819", "60.4k": "C23089",
          "68k": "C23231", "100k": "C25803", "150k": "C22807", "220k": "C22961", "1M": "C22935",
          "1.5M": "C4172", "3.9k": "C23018", "6.04k": "C25977"}
LCSC_C = {"10pF": "C1634", "18pF": "C1647", "1nF": "C1588", "10nF": "C57112", "22nF": "C21122", "47nF": "C1622",
          "100nF": "C14663", "470nF": "C1623", "1uF": "C15849", "2.2uF": "C23630", "4.7uF": "C19666",
          "10uF": "C15850", "10uF50V": "C77102", "22uF": "C12891", "220uF35V": "C454287"}

PARTS = []


def part(ref, fp, value, at, rot=0, pins=None, bom="smt", lcsc=None, mpn=None, label=None):
    PARTS.append(dict(ref=ref, fp=fp, value=value, at=at, rot=rot, pins=pins or {}, bom=bom, lcsc=lcsc,
                      mpn=mpn or value, label=label))


def res(ref, value, at, a, b, rot=0, fp=R0603):
    lcsc = {"22": "C25092"}[value] if fp == R0402 else LCSC_R[value]
    part(ref, fp, value, at, rot, {"1": a, "2": b}, "smt", lcsc, f"{fp.split('_')[1]} {value} 1%")


def cap(ref, value, at, a, b, rot=0, fp=C0603):
    lcsc = {"100nF": "C1525", "1uF": "C52923", "47nF": "C272875"}[value] if fp == C0402 else LCSC_C[value]
    part(ref, fp, value.replace("50V", " 50V").replace("35V", " 35V"), at, rot, {"1": a, "2": b}, "smt", lcsc, value)


def led(ref, at, anode, rot=0, k="GND"):
    part(ref, LED0603, "LED red", at, rot, {"1": k, "2": anode}, "smt", "C2286", "KT-0603R (JLC basic)")


def nfet(ref, at, gate, drain, rot=0, source="GND"):
    part(ref, SOT23, "AO3400A", at, rot, {"1": gate, "2": source, "3": drain}, "smt", "C20917", "AO3400A")


def tvs(ref, at, k, a="GND", rot=0, bidir=False):
    part(ref, SMB, "SMBJ20CA" if bidir else "SMBJ20A", at, rot, {"1": k, "2": a}, "smt",
         "C151258" if bidir else "C151257", "Littelfuse SMBJ20CA" if bidir else "Littelfuse SMBJ20A")


def ina226(ref, at, rot, inp, inn, vbus, a1, a0, label=None):
    """INA226 (SBOS547C p.3): 1 A1, 2 A0, 3 ALERT, 4 SDA, 5 SCL, 6 VS, 7 GND, 8 VBUS, 9 IN-, 10 IN+. VBUS is tied to the
    adjacent IN- (the load side of the shunt behind its 10 Ohm filter resistor: VBUS draws ~20 uA, 0.2 mV), so it
    needs no track of its own to the bus."""
    part(ref, INA_FP, "INA226", at, rot, {"1": a1, "2": a0, "3": "INA_ALERT", "4": "I2C1_SDA", "5": "I2C1_SCL",
                                          "6": "+3V3_PI", "7": "GND", "8": vbus, "9": inn, "10": inp},
         "smt", "C49851", "INA226AIDGSR", label)


def shunt(ref, value, at, rot, a, b, kp, kn, lcsc, mpn):
    part(ref, SHUNT, value, at, rot, {"1": a, "2": b, "3": kp, "4": kn}, "smt", lcsc, mpn)


def ina_filter(prefix, at, kp, kn, inp, inn, dx=1.6, rot=90):
    """10 Ohm in each sense line + 100 nF across (INA226 p.14, rev A review N2)."""
    x, y = at
    res(f"R{prefix}1", "10", (x, y), kp, inp, rot)
    res(f"R{prefix}2", "10", (x + dx, y), kn, inn, rot)
    cap(f"C{prefix}", "100nF", (x + 2 * dx, y), inp, inn, rot)


def buck(n, at, vin, vout, fb_bot, label):
    """LM61495 (SNVSBZ4A): 414 kHz (RT 39k to GND, p.16 eq. 3: 16.4 / (39 + 0.633)), auto PFM (MODE -> GND), no
    spread spectrum (SPSP -> GND),
    BIAS from the output, EN divider 100k/22k (starts at 7.0 V). Values from table 9-2 (p.33).
    Layout per p.48-50 (figure 11-2): the 470 nF caps right at the VIN/PGND pin pairs and the 10 uF ones outside
    them, CBOOT beside RBOOT/CBOOT with SW brought out between VIN2 and RBOOT, CBIAS at BIAS, SW straight to the
    inductor in front."""
    x, y = at
    sw, boot, vcc, fb, en = f"SW{n}", f"BOOT{n}", f"VCC{n}", f"FB{n}", f"EN{n}"
    part(f"U{n}", BUCK_FP, "LM61495", (x, y), 0,
         {"1": "GND", "2": vin, "3": boot, "4": boot, "5": vout, "6": vcc, "7": fb, "8": "GND", "9": f"RT{n}",
          "11": "GND", "12": "GND", "13": en, "14": vin, "15": "GND", "16": sw}, "smt", "C2943584", "LM61495RPHR", label)
    cap(f"C{n}01", "10uF50V", (x - 4.9, y + 1.65), vin, "GND", 90, C1210)
    cap(f"C{n}02", "10uF50V", (x + 4.9, y + 1.65), vin, "GND", 90, C1210)
    cap(f"C{n}03", "470nF", (x - 2.55, y + 1.65), vin, "GND", 90)
    cap(f"C{n}04", "470nF", (x + 2.55, y + 1.65), vin, "GND", 90)
    cap(f"C{n}05", "100nF", (x - 2.45, y - 0.55), boot, sw, 90, C0402)
    cap(f"C{n}06", "1uF", (x - 1.3, y - 3.75), "GND", vcc, 90)
    cap(f"C{n}07", "100nF", (x - 3.0, y - 2.2), "GND", vout, 0, C0402)
    part(f"L{n}", "Inductor_SMD:L_Coilcraft_XAL1010-XXX", "3.3uH", (x, y + 10.0), 90, {"1": sw, "2": vout}, "smt",
         "C3911672", "Coilcraft XAL1010-332ME 3.3 uH 4.1 mOhm 18 A sat")
    res(f"R{n}01", "100k", (x - 1.325, y - 6.7), vout, fb, 0)
    res(f"R{n}02", fb_bot, (x + 1.3, y - 6.7), fb, "GND", 0)
    res(f"R{n}03", "4.99k", (x - 2.6, y - 8.3), vout, f"FF{n}", 0)
    cap(f"C{n}08", "10pF", (x, y - 8.3), f"FF{n}", fb, 0)
    res(f"R{n}04", "100k", (x + 3.0, y - 3.5), en, vin, 0)
    res(f"R{n}05", "22k", (x + 3.0, y - 5.1), en, "GND", 0)
    res(f"R{n}06", "39k", (x + 0.95, y - 4.2), "GND", f"RT{n}", 90)
    for i, (dx, dy) in enumerate(((-6.0, 19.5), (-3.0, 19.5), (0.0, 19.5), (3.0, 19.5), (6.0, 19.5))):
        cap(f"C{n}{10 + i}", "22uF", (x + dx, y + dy), vout, "GND", 90, C1206)


def drv8316(n, side, at, bulk_at, bulk_rot=0):
    """DRV8316CR (SPI) per SLVSF16B: pins p.4-5, external parts table 8-1 p.19, buck in resistor mode p.25-26
    (disabled by BUCK_DIS after boot), 3x PWM mode (Mode 3: INHx = PWM, INLx = enable, VREF -> AVDD; the VREF cap is optional, p.19,
    and left out so the SPI and current-sense pins fan out freely). Charge-pump, CP and buck-resistor parts are
    0402 so their pads line up with the 0.5 mm pins without crossings.
    Pads (rot 0, board frame): VM 9-11 left-low, CP/CPH/CPL 8-6 left-middle, buck 3-5 left-high, outputs 13-20
    along the rear edge, logic 21-32 on the right, SPI and current-sense 33-40 along the front."""
    x, y = at
    s = side
    vm, g = "MOT_BUS", "GND_MOT"
    pins = {"2": g, "3": f"BK_{s}", "4": g, "5": f"SWBK_{s}", "6": f"CPL_{s}", "7": f"CPH_{s}", "8": f"CP_{s}",
            "9": vm, "10": vm, "11": vm, "12": g, "13": f"M{s}A", "14": f"M{s}A", "15": g, "16": f"M{s}B",
            "17": f"M{s}B", "18": g, "19": f"M{s}C", "20": f"M{s}C", "21": "DRVOFF", "22": "DRV_NFAULT",
            "23": "DRV_NSLEEP", "25": f"AVDD_{s}", "26": g, "27": f"INHA_{s}", "28": f"INL_{s}",
            "29": f"INHB_{s}", "30": f"INL_{s}", "31": f"INHC_{s}", "32": f"INL_{s}", "33": "SPI_MISO",
            "34": "SPI_MOSI", "35": "SPI_SCK", "36": f"NSCS_{s}", "37": f"AVDD_{s}", "38": f"SOC_{s}",
            "39": f"SOB_{s}", "40": f"SOA_{s}", "41": g}
    part(f"U{n}", DRV_FP, "DRV8316CR", (x, y), 0, pins, "smt", "C5447274", "DRV8316CRRGFR",
         f"DRV8316 {'L' if s == 'L' else 'R'}")
    cap(f"C{n}01", "100nF", (x - 4.6, y - 4.35), g, vm, 90)
    cap(f"C{n}02", "100nF", (x - 6.2, y - 4.35), g, vm, 90)
    cap(f"C{n}03", "10uF50V", (x - 8.4, y - 2.6), vm, g, 90, C1210)
    cap(f"C{n}04", "1uF", (x - 3.35, y - 1.27), vm, f"CP_{s}", 90, C0402)
    cap(f"C{n}05", "47nF", (x - 4.3, y - 0.25), f"CPH_{s}", f"CPL_{s}", 90, C0402)
    res(f"R{n}01", "22", (x - 3.35, y + 1.25), f"SWBK_{s}", f"BK_{s}", 90, R0402)
    cap(f"C{n}06", "10uF", (x - 8.0, y + 2.4), f"BK_{s}", g, 90, C0805)
    cap(f"C{n}07", "1uF", (x + 4.6, y - 0.75), f"AVDD_{s}", g, 0)
    part(f"C{n}09", CPOLY, "220uF 35V", bulk_at, bulk_rot, {"1": vm, "2": g}, "smt", LCSC_C["220uF35V"],
         "Panasonic EEH-ZK1V221UP 220 uF 35 V hybrid polymer, AEC-Q200")


def csa_rc(n, s, at):
    """Current-sense outputs to the ADC: 100 Ohm + 1 nF at the MCU pin (BLDC report 8.4)."""
    x, y = at
    for i, ph in enumerate("ABC"):
        res(f"R{n}{2 + i:02d}", "100", (x, y - 1.6 * i), f"SO{ph}_{s}", f"ADC_{ph}{s}", 0)
        cap(f"C{n}{10 + i}", "1nF", (x + 3.0, y - 1.6 * i), f"ADC_{ph}{s}", "GND", 0)


# ---------------------------------------------------------------- mechanical
for i, (x, y, d) in enumerate([(-38.0916, -121.8873, 4.3), (38.0916, -121.8873, 4.3), (-38.0916, 107.636, 4.3),
                               (38.0916, 107.636, 4.3), (-55.2597, 84.9505, 3.2), (55.2597, 84.9505, 3.2)]):
    fp = "MountingHole:MountingHole_4.3mm_M4" if d > 4 else "MountingHole:MountingHole_3.2mm_M3"
    part(f"H{i + 1}", fp, "deck standoff M4" if d > 4 else "deck standoff M3", (x, y), bom="none")

part("MOD1", "rabbit_body:RaspberryPi4_Standoffs", "Raspberry Pi 4", (13.0, -4.0), 0, bom="module",
     mpn="Raspberry Pi 4 Model B + 4x M2.5x6 standoffs")

# ---------------------------------------------------------------- power input: XT60 -> F1 -> LM74800 ideal diode + switch
# (SNOSDD8: pins p.3, EN/OV thresholds p.5, inrush eq.2 p.16, common-drain FETs with VS at the mid-point p.1/p.19)
part("J1", "Connector_AMASS:AMASS_XT60-M_1x02_P7.20mm_Vertical", "XT60 BAT", (50.0, -99.3), 270,
     {"1": "BAT_IN", "2": "GND"}, "tht", "C19268037", "AMASS XT60PB-M vertical", "BATTERY")
part("F1", FUSE, "15A", (50.0, -89.0), 90, {"1": "BAT_IN", "2": "BAT_F"}, "smt", "C44480",
     "Littelfuse 0451015.MRL 15 A 65 V", "F1 15A")
tvs("D7", (42.4, -95.5), "BAT_F", rot=270, bidir=True)
part("Q1", TDSON, "BSC010N04LS", (50.0, -80.0), 90, {"1": "BAT_F", "2": "BAT_F", "3": "BAT_F", "4": "DG",
                                                        "5": "SW_MID"}, "smt", "C501508",
     "Infineon BSC010N04LS OptiMOS 5 40 V 1.0 mOhm")
part("Q2", TDSON, "BSC010N04LS", (50.0, -66.5), 270, {"1": "VBUS_RAW", "2": "VBUS_RAW", "3": "VBUS_RAW",
                                                         "4": "HG", "5": "SW_MID"}, "smt", "C501508",
     "Infineon BSC010N04LS OptiMOS 5 40 V 1.0 mOhm")
part("U10", "rabbit_body:TI_DRR0012E_WSON-12_3x3mm_P0.5mm_EP1.3x2.5mm", "LM74800", (42.0, -73.5), 0,
     {"1": "DG", "2": "BAT_F", "3": "BAT_F", "4": "LM_SW", "5": "LM_OV", "6": "LM_EN", "7": "GND", "8": "HG",
      "9": "VBUS_RAW", "10": "SW_MID", "11": "LM_CAP", "12": "SW_MID"}, "smt", "C7216630", "LM74800MDRRR",
     "POWER SWITCH")
cap("C20", "100nF", (45.4, -70.6), "LM_CAP", "SW_MID", 0)
cap("C21", "100nF", (45.4, -76.4), "SW_MID", "GND", 180)
cap("C22", "100nF", (38.4, -71.0), "BAT_F", "GND", 90)
res("R40", "150k", (36.8, -74.0), "LM_SW", "LM_OV", 90)
res("R41", "10k", (35.2, -74.0), "LM_OV", "GND", 90)
res("R42", "100", (46.9, -61.2), "HG", "HG_DV", 90)
cap("C23", "47nF", (45.3, -61.2), "HG_DV", "GND", 90)
# soft latch: button pole 1 (BTN_ON to GND) turns Q4 on -> EN high; VBUS holds EN through D8 (8.2 V) while
# VBUS > 9.6 V; the Pi's gpio-poweroff (GPIO17) pulls EN low through Q5, and C25 holds Q5 on ~1 s after the Pi dies
part("Q4", SOT23, "MMBT3906", (38.0, -86.5), 0, {"1": "LATCH_B", "2": "BAT_F", "3": "LATCH_C"}, "smt", "C75549",
     "Nexperia MMBT3906,215 PNP 40 V")
res("R43", "100k", (34.8, -84.5), "BAT_F", "LATCH_B", 90)
res("R44", "22k", (34.8, -88.5), "LATCH_B", "BTN_ON", 90)
res("R45", "47k", (38.0, -82.4), "LATCH_C", "LM_EN", 0)
res("R46", "220k", (38.4, -78.6), "LM_EN", "GND", 0)
cap("C24", "10nF", (38.4, -77.0), "LM_EN", "GND", 0)
part("D8", SOD123, "BZT52C8V2", (36.0, -65.0), 90, {"1": "VBUS_RAW", "2": "HOLD_Z"}, "smt", "C173432", "BZT52C8V2")
res("R47", "47k", (36.0, -69.4), "HOLD_Z", "LM_EN", 90)
nfet("Q5", (39.6, -65.0), "OFF_G", "LM_EN", 90)
res("R48", "1k", (35.6, -60.4), "GPIO17", "OFF_A", 0)
part("D9", SOD323, "1N4148WS", (38.9, -60.4), 0, {"1": "OFF_G", "2": "OFF_A"}, "smt", "C2128", "1N4148WS")
cap("C25", "1uF", (42.3, -60.4), "OFF_G", "GND", 0)
res("R49", "1M", (42.3, -62.0), "OFF_G", "GND", 0)
cap("C26", "100nF", (34.8, -91.6), "BTN_ON", "GND", 90)

# battery shunt (INA226 0x41: A1 = GND, A0 = VS) -> VBUS
shunt("R1", "2mR 3W", (50.0, -55.0), 90, "VBUS_RAW", "VBUS", "SH1_P", "SH1_N", "C154685", "LR2512-23R002F4")
ina_filter("70", (41.4, -52.0), "SH1_P", "SH1_N", "INA1_P", "INA1_N")
ina226("U21", (42.0, -56.4), 0, "INA1_P", "INA1_N", "INA1_N", "GND", "+3V3_PI", "INA BAT 0x41")
cap("C27", "100nF", (39.0, -53.9), "+3V3_PI", "GND", 0)
tvs("D1", (56.0, -48.5), "VBUS", rot=90)
part("C30", CPOLY, "220uF 35V", (51.0, -37.5), 0, {"1": "VBUS", "2": "GND"}, "smt", LCSC_C["220uF35V"],
     "Panasonic EEH-ZK1V221UP 220 uF 35 V hybrid polymer, AEC-Q200")
cap("C31", "10uF50V", (45.5, -45.0), "VBUS", "GND", 90, C1210)
cap("C32", "10uF50V", (41.6, -45.0), "VBUS", "GND", 90, C1210)
res("R39", "10k", (56.6, -57.5), "LEDB_A", "VBUS", 90)
led("D5", (56.6, -61.0), "LEDB_A", 90)

# star ground: GND_MOT joins GND here only
part("NT1", "rabbit_body:NetTie_3.5mm", "star GND", (42.5, -106.5), 90, {"1": "GND_MOT", "2": "GND"}, "none")

# ---------------------------------------------------------------- motor branch: F2 -> 5 mOhm (INA226 0x45) -> MOT_BUS
part("F2", FUSE, "8A", (36.0, -48.5), 180, {"1": "VBUS", "2": "MOT_F"}, "smt", "C142876",
     "Littelfuse 0451008.MRL 8 A 125 V", "F2 MOTORS 8A")
shunt("R3", "5mR 3W", (27.0, -48.5), 180, "MOT_F", "MOT_BUS", "SH3_P", "SH3_N", "C154688", "LR2512-23R005F4")
ina_filter("71", (23.0, -41.0), "SH3_P", "SH3_N", "INA3_P", "INA3_N")
ina226("U22", (32.0, -40.0), 0, "INA3_P", "INA3_N", "INA3_N", "+3V3_PI", "+3V3_PI", "INA MOT 0x45")
cap("C28", "100nF", (34.4, -42.7), "+3V3_PI", "GND", 0)

drv8316(11, "L", (-26.0, -106.0), (-45.5, -103.0))
drv8316(12, "R", (26.0, -106.0), (29.5, -93.0), 270)
tvs("D10", (-16.0, -95.5), "MOT_BUS", "GND_MOT", rot=0)
for s, nx, ny in (("L", -20.0, -101.5), ("R", 34.0, -101.5)):         # NTC at each DRV8316, referenced to GND_MOT (offset is mV)
    n = "65" if s == "L" else "66"
    part(f"RT{n}", "Resistor_SMD:R_0603_1608Metric", "NTC 10k", (nx, ny), 90, {"1": f"NTC_{s}", "2": "GND_MOT"},
         "smt", "C13564", "NCP18XH103F03RB 10k B3380")
    res(f"R{n}", "10k", (36.6, -98.5) if s == "R" else (nx, -88.6), "+3V3_MCU", f"NTC_{s}", 90)

# phase, Hall and encoder connectors (rear edge; encoders vertical GH behind the Hall connectors)
for side, sgn in (("L", -1), ("R", 1)):
    n = "41" if side == "L" else "42"
    part(f"J{n}", "Connector_Molex:Molex_KK-396_A-41791-0003_1x03_P3.96mm_Vertical", "motor phases",
         (sgn * 26.0 - 3.96, -129.5), 0,
         {"1": f"M{side}A", "2": f"M{side}B", "3": f"M{side}C"}, "tht", "C240823", "Molex 26-60-4030 KK 396 7 A",
         f"MOTOR {side}")
    hx = sgn * 12.5
    n2 = "43" if side == "L" else "44"
    part(f"J{n2}", "Connector_JST:JST_PH_B5B-PH-K_1x05_P2.00mm_Vertical", "Halls", (hx - 4.0, -129.5), 0,
         {"1": f"5V_HALL_{side}", "2": "GND", "3": f"H{side}A", "4": f"H{side}B", "5": f"H{side}C"}, "tht",
         "C157993", "JST B5B-PH-K-S", f"HALL {side}")
    n3 = "45" if side == "L" else "46"
    part(f"J{n3}", "Connector_JST:JST_GH_BM07B-GHS-TBT_1x07-1MP_P1.25mm_Vertical", "encoder", (hx, -120.3), 0,
         {"1": f"5V_HALL_{side}", "2": "+3V3_MCU", "3": "GND", "4": f"ENC_{side}_A", "5": f"ENC_{side}_B",
          "6": f"ENC_{side}_Z", "7": "GND"}, "smt", "C378970", "JST BM07B-GHS-TBT", f"ENC {side} A/B/Z or SSI")
    res(f"R{n3}1", "10", (sgn * 20.3, -115.8), "+5V", f"5V_HALL_{side}", 90, R0805)
    cap(f"C{n3}1", "1uF", (sgn * 20.3, -119.6), f"5V_HALL_{side}", "GND", 90)
res("R30", "4.7k", (-4.4, -121.0), "BUMPER_REAR", "+3V3_PI", 90)
cap("C12", "100nF", (4.4, -121.0), "BUMPER_REAR", "GND", 90)

# brake chopper: LM393 on MOT_BUS with a TL431 reference, on 17.67 V / off 17.18 V (gen/calc.py), drives
# NCEP4090GU into 4 x 39 Ohm 2 W in parallel; works without the MCU and without the 5 V rail
for i, bx in enumerate((-9.0, -3.0, 3.0, 9.0)):
    part(f"R5{i}", R2512, "39R 2W", (bx, -97.5), 90, {"1": "BRK_D", "2": "MOT_BUS"}, "smt", "C175263",
         "CRH2512F39R0E04Z 2 W")
part("Q6", TDSON, "BSC026N04LS", (0.0, -106.0), 90, {"1": "GND_MOT", "2": "GND_MOT", "3": "GND_MOT",
                                                       "4": "BRK_G", "5": "BRK_D"}, "smt", "C3039672",
     "Infineon BSC026N04LS 40 V 2.6 mOhm (lower gate charge for the 10k pull-up)")
part("U17", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "LM393", (-10.0, -106.5), 0,
     {"1": "BRK_G", "2": "BRK_REF", "3": "BRK_SNS", "4": "GND_MOT", "5": "GND_MOT", "6": "BRK_REF",
      "8": "BRK_VCC"}, "smt", "C7955", "LM393DR2G")
res("R55", "100", (-15.6, -104.2), "MOT_BUS", "BRK_VCC", 0)
cap("C55", "1uF", (-15.6, -105.8), "BRK_VCC", "GND_MOT", 0)
part("U18", SOT23, "TL431", (-15.6, -109.6), 0, {"1": "BRK_REF", "2": "BRK_REF", "3": "GND_MOT"}, "smt", "C6971",
     "TL431BCDBZR 0.5 %")
res("R56", "4.7k", (-15.6, -112.6), "MOT_BUS", "BRK_REF", 0)
res("R57", "60.4k", (-10.0, -111.0), "MOT_BUS", "BRK_SNS", 0)
res("R58", "10k", (-10.0, -112.6), "BRK_SNS", "GND_MOT", 0)
res("R59", "1.5M", (-6.4, -111.0), "BRK_G", "BRK_SNS", 90)
res("R60", "10k", (7.4, -107.0), "MOT_BUS", "BRK_G", 90)
part("D11", SOD123, "BZT52C12", (5.4, -107.0), 90, {"1": "BRK_G", "2": "GND_MOT"}, "smt", "C173429", "BZT52C12")
res("R61", "100k", (9.0, -107.0), "BRK_G", "BRK_SENSE", 90)
res("R62", "33k", (13.0, -89.0), "BRK_SENSE", "GND", 90)
res("R63", "100k", (-7.8, -88.6), "MOT_BUS", "VMOT_SENSE", 90)
res("R64", "10k", (-6.2, -88.6), "VMOT_SENSE", "GND", 90)
cap("C63", "100nF", (-4.6, -88.6), "VMOT_SENSE", "GND", 90)

# ---------------------------------------------------------------- STM32G474RET6 (LQFP-64), pins: DS12288 table 12 p.57-61,
# AF table 13 p.73-79. TIM1 CH1-3 PA8-10 (AF6) -> left DRV, TIM8 CH1-3 PC6-8 (AF4) -> right DRV, TIM1_BKIN PB12 (AF6) and
# TIM8_BKIN PD2 (AF4) <- ESTOP; SPI3 PC10-12 (AF6) -> both DRV8316; incremental encoders (5 V A/B/I, BLDC report 8)
# on 5 V tolerant pins: A/B on timer encoder pairs (left TIM4 CH1/CH2 PB6/PB7, right TIM3 CH1/CH2 PB4/PB5, AF2; TIM5 is
# only on PA0-PA3 in LQFP-64), I on PB3 (left, EXTI3) and PC9 (right, TIM3_CH4 capture: EXTI9 is the right Hall C);
# the same lines can clock an SSI encoder by GPIO (A = CLK, B = DO, I = CSN); PB4/PB6 carry the UCPD dead-battery
# pull-downs until firmware sets PWR_CR3.UCPD_DBDIS;
# USART2 PA2/PA3 (AF7) <- Pi UART0; servo option TIM17_CH1 PA7 (AF1); current sense on ADC1/2-shared channels only,
# so the STM32G431RBT6 (same LQFP-64 pinout, 2 ADCs) fits as a fallback; Halls on 5 V tolerant FT pins.
MCU = {"1": "+3V3_MCU", "2": "HLA_M", "3": "HLB_M", "4": "HLC_M", "5": "OSC_IN", "6": "OSC_OUT", "7": "MCU_NRST",
       "8": "ADC_CL", "9": "ADC_AR", "10": "ADC_BR", "11": "ADC_CR", "12": "ADC_AL", "13": "ADC_BL",
       "14": "MCU_TX", "15": "GND", "16": "+3V3_MCU", "17": "MCU_RX", "18": "VMOT_SENSE", "19": "INL_R",
       "20": "DRV_NFAULT", "21": "SERVO_MCU", "22": "NTC_L", "23": "BRK_SENSE", "24": "DRV_NSLEEP", "25": "BUMP_F_M",
       "26": "BUMP_R_M", "27": "GND", "28": "+3V3_MCU", "29": "+3V3_MCU", "30": "INL_L", "31": "GND",
       "32": "+3V3_MCU", "33": "NTC_R", "34": "ESTOP", "35": "MCU_ALIVE", "36": "MCU_LED", "37": "NSCS_R",
       "38": "INHA_R", "39": "INHB_R", "40": "INHC_R", "41": "ENC_R_Z_M", "42": "INHA_L", "43": "INHB_L",
       "44": "INHC_L", "45": "HRA_M", "46": "HRB_M", "47": "GND", "48": "+3V3_MCU", "49": "SWDIO", "50": "SWCLK",
       "51": "NSCS_L", "52": "SPI_SCK", "53": "SPI_MISO", "54": "SPI_MOSI", "55": "ESTOP", "56": "ENC_L_Z_M",
       "57": "ENC_R_A_M", "58": "ENC_R_B_M", "59": "ENC_L_A_M", "60": "ENC_L_B_M", "61": "MCU_BOOT0", "62": "HRC_M",
       "63": "GND", "64": "+3V3_MCU"}
MX, MY = -3.0, -74.0
part("U1", "Package_QFP:LQFP-64_10x10mm_P0.5mm", "STM32G474RET6", (MX, MY), 0, MCU, "smt", "C521608",
     "STM32G474RET6 (alt. STM32G431RBT6 C431633, same pinout)", "MOTOR MCU")
for i, (dx, dy, r) in enumerate(((-7.7, -3.75, 90), (4.0, -7.7, 0), (7.7, 3.75, 90), (-3.75, 7.7, 0))):
    cap(f"C12{i}", "100nF", (MX + dx, MY + dy), "+3V3_MCU", "GND", r)
cap("C84", "4.7uF", (MX - 9.4, MY - 3.75), "+3V3_MCU", "GND", 90)
cap("C85", "1uF", (MX + 0.8, MY - 7.7), "+3V3_MCU", "GND", 0)
cap("C86", "10nF", (MX + 0.8, MY - 9.3), "+3V3_MCU", "GND", 0)
cap("C87", "100nF", (MX - 9.4, MY + 0.75), "MCU_NRST", "GND", 90)
part("Y1", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", "8MHz", (MX - 9.6, MY + 4.4), 0,
     {"1": "OSC_IN", "2": "GND", "3": "OSC_OUT", "4": "GND"}, "smt", "C367183", "8 MHz 12 pF 3225")
cap("C88", "18pF", (MX - 13.4, MY + 5.6), "OSC_IN", "GND", 0)
cap("C89", "18pF", (MX - 13.4, MY + 3.2), "OSC_OUT", "GND", 0)
part("U15", SOT23_5, "TLV75533", (MX + 10.0, MY + 10.5), 0, {"1": "+5V", "2": "GND", "3": "+5V", "5": "+3V3_MCU"},
     "smt", "C404027", "TLV75533PDBVR 3.3 V 500 mA")
cap("C90", "1uF", (MX + 13.2, MY + 10.5), "+5V", "GND", 90)
cap("C91", "4.7uF", (MX + 6.8, MY + 10.5), "+3V3_MCU", "GND", 90)
res("R90", "10k", (MX - 9.5, MY + 9.0), "MCU_BOOT0", "GND", 0)
res("R91", "1k", (MX - 9.5, MY + 10.6), "GPIO0", "MCU_BOOT0", 0)
res("R92", "1k", (MX - 9.5, MY + 12.2), "GPIO1", "MCU_NRST", 0)
res("R93", "1k", (MX + 10.0, MY + 14.6), "MCU_LED", "MCU_LED_A", 0)
led("D93", (MX + 13.4, MY + 14.6), "MCU_LED_A", 180)
part("J47", "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical_SMD", "SWD", (MX - 2.0, MY + 13.4), 90,
     {"1": "+3V3_MCU", "2": "SWDIO", "3": "GND", "4": "SWCLK", "5": "GND", "9": "GND", "10": "MCU_NRST"}, "smt",
     "C5382952", "Samtec FTSH-105-01-F-DV-K (ARM Cortex 10-pin)", "SWD")
# DRV8316 shared lines and enables (pulled to the safe state while the MCU is in reset)
for i, (ref, val, a, b) in enumerate((("R94", "5.1k", "DRV_NFAULT", "+3V3_MCU"), ("R95", "10k", "SPI_MISO", "+3V3_MCU"),
                                      ("R96", "100k", "DRV_NSLEEP", "GND"), ("R97", "100k", "INL_L", "GND"),
                                      ("R98", "100k", "INL_R", "GND"), ("R99", "10k", "NSCS_L", "+3V3_MCU"),
                                      ("R9A", "10k", "NSCS_R", "+3V3_MCU"))):
    res(ref, val, (MX + 10.0 + 1.6 * i, MY - 9.0), a, b, 90)
# encoder lines: 22 Ohm in series at the MCU on A/CLK, B/DO and Z/CSN
for s, x0 in (("L", MX - 14.5), ("R", MX + 10.5)):
    for i, (sig, a, b) in enumerate((("Z", f"ENC_{s}_Z_M", f"ENC_{s}_Z"), ("A", f"ENC_{s}_A_M", f"ENC_{s}_A"),
                                     ("B", f"ENC_{s}_B", f"ENC_{s}_B_M"))):
        res(f"R13{i + (0 if s == 'L' else 3)}", "22", (x0 + 1.6 * i, MY - 13.0), a, b, 90)
# current-sense RC at the ADC pins (left side of the MCU)
csa_rc(11, "L", (MX - 19.0, MY + 0.5))
csa_rc(12, "R", (MX - 19.0, MY - 5.5))
# Hall inputs: 1k series + 4.7k pull-up + 1 nF at the MCU (Hall outputs are open collector or 5 V push-pull;
# PC13-15, PA11, PA12, PB9 are 5 V tolerant FT pins). The XYT 3625 has no Halls once its driver is removed:
# the connectors stay for a bare BLDC with Halls.
for i, (h, m, x, y) in enumerate((("HLA", "HLA_M", MX - 24.0, MY + 16.0), ("HLB", "HLB_M", MX - 22.4, MY + 16.0),
                                  ("HLC", "HLC_M", MX - 20.8, MY + 16.0), ("HRA", "HRA_M", MX + 12.0, MY + 3.0),
                                  ("HRB", "HRB_M", MX + 13.6, MY + 3.0), ("HRC", "HRC_M", MX + 15.2, MY + 3.0))):
    res(f"R10{i}", "1k", (x, y), h, m, 90)
    res(f"R11{i}", "4.7k", (x, y + 3.2), h, "+3V3_MCU", 90)
    cap(f"C10{i}", "1nF", (x, y - 3.2), m, "GND", 90)
# bumpers also to the MCU (inputs only; the Pi keeps its pull-ups and the safety node)
res("R32B", "1k", (MX + 3.0, MY - 11.2), "BUMPER_FRONT", "BUMP_F_M", 0)
res("R33B", "1k", (MX + 3.0, MY - 12.8), "BUMPER_REAR", "BUMP_R_M", 0)
# E-stop: Pi GPIO16 -> 100 Ohm -> loop jumper J5 -> ESTOP (10k to GND here: a dead Pi, an open loop or a broken
# wire is STOP). ESTOP -> TIM1_BKIN (PB12) + TIM8_BKIN (PD2): low-side brake at once, no code.
# ESTOP -> 100k/2.2uF (~0.29 s) and MCU_ALIVE (charge pump) -> Schmitt NAND -> DRVOFF: all six FETs off.
res("R16", "100", (-31.7, -13.0), "GPIO16", "ESTOP_A", 90)
part("J5", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", "E-stop loop", (-36.0, -31.5), 90,
     {"1": "ESTOP_A", "2": "ESTOP"}, "tht", "C2915055", "Wurth 61300211121 1x2 header + jumper (or the NC E-stop)",
     "E-STOP")
res("R17", "10k", (MX + 17.6, MY + 9.0), "ESTOP", "GND", 90)
res("R18", "100k", (MX + 19.2, MY + 9.0), "ESTOP", "ESTOP_DLY", 90)
cap("C18", "2.2uF", (MX + 20.8, MY + 9.0), "ESTOP_DLY", "GND", 90)
part("U16", SOT23_5, "SN74LVC1G132", (MX + 19.6, MY + 4.4), 0, {"1": "ESTOP_DLY", "2": "ALIVE_DET", "3": "GND",
                                                                "4": "DRVOFF", "5": "+3V3_MCU"}, "smt", "C403723",
     "SN74LVC1G132DBVR Schmitt NAND")
cap("C19", "100nF", (MX + 22.8, MY + 4.4), "+3V3_MCU", "GND", 90)
cap("C14A", "100nF", (MX + 17.6, MY - 2.0), "MCU_ALIVE", "ALIVE_AC", 90)
part("D12", SOT23, "BAT54S", (MX + 20.6, MY - 2.0), 0, {"1": "GND", "2": "ALIVE_DET", "3": "ALIVE_AC"}, "smt",
     "C8592", "BAT54S")
cap("C14B", "100nF", (MX + 23.6, MY - 2.0), "ALIVE_DET", "GND", 90)
res("R14B", "100k", (MX + 25.2, MY - 2.0), "ALIVE_DET", "GND", 90)

# ---------------------------------------------------------------- Pi UART0 -> MCU USART2 (PA2/PA3, bootloader port, AN2606),
# or to a RoboClaw (fallback) by moving the solder jumpers; RoboClaw power from MOT_BUS / GND_MOT
res("R10", "100", (-31.7, -20.0), "GPIO14", "UART0_TX", 90)
res("R11", "100", (-31.7, -16.5), "UART0_RX", "GPIO15", 90)
part("JP1", JP3, "UART0 TX", (-36.0, -20.0), 0, {"1": "MCU_RX", "2": "UART0_TX", "3": "RC_S1"}, "none")
part("JP2", JP3, "UART0 RX", (-36.0, -16.5), 0, {"1": "MCU_TX", "2": "UART0_RX", "3": "RC_S2"}, "none")
part("J48", "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical", "RoboClaw S", (-54.5, -40.0), 270,
     {"1": "RC_S1", "2": "RC_S2", "3": "ESTOP", "4": "GND"}, "tht", "C144395", "JST B4B-XH-A",
     "ROBOCLAW S")
# motor-bus output: RoboClaw B+/B- for the fallback, or a spare battery-level output (rev A's F7/J20) sharing F2 10 A
part("J49", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal", "MOT_BUS out",
     (-53.0, -95.0), 90, {"1": "MOT_BUS", "2": "GND_MOT"}, "tht", "C7509570", "Phoenix Contact MKDS 1,5/2-5,08 (1729128)",
     "VMOT OUT")

# ---------------------------------------------------------------- front: VBUS strip, Jetson eFuse, 5.1 V and 6 V bucks
tvs("D13", (45.5, 30.5), "VBUS", rot=90)
part("C33", CPOLY, "220uF 35V", (37.5, 43.5), 0, {"1": "VBUS", "2": "GND"}, "smt", LCSC_C["220uF35V"],
     "Panasonic EEH-ZK1V221UP 220 uF 35 V hybrid polymer, AEC-Q200")

# Jetson: TPS16630 eFuse straight from VBUS (Jetson J16 takes 9-20 V), 4.48 A limit, 9.6 V UVLO, 19.2 V OVP,
# auto-retry (68k/10k UVLO 9.4 V, 3.9k ILIM 4.6 A); SHDN has an internal pull-up (2.48-3.3 V open circuit, p.9): Q7 (GPIO25 high) turns the Jetson off.
# TPS1663 pins: SLVSET9G p.5-6 (HTSSOP).
JE = (-6.0, 47.0)
part("U5", EFUSE_FP, "TPS16630", JE, 0,
     {"1": "VBUS", "2": "VBUS", "3": "VBUS", "6": "VBUS", "7": "JET_UVLO", "8": "JET_OVP", "9": "GND",
      "10": "JET_DVDT", "11": "JET_ILIM", "12": "GND", "13": "JET_SHDN", "18": "JET_OUT", "19": "JET_OUT",
      "20": "JET_OUT", "21": "GND"}, "smt", "C1849461", "TPS16630PWPR 60 V 6 A eFuse", "JETSON EFUSE")
res("R80", "68k", (JE[0] - 6.0, JE[1] - 1.6), "JET_UVLO", "VBUS", 90)
res("R81", "10k", (JE[0] - 7.6, JE[1] - 1.6), "JET_UVLO", "GND", 90)
res("R82", "150k", (JE[0] - 6.0, JE[1] - 4.8), "VBUS", "JET_OVP", 90)
res("R83", "10k", (JE[0] - 7.6, JE[1] - 4.8), "JET_OVP", "GND", 90)
cap("C80", "47nF", (JE[0] - 9.2, JE[1] - 3.2), "JET_DVDT", "GND", 90)
res("R84", "3.9k", (JE[0] + 6.0, JE[1] - 3.0), "JET_ILIM", "GND", 90)
nfet("Q7", (JE[0] + 7.0, JE[1] + 1.4), "Q7_G", "JET_SHDN", 0)
res("R86", "1k", (JE[0] + 10.4, JE[1] + 1.4), "GPIO25", "Q7_G", 90)
res("R87", "100k", (JE[0] + 7.0, JE[1] + 4.4), "Q7_G", "GND", 0)
cap("C81", "100nF", (JE[0] - 5.5, JE[1] + 4.6), "VBUS", "GND", 0)
cap("C82", "1uF", (JE[0] + 2.6, JE[1] + 5.6), "JET_OUT", "GND", 0, C0805)
shunt("R4", "10mR 1W", (JE[0] + 1.0, JE[1] + 10.0), 0, "JET_OUT", "JET_PWR", "SH4_P", "SH4_N", "C844901",
      "Vishay WSL2512R0100FEA 10 mOhm 1 W")
ina_filter("72", (JE[0] + 7.5, JE[1] + 6.8), "SH4_P", "SH4_N", "INA4_P", "INA4_N")
ina226("U19", (JE[0] + 10.0, JE[1] + 11.0), 0, "INA4_P", "INA4_N", "INA4_N", "+3V3_PI", "I2C1_SDA", "INA JET 0x46")
cap("C83", "100nF", (JE[0] + 11.0, JE[1] + 14.6), "+3V3_PI", "GND", 0)
tvs("D14", (-19.0, 69.0), "JET_PWR", rot=90)
part("J21", "Connector_AMASS:AMASS_XT30PW-F_1x02_P2.50mm_Horizontal", "XT30 JETSON", (-27.5, 72.0), 90,
     {"1": "JET_PWR", "2": "GND"}, "tht", "C2913282", "AMASS XT30PW-F", "JETSON 9-20V")
res("R38", "4.7k", (-40.5, 59.5), "JET_PWR", "LED12_A", 90)
led("D4", (-40.5, 63.0), "LED12_A", 270)

# 5.17 V body rail (Pi, lidar, ToF LDO, MCU LDO, Halls, fan): F3 5 A -> LM61495 (100k/24k)
part("F3", FUSE, "5A", (-40.6, 37.0), 0, {"1": "VBUS", "2": "BODY_IN"}, "smt", "C48467",
     "Littelfuse 0451005.MRL 5 A", "F3 5V 5A")
buck(4, (-30.0, 45.0), "BODY_IN", "+5V", "24k", "5.2V BUCK")
cap("C9", "10uF", (-22.4, 38.4), "+5V", "GND", 90, C0805)
cap("C13", "10uF", (-15.5, 37.5), "+3V3_PI", "GND", 0, C0805)
res("R36", "1k", (-47.0, 30.5), "+5V", "LED5_A", 90)
led("D2", (-47.0, 34.0), "LED5_A", 270)

# 6 V servo rail: F4 5 A -> LM61495 -> 10 mOhm (INA226 0x44) -> servo headers
part("F4", FUSE, "5A", (28.0, 38.5), 180, {"1": "VBUS", "2": "STEER_IN"}, "smt", "C48467",
     "Littelfuse 0451005.MRL 5 A", "F4 6V 5A")
buck(6, (14.0, 45.0), "STEER_IN", "6V_RAW", "20k", "6V SERVO BUCK")
shunt("R2", "10mR 1W", (34.0, 52.5), 270, "6V_RAW", "SERVO_6V", "SH2_P", "SH2_N", "C844901",
      "Vishay WSL2512R0100FEA 10 mOhm 1 W")
ina_filter("73", (24.5, 48.5), "SH2_P", "SH2_N", "INA2_P", "INA2_N")
ina226("U20", (27.5, 56.5), 0, "INA2_P", "INA2_N", "INA2_N", "+3V3_PI", "GND", "INA 6V 0x44")
cap("C29", "100nF", (23.2, 56.5), "+3V3_PI", "GND", 90)
res("R37", "1.5k", (38.6, 58.0), "SERVO_6V", "LED6_A", 90)
led("D3", (38.6, 61.5), "LED6_A", 270)

# ToF 3.3 V (TPS73733, EN pulled to 5 V, Q8 pulls it low when GPIO18 is high), as rev A
part("U7", "Package_TO_SOT_SMD:SOT-223-6", "TPS73733", (-6.0, 75.0), 0,
     {"1": "+5V", "2": "+3V3_TOF", "3": "GND", "4": "TPS_NR", "5": "TOF_EN", "6": "GND"}, "smt", "C31334",
     "TPS73733DCQR")
cap("C6", "10uF", (-13.0, 73.0), "+5V", "GND", 90, C0805)
cap("C7", "10uF", (0.5, 73.0), "+3V3_TOF", "GND", 90, C0805)
cap("C8", "10nF", (-10.0, 79.5), "TPS_NR", "GND", 0)
res("R26", "100k", (-10.0, 82.0), "TOF_EN", "+5V", 0)
nfet("Q8", (-1.5, 81.0), "Q8_G", "TOF_EN", 0)
res("R22", "1k", (3.0, 80.0), "GPIO18", "Q8_G", 90)
res("R23", "100k", (-1.5, 84.6), "Q8_G", "GND", 0)
res("R40A", "330", (5.0, 74.5), "+3V3_TOF", "LED33_A", 90)
led("D6", (5.0, 78.0), "LED33_A", 270)

# ---------------------------------------------------------------- Pi header (40-pin IDC, ribbon to the Pi)
PI_PINS = {1: "+3V3_PI", 2: "+5V", 3: "I2C1_SDA", 4: "+5V", 5: "I2C1_SCL", 6: "GND", 7: "TOF_FL_SDA", 8: "GPIO14",
           9: "GND", 10: "GPIO15", 11: "GPIO17", 12: "GPIO18", 13: "GPIO27", 14: "GND", 15: "TOF_RR_SDA",
           16: "TOF_RR_SCL", 17: "+3V3_PI", 18: "INA_ALERT", 19: "TOF_RL_SDA", 20: "GND", 21: "GPIO9", 22: "GPIO25",
           23: "TOF_RL_SCL", 24: "GPIO8", 25: "GND", 26: "TOF_FR_SCL", 27: "GPIO0", 28: "GPIO1", 29: "TOF_FL_SCL",
           30: "GND", 31: "TOF_FR_SDA", 32: "GPIO12", 33: "GPIO13", 34: "GND", 35: "GPIO19", 36: "GPIO16",
           37: "POWER_BTN", 38: "BUMPER_FRONT", 39: "GND", 40: "BUMPER_REAR"}
part("J3", "Connector_IDC:IDC-Header_2x20_P2.54mm_Vertical", "Pi 40-pin", (-21.13, 28.73), 90,
     {str(k): v for k, v in PI_PINS.items()}, "tht", "C7433390", "Wurth 61204021621 2x20 box header",
     "RASPBERRY PI 40-PIN (ribbon)")
res("R31", "10k", (20.0, -36.5), "INA_ALERT", "+3V3_PI", 0)
res("R12", "100", (-23.0, 84.0), "GPIO8", "LIDAR_RX", 90)
res("R13", "100", (-21.0, 84.0), "LIDAR_TX", "GPIO9", 90)
res("R14", "1k", (-19.0, 84.0), "GPIO12", "JET_UART_RX", 90)
res("R15", "1k", (-17.0, 84.0), "JET_UART_TX", "GPIO13", 90)

# ToF x4 (VL53L8CX on Pololu 3419): VIN, GND, SCL, GND, SDA; 4.7k pull-ups on the board (rev A review N3)
for ref, at, pre, label in (("J8", (-22.0, 129.0), "TOF_FL", "TOF FL"), ("J9", (14.0, 129.0), "TOF_FR", "TOF FR"),
                            ("J10", (-55.0, -114.5), "TOF_RL", "TOF RL"), ("J11", (47.0, -114.5), "TOF_RR", "TOF RR")):
    part(ref, "Connector_JST:JST_PH_B5B-PH-K_1x05_P2.00mm_Vertical", "ToF", at, 0,
         {"1": "+3V3_TOF", "2": "GND", "3": f"{pre}_SCL", "4": "GND", "5": f"{pre}_SDA"}, "tht", "C157993",
         "JST B5B-PH-K-S", label)
for i, (pre, x, y) in enumerate((("TOF_FL", -20.0, 123.0), ("TOF_FR", 16.0, 123.0), ("TOF_RL", -53.0, -108.5),
                                 ("TOF_RR", 49.0, -120.5))):
    res(f"R12{i}A", "4.7k", (x, y), f"{pre}_SCL", "+3V3_TOF", 0)
    res(f"R12{i}B", "4.7k", (x + 3.2, y), f"{pre}_SDA", "+3V3_TOF", 0)

part("J12", "Connector_JST:JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical", "lidar C1", (-33.0, 97.0), 0,
     {"1": "+5V", "2": "GND", "3": "LIDAR_TX", "4": "LIDAR_RX"}, "tht", "C131334", "JST B4B-PH-K-S", "LIDAR 5V TX RX")
part("J13", "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical", "bumpers front", (-1.25, 129.0), 0,
     {"1": "BUMPER_FRONT", "2": "GND"}, "tht", "C158012", "JST B2B-XH-A", "BUMP F")
part("J14", "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical", "bumpers rear", (-1.25, -129.5), 0,
     {"1": "BUMPER_REAR", "2": "GND"}, "tht", "C158012", "JST B2B-XH-A", "BUMP R")
res("R29", "4.7k", (6.0, 121.0), "BUMPER_FRONT", "+3V3_PI", 0)
cap("C11", "100nF", (6.0, 123.0), "BUMPER_FRONT", "GND", 0)

# power button (2-pole, lit; pole 1 = BTN_ON to GND starts the latch), status LED, Pi fan, Jetson console
part("J15", "Connector_JST:JST_XH_B5B-XH-A_1x05_P2.50mm_Vertical", "button", (37.5, 90.0), 0,
     {"1": "BTN_ON", "2": "GND", "3": "POWER_BTN", "4": "+5V", "5": "BTN_LED_K"}, "tht", "C157991", "JST B5B-XH-A",
     "BUTTON")
res("R28", "10k", (30.0, 95.0), "POWER_BTN", "+3V3_PI", 0)
cap("C10", "100nF", (30.0, 97.0), "POWER_BTN", "GND", 0)
nfet("Q3", (30.0, 87.5), "Q3_G", "BTN_LED_K", 0)
res("R24", "1k", (26.0, 87.5), "GPIO27", "Q3_G", 90)
res("R25", "100k", (30.0, 84.0), "Q3_G", "GND", 0)
part("J16", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", "status LED", (40.0, 98.0), 0,
     {"1": "STATUS_LED_A", "2": "GND"}, "tht", "C131337", "JST B2B-PH-K-S", "LED")
res("R27", "330", (34.0, 101.0), "GPIO19", "STATUS_LED_A", 0)
part("J17", "Connector_JST:JST_PH_B3B-PH-K_1x03_P2.00mm_Vertical", "Jetson UART", (-34.0, 89.5), 0,
     {"1": "JET_UART_RX", "2": "JET_UART_TX", "3": "GND"}, "tht", "C131339", "JST B3B-PH-K-S", "JETSON J14 3/4/7")
part("J18", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", "Pi fan 5V", (-52.0, 22.0), 0,
     {"1": "+5V", "2": "GND"}, "tht", "C131337", "JST B2B-PH-K-S", "FAN 5V")

# ---------------------------------------------------------------- PCA9685 + servo headers (S0 can take the MCU's
# TIM17 PWM instead: cut JP3 1-2, bridge 2-3)
pca = {str(i): "GND" for i in (1, 2, 3, 4, 5, 14, 23, 24, 25)}
pca.update({"6": "PCA_LED0", "7": "PCA_LED1", "8": "PCA_LED2", "9": "PCA_LED3", "26": "I2C1_SCL", "27": "I2C1_SDA",
            "28": "+3V3_PI"})
part("U8", "Package_SO:TSSOP-28_4.4x9.7mm_P0.65mm", "PCA9685PW", (8.0, 93.0), 0, pca, "smt", "C2678753",
     "PCA9685PW,118 (alt. PCA9685PW/Q900 C92206)")
cap("C3", "100nF", (12.5, 99.0), "+3V3_PI", "GND", 0)
cap("C4", "10uF", (12.5, 87.0), "+3V3_PI", "GND", 0, C0805)
for i in range(4):
    res(f"R{32 + i}", "220", (-6.0 + 4.0 * i, 101.0), f"PCA_LED{i}", f"PWM{i}" if i else "PWM0_PCA", 90)
    part(f"J{22 + i}", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", f"servo {i}",
         (-6.0 + 4.0 * i, 112.0), 0, {"1": f"PWM{i}", "2": "SERVO_6V", "3": "GND"}, "tht", "C2915006",
         "Wurth 61300311121 1x3 header", "SERVO S0-S3" if i == 0 else None)
part("JP3", JP3, "S0 source", (-10.0, 106.0), 90, {"1": "PWM0_PCA", "2": "PWM0", "3": "PWM0_MCU"}, "none")
res("R89", "220", (-12.6, 106.0), "SERVO_MCU", "PWM0_MCU", 90)
part("C14", "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm", "470uF 16V", (14.0, 108.0), 0,
     {"1": "SERVO_6V", "2": "GND"}, "tht", "C242145", "Panasonic EEU-FR1C471 470 uF 16 V low-ESR")

# ---------------------------------------------------------------- RTC
rtc = {str(i): "GND" for i in range(5, 14)}
rtc.update({"2": "+3V3_PI", "14": "RTC_VBAT", "15": "I2C1_SDA", "16": "I2C1_SCL"})
part("U9", "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm", "DS3231SN", (-14.0, 96.5), 0, rtc, "smt", "C9866", "DS3231SN#T&R")
cap("C5", "100nF", (-8.0, 90.5), "+3V3_PI", "GND", 0)
part("BT1", "Battery:BatteryHolder_Keystone_3000_1x12mm", "CR1220", (-24.0, 114.0), 0,
     {"1": "RTC_VBAT", "2": "GND"}, "smt", "C238097", "Keystone 3000 SMT retainer (CR1220 cell not included)")

# ---------------------------------------------------------------- test points
for i, (net, at) in enumerate([("VBUS", (37.0, -36.5)), ("+5V", (-19.9, 45.0)), ("SERVO_6V", (40.5, 54.0)),
                               ("JET_PWR", (-10.0, 63.8)), ("+3V3_TOF", (8.0, 70.0)), ("GND", (-1.0, -37.0)),
                               ("GND", (-8.0, 88.0)), ("INA_ALERT", (17.0, -36.5)), ("MOT_BUS", (-36.5, -91.0)),
                               ("+3V3_MCU", (MX - 16.0, MY + 13.0)), ("GND_MOT", (-40.0, -112.0)),
                               ("BAT_F", (37.0, -92.0))]):
    part(f"TP{i + 1}", "TestPoint:TestPoint_THTPad_D1.5mm_Drill0.7mm", net, at, 0, {"1": net}, "none",
         label={"VBUS": "VBUS", "+5V": "5V", "SERVO_6V": "6V", "JET_PWR": "JET", "+3V3_TOF": "3V3T", "GND": "GND",
                "INA_ALERT": "ALERT", "MOT_BUS": "VMOT", "+3V3_MCU": "3V3M", "GND_MOT": "GNDM",
                "BAT_F": "BAT"}[net])


# label placement tweaks: ref -> (dx, dy, "top" | "bottom" | "right")
LABEL_POS = {"J5": (1.5, 0.0, "top"), "J22": (6.0, 0.0, "top"), "TP7": (0.0, 0.0, "bottom"), "F1": (0.0, 0.0, "right"),
             "J20": (0.0, 0.0, "top"), "J17": (0.0, 0.0, "top"), "J12": (0.0, 0.0, "top"), "J15": (0.0, 0.0, "top"),
             "J16": (0.0, 0.0, "top"), "J41": (0.0, 0.0, "top"), "J42": (0.0, 0.0, "top"),
             "J43": (0.0, 0.0, "top"), "J44": (0.0, 0.0, "top"), "J14": (0.0, 0.0, "top")}

# extra silkscreen text: (text, X, Y, size, layer "F"/"B")
SILK = [(f"RABBIT 2.0 BODY  rev {REV}  2026-10", -20.0, -50.0, 1.6, "B"),
        ("4L 1.6 mm, 1 oz outer; deck of the Red Ackerman kit", -20.0, -54.0, 1.0, "B"),
        (f"rev {REV}", 0.0, 117.5, 1.2, "F"),
        ("FRONT ^", 0.0, 120.0, 1.4, "F"),
        ("+", 44.0, -99.3, 1.4, "F"), ("-", 55.8, -106.5, 1.4, "F"),
        ("STAR GND", 41.0, -102.6, 1.0, "F")]

# cable passthrough for the ZED USB 3 cable (rev A review S6): 11.1 x 18 mm over the kit plate slot
CUTOUTS = [[(21.5, 64.6), (32.6, 64.6), (32.6, 82.6), (21.5, 82.6)]]


def nets():
    s = set()
    for p in PARTS:
        s.update(p["pins"].values())
    return sorted(s)


# net classes (build_board.py clears the classes of the old .kicad_pro first: rev A review S5)
# Power nets are carried by hand-drawn pours and tracks (routing.py); the class widths below only apply to the
# low-current taps the autorouter adds (sense, bias, dividers), so they fit 0.5 mm-pitch IC pins.
POWER_HI = ["BAT_IN", "BAT_F", "SW_MID", "VBUS_RAW", "VBUS", "MOT_F", "MOT_BUS", "GND_MOT", "BRK_D", "DG", "HG"]
POWER_5V = ["+5V", "6V_RAW", "SERVO_6V", "JET_OUT", "JET_PWR", "BODY_IN", "STEER_IN", "SW4", "SW6",
            "MLA", "MLB", "MLC", "MRA", "MRB", "MRC"]
POWER_MID = ["+3V3_TOF"]
POWER_LO = ["+3V3_PI", "+3V3_MCU", "5V_HALL_L", "5V_HALL_R", "BRK_VCC"]
