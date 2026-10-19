"""Rabbit 2.0 body board, revision C: parts, nets and placement (the netlist source of truth).

Rev B (pcb/rabbit-body, git eb7deb0) carried 2 x DRV8316 for BLDC motors, a RoboClaw fallback and INA226 monitors.
Rev C (spec docs/reports/2026-10-10-body-pcb-rev-c.md, decisions in its section 11a) drives the stock Hiwonder
JGB37-520R30-12 brushed motors with 2 x DRV8243H, switches every load from the Pi (LM5069 motor bus, 2 x TPS16630 on the
battery, 10 x TPS259470L after the bucks (3 lidar, servo, arm, encoder, 2 fans, spare 5 V, Pi USB-C), all with fault
flags and current readback through 2 x ADS7128), adds 6 ToF ports behind a TCA9548A on the Pi's I2C6, 3 lidar ports on
the Pi UARTs, 4 INA238 monitors (battery, motor bus, 5 V, servo), IMU, CAN-FD and USB-C on the STM32G474.
Per-IC pin tables, external parts, LCSC numbers and datasheet pages: data/pcb-revc/ics/*.json (cited as <file>.json);
STM32 pins data/pcb-revc/ics/stm32_pinmap.md, Pi pins pi_pinmap.md, I2C addresses i2c_address_map.json.

Board frame: mm, origin at the deck centre, +X = robot right, +Y = robot front, top view. `rot` is the KiCad footprint
orientation in degrees. side "B" parts are flipped by build_board.py about their own Y axis; `at` stays in the top-view
frame. `bom`: "smt" / "tht" = assembled by JLCPCB from LCSC stock, "hand" = soldered by the owner, "dnp" = footprint
only, "module" = existing module on standoffs, "none" = mechanical or copper only.
Grounds: GND is the logic ground; GND_MOT is the motor power ground (DRV8243 GND pads and their strap resistors, bulk
caps, brake chopper, freewheel diode) and joins GND only at the star NT1 next to the battery connector.
Height rules (spec section 2): bottom parts <= 8 mm over the motors (Y -60..-130), <= 10 mm elsewhere; tall parts
(inductors, polymers, THT headers, Micro-Fit) on the top; under the Pi only bottom parts.
"""

import json
import math
from pathlib import Path

REV = "C"
N_TOF = 6
K = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/"

R0603 = "Resistor_SMD:R_0603_1608Metric"
R0402 = "Resistor_SMD:R_0402_1005Metric"
R0805 = "Resistor_SMD:R_0805_2012Metric"
R1206 = "Resistor_SMD:R_1206_3216Metric"
R2512 = "Resistor_SMD:R_2512_6332Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"
CPOLY = "Capacitor_SMD:CP_Elec_8x10.5"
CPOLY10 = "Capacitor_SMD:CP_Elec_10x10.5"
LED0603 = "LED_SMD:LED_0603_1608Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
SOT23_6 = "Package_TO_SOT_SMD:SOT-23-6"
SOD123 = "Diode_SMD:D_SOD-123"
SOD323 = "Diode_SMD:D_SOD-323"
SMA = "Diode_SMD:D_SMA"
SMB = "Diode_SMD:D_SMB"
SMC = "Diode_SMD:D_SMC"
TDSON = "Package_TO_SOT_SMD:TDSON-8-1"
MSOP10 = "Package_SO:MSOP-10_3x3mm_P0.5mm"
FUSE = "rabbit_body:Fuse_Littelfuse_NANO2_451_2410"
SHUNT = "rabbit_body:R_Shunt_2512_Kelvin"
SHUNT_WSK = "Resistor_SMD:R_Shunt_Vishay_WSK2512_6332Metric_T1.19mm"
DRV_FP = "rabbit_body:TI_RXY0014A_VQFN-HR-14_3x4.5mm"
BUCK_FP = "rabbit_body:TI_RPH0016B_VQFN-HR-16_3.5x4.5mm"
EF_FP = "rabbit_body:TI_RPW0010A_VQFN-HR-10_2x2mm"
EFUSE_FP = "Package_SO:HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP3.4x6.5mm_Mask2.96x2.96mm_ThermalVias"
INA_FP = MSOP10
ESD_FP = "Package_SON:USON-10_2.5x1.0mm_P0.5mm"
RARRAY = "Resistor_SMD:R_Array_Convex_4x0603"
JP2 = "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm"
JP3 = "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm_NumberLabels"
TP_FP = "TestPoint:TestPoint_THTPad_D1.5mm_Drill0.7mm"
USBC_V = "Connector_USB:USB_C_Receptacle_GCT_USB4115-03-C"
GH6 = "Connector_JST:JST_GH_BM06B-GHS-TBT_1x06-1MP_P1.25mm_Vertical"
GH4 = "Connector_JST:JST_GH_BM04B-GHS-TBT_1x04-1MP_P1.25mm_Vertical"
PH6 = "Connector_JST:JST_PH_B6B-PH-K_1x06_P2.00mm_Vertical"
PH6_SMD = "Connector_JST:JST_PH_B6B-PH-SM4-TB_1x06-1MP_P2.00mm_Vertical"
XH2 = "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical"
XH4 = "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical"
XH5 = "Connector_JST:JST_XH_B5B-XH-A_1x05_P2.50mm_Vertical"
XT30 = "Connector_AMASS:AMASS_XT30UPB-F_1x02_P5.0mm_Vertical"
KK4 = "Connector_Molex:Molex_KK-254_AE-6410-04A_1x04_P2.54mm_Vertical"

# 1 % 0603 resistors (UNI-ROYAL 0603WAF, JLC basic unless noted) and generic caps, as rev B
LCSC_R = {"39k": "C23153", "0": "C21189", "10": "C22859", "22": "C23345", "100": "C22775", "220": "C22962",
          "330": "C23138", "1k": "C21190", "1.5k": "C22843", "2.2k": "C4190", "4.7k": "C23162", "4.99k": "C23046",
          "5.1k": "C23186", "10k": "C25804", "11k": "C25950", "22k": "C31850", "24k": "C23352", "20k": "C4184",
          "33k": "C4216", "47k": "C25819", "56k": "C23206", "60.4k": "C23089", "68k": "C23231", "100k": "C25803",
          "150k": "C22807", "220k": "C22961", "1M": "C22935", "1.5M": "C4172", "3.9k": "C23018", "6.04k": "C25977",
          "8.45k": "C14892", "13.7k": "C22793", "8.25k": "C185307",
          "300": "C23025", "750": "C23241", "887": "C93619", "200k": "C25811", "9.53k": "C23127"}
LCSC_C = {"10pF": "C1634", "18pF": "C1647", "470pF": "C85979", "1nF": "C1588", "2.2nF": "C77033", "4.7nF": "C1621",
          "10nF": "C57112", "22nF": "C77056", "47nF": "C1622", "100nF": "C14663", "470nF": "C1623", "1uF": "C15849",
          "2.2uF": "C23630", "4.7uF": "C19666", "10uF": "C15850", "10uF50V": "C77102", "22uF": "C12891",
          "220uF35V": "C454287"}
# 0.1 % 25 ppm thin film (Yageo RT0603BRD / Viking AR03), LCSC numbers from the ics/*.json files
LCSC_P = {"1.5k": "C318129", "25.5k": "C861257", "47.5k": "C136962", "14.7k": "C705725", "6.81k": "C861538",
          "100k": "C122538", "20k": "C723637", "71.5k": "C861546", "115k": "C861084", "10k": "C95204",
          "23.2k": "C861244", "45.3k": "C861415", "80.6k": "C861568", "40.2k": "C374525", "61.9k": "C861498",
          "6.65k": "C861536", "4.42k": "C861442", "1.65k": "C705743", "549": "C861470"}

PARTS = []
USED = set()


def part(ref, fp, value, at, rot=0, pins=None, bom="smt", lcsc=None, mpn=None, label=None, side="F"):
    """side: "F" top, "B" bottom (flipped about the part's Y axis by KiCad; `at` stays in the top view frame)."""
    assert ref not in USED, f"duplicate ref {ref}"
    USED.add(ref)
    PARTS.append(dict(ref=ref, fp=fp, value=value, at=(round(at[0], 3), round(at[1], 3)), rot=rot % 360,
                      pins=pins or {}, bom=bom, lcsc=lcsc, mpn=mpn or value, label=label, side=side))


def nref(prefix, base):
    """Next free reference >= base (blocks number their parts from their own base)."""
    i = base
    while f"{prefix}{i}" in USED:
        i += 1
    return f"{prefix}{i}"


def res(ref, value, at, a, b, rot=0, fp=R0603, side="F", lcsc=None, mpn=None, bom="smt", prec=False):
    """Resistor; prec=True picks the 0.1 % 25 ppm part of LCSC_P."""
    if lcsc is None:
        lcsc = {"22": "C25092"}[value] if fp == R0402 else (LCSC_P[value] if prec else LCSC_R[value])
    mpn = mpn or (f"0603 {value} 0.1% 25ppm thin film" if prec else f"{fp.split('_')[1]} {value} 1%")
    part(ref, fp, value, at, rot, {"1": a, "2": b}, bom, lcsc, mpn, side=side)


def cap(ref, value, at, a, b, rot=0, fp=C0603, side="F", lcsc=None, mpn=None, bom="smt"):
    if lcsc is None:
        lcsc = {"100nF": "C1525", "1uF": "C52923", "47nF": "C272875"}[value] if fp == C0402 else LCSC_C[value]
    part(ref, fp, value.replace("50V", " 50V").replace("35V", " 35V"), at, rot, {"1": a, "2": b}, bom, lcsc,
         mpn or value, side=side)


def led(ref, at, anode, rot=0, k="GND", side="F"):
    part(ref, LED0603, "LED red", at, rot, {"1": k, "2": anode}, "smt", "C2286", "KT-0603R (JLC basic)", side=side)


def nfet(ref, at, gate, drain, rot=0, source="GND", side="F", kind="AO3400A"):
    """SOT-23 N-FET, pins 1 G, 2 S, 3 D (rev B nfet()). 2N7002K-7 C85047 for logic-level switches."""
    lcsc, mpn = {"AO3400A": ("C20917", "AO3400A"), "2N7002K": ("C85047", "Diodes 2N7002K-7 60 V")}[kind]
    part(ref, SOT23, kind, at, rot, {"1": gate, "2": source, "3": drain}, "smt", lcsc, mpn, side=side)


def tvs(ref, at, k, a="GND", rot=0, bidir=False, side="F"):
    part(ref, SMB, "SMBJ20CA" if bidir else "SMBJ20A", at, rot, {"1": k, "2": a}, "smt",
         "C151258" if bidir else "C151257", "Littelfuse SMBJ20CA" if bidir else "Littelfuse SMBJ20A", side=side)


def esd4(ref, at, lines, rot=0, side="F"):
    """TI TPD4E05U06DQAR (USON-10 2.5 x 1.0, C138714): pins 1, 2, 4, 5 = IO, 3 and 8 = GND, 6, 7, 9, 10 = NC for
    flow-through routing (TPD4E05U06 DS pin table [from memory, verify]). `lines` fills IO 1, 2, 4, 5 in order."""
    pins = {"3": "GND", "8": "GND"}
    for p, n in zip(("1", "2", "4", "5"), lines):
        if n:
            pins[p] = n
    part(ref, ESD_FP, "TPD4E05U06", at, rot, pins, "smt", "C138714", "TI TPD4E05U06DQAR", side=side)


def tp(ref, net, at, label=None):
    part(ref, TP_FP, net, at, 0, {"1": net}, "none", label=label)


class Blk:
    """Local placement frame of a block: (dx, dy) in the top-view frame, x mirrored for bottom blocks so that the
    passives stay next to the pins of the (mirrored) IC."""

    def __init__(self, x, y, side="F"):
        self.x, self.y, self.side = x, y, side
        self.s = -1 if side == "B" else 1

    def at(self, dx, dy):
        return (self.x + self.s * dx, self.y + dy)


# ---------------------------------------------------------------- helpers per IC

def ina238(u, at, side, sh_p, sh_n, vbus, a1, a0, label):
    """INA238AIDGSR (SLYS025B; pins table 4-1 p.3 = INA226 pinout: 1 A1, 2 A0, 3 ALERT, 4 SDA, 5 SCL, 6 VS, 7 GND,
    8 VBUS, 9 IN-, 10 IN+; address straps table 6-2 p.18). Sense inputs through 10 Ohm + 100 nF (p.32-33); VBUS
    straight to the load-side Kelvin tap (ina238.json vbus_warning: rev B's VBUS behind the 10 Ohm read ~84 mA false
    current). VS 100 nF at pin 6 (p.36). ALERT to the shared PWR_ALERT_N (Pi GPIO24)."""
    n = u[1:]
    b = Blk(*at, side)
    inp, inn = f"INA{n}_P", f"INA{n}_N"
    part(u, INA_FP, "INA238", b.at(0, 0), 0,
         {"1": a1, "2": a0, "3": "PWR_ALERT_N", "4": "I2C1_SDA", "5": "I2C1_SCL", "6": "+3V3_PI", "7": "GND",
          "8": vbus, "9": inn, "10": inp}, "smt", "C2868250", "TI INA238AIDGSR", label, side)
    res(f"R{n}1", "10", b.at(4.8, 1.5), sh_p, inp, 90, side=side)
    res(f"R{n}2", "10", b.at(6.45, 1.5), sh_n, inn, 90, side=side)
    cap(f"C{n}1", "100nF", b.at(8.1, 1.5), inp, inn, 90, side=side)
    cap(f"C{n}2", "100nF", b.at(4.9, -2.4), "+3V3_PI", "GND", 0, side=side)


def shunt(ref, value, at, rot, a, b, kp, kn, lcsc, mpn, side="F", fp=SHUNT):
    """Kelvin shunt. rabbit_body:R_Shunt_2512_Kelvin: 1/2 current, 3/4 sense; Vishay WSK2512 footprint: 1/4 current,
    2/3 sense (2 next to 1)."""
    pins = {"1": a, "2": b, "3": kp, "4": kn} if fp == SHUNT else {"1": a, "4": b, "2": kp, "3": kn}
    part(ref, fp, value, at, rot, pins, "smt", lcsc, mpn, side=side)


def efuse(u, name, rail, out, r_ilm, dvdt, itimer, ovlo, at, side="B", schottky=None):
    """TPS259470L eFuse (SLVSFC9C; pins table 5-1 p.5-6, tps259470l.json): 1 EN/UVLO <- {X}_EN (PCAL6524 0x22, 100k
    pull-down array at the expander), 2 OVLO <- shared per-rail divider, 3 AUXOFF NC, 4 FLT -> {X}_FLT (10k pull-up
    array at PCAL6524 0x23), 5 IN, 6 OUT, 7 DVDT, 8 GND, 9 ILM, 10 ITIMER.
    R_ILM = 3334 / I_LIM (p.32 eq.7), 0.1 %; ILM -> 10k -> {X}_IMON with the 1 nF at the ADS7128 input only (spec 11a);
    C_IN 100 nF (p.62), C_OUT 1 uF (p.63), C_dVdt (p.30 eq.4), C_ITIMER (p.32 eq.8); Schottky OUT -> GND on inductive
    loads (p.60, p.63). Cell: IN/OUT bars exit at the top (caps), ILM/ITIMER/DVDT passives beside pins 7-10."""
    b = Blk(*at, side)
    X = name
    base = int(u[1:]) * 10
    retry = name == "USB_PI"   # the Pi's own feed retries after a trip instead of latching off until a power cycle
    part(u, EF_FP, "TPS259470A" if retry else "TPS259470L", b.at(0, 0), 0,
         {"1": f"{X}_EN", "2": ovlo, "4": f"{X}_FLT", "5": rail, "6": out, "7": f"{X}_DVDT", "8": "GND",
          "9": f"{X}_ILM", "10": f"{X}_ITMR"}, "smt", "C3662799" if retry else "C3662793",
         "TI TPS259470ARPWR auto-retry" if retry else "TI TPS259470LRPWR", side=side)
    cap(f"C{base + 1}", "100nF", b.at(-1.6, 2.6), rail, "GND", 0, side=side, lcsc="C77055",
        mpn="Murata GRM188R71H104KA93D 100nF 50V X7R")
    cap(f"C{base + 2}", "1uF", b.at(1.6, 2.6), out, "GND", 0, side=side, lcsc="C85862",
        mpn="Murata GCM188R71E105KA64D 1uF 25V X7R AEC-Q200")
    if r_ilm in LCSC_P:
        res(f"R{base + 1}", r_ilm, b.at(2.9, -0.8), f"{X}_ILM", "GND", 90, side=side, prec=True)
    else:   # no 0.1 % part of this value checked at JLC: 1 % (limit only, readback gain 1 %)
        res(f"R{base + 1}", r_ilm, b.at(2.9, -0.8), f"{X}_ILM", "GND", 90, side=side)
    dl = {"1nF": ("C77026", "Murata GRM1885C1H102JA01D C0G"), "10nF": ("C85973", "Murata GRM1885C1H103JA01D C0G"),
          "22nF": ("C77056", "Murata GRM188R71H223KA01D X7R"), "2.2nF": ("C77033", "C0G 50V"),
          "4.7nF": ("C85980", "C0G 50V")}
    cap(f"C{base + 4}", itimer, b.at(4.55, -0.8), f"{X}_ITMR", "GND", 90, side=side, lcsc=dl[itimer][0],
        mpn=dl[itimer][1])
    cap(f"C{base + 3}", dvdt, b.at(2.9, -4.0), f"{X}_DVDT", "GND", 90, side=side, lcsc=dl[dvdt][0], mpn=dl[dvdt][1])
    res(f"R{base + 2}", "10k", b.at(4.55, -4.0), f"{X}_ILM", f"{X}_IMON", 90, side=side)
    if schottky == "SMA":
        part(f"D{base + 1}", SMA, "B340A", b.at(-0.8, -7.5), 0, {"1": out, "2": "GND"}, "smt", "C85098",
             "Diodes B340A-13-F 40 V 3 A Schottky", side=side)


def tps16630(u, at, side, vin, out, shdn, imon_src, imon, flt, r_ilim, mode_gnd, base, jetson):
    """TPS16630PWPR eFuse on the battery (SLVSET9G; HTSSOP-20 pins table 5-1 p.5-6: 1-3 IN, 6 P_IN, 7 UVLO, 8 OVP,
    9 GND, 10 dVdT, 11 ILIM, 12 MODE, 13 SHDN, 14 IMON, 15 FLT, 16 PGOOD, 18-20 OUT, 4/5/17 NC, 21 PowerPAD -> GND).
    UVLO 68k/10k = 9.36 V, OVP 150k/10k = 19.2 V (V_UVLOR/V_OVPR 1.2 V p.8), dVdT 47 nF (rev B), I_OL = 18 / R_ILIM[k]
    (p.20 eq.6), IMON 27.9 uA/A (p.12, eq.9 p.24) into 10k = 0.279 V/A (8.9 A full scale at the 2.5 V ADC reference),
    then 10k to the ADC (the IMON pin itself carries no capacitor, p.25); MODE open = latch-off, GND = auto-retry
    (table 8-1 p.26); FLT open drain (p.6). Jetson: SHDN has an internal pull-up (2.7 V open, p.8) and Q7 (GPIO25
    high) pulls it low (rev B). Spare: SHDN driven by the expander with a 10k pull-down (the pin sources up to 10 uA,
    p.8: 100k alone would sit at 1 V)."""
    b = Blk(*at, side)
    pins = {"1": vin, "2": vin, "3": vin, "6": vin, "7": f"{u}_UVLO", "8": f"{u}_OVP", "9": "GND",
            "10": f"{u}_DVDT", "11": f"{u}_ILIM", "13": shdn, "14": imon_src, "15": flt, "18": out, "19": out,
            "20": out, "21": "GND"}
    if mode_gnd:
        pins["12"] = "GND"
    part(u, EFUSE_FP, "TPS16630", b.at(0, 0), 0, pins, "smt", "C1849461", "TI TPS16630PWPR 60 V 6 A eFuse",
         "JETSON EFUSE" if jetson else "SPARE VBAT EFUSE", side=side)
    res(f"R{base}", "68k", b.at(-5.4, 2.4), f"{u}_UVLO", vin, 90, side=side)
    res(f"R{base + 1}", "10k", b.at(-7.05, 2.4), f"{u}_UVLO", "GND", 90, side=side)
    res(f"R{base + 2}", "150k", b.at(-5.4, -1.0), vin, f"{u}_OVP", 90, side=side)
    res(f"R{base + 3}", "10k", b.at(-7.05, -1.0), f"{u}_OVP", "GND", 90, side=side)
    cap(f"C{base}", "47nF", b.at(-5.4, -4.4), f"{u}_DVDT", "GND", 90, side=side)
    cap(f"C{base + 1}", "100nF", b.at(-7.05, -4.4), vin, "GND", 90, side=side)
    cap(f"C{base + 2}", "1uF", b.at(1.5, -4.6), out, "GND", 0, C0805, side=side, lcsc="C28323",
        mpn="Samsung CL21B105KBFNNNE 1uF 50V X7R 0805")
    res(f"R{base + 4}", r_ilim, b.at(5.4, 2.4), f"{u}_ILIM", "GND", 90, side=side)
    res(f"R{base + 5}", "10k", b.at(7.05, 2.4), imon_src, "GND", 90, side=side)
    res(f"R{base + 8}", "10k", b.at(5.4, -1.0), imon_src, imon, 90, side=side)
    if jetson:
        res(f"R{base + 6}", "1k", b.at(8.7, 2.4), "GPIO25", f"{u}_Q_G", 90, side=side)
        res(f"R{base + 7}", "100k", b.at(7.05, -1.0), f"{u}_Q_G", "GND", 90, side=side)
        nfet("Q7", b.at(6.2, -5.2), f"{u}_Q_G", shdn, 0, side=side)
    else:
        res(f"R{base + 6}", "10k", b.at(7.05, -1.0), shdn, "GND", 90, side=side)


def buck(n, at, vin, vout, label, fb_bot=None, en=None, pg=None, servo=False):
    """LM61495 (SNVSBZ4A, pins table 6-1 p.3-4): 414 kHz (RT 39k to GND, p.16 eq.3: 16.4 / (39 + 0.633)), auto PFM
    (MODE -> GND), no spread spectrum (SPSP -> GND), BIAS from the output, RESET (pin 10, open drain, p.4) -> PG net.
    EN: 100k/22k from VIN (starts at 7.0 V) or, for the servo rail, the Pi's expander output (100k pull-down array,
    EN threshold ~1.26 V). Layout per p.48-50 (figure 11-2) as rev B. Servo FB (lm61495_servo_fb.json): 100k/20.0k
    0.1 % = 6.000 V; 2N7002K adds 71.5k 0.1 % in parallel -> 7.399 V when SERVO_7V4 is high (gate pulled down)."""
    x, y = at
    sw, boot, vcc, fb, enn = f"SW{n}", f"BOOT{n}", f"VCC{n}", f"FB{n}", en or f"EN{n}"
    part(f"U{n}", BUCK_FP, "LM61495", (x, y), 0,
         {"1": "GND", "2": vin, "3": boot, "4": boot, "5": vout, "6": vcc, "7": fb, "8": "GND", "9": f"RT{n}",
          "10": pg, "11": "GND", "12": "GND", "13": enn, "14": vin, "15": "GND", "16": sw}, "smt", "C2943584",
         "TI LM61495RPHR", label)
    cap(f"C{n}01", "10uF50V", (x - 4.9, y + 1.65), vin, "GND", 90, C1210)
    cap(f"C{n}02", "10uF50V", (x + 4.9, y + 1.65), vin, "GND", 90, C1210)
    cap(f"C{n}03", "470nF", (x - 2.55, y + 1.65), vin, "GND", 90, lcsc="C361189", mpn="TDK C1608X7R1H474KT000E 50V")
    cap(f"C{n}04", "470nF", (x + 2.55, y + 1.65), vin, "GND", 90, lcsc="C361189", mpn="TDK C1608X7R1H474KT000E 50V")
    cap(f"C{n}05", "100nF", (x - 2.45, y - 0.55), boot, sw, 90, C0402)
    cap(f"C{n}06", "1uF", (x - 1.3, y - 3.75), "GND", vcc, 90)
    cap(f"C{n}07", "100nF", (x - 3.0, y - 2.2), "GND", vout, 0, C0402)
    part(f"L{n}", "Inductor_SMD:L_Coilcraft_XAL1010-XXX", "3.3uH", (x, y + 10.0), 90, {"1": sw, "2": vout}, "smt",
         "C3911672", "Coilcraft XAL1010-332MED 3.3 uH 18 A sat")
    if servo:
        res(f"R{n}01", "100k", (x - 1.325, y - 6.7), vout, fb, 0, prec=True)
        res(f"R{n}02", "20k", (x + 1.3, y - 6.7), fb, "GND", 0, prec=True)
        res(f"R{n}09", "71.5k", (x + 4.6, y - 6.7), fb, f"FB{n}_SEL", 0, prec=True)
        nfet(f"Q{n}01", (x + 6.3, y - 3.4), "SERVO_7V4", f"FB{n}_SEL", 0, kind="2N7002K")
    else:
        res(f"R{n}01", "100k", (x - 1.325, y - 6.7), vout, fb, 0)
        res(f"R{n}02", fb_bot, (x + 1.3, y - 6.7), fb, "GND", 0)
    res(f"R{n}03", "4.99k", (x - 2.6, y - 8.3), vout, f"FF{n}", 0)
    cap(f"C{n}08", "10pF", (x, y - 8.3), f"FF{n}", fb, 0)
    if en is None:
        res(f"R{n}04", "100k", (x + 3.0, y - 3.5), enn, vin, 0)
        res(f"R{n}05", "22k", (x + 3.0, y - 5.1), enn, "GND", 0)
    res(f"R{n}06", "39k", (x + 0.95, y - 4.2), "GND", f"RT{n}", 90)
    for i, dx in enumerate((-6.0, -3.0, 0.0, 3.0, 6.0)):
        cap(f"C{n}{10 + i}", "22uF", (x + dx, y + 19.5), vout, "GND", 90, C1206)


# ---------------------------------------------------------------- mechanical
for i, (x, y, d) in enumerate([(-38.0916, -121.8873, 4.3), (38.0916, -121.8873, 4.3), (-38.0916, 107.636, 4.3),
                               (38.0916, 107.636, 4.3), (-55.2597, 84.9505, 3.2), (55.2597, 84.9505, 3.2)]):
    fp = "MountingHole:MountingHole_4.3mm_M4" if d > 4 else "MountingHole:MountingHole_3.2mm_M3"
    part(f"H{i + 1}", fp, "deck standoff M4" if d > 4 else "deck standoff M3", (x, y), bom="none")

# ZED 2i on two M3 x 5 mm standoffs (drawing: M3 holes 36 mm apart, 21.8 mm from the camera's back face), centred,
# its front face on the board's front edge (cad/robot/parts/zed.py, gen/outline_revc.py)
ZED_FRONT = max(max(sg["start"][1], sg["end"][1]) for sg in json.loads((Path(__file__).resolve().parent /
                                                                          "outline.json").read_text())["segments"])
for i, x in enumerate((-18.0, 18.0)):
    part(f"H{40 + i}", "MountingHole:MountingHole_3.2mm_M3", "ZED 2i M3 standoff", (x, ZED_FRONT - 43.1 + 21.8),
         bom="none")
PI_X, PI_Y = 13.0, -4.0
part("MOD1", "rabbit_body:RaspberryPi4_Standoffs", "Raspberry Pi 4", (PI_X, PI_Y), 0, bom="module",
     mpn="Raspberry Pi 4 Model B + 4x M2.5x6 standoffs")

# global fiducials for the pick-and-place cameras: three per side, asymmetric, >= 3.7 mm from the edge and outside the
# ToF bracket flanges (gen/fixups.py checks the 1.5 mm copper-free ring after routing)
for i, (side, x, y) in enumerate((("F", -55.0, -128.0), ("F", 62.0, -30.0), ("F", -45.0, 120.0),
                                  ("B", 55.0, -128.0), ("B", -60.0, -22.0), ("B", 40.0, 118.0))):
    part(f"FID{i + 1}", "Fiducial:Fiducial_1mm_Mask2mm", "fiducial", (x, y), bom="none", side=side)

# ---------------------------------------------------------------- power input (rev B, unchanged): XT60 -> F1 -> LM74800
# ideal diode + switch (SNOSDD8: pins p.3, EN/OV thresholds p.5, inrush eq.2 p.16, common-drain FETs p.1/p.19)
part("J1", "Connector_AMASS:AMASS_XT60-M_1x02_P7.20mm_Vertical", "XT60 BAT", (50.0, -106.5), 90,
     {"1": "GND", "2": "BAT_IN"}, "tht", "C19268037", "AMASS XT60PB-M vertical", "BATTERY")
part("F1", FUSE, "20A", (50.0, -89.0), 90, {"1": "BAT_IN", "2": "BAT_F"}, "smt", "C178980",
     "Littelfuse 0451020.MRL 20 A 65 V", "F1 20A")
tvs("D7", (42.4, -95.5), "BAT_F", rot=270, bidir=True)
part("Q1", TDSON, "BSC010N04LS", (50.0, -80.0), 90, {"1": "BAT_F", "2": "BAT_F", "3": "BAT_F", "4": "DG",
                                                        "5": "SW_MID"}, "smt", "C501508",
     "Infineon BSC010N04LS OptiMOS 5 40 V 1.0 mOhm")
part("Q2", TDSON, "BSC010N04LS", (50.0, -66.5), 270, {"1": "VBUS_RAW", "2": "VBUS_RAW", "3": "VBUS_RAW",
                                                         "4": "HG", "5": "SW_MID"}, "smt", "C501508",
     "Infineon BSC010N04LS OptiMOS 5 40 V 1.0 mOhm")
part("U10", "rabbit_body:TI_DRR0012E_WSON-12_3x3mm_P0.5mm_EP1.3x2.5mm", "LM74800", (42.0, -73.5), 0,
     {"1": "DG", "2": "BAT_F", "3": "BAT_F", "4": "LM_SW", "5": "LM_OV", "6": "LM_EN", "7": "GND", "8": "HG",
      "9": "VBUS_RAW", "10": "SW_MID", "11": "LM_CAP", "12": "SW_MID"}, "smt", "C7216630", "TI LM74800MDRRR",
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
res("R45", "220k", (38.0, -82.4), "LATCH_C", "LM_EN", 0)
res("R46", "220k", (38.4, -78.6), "LM_EN", "GND", 0)
cap("C24", "10nF", (38.4, -77.0), "LM_EN", "GND", 0)
part("D8", SOD123, "BZT52C8V2", (36.0, -65.0), 90, {"1": "VBUS_RAW", "2": "HOLD_Z"}, "smt", "C173432", "BZT52C8V2")
res("R47", "47k", (36.0, -69.4), "HOLD_Z", "LM_EN", 90)
nfet("Q5", (39.6, -65.0), "OFF_G", "LM_EN", 90)
res("R48", "1k", (35.6, -60.4), "GPIO17", "OFF_A", 0)
part("D9", SOD323, "1N4148WS", (38.9, -60.4), 0, {"1": "OFF_G", "2": "OFF_A"}, "smt", "C2128", "1N4148WS")
cap("C25", "1uF", (42.3, -60.4), "OFF_G", "GND", 0)
res("R49", "1M", (42.3, -62.0), "OFF_G", "GND", 0)
cap("C26", "100nF", (34.8, -91.6), "BTN_ON", "BAT_F", 90)   # to BAT_F: plugging the battery in is no press

# battery shunt -> VBUS; INA238 #1 0x40 (A1 = A0 = GND). WSLP25122L000FEA (2 mOhm, 3 W power metal strip, C2090981)
# replaces the WSLP2726 of ina238.json: same value, fits the rev B 2512 Kelvin land, no unverified custom footprint
shunt("R1", "2mR 3W", (50.0, -55.0), 90, "VBUS_RAW", "VBUS", "SH1_P", "SH1_N", "C2090981",
      "Vishay WSLP25122L000FEA 2 mOhm 1% 3 W")
ina238("U21", (38.5, -53.0), "F", "SH1_P", "SH1_N", "SH1_N", "GND", "GND", "INA BAT 0x40")
tvs("D1", (56.0, -48.5), "VBUS", rot=90)
part("C30", CPOLY, "220uF 35V", (51.0, -37.5), 0, {"1": "VBUS", "2": "GND"}, "smt", LCSC_C["220uF35V"],
     "Panasonic EEH-ZK1V221UP 220 uF 35 V hybrid polymer, AEC-Q200")
cap("C31", "10uF50V", (45.5, -45.0), "VBUS", "GND", 90, C1210)
cap("C32", "10uF50V", (41.6, -45.0), "VBUS", "GND", 90, C1210)
res("R39", "10k", (56.6, -57.5), "LEDB_A", "VBUS", 90)
led("D5", (56.6, -61.0), "LEDB_A", 90)
# VBUS sense for the MCU (PC3): tells "motor bus switched off" from "battery low" (stm32_pinmap.md pin 11)

# star ground: GND_MOT joins GND here only
part("NT1", "rabbit_body:NetTie_3.5mm", "star GND", (42.5, -106.5), 90, {"1": "GND_MOT", "2": "GND"}, "none")

# ---------------------------------------------------------------- motor bus: F2 10 A -> 5 mOhm (LM5069 sense + INA238 #2
# 0x41) -> BSC010N04LS -> MOT_BUS (lm5069_bsc010n04ls.json, SNVS452G). dv/dt start (fig 1 p.1: 100 nF, 1N4148WS, 1k,
# MMBT3906): the FET's linear SOA is too weak for a power-limited start. UVLO 47.5k/14.7k (11.58 V on / 10.58 V off),
# OVLO 47.5k/6.81k (19.94 V off) (p.23 eq.34-37), R_PWR 8.45k = 17 W (p.20 eq.10), C_TIMER 22 nF = 1.04 ms (p.21 eq.14).
# Bus OFF by default (spec 11a): Q31 pulls UVLO low while MOT_BUS_OFF is high; MOT_BUS_OFF has a 100k pull-UP to
# +3V3_PI in the expander's array, so the bus stays off until the Pi drives PCAL6524 0x22 P2_4 low. PGD -> MOT_BUS_PG
# (0x23 P2_5, 10k array pull-up).
part("F2", FUSE, "10A", (36.0, -48.5), 180, {"1": "VBUS", "2": "MOT_F"}, "smt", "C44479",
     "Littelfuse 0451010.MRL 10 A", "F2 MOTORS 10A")
shunt("R3", "5mR 1W", (27.0, -48.5), 180, "MOT_F", "MOT_SNS_D", "MOT_SNS_P", "MOT_SNS_N", "C844900",
      "Vishay WSL25125L000FEA 5 mOhm 1% 1 W")
cap("C301", "100nF", (27.0, -44.6), "MOT_F", "GND", 0, lcsc="C77055", mpn="Murata GRM188R71H104KA93D 50V")
ina238("U22", (31.0, -38.5), "F", "MOT_SNS_P", "MOT_SNS_N", "MOT_BUS", "GND", "+3V3_PI", "INA MOT 0x41")
part("Q30", TDSON, "BSC010N04LS", (16.0, -48.5), 0, {"1": "MOT_BUS", "2": "MOT_BUS", "3": "MOT_BUS", "4": "MOT_GATE",
                                                       "5": "MOT_SNS_D"}, "smt", "C501508",
     "Infineon BSC010N04LS 40 V 1.0 mOhm (motor bus switch)")
part("U30", MSOP10, "LM5069-1", (15.0, -40.0), 0,
     {"1": "MOT_SNS_N", "2": "MOT_F", "3": "MOT_UVLO", "4": "MOT_OVLO", "5": "GND", "6": "MOT_TMR", "7": "MOT_PWR",
      "8": "MOT_BUS_PG", "9": "MOT_BUS", "10": "MOT_GATE"}, "smt", "C486026", "TI LM5069MM-1/NOPB (latch-off)",
     "MOTOR BUS SWITCH")
res("R301", "47.5k", (7.0, -35.5), "MOT_F", "MOT_UVLO", 0, prec=True)
res("R302", "14.7k", (7.0, -37.2), "MOT_UVLO", "GND", 0, prec=True)
res("R303", "47.5k", (7.0, -38.9), "MOT_F", "MOT_OVLO", 0, prec=True)
res("R304", "6.81k", (7.0, -40.6), "MOT_OVLO", "GND", 0, prec=True)
res("R305", "8.45k", (7.0, -42.3), "MOT_PWR", "GND", 0)
cap("C302", "22nF", (7.0, -44.0), "MOT_TMR", "GND", 0, lcsc="C77056", mpn="Murata GRM188R71H223KA01D X7R")
nfet("Q31", (3.4, -38.6), "MOT_BUS_OFF", "MOT_UVLO", 0, kind="2N7002K")
cap("C303", "100nF", (7.0, -54.2), "MOT_DVC", "GND", 0, lcsc="C77055", mpn="Murata GRM188R71H104KA93D 50V")
res("R306", "1k", (10.3, -54.2), "MOT_GATE", "MOT_DVB", 0)
part("D30", SOD323, "1N4148WS", (13.7, -54.2), 0, {"1": "MOT_DVC", "2": "MOT_GATE"}, "smt", "C2128",
     "1N4148WS (pin 1 cathode)")
part("Q32", SOT23, "MMBT3906", (17.6, -54.2), 0, {"1": "MOT_DVB", "2": "MOT_DVC", "3": "GND"}, "smt", "C75549",
     "Nexperia MMBT3906 PNP (fig 1 Q2: E = C_dv/dt top, C = GND)")

# ---------------------------------------------------------------- DRV8243H x2 (drv8243.json, SLVSG23E; pins table 5-2
# p.6-7, typical application fig 9-5 p.61) on the BOTTOM in front of each motor connector. MODE open = PWM mode
# (table 7-3 p.33; DNP 0R for PH/EN), SR 0R = LVL1 24.5 V/us (p.14), DIAG 100k = LVL5 latch, OLP off (p.40 table 7-11),
# R_IPROPI 1.5k 0.1 % = 0.489 V/A (p.37-38 eq.2) + 10 nF C0G (p.41), IPROPI -> 1k -> MCU with 1 nF and a BAT54S clamp at
# the MCU (IPROPI clamps at 4.5-5.5 V, p.16). ITRIP series ladder 8.25k / 13.7k / 25.5k (every state inside a +-10 %
# band, p.13): Q01 shorts the ladder after 8.25k while ITRIP_SEL is high. Spec 11a: 2.41 A by default -> ITRIP_SEL is
# pulled UP (R_ITSEL to +3V3_MCU) and the STM32 drives PB11 low for 4.05 A (R11 0R fitted; removed = 4.73 A).
# ITRIP is transparent in the H variant (p.39). Straps return to GND_MOT at the driver.
DRV_AT = {"L": (-20.5, -83.0), "R": (25.5, -83.0)}


def drv8243(n, s):
    x, y = DRV_AT[s]
    b = Blk(x, y, "B")
    g, vm = "GND_MOT", "MOT_BUS"
    part(f"U{n}", DRV_FP, "DRV8243H", b.at(0, 0), 0,
         {"1": f"DRV_{s}_NFAULT", "2": f"IPROPI_{s}", "3": f"DRV_{s}_NSLEEP", "4": vm, "5": f"M{s}_OUT2", "6": g,
          "7": f"M{s}_OUT1", "8": "DRVOFF", "9": f"DRV_{s}_IN1", "10": f"DRV_{s}_IN2", "11": f"M{s}_DIAG",
          "12": f"M{s}_SR", "13": f"M{s}_ITRIP", "14": f"M{s}_MODE"}, "smt", "C3040833",
         "TI DRV8243HQRXYRQ1 (AEC-Q100)", f"DRV8243 {s}", side="B")
    cap(f"C{n}01", "100nF", b.at(0.4, 3.6), vm, g, 0, side="B", lcsc="C77055", mpn="Murata GRM188R71H104KA93D 50V")
    cap(f"C{n}02", "10uF50V", b.at(-3.6, 5.2), vm, g, 0, C1210, side="B")
    res(f"R{n}01", "1.5k", b.at(-3.6, -0.8), f"IPROPI_{s}", g, 90, side="B", prec=True)
    cap(f"C{n}04", "10nF", b.at(-5.25, -0.8), f"IPROPI_{s}", g, 90, side="B", lcsc="C85973",
        mpn="Murata GRM1885C1H103JA01D C0G")
    res(f"R{n}02", "1k", b.at(-6.9, -0.8), f"IPROPI_{s}", f"IPROPI_{s}_M", 90, side="B")
    res(f"R{n}03", "10k", b.at(-3.6, -4.3), f"DRV_{s}_NFAULT", "+3V3_MCU", 90, side="B")
    res(f"R{n}04", "0", b.at(-0.8, -4.6), f"M{s}_SR", g, 90, side="B")
    res(f"R{n}05", "100k", b.at(0.85, -4.6), f"M{s}_DIAG", g, 90, side="B")
    res(f"R{n}06", "0", b.at(2.5, -4.6), f"M{s}_MODE", g, 90, side="B", bom="dnp")
    res(f"R{n}07", "8.25k", b.at(3.6, -0.8), f"M{s}_ITRIP", f"M{s}_ITN1", 90, side="B")
    res(f"R{n}08", "13.7k", b.at(5.25, -0.8), f"M{s}_ITN1", f"M{s}_ITN2", 90, side="B")
    res(f"R{n}09", "25.5k", b.at(6.9, -0.8), f"M{s}_ITN2", g, 90, side="B", prec=True)
    res(f"R{n}11", "0", b.at(4.15, -4.6), f"M{s}_ITN2", g, 90, side="B")
    nfet(f"Q{n}01", b.at(6.6, -4.3), "ITRIP_SEL", f"M{s}_ITN1", 90, source=g, side="B", kind="2N7002K")
    part(f"Q{n}02", SOT23, "2N7002K", b.at(6.6, 3.0), 90, {"1": "ITRIP_SEL2", "2": g, "3": f"M{s}_ITN2"}, "dnp",
         "C85047", "2N7002K (DNP: second ITRIP line option)", side="B")
    # NTC at the driver, referenced to GND_MOT (offset is mV, rev B)
    part(f"RT{n}", R0603, "NTC 10k", b.at(-6.9, 2.4), 90, {"1": f"NTC_{s}", "2": g}, "smt", "C13564",
         "Murata NCP18XH103F03RB 10k B3380", side="B")


drv8243(11, "L")
drv8243(12, "R")

# bulk on MOT_BUS at each driver (top, 10.5 mm tall polymers are not allowed on the bottom over the motors)
for n, s in ((11, "L"), (12, "R")):
    part(f"C{n}03", CPOLY, "220uF 35V", (DRV_AT[s][0], -95.0), 0, {"1": "MOT_BUS", "2": "GND_MOT"}, "smt",
         LCSC_C["220uF35V"], "Panasonic EEH-ZK1V221UP 220 uF 35 V hybrid polymer, AEC-Q200")

# motor connectors on the BOTTOM in the gap between the two motors' rear ends (board X -14.3..14.3 at the rear axle,
# 28.6 mm wide and ~50 mm deep to deck 1 in cad/robot): over the motors themselves only ~10.7 mm is left, too little
# for the PH plug and the bend of the kit cable (~10 cm, to the motor's end cap). Both cables leave straight down.
# The rev C draft's right-angle Micro-Fit option behind each one is dropped (owner: no cable sticking out sideways;
# the kit motors run at 0.4-1 A against the 2.41 A ITRIP of the PH cable). JST B6B-PH-SM4-TB
# (PH 2.0 vertical SMD, C471518), kit cable order 1 M2, 2 VCC, 3 H1, 4 H2, 5 GND, 6 M1. Molex Micro-Fit 3.0 43650-0600
# (C492352, right angle THT, 8.5 A/pin, same order) behind each one on the TOP, DNP by default: 9.9 mm tall, above the
# bottom height limit over the motors.
for s, x, px in (("L", -20.5, -7.0), ("R", 25.5, 7.0)):
    n = "41" if s == "L" else "42"
    part(f"J{n}", PH6_SMD, "motor PH-6", (px, -84.0), 90,
         {"1": f"M{s}_OUT2", "2": "ENC_3V3", "3": f"ENC_{s}_A", "4": f"ENC_{s}_B", "5": "GND",
          "6": f"M{s}_OUT1"}, "smt", "C471518", "JST B6B-PH-SM4-TB(LF)(SN)", f"MOTOR {s}", side="B")
    # encoder A/B: ESD at the connector, 22 R in series at the MCU (rev B)
    esd4(f"D{n}", (px, -95.5), (f"ENC_{s}_A", f"ENC_{s}_B"), 0, side="B")

# ---------------------------------------------------------------- brake chopper (rev B, unchanged circuit): LM393 on
# MOT_BUS with a TL431 reference, on 17.67 V / off 17.18 V (gen/calc.py), drives BSC026N04LS into 4 x 39 Ohm 2 W;
# works without the MCU and without the 5 V rail. LM74800 blocks regen into the battery, so this is the only sink.
for i, bx in enumerate((-9.0, -3.0, 3.0, 9.0)):
    part(f"R5{i}", R2512, "39R 2W", (bx, -97.5), 90, {"1": "BRK_D", "2": "MOT_BUS"}, "smt", "C175263",
         "CRH2512F39R0E04Z 2 W")
part("Q6", TDSON, "BSC026N04LS", (0.0, -106.0), 90, {"1": "GND_MOT", "2": "GND_MOT", "3": "GND_MOT",
                                                       "4": "BRK_G", "5": "BRK_D"}, "smt", "C3039672",
     "Infineon BSC026N04LS 40 V 2.6 mOhm")
part("U17", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "LM393", (-7.6, -107.0), 0,
     {"1": "BRK_G", "2": "BRK_REF", "3": "BRK_SNS", "4": "GND_MOT", "5": "GND_MOT", "6": "BRK_REF",
      "8": "BRK_VCC"}, "smt", "C7955", "onsemi LM393DR2G")
for i, (ref, val, a, b) in enumerate((("R55", "100", "MOT_BUS", "BRK_VCC"), ("R56", "4.7k", "MOT_BUS", "BRK_REF"),
                                      ("R57", "60.4k", "MOT_BUS", "BRK_SNS"), ("R58", "10k", "BRK_SNS", "GND_MOT"),
                                      ("R59", "1.5M", "BRK_G", "BRK_SNS"), ("R60", "10k", "MOT_BUS", "BRK_G"),
                                      ("R61", "100k", "BRK_G", "BRK_SENSE"))):
    res(ref, val, (-9.6 + 3.2 * i, -112.6), a, b, 0)
cap("C55", "1uF", (-9.6, -114.3), "BRK_VCC", "GND_MOT", 0)
part("U18", SOT23, "TL431", (-5.4, -115.6), 0, {"1": "BRK_REF", "2": "BRK_REF", "3": "GND_MOT"}, "smt", "C6971",
     "TI TL431BCDBZR 0.5 %")
part("D11", SOD123, "BZT52C12", (-0.6, -115.6), 0, {"1": "BRK_G", "2": "GND_MOT"}, "smt", "C173429", "BZT52C12")
res("R62", "33k", (4.4, -114.3), "BRK_SENSE", "GND", 0)
tvs("D10", (7.2, -106.0), "MOT_BUS", "GND_MOT", rot=90)
# freewheel path for the motor current when the LM5069 FET opens (OUT must not go below -1 V, SNVS452G p.28-29 fig 44)
part("D31", SMC, "B540C", (12.0, -118.5), 0, {"1": "MOT_BUS", "2": "GND_MOT"}, "smt", "C72264",
     "Diodes B540C-13-F 40 V 5 A Schottky")

# ---------------------------------------------------------------- STM32G474RET6 (LQFP-64), pins per stm32_pinmap.md
# (DS12288 table 12 p.57-72, AF table 13 p.73-79). Deviation: PA6 (pin 20) reads USB VBUS through 22k/33k instead of
# the optional IMU CLKIN (pinmap "alternatives": a self-powered USB device must detect VBUS).
MCU = {"1": "+3V3_MCU", "2": "BUMP_F_M", "3": "BUMP_R_M", "4": "ESTOP2_M", "5": "OSC_IN", "6": "OSC_OUT",
       "7": "MCU_NRST", "8": "IPROPI_L_M", "9": "IPROPI_R_M", "10": "VMOT_SENSE", "11": "MCU_ALIVE", "12": "NTC_L",
       "13": "NTC_R", "14": "MCU_TX", "15": "GND", "16": "+3V3_MCU", "17": "MCU_RX", "18": "DRVOFF_MON", "19": "MCU_LED",
       "20": "USB_VBUS_DET", "21": "SERVO_MCU", "22": "IMU_CS", "23": "BRK_SENSE", "24": "IMU_INT1",
       "25": "DRV_L_NFAULT", "26": "DRV_R_NFAULT", "27": "GND", "28": "+3V3_MCU_A", "29": "+3V3_MCU_A", "30": "ESTOP",
       "31": "GND", "32": "+3V3_MCU", "33": "ITRIP_SEL", "34": "CAN_RX", "35": "CAN_TX", "36": "DRV_L_NSLEEP",
       "37": "CAN_STB", "38": "DRV_R_IN1", "39": "DRV_R_IN2", "40": "I2C3_SCL", "41": "I2C3_SDA", "42": "DRV_L_IN1",
       "43": "DRV_L_IN2", "44": "DRV_R_NSLEEP", "45": "USB_DM", "46": "USB_DP", "47": "GND", "48": "+3V3_MCU",
       "49": "SWDIO", "50": "SWCLK", "51": "FAN1_TACH_M", "52": "SPI3_SCK", "53": "SPI3_MISO", "54": "SPI3_MOSI",
       "55": "ESTOP", "56": "FAN2_TACH_M", "57": "ENC_R_A_M", "58": "ENC_R_B_M", "59": "ENC_L_A_M",
       "60": "ENC_L_B_M", "61": "MCU_BOOT0", "62": "ARM_UART_M", "63": "GND", "64": "+3V3_MCU"}
MX, MY = -3.0, -74.0
part("U1", "Package_QFP:LQFP-64_10x10mm_P0.5mm", "STM32G474RET6", (MX, MY), 0, MCU, "smt", "C521608",
     "ST STM32G474RET6", "MOTOR MCU")
for i, (dx, dy, r) in enumerate(((-7.7, -3.75, 90), (4.0, -7.7, 0), (7.7, 3.75, 90), (-3.75, 7.7, 0))):
    cap(f"C12{i}", "100nF", (MX + dx, MY + dy), "+3V3_MCU", "GND", r)
cap("C84", "4.7uF", (MX - 9.4, MY - 3.75), "+3V3_MCU", "GND", 90)
# VDDA = VREF+ through 10 R (stm32_pinmap.md pins 28/29): 1 uF + 100 nF + 10 nF
cap("C85", "1uF", (MX + 0.8, MY - 7.7), "+3V3_MCU_A", "GND", 0)
cap("C86", "10nF", (MX + 0.8, MY - 9.3), "+3V3_MCU_A", "GND", 0)
cap("C83", "100nF", (MX + 4.0, MY - 9.3), "+3V3_MCU_A", "GND", 0)
res("R100", "10", (MX - 2.4, MY - 9.3), "+3V3_MCU", "+3V3_MCU_A", 0)
cap("C87", "100nF", (MX - 9.4, MY + 0.75), "MCU_NRST", "GND", 90)
part("Y1", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", "8MHz", (MX - 9.6, MY + 4.4), 0,
     {"1": "OSC_IN", "2": "GND", "3": "OSC_OUT", "4": "GND"}, "smt", "C367183", "8 MHz 12 pF 3225")
cap("C88", "18pF", (MX - 13.4, MY + 5.6), "OSC_IN", "GND", 0)
cap("C89", "18pF", (MX - 13.4, MY + 3.2), "OSC_OUT", "GND", 0)
# row above the MCU (Y -63.9): VMOT sense (rev B R63/R64/C63), NTC pull-ups, BOOT0/NRST from the Pi (rev B R90-R92),
# fan tach 1k series, encoder 22 R series (rev B), ITRIP_SEL pull-up, 3.3 V LDO
ROW_A, ROW_B = -63.9, -60.0
res("R63", "100k", (-20.6, ROW_A), "MOT_BUS", "VMOT_SENSE", 90)
res("R64", "10k", (-18.95, ROW_A), "VMOT_SENSE", "GND", 90)
cap("C63", "100nF", (-17.3, ROW_A), "VMOT_SENSE", "GND", 90)
res("R90", "10k", (-15.65, ROW_A), "MCU_BOOT0", "GND", 90)
res("R91", "1k", (-14.0, ROW_A), "GPIO0", "MCU_BOOT0", 90)
res("R92", "1k", (-12.35, ROW_A), "GPIO1", "MCU_NRST", 90)
for i in range(2):   # fan tach: 1k series into the FT pins PA15 / PB3, 10k pull-up (connectors.json J_FAN)
    res(f"R14{i}", "1k", (-10.7 + 1.5 * i, ROW_A), f"FAN{i + 1}_TACH", f"FAN{i + 1}_TACH_M", 90)
    res(f"R14{i + 2}", "10k", (-10.7 + 1.5 * i, ROW_B), f"FAN{i + 1}_TACH", "+3V3_MCU", 90)
for i, (s, ab) in enumerate((("L", "A"), ("L", "B"), ("R", "A"), ("R", "B"))):
    res(f"R13{i}", "22", (-3.3 + 1.65 * i, ROW_A), f"ENC_{s}_{ab}", f"ENC_{s}_{ab}_M", 90)
# ITRIP_SEL: pulled UP = 2.41 A while the MCU is in reset (spec 11a); ITRIP_SEL2 = DNP second line (drv8243.json Q_B)
res("R1150", "100k", (3.3, ROW_A), "ITRIP_SEL", "+3V3_MCU", 90)
res("R1151", "100k", (4.95, ROW_A), "ITRIP_SEL2", "GND", 90, bom="dnp")
for s, x in (("L", -26.0), ("R", -27.65)):
    res(f"R{11 if s == 'L' else 12}12", "10k", (x, -76.0), "+3V3_MCU", f"NTC_{s}", 90)
# 3.3 V for the MCU, IMU and CAN logic from +5V_MCU (TPS2121 mux: board 5.17 V or USB VBUS), TLV755P SOT-23-5:
# 1 IN, 2 GND, 3 EN, 4 NC, 5 OUT (tlv755p.pdf p.3)
part("U15", SOT23_5, "TLV75533", (12.0, ROW_A), 0, {"1": "+5V_MCU", "2": "GND", "3": "+5V_MCU", "5": "+3V3_MCU"},
     "smt", "C404027", "TI TLV75533PDBVR 3.3 V 500 mA")
cap("C90", "1uF", (15.4, ROW_A), "+5V_MCU", "GND", 90)
cap("C91", "4.7uF", (8.6, ROW_A), "+3V3_MCU", "GND", 90)
res("R93", "1k", (12.0, ROW_B), "MCU_LED", "MCU_LED_A", 0)
led("D93", (15.4, ROW_B), "MCU_LED_A", 180)
# SWD: Tag-Connect TC2030-IDC-NL (connectors.json): 1 VTref, 2 SWDIO, 3 NRST, 4 SWCLK, 5 GND, 6 SWO (NC)
part("J47", "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical", "TC2030 SWD", (-3.0, -59.6), 0,
     {"1": "+3V3_MCU", "2": "SWDIO", "3": "MCU_NRST", "4": "SWCLK", "5": "GND"}, "none", None,
     "Tag-Connect TC2030-IDC-NL footprint (no part)", "SWD")
tp("TP1", "+3V3_MCU", (-18.5, -57.0), "3V3M")
# pull-ups/downs that hold everything safe while the MCU is in reset (below the MCU)
for i, (ref, val, a, b) in enumerate((("R94", "4.7k", "DRV_L_NSLEEP", "GND"), ("R95", "4.7k", "DRV_R_NSLEEP", "GND"),
                                      ("R96", "2.2k", "I2C3_SCL", "+3V3_MCU"), ("R97", "2.2k", "I2C3_SDA", "+3V3_MCU"),
                                      ("R98", "10k", "CAN_STB", "+3V3_MCU"))):
    res(ref, val, (6.0 + 1.65 * i, -84.5), a, b, 90)
# Pi UART0 <-> MCU USART2 (PA2/PA3, bootloader port, AN2606), 100 R series (rev B R10/R11)
res("R10", "100", (6.0, -88.2), "GPIO14", "MCU_RX", 90)
res("R11", "1k", (7.65, -88.2), "MCU_TX", "GPIO15", 90)
# IPROPI to the ADC: 1k at the driver (bottom) + 1 nF C0G and a BAT54S clamp to the rails here (pinmap pins 8/9)
for i, s in enumerate("LR"):
    n = 11 + i
    cap(f"C{n}05", "1nF", (-16.4, -75.0 - 1.7 * i), f"IPROPI_{s}_M", "GND", 0, lcsc="C77026",
        mpn="Murata GRM1885C1H102JA01D C0G")
    part(f"D{n}05", SOT23, "BAT54S", (-20.6, -76.0 - 3.6 * i), 0,
         {"1": "GND", "2": "+3V3_MCU", "3": f"IPROPI_{s}_M"}, "smt", "C8592", "BAT54S (clamp to GND and 3V3)")
# USB VBUS detect on PA6 (TT pin): 22k / 33k = 3.15 V at 5.25 V; bumpers to the MCU through 1k (rev B)
res("R150", "22k", (-24.0, -83.0), "USB_VBUS", "USB_VBUS_DET", 0)
res("R151", "33k", (-24.0, -84.7), "USB_VBUS_DET", "GND", 0)
res("R32", "1k", (-24.0, -86.4), "BUMPER_FRONT", "BUMP_F_M", 0)
res("R33", "1k", (-24.0, -88.1), "BUMPER_REAR", "BUMP_R_M", 0)
# E-stop logic (rev B): ESTOP -> TIM1_BKIN (PB10) + TIM8_BKIN (PD2): high-side brake at once (DRV8243 IN1/IN2 = 0/0,
# table 7-5 p.34); ESTOP -> 100k/2.2uF (~0.29 s) and MCU_ALIVE (charge pump) -> Schmitt NAND -> DRVOFF: bridges Hi-Z.
# DRVOFF is read back on PA4 (pin 18) through 10k, so a PA4 misconfigured as an output cannot fight the NAND.
res("R17", "10k", (14.6, -68.5), "ESTOP", "GND", 90)
res("R18", "100k", (16.25, -68.5), "ESTOP", "ESTOP_DLY", 90)
cap("C18", "2.2uF", (17.9, -68.5), "ESTOP_DLY", "GND", 90)
part("U16", SOT23_5, "SN74LVC1G132", (16.6, -73.5), 0, {"1": "ESTOP_DLY", "2": "ALIVE_DET", "3": "GND",
                                                        "4": "DRVOFF", "5": "+3V3_MCU"}, "smt", "C403723",
     "TI SN74LVC1G132DBVR Schmitt NAND")
cap("C19", "100nF", (19.8, -73.5), "+3V3_MCU", "GND", 90)
cap("C14A", "100nF", (12.6, -78.0), "MCU_ALIVE", "ALIVE_AC", 90)
part("D12", SOT23, "BAT54S", (15.6, -78.0), 0, {"1": "GND", "2": "ALIVE_DET", "3": "ALIVE_AC"}, "smt",
     "C8592", "BAT54S")
cap("C14B", "100nF", (18.6, -78.0), "ALIVE_DET", "GND", 90)
res("R14B", "100k", (20.25, -78.0), "ALIVE_DET", "GND", 90)
tp("TP2", "DRVOFF", (23.0, -68.5), "DRVOFF")
res("R19", "10k", (25.0, -76.0), "DRVOFF", "DRVOFF_MON", 90)
tp("TP3", "ESTOP", (23.0, -73.0), "ESTOP")

# ---------------------------------------------------------------- MCU power mux + USB-C (rear edge, top, reachable with
# the robot assembled). TPS2121 (tps2121.json, SLVSEA3F): IN1 = +5V priority, IN2 = USB VBUS, XCOMP (PR1 20k/10k,
# CP2 23.2k/10k, p.25-26), OV2 45.3k/10k (5.6-6.1 V), OV1 -> GND, ILM 80.6k = 1.5 A (p.13 eq.2), SS 100 nF,
# ST -> test point (no MCU pin left). USB4105 (usb4105.json): CC 5.1k Rd each, D+/D- through USBLC6-2SC6
# (flow-through) to PA11/PA12.
part("J50", USBC_V, "USB-C MCU", (17.5, -130.5), 0,
     {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "A4": "USB_VBUS", "A9": "USB_VBUS", "B4": "USB_VBUS",
      "B9": "USB_VBUS", "A5": "USB_CC1", "B5": "USB_CC2", "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM",
      "B7": "USB_DM", "SH": "GND"}, "smt", "C5250720", "GCT USB4115-03-C vertical", "USB MCU")
res("R471", "5.1k", (7.5, -125.0), "USB_CC1", "GND", 90)
res("R472", "5.1k", (16.5, -125.0), "USB_CC2", "GND", 90)
part("U47", SOT23_6, "USBLC6-2SC6", (12.0, -124.5), 0, {"1": "USB_DP", "2": "GND", "3": "USB_DM", "4": "USB_DM",
                                                        "5": "USB_VBUS", "6": "USB_DP"}, "smt", "C7519",
     "ST USBLC6-2SC6")
part("U32", "rabbit_body:TI_RUX0012A_VQFN-HR-12_2x2.5mm", "TPS2121", (24.0, -123.5), 0,
     {"1": "+5V_MCU", "2": "USB_VBUS", "3": "MUX_CP2", "4": "MUX_OV2", "5": "GND", "6": "MUX_PR1", "7": "+5V",
      "8": "+5V_MCU", "9": "PWR_SRC_IN1", "10": "MUX_ILM", "11": "MUX_SS", "12": "GND"}, "smt", "C485916",
     "TI TPS2121RUXR", "MCU 5V MUX")
for i, (val, a, b, prec) in enumerate((("20k", "+5V", "MUX_PR1", True), ("10k", "MUX_PR1", "GND", True),
                                       ("23.2k", "USB_VBUS", "MUX_CP2", True), ("10k", "MUX_CP2", "GND", True),
                                       ("45.3k", "USB_VBUS", "MUX_OV2", True), ("10k", "MUX_OV2", "GND", True),
                                       ("80.6k", "MUX_ILM", "GND", True), ("10k", "PWR_SRC_IN1", "+3V3_MCU", False))):
    res(f"R32{i}", val, (19.4 + 1.65 * i, -119.5), a, b, 90, prec=prec)
cap("C321", "100nF", (27.5, -124.0), "MUX_SS", "GND", 90, lcsc="C77055", mpn="Murata GRM188R71H104KA93D")
cap("C322", "1uF", (20.4, -126.5), "+5V", "GND", 0, lcsc="C85862", mpn="Murata GCM188R71E105KA64D")
cap("C323", "1uF", (24.5, -127.5), "USB_VBUS", "GND", 0, lcsc="C85862", mpn="Murata GCM188R71E105KA64D")
cap("C324", "10uF", (29.5, -127.8), "+5V_MCU", "GND", 0, C0805, lcsc="C237493",
    mpn="Murata GRM21BZ71E106KE15L 25V")
tp("TP4", "PWR_SRC_IN1", (27.5, -131.5), "SRC")
tp("TP5", "+5V_MCU", (31.0, -131.5), "5VM")

# ---------------------------------------------------------------- IMU (icm42688p.json): ICM-42688-P on SPI3, near the
# board centre line, away from holes, buzzer and inductors; +3V3_IMU through 10 R. Bosch LGA-14 land (pad centres equal
# the ICM leads, p.55). Pin 9 (INT2/FSYNC/CLKIN) can take the DS3231 32 kHz TCXO through DNP 0R (ds3231.json option).
IX, IY = -14.0, -46.0
part("U42", "Package_LGA:Bosch_LGA-14_3x2.5mm_P0.5mm", "ICM-42688-P", (IX, IY), 0,
     {"1": "SPI3_MISO", "2": "GND", "3": "GND", "4": "IMU_INT1", "5": "+3V3_IMU", "6": "GND", "7": "GND",
      "8": "+3V3_IMU", "9": "IMU_CLKIN", "10": "GND", "11": "GND", "12": "IMU_CS", "13": "SPI3_SCK",
      "14": "SPI3_MOSI"}, "smt", "C1850418", "TDK ICM-42688-P (not the TOKMAS/-PC clones)", "IMU")
cap("C421", "100nF", (IX + 3.6, IY + 1.0), "+3V3_IMU", "GND", 90)
cap("C422", "2.2uF", (IX + 5.25, IY + 1.0), "+3V3_IMU", "GND", 90, lcsc="C100082", mpn="Samsung CL10B225KP8NNNC")
cap("C423", "10nF", (IX - 3.6, IY + 1.0), "+3V3_IMU", "GND", 90)
res("R421", "10", (IX + 6.9, IY + 1.0), "+3V3_MCU", "+3V3_IMU", 90)
res("R422", "10k", (IX - 5.25, IY + 1.0), "IMU_CS", "+3V3_IMU", 90)
res("R423", "0", (IX - 6.9, IY + 1.0), "RTC_32K", "IMU_CLKIN", 90, bom="dnp")
res("R424", "10k", (IX - 8.55, IY + 1.0), "RTC_32K", "+3V3_MCU", 90, bom="dnp")
res("R425", "100k", (IX - 6.9, IY - 2.4), "IMU_CLKIN", "GND", 90)   # CLKIN tied low while R423 is not fitted (DS)

# ---------------------------------------------------------------- CAN-FD (tcan1044av.json): TCAN1044AV-Q1 on FDCAN2,
# VCC from +5V_MCU, VIO +3V3_MCU; split termination 2 x 60.4 R 1206 + 4.7 nF with two solder jumpers (open);
# PESD2CANFD24V; JST GH-4 at the rear edge (1 +5V_AUX from the spare 5 V eFuse, 2 CANH, 3 CANL, 4 GND).
part("J51", GH4, "CAN GH-4", (-23.5, -130.5), 0, {"1": "+5V_AUX", "2": "CANH", "3": "CANL", "4": "GND",
                                                   "MP": "GND"}, "smt", "C161692", "JST BM04B-GHS-TBT(LF)(SN) vertical", "CAN")
part("U46", "Package_SON:VSON-8-1EP_3x3mm_P0.65mm_EP1.65x2.4mm", "TCAN1044AV", (-22.0, -125.3), 0,
     {"1": "CAN_TX", "2": "GND", "3": "+5V_MCU", "4": "CAN_RX", "5": "+3V3_MCU", "6": "CANL", "7": "CANH",
      "8": "CAN_STB", "9": "GND"}, "smt", "C3234119", "TI TCAN1044AVDRBRQ1")
cap("C461", "100nF", (-27.0, -124.5), "+5V_MCU", "GND", 0)
cap("C462", "100nF", (-27.0, -126.2), "+3V3_MCU", "GND", 0)
part("D461", SOT23, "PESD2CANFD24V", (-16.5, -125.5), 0, {"1": "CANH", "2": "CANL", "3": "GND"}, "smt",
     "C552486", "Nexperia PESD2CANFD24V-TR (pins 1/2 lines, 3 GND [check])")
part("JP461", JP2, "CANH term", (-30.5, -129.0), 90, {"1": "CANH", "2": "CAN_TH"}, "none")
part("JP462", JP2, "CANL term", (-30.5, -125.4), 90, {"1": "CANL", "2": "CAN_TL"}, "none")
part("R461", R1206, "60.4R", (-30.5, -121.5), 0, {"1": "CAN_TH", "2": "CAN_SPLIT"}, "smt", "C57572",
     "UNI-ROYAL 1206W4F604JT5E 60.4 R 1%")
part("R462", R1206, "60.4R", (-30.5, -118.8), 0, {"1": "CAN_SPLIT", "2": "CAN_TL"}, "smt", "C57572",
     "UNI-ROYAL 1206W4F604JT5E 60.4 R 1%")
cap("C463", "4.7nF", (-26.5, -119.8), "CAN_SPLIT", "GND", 90)

# ---------------------------------------------------------------- temperature (tmp117.json): TMP117 0x48 at the DRV8243
# pair (bottom, on the GND pour next to them) and 0x49 between the bucks (top); STM32 I2C3, ALERT not wired.
part("U44", "Package_SON:WSON-6-1EP_2x2mm_P0.65mm_EP1x1.6mm", "TMP117 0x48", (0.0, -76.0), 0,
     {"1": "I2C3_SCL", "2": "GND", "4": "GND", "5": "+3V3_MCU", "6": "I2C3_SDA", "7": "GND"}, "smt", "C699536",
     "TI TMP117AIDRVR", side="B")
cap("C441", "100nF", (0.0, -79.0), "+3V3_MCU", "GND", 0, side="B")
part("U45", "Package_SON:WSON-6-1EP_2x2mm_P0.65mm_EP1x1.6mm", "TMP117 0x49", (-8.0, 47.0), 0,
     {"1": "I2C3_SCL", "2": "GND", "4": "+3V3_MCU", "5": "+3V3_MCU", "6": "I2C3_SDA", "7": "GND"}, "smt", "C699536",
     "TI TMP117AIDRVR")
cap("C451", "100nF", (-8.0, 49.8), "+3V3_MCU", "GND", 0)

# ---------------------------------------------------------------- magnetometer (mmc5983ma.json), assembled (owner: fit everything):
# I2C3 0x30, SPI_CS tied to VDDIO; KiCad LGA-16 pad 1 is the package rotated 90 deg (sensor axes rotated in firmware)
part("U43", "Package_LGA:LGA-16_3x3mm_P0.5mm", "MMC5983MA", (14.0, 125.0), 0,
     {"1": "I2C3_SCL", "2": "+3V3_MCU", "4": "+3V3_MCU", "9": "GND", "10": "MAG_CAP", "11": "GND", "13": "+3V3_MCU",
      "16": "I2C3_SDA"}, "smt", "C404329", "MEMSIC MMC5983MA")
cap("C431", "1uF", (14.0, 128.2), "+3V3_MCU", "GND", 0, bom="smt", lcsc="C29936", mpn="Samsung CL10B105KA8NNNC")
cap("C432", "10uF", (17.6, 125.0), "MAG_CAP", "GND", 90, C0805, bom="smt", lcsc="C95841",
    mpn="Samsung CL21B106KOQNNNE 16V")

# ---------------------------------------------------------------- E-stop: 2-channel NC input (connectors.json J_ESTOP):
# 1 ESTOP_A (Pi GPIO16 via 100 R), 2 ESTOP (10k to GND: a dead Pi, an open loop or a broken wire is STOP),
# 3 +3V3_MCU via 1k (channel 2 source), 4 ESTOP2_M (-> PC15, 10k to GND). A shorting plug 1-2 + 3-4 runs without a
# button (replaces rev B's J5 jumper). TPD4E05U06 at the connector.
EX, EY = -52.0, -112.0
part("J52", XH4, "E-stop XH-4", (EX, EY), 90, {"1": "ESTOP_A", "2": "ESTOP", "3": "ESTOP2_SRC", "4": "ESTOP2_M"},
     "tht", "C144395", "JST B4B-XH-A(LF)(SN)", "E-STOP")
res("R16", "1k", (EX + 7.0, EY + 8.2), "GPIO16", "ESTOP_A", 90)
res("R160", "1k", (EX + 8.65, EY + 8.2), "+3V3_MCU", "ESTOP2_SRC", 90)
res("R161", "10k", (EX + 10.3, EY + 8.2), "ESTOP2_M", "GND", 90)
esd4("D52", (EX + 7.0, EY + 2.5), ("ESTOP_A", "ESTOP", "ESTOP2_SRC", "ESTOP2_M"), 0)

# ---------------------------------------------------------------- 5.17 V body rail: F3 8 A -> LM61495 (100k/24k) ->
# 5 mOhm (INA238 0x47) -> +5V. The Pi is fed from +5V through the U87 eFuse and J53 USB-C (ribbon 5 V pins open).
BUCK_Y = 46.5
part("F3", FUSE, "8A", (-40.6, 37.0), 0, {"1": "VBUS", "2": "BODY_IN"}, "smt", "C142876",
     "Littelfuse 0451008.MRL 8 A", "F3 5V 8A")
buck(4, (-30.0, BUCK_Y), "BODY_IN", "+5V_BUCK", "5.17V BUCK", fb_bot="24k", pg="5V_PG")
shunt("R6", "5mR 1W", (-16.0, 63.5), 0, "+5V_BUCK", "+5V", "SH6_P", "SH6_N", "C844900",
      "Vishay WSL25125L000FEA 5 mOhm 1% 1 W")
ina238("U26", (-20.0, 56.5), "F", "SH6_P", "SH6_N", "SH6_N", "+3V3_PI", "I2C1_SCL", "INA 5V 0x47")
cap("C9", "10uF", (-6.0, 63.5), "+5V", "GND", 90, C0805)
res("R36", "1k", (-47.0, 30.5), "+5V", "LED5_A", 90)
led("D2", (-47.0, 34.0), "LED5_A", 270)
cap("C13", "10uF", (-28.6, 33.5), "+5V", "GND", 90, C0805)

# ---------------------------------------------------------------- servo rail: F4 10 A -> LM61495 6.0/7.4 V -> 5 mOhm
# (INA238 #3 0x43) -> SERVO_RAW -> TPS259470L 549 R (6.07 A, ITIMER 22 nF, dVdt 4.7 nF) -> SERVO_PWR -> 8 headers.
# EN and the 7.4 V select from PCAL6524 0x22 (P1_4, P1_5), RESET -> SERVO_BUCK_PG (0x23 P1_4).
part("F4", FUSE, "10A", (28.0, 38.5), 180, {"1": "VBUS", "2": "STEER_IN"}, "smt", "C44479",
     "Littelfuse 0451010.MRL 10 A", "F4 SERVO 10A")
buck(6, (14.0, BUCK_Y), "STEER_IN", "SERVO_BUCK", "SERVO BUCK", en="SERVO_BUCK_EN", pg="SERVO_BUCK_PG", servo=True)
shunt("R2", "5mR 1W", (34.0, 56.0), 270, "SERVO_BUCK", "SERVO_RAW", "SH3_P", "SH3_N", "C844900",
      "Vishay WSL25125L000FEA 5 mOhm 1% 1 W")
ina238("U23", (25.0, 61.5), "F", "SH3_P", "SH3_N", "SH3_N", "GND", "I2C1_SCL", "INA SERVO 0x43")
tvs("D13", (45.5, 30.5), "VBUS", rot=90)
part("C33", CPOLY, "220uF 35V", (37.0, 44.0), 90, {"1": "VBUS", "2": "GND"}, "smt", LCSC_C["220uF35V"],
     "Panasonic EEH-ZK1V221UP 220 uF 35 V hybrid polymer, AEC-Q200")

# ---------------------------------------------------------------- ToF 3.3 V rail (tps62826.json, SLVSEF9I): +5V ->
# TPS62826 3 A (FB 115k/25.5k 0.1 % = 3.306 V, C_FF 470 pF, p.12 eq.4-5) -> +3V3_TOF -> the 6 ToF ports (through
# the carrier's own regulators) and the encoder eFuse U78. EN from PCAL6524 0x22 P2_5 (pull-down: off until the Pi
# enables it), PG -> 0x23 P2_6.
TX0, TY0 = -4.0, 50.0
b = Blk(TX0, TY0, "B")
part("U31", "rabbit_body:TI_DMQ0006A_VSON-HR-6_1.5x1.5mm", "TPS62826", b.at(0, 0), 0,
     {"1": "TOF3V3_EN", "2": "TOF3V3_PG", "3": "FB_TOF", "4": "GND", "5": "SW_TOF", "6": "+5V"}, "smt", "C2073319",
     "TI TPS62826DMQR", "3V3 TOF BUCK", side="B")
part("L31", "Inductor_SMD:L_Coilcraft_XxL4020", "0.47uH", b.at(4.4, 0), 0, {"1": "SW_TOF", "2": "+3V3_TOF"},
     "smt", "C5837785", "Coilcraft XGL4020-471MEC 0.47 uH 13.4 A", side="B")
cap("C311", "10uF", b.at(-0.3, 2.2), "+5V", "GND", 0, side="B", lcsc="C237435", mpn="Murata GRM188Z71A106MA73D 10V")
cap("C312", "100nF", b.at(-0.3, -2.0), "+5V", "GND", 0, side="B", lcsc="C77055", mpn="Murata GRM188R71H104KA93D")
for i in range(3):
    cap(f"C31{3 + i}", "10uF", b.at(9.3, 1.7 - 1.7 * i), "+3V3_TOF", "GND", 0, side="B", lcsc="C237435",
        mpn="Murata GRM188Z71A106MA73D 10V")
res("R311", "115k", b.at(-3.4, 1.2), "+3V3_TOF", "FB_TOF", 90, side="B", prec=True)
res("R312", "25.5k", b.at(-5.05, 1.2), "FB_TOF", "GND", 90, side="B", prec=True)
cap("C316", "470pF", b.at(-6.7, 1.2), "+3V3_TOF", "FB_TOF", 90, side="B", lcsc="C85979",
    mpn="Murata GRM1885C1H471JA01D C0G")
res("R40A", "330", b.at(-3.4, -2.6), "+3V3_TOF", "LED33_A", 90, side="B")
led("D6", b.at(-5.05, -2.6), "LED33_A", 90, side="B")

# ---------------------------------------------------------------- shared eFuse OVLO dividers (tps259470l.json): one per
# rail, V_OV = 1.20 V x (R1 + R2) / R2 (p.27 eq.2): +5V 40.2k/10k = 6.02 V, +3V3_TOF 23.2k/10k = 3.98 V, servo
# 61.9k/10k = 8.63 V
for i, (top, rail, net) in enumerate((("40.2k", "+5V", "OVLO_5V"), ("23.2k", "+3V3_TOF", "OVLO_3V3"))):
    res(f"R16{2 + 2 * i}", top, (24.5 + 3.3 * i, -8.5), rail, net, 90, side="B", prec=True)
    res(f"R16{3 + 2 * i}", "10k", (26.15 + 3.3 * i, -8.5), net, "GND", 90, side="B", prec=True)

# ---------------------------------------------------------------- eFuses under the Pi (bottom): encoders on +3V3_TOF
# (0.5 A, 6.65k), fans x2 (0.5 A), spare 5 V (2 A, 1.65k), Pi USB-C (3.76 A, 887 R, auto-retry) on +5V
EFUSES = []   # (U, name, rail, out, R_ILM, dVdt, ITIMER, OVLO, at, schottky)
EFUSES.append(("U78", "ENC", "+3V3_TOF", "ENC_3V3", "6.65k", "2.2nF", "1nF", "OVLO_3V3", (16.0, 3.5), None))
EFUSES.append(("U84", "FAN1", "+5V", "FAN1_5V", "6.65k", "2.2nF", "10nF", "OVLO_5V", (-14.0, -8.5), "SMA"))
EFUSES.append(("U85", "FAN2", "+5V", "FAN2_5V", "6.65k", "2.2nF", "10nF", "OVLO_5V", (-4.0, -8.5), "SMA"))
EFUSES.append(("U86", "AUX", "+5V", "+5V_AUX", "1.65k", "2.2nF", "10nF", "OVLO_5V", (6.0, -8.5), None))
# Pi 4 power (owner, Q47 -> USB-C): +5V -> this eFuse -> J53 USB-C -> the Pi's USB-C input; the ribbon's 5 V pins 2/4
# stay open (two feeds would back-power each other). EN is a 100k/100k divider from +5V, not on the expander: an
# expander reset (GPIO6) must not cut the Pi's own power; the Pi goes off only with the main latch.
EFUSES.append(("U87", "USB_PI", "+5V", "+5V_PI_USBC", "887", "2.2nF", "10nF", "OVLO_5V", (16.0, -8.5), None))
# lidar eFuses on +5V (spec 11a), under the lidar ports (bottom front)
for i in range(3):
    EFUSES.append((f"U{80 + i}", f"LIDAR{i + 1}", "+5V", f"LIDAR{i + 1}_5V", "1.65k", "2.2nF", "10nF", "OVLO_5V",
                   (-38.0 + 16.0 * i, 79.0), "SMA"))
EFUSES.append(("U83", "SERVO", "SERVO_RAW", "SERVO_PWR", "549", "4.7nF", "22nF", "OVLO_SERVO", (-32.0, 99.5), None))
for u, name, rail, out, rilm, dvdt, itm, ovlo, at, sch in EFUSES:
    side = "F" if name == "SERVO" else "B"
    efuse(u, name, rail, out, rilm, dvdt, itm, ovlo, at, side, sch)
res("R879", "100k", (19.6, -9.3), "USB_PI_EN", "+5V", 90, side="B")
res("R878", "100k", (21.3, -9.3), "USB_PI_EN", "GND", 90, side="B")   # EN 2.6 V: inside its 5 V recommended max
# servo rail extras: Schottky B540C on SERVO_PWR (5.5 A, tps259470l.json note), 2 x 470 uF 25 V hybrid polymer
# (Panasonic EEHZK1E471P, C242138, spec 5), OVLO divider
part("D831", SMC, "B540C", (-8.0, 103.0), 0, {"1": "SERVO_PWR", "2": "GND"}, "smt", "C72264",
     "Diodes B540C-13-F 40 V 5 A Schottky")
for i, x in enumerate((-20.5, 22.0)):
    part(f"C83{5 + i}", CPOLY10, "470uF 25V", (x, 104.3 if x < 0 else 105.0), 0, {"1": "SERVO_PWR", "2": "GND"}, "smt", "C242138",
         "Panasonic EEHZK1E471P 470 uF 25 V hybrid polymer")
res("R166", "61.9k", (-42.5, 98.5), "SERVO_RAW", "OVLO_SERVO", 0, prec=True)
res("R167", "10k", (-42.5, 96.8), "OVLO_SERVO", "GND", 0, prec=True)
res("R37", "1.5k", (-4.0, 98.5), "SERVO_PWR", "LED6_A", 0)
led("D3", (-0.6, 98.5), "LED6_A", 0)

# ---------------------------------------------------------------- xArm 1S bus servos (data/pcb-revc/ics/xarm_bus.md):
# power from SERVO_RAW (the 10 A servo buck, 6.0 / 7.4 V, behind INA238 0x43) through its own TPS259470L eFuse, the
# active current limit variant (SLVSFC9C device table p.4): R_ILM 750 R -> 4.45 A (3334 / R, p.32 eq.7), a stalled arm is held
# at its limit; arm + steering at worst-case limits (4.84 + 6.60 A) exceed the buck's 9.8 A minimum, accepted: the arm
# and the steering do not move at the same time (owner, 2026-10-11)
# (sim S-2); latch-off after thermal shutdown (the Pi re-enables it); OVLO on the steering eFuse's divider
# (61.9k/10k = 8.63 V), so a servo buck failing high never reaches the arm (replaces the TLV6700 of round 1, and the
# TPS259824L that JLC does not stock); ILM -> 10k -> ARM_IMON (ADS7128 0x17 AIN5), FLT -> AIN6 as GPIO with 10k to
# ADC_AVDD; EN <- ARM_EN (PCAL6524 0x22, 100k pull-down array): off until the Pi enables it.
# Signal: STM32 PB9 USART3_TX AF7 single-wire half-duplex, open drain, 4.7k to 3.3 V -> BSS138 (gate
# at 3.3 V) -> ARM_SIG_B, 4.7k to ARM_5V (TLV76050 from ARM_PWR: no pull-up feeds unpowered servos; BAT54WS keeps
# ARM_5V below ARM_PWR) -> 390 R 1206 -> ARM_SIG (PB9 <= 20 mA even with SIG on ARM_PWR), TPD1E10B09 (9 V working: survives 8.4 V on SIG).
# ARM_PWR: 220 uF polymer + 2 x 22 uF, B340A for the cable's inductive kick when the eFuse opens.
# 2 x PH-3 vertical in parallel (chain can be split in two branches): 1 GND, 2 ARM_PWR, 3 ARM_SIG.
AX, AY = 11.0, 75.0
efuse("U88", "ARM", "SERVO_RAW", "ARM_PWR", "750", "4.7nF", "22nF", "OVLO_SERVO", (AX, AY), side="F")
cap("C889", "10uF50V", (AX - 5.4, AY), "SERVO_RAW", "GND", 90, C1210)
res("R886", "10k", (AX - 5.4, AY - 4.4), "ARM_FLT", "ADC_AVDD", 90)
cap("C885", "22uF", (AX - 1.6, AY + 4.6), "ARM_PWR", "GND", 0, C1206)
cap("C886", "22uF", (AX + 3.2, AY + 4.6), "ARM_PWR", "GND", 0, C1206)
part("C887", CPOLY, "220uF 35V", (-1.5, 73.0), 90, {"1": "ARM_PWR", "2": "GND"}, "smt", LCSC_C["220uF35V"],
     "Panasonic EEH-ZK1V221UP 220 uF 35 V hybrid polymer, AEC-Q200")
part("D88", SMA, "B340A", (AX + 7.4, AY - 1.0), 90, {"1": "ARM_PWR", "2": "GND"}, "smt", "C85098",
     "Diodes B340A-13-F 40 V 3 A Schottky")
part("U89", SOT23, "TLV76050", (-3.0, 81.6), 0, {"1": "ARM_5V", "2": "ARM_PWR", "3": "GND"}, "smt", "C2867465",
     "TI TLV76050DBZR 5 V 100 mA")
cap("C895", "1uF", (-3.0, 84.2), "ARM_PWR", "GND", 0)
cap("C896", "1uF", (0.0, 81.6), "ARM_5V", "GND", 90)
res("R890", "4.7k", (16.4, 83.4), "ARM_PWR", "GND", 90)   # bleed: ARM_PWR falls in ~1 s
part("D90", SOD323, "BAT54WS", (0.0, 84.0), 0, {"1": "ARM_PWR", "2": "ARM_5V"}, "smt", "C124205",
     "Diodes BAT54WS-7-F (ARM_5V cannot rise above ARM_PWR: 8.4 V on SIG, sim S-3)", side="B")
part("Q88", SOT23, "BSS138", (4.0, 82.6), 0, {"1": "+3V3_MCU", "2": "ARM_UART_M", "3": "ARM_SIG_B"}, "smt", "C82045",
     "onsemi BSS138LT1G")
res("R887", "4.7k", (14.7, 83.4), "ARM_UART_M", "+3V3_MCU", 90)
res("R888", "4.7k", (7.6, 83.0), "ARM_SIG_B", "ARM_5V", 90)
res("R889", "390", (9.6, 83.4), "ARM_SIG_B", "ARM_SIG", 90, fp=R1206, lcsc="C4491",
    mpn="1206 390R 1% 0.25 W (PB9 <= 20 mA with SIG shorted to ARM_PWR, round2 A-1)")
part("D89", "rabbit_body:TI_DPY0002A_X1SON-2", "TPD1E10B09", (11.9, 83.4), 90, {"1": "ARM_SIG", "2": "GND"}, "smt",
     "C88031", "TI TPD1E10B09DPYR 9 V bidirectional ESD")
for i, x in enumerate((3.5, 12.5)):
    part(f"J8{i}", "Connector_JST:JST_PH_B3B-PH-K_1x03_P2.00mm_Vertical", "xArm bus", (x, 90.2), 0,
         {"1": "GND", "2": "ARM_PWR", "3": "ARM_SIG"}, "tht", "C131339", "JST B3B-PH-K-S(LF)(SN)",
         "ARM - + S" if i == 0 else "ARM 2")

# ---------------------------------------------------------------- ADS7128 x2 + REF3425 (ads7128.json, SBAS868A): per-load
# current from the eFuse ILM / TPS16630 IMON pins, 10k at the source + 1 nF at the ADC pin (spec 11a). AVDD is the
# reference: REF3425 2.5 V for both (pins 1/2 GND, 3 EN, 4 IN, 5 OUT_S, 6 OUT_F). Addresses (table 2 p.16):
# 0x10 ADDR open, 0x11 11k ADDR->GND, 0x17 0R DECAP->ADDR. Channels per ads7128.json; ADC3 AIN3/AIN4 take the Pi
# USB-C eFuse ILM and its FLT (as GPIO, pulled to ADC_AVDD: AIN abs max is AVDD + 0.3 V, p.5).
ADC = [("U35", "0x11", ["LIDAR1_IMON", "LIDAR2_IMON", "LIDAR3_IMON", "SERVO_IMON", "FAN1_IMON", "FAN2_IMON",
                        "AUX_IMON", "ENC_IMON"], (43.0, 7.0)),
       ("U36", "0x17", [None, "JET_IMON", "SPAREBAT_IMON", "USB_PI_IMON", "USB_PI_FLT", "ARM_IMON", "ARM_FLT", None],
        (43.0, -3.0))]
AIN_PIN = ("15", "16", "1", "2", "3", "4", "5", "6")   # AIN0..AIN7 (ads7128.json pins_generic, DS p.4)
for u, addr, ch, at in ADC:
    k = {"U35": 1, "U36": 2}[u]   # net names ADC2_*, ADC3_* as before; ADC1 (ToF ports) removed
    b = Blk(*at, "B")
    n = int(u[1:])
    pins = {"7": "ADC_AVDD", "8": f"ADC{k + 1}_DECAP", "9": "GND", "10": "+3V3_PI", "12": "PWR_ALERT_N",
            "13": "I2C1_SCL", "14": "I2C1_SDA", "17": "GND"}
    if addr != "0x10":
        pins["11"] = f"ADC{k + 1}_ADDR"
    for p, net in zip(AIN_PIN, ch):
        if net:
            pins[p] = net
    part(u, "Package_DFN_QFN:WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm", "ADS7128", b.at(0, 0), 0, pins, "smt",
         "C2867992", "TI ADS7128IRTER", f"ADC {addr}", side="B")
    cap(f"C{n}1", "1uF", b.at(-0.2, -4.0), "ADC_AVDD", "GND", 0, side="B", lcsc="C29936",
        mpn="Samsung CL10B105KA8NNNC")
    cap(f"C{n}2", "1uF", b.at(3.3, -4.0), f"ADC{k + 1}_DECAP", "GND", 0, side="B", lcsc="C29936",
        mpn="Samsung CL10B105KA8NNNC")
    cap(f"C{n}3", "1uF", b.at(3.9, 0.5), "+3V3_PI", "GND", 90, side="B", lcsc="C29936", mpn="Samsung CL10B105KA8NNNC")
    if addr == "0x11":
        res(f"R{n}1", "11k", b.at(5.55, 0.5), "ADC2_ADDR", "GND", 90, side="B")
    if addr == "0x17":
        res(f"R{n}1", "0", b.at(5.55, 0.5), "ADC3_DECAP", "ADC3_ADDR", 90, side="B")
    # 1 nF hold caps at the ADC pins (CSH 12 pF kick-back, p.14)
    nets = [x for x in ch if x and x not in ("USB_PI_FLT", "ARM_FLT")]
    for j, net in enumerate(nets):
        cap(f"C{n}{5 + j}", "1nF", b.at(-3.95 - 1.65 * (j % 4), 1.65 - 3.3 * (j // 4)), net, "GND", 90, side="B")
res("R362", "10k", (46.0, -9.6), "USB_PI_FLT", "ADC_AVDD", 0, side="B")
part("U33", SOT23_6, "REF3425", (55.0, 17.0), 90, {"1": "GND", "2": "GND", "3": "+5V", "4": "+5V", "5": "ADC_AVDD",
                                                  "6": "ADC_AVDD"}, "smt", "C187836",
     "TI REF3425IDBVR 2.5 V 0.05 % 6 ppm", side="B")
cap("C331", "100nF", (55.0, 13.4), "+5V", "GND", 0, side="B")
cap("C332", "1uF", (55.0, 20.6), "ADC_AVDD", "GND", 0, side="B", lcsc="C29936", mpn="Samsung CL10B105KA8NNNC")

# ---------------------------------------------------------------- PCAL6524 x2 (pcal6524.json, NXP Rev.2): 0x22 = load
# enables (outputs, 100k pull-down arrays: all I/O are inputs at power-on, p.7), 0x23 = FLT/PG inputs with latched
# interrupts (10k pull-up arrays). RESET (pin 28) = EXP_RESET_N from Pi GPIO6 with a 10k pull-down: every switched
# load stays off until the Pi drives it high (pi_pinmap.md). INT -> EXP_INT_N (GPIO7). QFN-32 5x5 EP3.1 KiCad land
# instead of the NXP HUQFN32 land (pads 0.875 x 0.25 at +-2.44 vs NXP 0.9 x 0.29 at +-2.55, EP 3.1 vs 3.0).
EN_PORT = ["EXP_OUT_SPARE7", "EXP_OUT_SPARE8", "EXP_OUT_SPARE9", "EXP_OUT_SPARE10", "EXP_OUT_SPARE5", "EXP_OUT_SPARE6", "ARM_EN", "EXP_OUT_SPARE4",
           "LIDAR1_EN", "LIDAR2_EN", "LIDAR3_EN", "SERVO_EN", "SERVO_BUCK_EN", "SERVO_7V4", "FAN1_EN", "FAN2_EN",
           "AUX_EN", "ENC_EN", "EXP_OUT_SPARE3", "SPAREBAT_EN", "MOT_BUS_OFF", "TOF3V3_EN", "EXP_OUT_SPARE2", "EXP_OUT_SPARE"]
FLT_PORT = ["EXP_IN_SPARE3", "EXP_IN_SPARE4", "EXP_IN_SPARE5", "EXP_IN_SPARE6", "EXP_IN_SPARE7", "EXP_IN_SPARE8", "EXP_IN_SPARE1", "EXP_IN_SPARE2",
            "LIDAR1_FLT", "LIDAR2_FLT", "LIDAR3_FLT", "SERVO_FLT", "SERVO_BUCK_PG", "5V_PG", "FAN1_FLT", "FAN2_FLT",
            "AUX_FLT", "ENC_FLT", "EXP_IN_SPARE9", "SPAREBAT_FLT", "JET_FLT", "MOT_BUS_PG", "TOF3V3_PG", "RTC_INT_N"]
PCAL = (("U37", EN_PORT, "GND", (-12.0, -24.0), "GND", 1), ("U38", FLT_PORT, "+3V3_PI", (4.0, -24.0), "+3V3_PI", 7))
for u, port, addr, at, pull, rn0 in PCAL:
    b = Blk(*at, "B")
    pins = {str(i + 1): net for i, net in enumerate(port)}
    pins.update({"25": "GND", "26": addr, "27": "+3V3_PI", "28": "EXP_RESET_N", "29": "I2C1_SCL", "30": "I2C1_SDA",
                 "31": "+3V3_PI", "32": "EXP_INT_N", "33": "GND"})
    part(u, "Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm", "PCAL6524", b.at(0, 0), 0, pins, "smt", "C3000497",
         "NXP PCAL6524HEAZ", f"EXP 0x{'22' if addr == 'GND' else '23'}", side="B")
    n = int(u[1:])
    cap(f"C{n}1", "100nF", b.at(-1.6, 4.0), "+3V3_PI", "GND", 0, side="B")
    cap(f"C{n}2", "100nF", b.at(1.6, 4.0), "+3V3_PI", "GND", 0, side="B")
    # arrays: R_Array_Convex_4x0603, resistor k between pins k and 9-k; 4 lines per array, P0 left, P1 bottom, P2 right
    spots = [((-5.5, 2.0), 0), ((-5.5, -2.0), 0), ((-2.0, -5.3), 90), ((2.0, -5.3), 90), ((5.5, -2.0), 0),
             ((5.5, 2.0), 0)]
    for j, ((dx, dy), r) in enumerate(spots):
        lines = port[4 * j: 4 * j + 4]
        pins = {}
        for k, line in enumerate(lines):
            other = pull
            if line == "MOT_BUS_OFF":
                other = "+3V3_MCU"   # motor bus OFF by default (spec 11a)
            pins[str(k + 1)], pins[str(8 - k)] = line, other
        val, lcsc, mpn = (("100k x4", "C1996", "UNI-ROYAL 4D03WGJ0104T5E 100k x4") if pull == "GND" else
                          ("10k x4", "C29718", "UNI-ROYAL 4D03WGJ0103T5E 10k x4"))
        part(f"RN{rn0 + j}", RARRAY, val, b.at(dx, dy), r, pins, "smt", lcsc, mpn, side="B")
res("R371", "10k", (16.0, -21.0), "EXP_RESET_N", "GND", 0, side="B")
res("R372", "10k", (16.0, -22.7), "EXP_INT_N", "+3V3_PI", 0, side="B")
res("R373", "10k", (16.0, -24.4), "PWR_ALERT_N", "+3V3_PI", 0, side="B")

# ---------------------------------------------------------------- ToF: TCA9548A 0x77 (tca9548a.json, A2..A0 = VCC,
# RESET = GPIO23 with 10k pull-up) and TCA6416A 0x20 (tca6416a.json, P0 = LPn outputs, P1 = INT inputs, RESET =
# EXP_RESET_N); per port (JST GH-6, 1 GND, 2 TOFn_3V3, 3 SDA, 4 SCL, 5 INT, 6 LPn): 4.7k SDA/SCL and 10k INT pull-ups to
# the port's switched 3.3 V, 1k in LPn, TPD4E05U06 on the four lines.
part("U40", "Package_DFN_QFN:Texas_RGE0024C_VQFN-24-1EP_4x4mm_P0.5mm_EP2.1x2.1mm", "TCA9548A", (16.0, 46.0), 0,
     {"1": "TOF1_SDA", "2": "TOF1_SCL", "3": "TOF2_SDA", "4": "TOF2_SCL", "5": "TOF3_SDA", "6": "TOF3_SCL",
      "7": "TOF4_SDA", "8": "TOF4_SCL", "9": "GND", "10": "TOF5_SDA", "11": "TOF5_SCL", "12": "TOF6_SDA",
      "13": "TOF6_SCL", "14": "MUX_SD6", "15": "MUX_SC6", "16": "MUX_SD7", "17": "MUX_SC7", "18": "+3V3_PI",
      "19": "I2C6_SCL", "20": "I2C6_SDA", "21": "+3V3_PI", "22": "+3V3_PI", "23": "+3V3_PI", "24": "TOF_MUX_RESET_N",
      "25": "GND"}, "smt", "C555456", "TI TCA9548ARGER", "TOF MUX 0x77", side="B")
cap("C892", "100nF", (16.0, 50.0), "+3V3_PI", "GND", 0, side="B")
res("R891", "10k", (20.2, 42.6), "TOF_MUX_RESET_N", "+3V3_PI", 0, side="B")
# the mux is alone on the Pi's I2C6 (dtoverlay=i2c6,pins_22_23, 400 kHz): ToF firmware loads and frames never load
# I2C1 (power control); the Pi has no pull-ups on GPIO22/23
res("R892", "2.2k", (12.0, 44.0), "I2C6_SDA", "+3V3_PI", 90, side="B")
res("R893", "2.2k", (10.35, 44.0), "I2C6_SCL", "+3V3_PI", 90, side="B")
part("U41", "Package_DFN_QFN:WQFN-24-1EP_4x4mm_P0.5mm_EP2.45x2.45mm", "TCA6416A", (25.0, 46.0), 0,
     {**{str(i + 1): f"TOF{i + 1}_LPN_X" for i in range(N_TOF)}, "9": "GND",
      **{str(10 + i): f"TOF{i + 1}_INT" for i in range(N_TOF)}, "7": "TOFX_P06", "8": "TOFX_P07", "16": "TOFX_P16",
      "17": "TOFX_P17", "18": "GND", "19": "I2C1_SCL", "20": "I2C1_SDA",
      "21": "+3V3_PI", "22": "EXP_IN_SPARE1", "23": "+3V3_PI", "24": "EXP_RESET_N", "25": "GND"}, "smt", "C182336",
     "TI TCA6416ARTWR", "TOF IO 0x20", side="B")
# U41 INT has no mask (TCA6416A p.19/21) and every ToF frame toggles it: it goes to U38 P0_6 (maskable, RN8 pull-up),
# not onto the Pi's EXP_INT_N power-fault line (round4-firmware.md R-1)
# channels 7/8 and their expander lines are spare (6 ToF ports): idle-high pull-ups on the mux channels so enabling one
# by mistake leaves a valid idle bus, pull-downs on the expander inputs so they never float
part("RN40", RARRAY, "10k x4", (16.0, 40.6), 0, {"1": "MUX_SD6", "8": "+3V3_PI", "2": "MUX_SC6", "7": "+3V3_PI",
                                                 "3": "MUX_SD7", "6": "+3V3_PI", "4": "MUX_SC7", "5": "+3V3_PI"},
     "smt", "C29718", "UNI-ROYAL 4D03WGJ0103T5E 10k x4", side="B")
part("RN41", RARRAY, "100k x4", (25.0, 40.6), 0, {"1": "TOFX_P06", "8": "GND", "2": "TOFX_P07", "7": "GND",
                                                  "3": "TOFX_P16", "6": "GND", "4": "TOFX_P17", "5": "GND"},
     "smt", "C1996", "UNI-ROYAL 4D03WGJ0104T5E 100k x4", side="B")
cap("C890", "100nF", (23.4, 50.0), "+3V3_PI", "GND", 0, side="B")
cap("C891", "100nF", (26.6, 50.0), "+3V3_PI", "GND", 0, side="B")

# ToF ports, one per sensor bracket (gen/tof.json, poses checked for field of view in cad/robot/tof_fov.py; bracket
# cad/robot/parts/tof_mount.py): two M2.5 holes set the bracket's heading (the bracket footprint is placed at the edge
# point; the vertical GH-6 ports (mating downward) sit where the bottom has room, `port` in tof.json, 100 mm cables.
# The bracket footprint carries the holes and the keep-outs: the flange under the board, the screw heads on top.
TOF = json.loads((Path(__file__).resolve().parent / "tof.json").read_text())["sensors"]
for i, sen in enumerate(TOF):
    n = i + 1
    a = math.radians(sen["yaw"])
    nx, ny = math.sin(a), math.cos(a)
    ux, uy = math.cos(a), -math.sin(a)

    def pp(du, dv):
        return (sen["X"] + ux * du + nx * dv, sen["Y"] + uy * du + ny * dv)
    rot = round(-sen["yaw"]) % 360
    part(f"H{20 + i}", "rabbit_body:ToF_Bracket_M2.5", f"ToF {n} bracket", pp(0.0, 0.0), rot, bom="none")
    px, py = sen["port"]
    inward = 1.0 if py < 0 else -1.0
    part(f"J6{i}", GH6, f"ToF {n}", (px, py), 0 if inward < 0 else 180,
         {"1": "GND", "2": "+3V3_TOF", "3": f"TOF{n}_SDA", "4": f"TOF{n}_SCL", "5": f"TOF{n}_INT",
          "6": f"TOF{n}_LPN", "MP": "GND"}, "smt", "C3011957",
         "HCTL HC-GH-6PLT (GH-compatible vertical, JST BM06B land; JLC stock, genuine JST is not)", f"TOF{n} {sen['name']}",
         side="B")
    esd4(f"D6{i}", (px, py + inward * 5.5), (f"TOF{n}_SDA", f"TOF{n}_SCL", f"TOF{n}_INT", f"TOF{n}_LPN"), 0,
         side="B")
    for j, (dx, val, net_a, net_b) in enumerate(((-3.9, "4.7k", f"TOF{n}_SDA", "+3V3_TOF"),
                                                 (-1.3, "4.7k", f"TOF{n}_SCL", "+3V3_TOF"),
                                                 (1.3, "10k", f"TOF{n}_INT", "+3V3_TOF"),
                                                 (3.9, "1k", f"TOF{n}_LPN_X", f"TOF{n}_LPN"))):
        res(f"R9{i}{j}", val, (px + dx, py + inward * 9.0), net_a, net_b, 90, side="B")

# ---------------------------------------------------------------- lidar ports x3 (connectors.json J_LIDAR, top front):
# JST XH-5 THT, the RPLIDAR C1 cable plugs straight in (Slamtec C1 DS p.11-12: XH2.54-5P, VCC red, TX yellow, RX green,
# GND black, 5th position empty): 1 LIDARn_5V (TPS259470L 2.0 A, C1 start-up 0.8 A typ.), 2 LIDARn_TX (lidar out -> Pi RX), 3 LIDARn_RX
# (Pi TX ->, C1 input max 3.5 V), 4 GND, 5 NC. Pi UART3 (GPIO4/5), UART4 (GPIO8/9), UART5 (GPIO12/13), 100 R
# series + TPD4E05U06. +5V -> the three eFuses (bottom, under the ports).
LIDAR_UART = (("GPIO4", "GPIO5"), ("GPIO8", "GPIO9"), ("GPIO12", "GPIO13"))
for i in range(3):
    n = i + 1
    x0, y0 = -47.0 + 16.5 * i, 91.0
    part(f"J7{n}", XH5, f"lidar {n}", (x0, y0), 0,
         {"1": f"LIDAR{n}_5V", "2": f"LIDAR{n}_TX", "3": f"LIDAR{n}_RX", "4": "GND"}, "tht", "C157991",
         "JST B5B-XH-A(LF)(SN)", f"LIDAR{n}")
    tx, rx = LIDAR_UART[i]
    res(f"R10{n}1", "1k", (x0 + 1.0, y0 - 6.3), tx, f"LIDAR{n}_RX", 90, side="B")
    res(f"R10{n}2", "1k", (x0 + 2.65, y0 - 6.3), f"LIDAR{n}_TX", rx, 90, side="B")
    esd4(f"D7{n}", (x0 + 7.0, y0 - 6.3), (f"LIDAR{n}_TX", f"LIDAR{n}_RX", None, None), 0, side="B")

# ---------------------------------------------------------------- Jetson power (bottom, under the MCU/LM5069 area):
# TPS16630 3.53 A (5.1k), auto-retry (MODE = GND) -> XT30 at the left edge (owner's pigtail to a 5.5 x 2.5 barrel);
# its own IMON pin gives the current (no INA238). FLT -> 0x23 P2_4, IMON -> ADS7128 0x17 AIN1. Spare battery-level
# output: TPS16630 3.83 A (4.7k), latch-off (MODE open), EN from 0x22 P2_3 -> XT30.
# XT30UPB-F vertical on the bottom (plug mates from below; pad 1 = GND at the chamfered end, '-' on the footprint silk,
# pad 2 = output), THT tails on the top.
for (u, y, out_ef, out, shdn, imsrc, imon, flt, rilim, mode_gnd, base, jet, sh, ina, a1, a0, lbl, d, j, jl) in (
        ("U5", -41.0, "JET_EF", "JET_PWR", "JET_SHDN", "JET_IMON_SRC", "JET_IMON", "JET_FLT", "5.1k", True, 80, True,
         "R4", "U24", "+3V3_PI", "GND", "INA JET 0x44", "D14", "J21", "JETSON 9-17V 3.5A"),
        ("U7", -64.0, "SPARE_EF", "SPARE_VBAT", "SPAREBAT_EN", "SPARE_IMON_SRC", "SPAREBAT_IMON", "SPAREBAT_FLT",
         "4.7k", False, 180, False, "R5", "U25", "+3V3_PI", "+3V3_PI", "INA SPARE 0x45", "D15", "J20",
         "VBAT OUT 4A")):
    tps16630(u, (-26.0, y), "B", "VBUS", out, shdn, imsrc, imon, flt, rilim, mode_gnd, base, jet)
    tvs(d, (-37.5, y - 11.0), out, rot=0, side="B")
    part(j, XT30, "XT30 " + ("JETSON" if jet else "SPARE VBAT"), (-53.5, -35.0 if jet else -48.0), 90, {"1": "GND", "2": out}, "tht",
         "C108769", "AMASS XT30UPB-F vertical", jl, side="B")
res("R38", "4.7k", (-17.0, -52.0), "JET_PWR", "LED12_A", 0, side="B")
led("D4", (-13.6, -52.0), "LED12_A", 0, side="B")

# ---------------------------------------------------------------- Pi header (40-pin IDC, ribbon to the Pi), pi_pinmap.md
PI_PINS = {1: "+3V3_PI", 3: "I2C1_SDA", 5: "I2C1_SCL", 6: "GND", 7: "GPIO4", 8: "GPIO14",
           9: "GND", 10: "GPIO15", 11: "GPIO17", 12: "BUZZER_PWM", 13: "GPIO27", 14: "GND", 15: "I2C6_SDA",
           16: "I2C6_SCL", 17: "+3V3_PI", 18: "PWR_ALERT_N", 19: "LED_DI", 20: "GND", 21: "GPIO9",
           22: "GPIO25", 23: "LED_CI", 24: "GPIO8", 25: "GND", 26: "EXP_INT_N", 27: "GPIO0", 28: "GPIO1",
           29: "GPIO5", 30: "GND", 31: "EXP_RESET_N", 32: "GPIO12", 33: "GPIO13", 34: "GND", 35: "TOF_MUX_RESET_N",
           36: "GPIO16", 37: "POWER_BTN", 38: "BUMPER_FRONT", 39: "GND", 40: "BUMPER_REAR"}
part("J3", "Connector_IDC:IDC-Header_2x20_P2.54mm_Vertical", "Pi 40-pin", (-21.13, 30.2), 90,
     {str(k): v for k, v in PI_PINS.items()}, "tht", "C7433390", "Wurth 61204021621 2x20 box header",
     "RASPBERRY PI 40-PIN (ribbon)")
tp("TP6", "I2C6_SDA", (36.0, 31.0), "SDA6")
tp("TP7", "I2C6_SCL", (39.0, 31.0), "SCL6")
tp("TP8", "EXP_INT_N", (36.0, 27.5), "INT")
tp("TP9", "PWR_ALERT_N", (39.0, 27.5), "ALERT")

# ---------------------------------------------------------------- PCA9685 0x60 (pca9685.json: A5 = VDD, A4-A0 = GND;
# 0x70 All Call stays reserved) + 8 servo headers (Wurth 1x3, 1 PWM, 2 SERVO_PWR, 3 GND); ch 8-10 spare (the C1
# lidar has no motor line), 11-12 fan PWM (through 2N7002K: fans pull PWM up to 5 V internally), 13-15 spare. S0 can take the MCU's TIM17 PWM
# (cut JP3 1-2, bridge 2-3).
pca = {str(i): "GND" for i in (1, 2, 3, 4, 5, 14, 23, 25)}
pca.update({"24": "+3V3_PI", "26": "I2C1_SCL", "27": "I2C1_SDA", "28": "+3V3_PI",
            **{str(6 + i): f"PCA_SERVO{i}" for i in range(8)}, "18": "PCA_FAN1_PWM", "19": "PCA_FAN2_PWM"})
part("U8", "Package_SO:TSSOP-28_4.4x9.7mm_P0.65mm", "PCA9685PW", (8.0, 105.0), 90, pca, "smt", "C2678753",
     "NXP PCA9685PW,118 (alt. PCA9685PW/Q900 C92206)", "PWM 0x60")
cap("C3", "100nF", (8.0, 99.6), "+3V3_PI", "GND", 0)
cap("C4", "10uF", (12.0, 99.6), "+3V3_PI", "GND", 0, C0805)
SERVO_X = [-14.0 + 4.0 * i for i in range(8)]
for i, sx in enumerate(SERVO_X):
    sig = f"SERVO{i}_PCA" if i == 0 else f"SERVO{i}_PWM"
    res(f"R300{i}", "220", (sx, 110.6), f"PCA_SERVO{i}", sig, 90)
    part(f"J2{2 + i}", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", f"servo {i}", (sx, 120.5), 0,
         {"1": f"SERVO{i}_PWM", "2": "SERVO_PWR", "3": "GND"}, "tht", "C2915006", "Wurth 61300311121 1x3 header",
         "SERVO S0-S7  S + -" if i == 0 else None)
part("JP3", JP3, "S0 source", (-18.0, 113.0), 90, {"1": "SERVO0_PCA", "2": "SERVO0_PWM", "3": "SERVO0_MCU"}, "none")
res("R89", "220", (-20.6, 113.0), "SERVO_MCU", "SERVO0_MCU", 90)

# ---------------------------------------------------------------- RTC (ds3231.json): DS3231SN 0x68, INT/SQW -> 0x23 P2_7
# (10k in the pull-up array), 32kHz option to the IMU, CR1220 retainer
rtc = {str(i): "GND" for i in range(5, 14)}
rtc.update({"1": "RTC_32K", "2": "+3V3_PI", "3": "RTC_INT_N", "14": "RTC_VBAT", "15": "I2C1_SDA", "16": "I2C1_SCL"})
part("U9", "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm", "DS3231SN", (-12.0, 77.0), 0, rtc, "smt", "C9866",
     "Analog Devices DS3231SN#T&R", "RTC")
cap("C5", "100nF", (-12.0, 69.6), "+3V3_PI", "GND", 0)
part("BT1", "Battery:BatteryHolder_Keystone_3000_1x12mm", "CR1220", (-34.0, 77.5), 0,
     {"1": "RTC_VBAT", "2": "GND"}, "smt", "C238097", "Keystone 3000 SMT retainer (CR1220 cell not included)")

# ---------------------------------------------------------------- bumpers, power button (rev B)
part("J13", XH2, "bumpers front", (-27.0, 118.0), 0, {"1": "BUMPER_FRONT", "2": "GND"}, "tht", "C158012",
     "JST B2B-XH-A(LF)(SN)", "BUMP F")
part("J14", XH2, "bumpers rear", (-1.25, -121.0), 0, {"1": "BUMPER_REAR", "2": "GND"}, "tht", "C158012",
     "JST B2B-XH-A(LF)(SN)", "BUMP R")
res("R29", "4.7k", (-27.0, 113.4), "BUMPER_FRONT", "+3V3_PI", 0, side="B")
cap("C11", "100nF", (-27.0, 111.7), "BUMPER_FRONT", "GND", 0, side="B")
res("R30", "4.7k", (-8.6, -126.0), "BUMPER_REAR", "+3V3_PI", 90)
cap("C12", "100nF", (-6.8, -126.0), "BUMPER_REAR", "GND", 90)
part("J15", XH5, "button", (35.0, 90.0), 0,
     {"1": "BTN_ON", "2": "GND", "3": "POWER_BTN", "4": "+5V", "5": "BTN_LED_K"}, "tht", "C157991",
     "JST B5B-XH-A(LF)(SN)", "BUTTON")
res("R28", "10k", (32.0, 96.0), "POWER_BTN", "+3V3_PI", 0)
cap("C10", "100nF", (35.4, 96.0), "POWER_BTN", "GND", 0)
nfet("Q3", (40.0, 96.5), "Q3_G", "BTN_LED_K", 0)
res("R24", "1k", (44.0, 96.0), "GPIO27", "Q3_G", 0)
res("R25", "100k", (44.0, 97.7), "Q3_G", "GND", 0)

# ---------------------------------------------------------------- fans x2 (connectors.json J_FAN, Molex KK 254 4-pin):
# 1 GND, 2 FANn_5V (eFuse 0.5 A), 3 FANn_TACH (10k pull-up + 1k at the MCU), 4 FANn_PWM (2N7002K open drain from
# PCA9685 ch 11/12: PWM is inverted in firmware). Fan 1 next to the Pi, fan 2 next to the motor drivers.
for i, (fx, fy, rot) in enumerate(((-46.0, 18.0, 0), (-50.0, -82.0, 0))):
    n = i + 1
    part(f"J5{5 + i}", KK4, f"fan {n}", (fx, fy), rot,
         {"1": "GND", "2": f"FAN{n}_5V", "3": f"FAN{n}_TACH", "4": f"FAN{n}_PWM"}, "tht", "C240840",
         "Molex 47053-1000 KK 254 fan header", f"FAN{n}")
    nfet(f"Q5{5 + i}", (fx + 3.0, fy - 6.0), f"PCA_FAN{n}_PWM", f"FAN{n}_PWM", 0, kind="2N7002K")
    res(f"R5{5 + i}0", "100k", (fx + 6.8, fy - 6.0), f"PCA_FAN{n}_PWM", "GND", 90)

# ---------------------------------------------------------------- spare 5 V out (XH-2, eFuse 2 A) and the Pi USB-C power
# output (Q47 option, connectors.json J_PI_USBC): USB4115 power-only, the board is the source: 10k Rp on CC1/CC2 to the
# eFuse output (default USB power, no Rp while off)
part("J58", XH2, "spare 5V", (-54.0, -18.0), 0, {"1": "+5V_AUX", "2": "GND"}, "tht", "C158012",
     "JST B2B-XH-A(LF)(SN)", "5V OUT 2A")
part("J53", USBC_V, "USB-C Pi power", (-53.0, -3.0), 90,
     {"A4": "+5V_PI_USBC", "B4": "+5V_PI_USBC", "A9": "+5V_PI_USBC", "B9": "+5V_PI_USBC", "A5": "PIUSB_CC1",
      "B5": "PIUSB_CC2", "A1": "GND", "B1": "GND", "A12": "GND", "B12": "GND", "SH": "GND"}, "smt", "C5250720",
     "GCT USB4115-03-C vertical (power only: data pins open)", "PI 5V USB-C")
res("R531", "10k", (-49.0, -0.6), "PIUSB_CC1", "+5V_PI_USBC", 90)   # Rp 10k to 5 V advertises 3.0 A (USB-C spec)
res("R532", "10k", (-49.0, -5.4), "PIUSB_CC2", "+5V_PI_USBC", 90)

LED_DY = ZED_FRONT - 134.9689   # the row follows the front edge (the nose grew for the ZED)
# ---------------------------------------------------------------- status LEDs: SK9822-EC20 x8 (sk9822.json) from Pi SPI0
# (GPIO10 MOSI, GPIO11 SCLK) through SN74AHCT1G125 (VIH 2.0 V at 5 V, p.4; SK9822 needs VIH >= 3.4 V) + 100 R, 100k
# input pull-downs (dark while the Pi boots); 100 nF per LED; a row along the front edge (visible with deck 3 in place)
for i, (net, a, x) in enumerate((("LED_DI", "LED_DI_5V", -6.0), ("LED_CI", "LED_CI_5V", 6.0))):
    part(f"U4{8 + i}", SOT23_5, "74AHCT1G125", (x, 125.6 + LED_DY), 0,
         {"1": "GND", "2": net, "3": "GND", "4": a, "5": "+5V"}, "smt", "C7484", "TI SN74AHCT1G125DBVR")
    cap(f"C48{i}", "100nF", (x + (1.4 if x < 0 else -1.4), 128.4 + LED_DY), "+5V", "GND", 0)
    res(f"R48{i}", "100k", (x - 4.5 if i == 0 else x - 4.2, 125.6 + LED_DY), net, "GND", 90)
    res(f"R48{2 + i}", "100", (x + 4.2 if i == 0 else x + 4.5, 125.6 + LED_DY), a, f"LED1_{'DI' if i == 0 else 'CI'}", 90)
cap("C489", "10uF", (0.0, 129.0 + LED_DY), "+5V", "GND", 0, C0805)
# LED x and its 100 nF (x, y, rot): the row leaves room for the ToF bracket screws (H20-H22)
LED_ROW = ((-28.5, (-28.5, 125.1, 0)), (-18.0, (-20.2, 131.5, 90)), (-13.7, (-15.9, 131.5, 90)),
           (-3.3, (-1.1, 131.5, 90)), (3.3, (1.1, 131.5, 90)), (13.7, (15.9, 131.5, 90)), (18.0, (20.2, 131.5, 90)),
           (28.5, (28.5, 125.1, 0)))
for i, (lx, (cx, cy, cr)) in enumerate(LED_ROW):
    cy += LED_DY
    n = i + 1
    dout = f"LED{n + 1}_DI" if n < 8 else "LED_DOUT"
    cout = f"LED{n + 1}_CI" if n < 8 else "LED_COUT"
    part(f"LED{n}", "rabbit_body:LED_SK9822-EC20_2x2mm", "SK9822-EC20", (lx, (127.5 if abs(lx) > 25 else 131.5) + LED_DY), 0,
         {"1": dout, "2": "GND", "3": f"LED{n}_DI", "4": f"LED{n}_CI", "5": "+5V", "6": cout}, "smt", "C2909059",
         "Opsco SK9822-EC20")
    cap(f"C49{i}", "100nF", (cx, cy), "+5V", "GND", cr)
tp("TP10", "LED_DOUT", (-19.5, 123.5 + LED_DY), "DO")
tp("TP11", "LED_COUT", (-19.5, 126.5 + LED_DY), "CO")

# ---------------------------------------------------------------- buzzer (pklcs1212.json): PKLCS1212E4001 from GPIO18
# (PWM0) through AO3400A, 100 R gate, 100k pull-down, 1k across the piezo
part("LS1", "Buzzer_Beeper:Buzzer_Murata_PKLCS1212E", "PKLCS1212E", (41.0, 78.0), 0, {"1": "+5V", "2": "BUZ_D"},
     "smt", "C113159", "Murata PKLCS1212E4001-R1 4 kHz")
nfet("Q9", (41.0, 69.6), "BUZ_G", "BUZ_D", 0)
res("R190", "100", (34.3, 67.6), "BUZZER_PWM", "BUZ_G", 0)
res("R191", "100k", (37.4, 67.6), "BUZ_G", "GND", 0)
res("R192", "1k", (34.3, 69.3), "+5V", "BUZ_D", 0)

# ---------------------------------------------------------------- remaining test points (every rail)
for i, (net, at, lbl) in enumerate([("VBUS", (42.5, -36.5), "VBUS"), ("+5V", (-19.9, 40.0), "5V"),
                                    ("SERVO_PWR", (16.5, 97.5), "SRV"), ("SERVO_RAW", (40.5, 61.0), "SRVR"),
                                    ("+3V3_TOF", (-2.0, 40.0), "3V3T"), ("GND", (-1.0, -37.0), "GND"),
                                    ("GND", (19.5, 84.0), "GND"), ("MOT_BUS", (-36.5, -91.0), "VMOT"),
                                    ("GND_MOT", (-12.0, -122.0), "GNDM"), ("BAT_F", (37.0, -92.0), "BAT"),
                                    ("+3V3_PI", (-34.5, 33.5), "3V3P"),
                                    ("ADC_AVDD", (42.0, 27.5), "REF"),
                                    ("+5V_AUX", (-46.0, -26.0), "5VA"), ("JET_PWR", (-36.0, -30.0), "JET"),
                                    ("SPARE_VBAT", (-36.0, -80.0), "VBA"), ("MOT_F", (42.5, -40.5), "MOTF")]):
    tp(f"TP{20 + i}", net, at, lbl)


# label placement tweaks: ref -> (dx, dy, "top" | "bottom" | "right")
LABEL_POS = {"J22": (12.0, 0.0, "top"), "F1": (0.0, 0.0, "right"), "J15": (0.0, 0.0, "top"),
             "J14": (0.0, 0.0, "top"), "J20": (0.0, 0.0, "right"), "J21": (0.0, 0.0, "right"),
             "J53": (0.0, 0.0, "right"), "J58": (3.0, 0.0, "top"), "J63": (0.0, 0.0, "right"),
             "J64": (0.0, 0.0, "right"), "J65": (-3.0, 0.0, "top"), "J66": (-3.0, 0.0, "top"),
             "J60": (0.0, 0.0, "bottom"), "J61": (0.0, 0.0, "bottom"), "J62": (0.0, 0.0, "bottom"),
             "U23": (0.0, 0.0, "bottom"), "U28": (0.0, 0.0, "bottom")}

# extra silkscreen text: (text, X, Y, size, layer "F"/"B")
SILK = [(f"RABBIT 2.0 BODY  rev {REV}  2026-10", 2.0, -110.0, 1.6, "B"),
        ("8L 2.0 mm, 2 oz outer, ENIG; deck 2 of the Red Ackerman kit", 2.0, -113.5, 1.0, "B"),
        (f"FRONT ^  rev {REV}", -33.0, 113.5, 1.2, "F"),
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
POWER_HI = ["VBUS", "MOT_SNS_D", "GND_MOT", "BRK_D", "DG", "HG"]
# outer layers only (2 oz outer copper, IPC-2221 external, 20 K rise): 3.0 mm ~ 13 A, 2.0 mm ~ 9 A
POWER_15A = ["BAT_IN", "BAT_F", "SW_MID", "VBUS_RAW"]
POWER_10A = ["SERVO_BUCK", "SERVO_RAW", "SERVO_PWR", "STEER_IN", "SW6", "SW4", "+5V_BUCK", "MOT_F",
             "MOT_BUS", "ML_OUT1", "ML_OUT2", "MR_OUT1", "MR_OUT2"]
# the arm rail: 4.45 A limit, 5.7 A worst case; 1.2 mm on 2 oz outer ~ 6 A at 20 K
POWER_5A = ["ARM_PWR"]
POWER_5V = ["+5V", "JET_PWR", "SPARE_VBAT", "BODY_IN", "+5V_PI_USBC"]
POWER_MID = ["+3V3_TOF", "SW_TOF", "+5V_AUX", "+5V_MCU", "USB_VBUS"]
POWER_LO = ["+3V3_PI", "+3V3_MCU", "+3V3_MCU_A", "BRK_VCC", "ADC_AVDD"] + \
    [f"LIDAR{i}_5V" for i in range(1, 4)] + \
    ["ENC_3V3", "FAN1_5V", "FAN2_5V"]


# Floorplan for the enlarged board (2026-10-11, Fable's plan, data/pcb-revc/review/floorplan-2026-10-11.md): positions,
# rotations and sides in gen/placement.json override the defaults above (halved the unrouted count, 56 -> 27-29).
for _ref, _v in json.loads((Path(__file__).resolve().parent / "placement.json").read_text()).items():
    _p = next((p for p in PARTS if p["ref"] == _ref), None)
    if _p is None:   # a part removed after the floorplan
        continue
    if "at" in _v:
        _p["at"] = (round(_v["at"][0], 3), round(_v["at"][1], 3))
    if "rot" in _v:
        _p["rot"] = _v["rot"] % 360
    if "side" in _v:
        _p["side"] = _v["side"]
