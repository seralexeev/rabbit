"""Net-by-net electrical audit of the body board rev C (pcb/rabbit-body-c/gen/design.py is the netlist).

Method (independent of gen/check_netlist.py):
1. every power net gets a voltage and a power domain (RAILS); a DC solver (exact nodal analysis per connected component, with
   piecewise-linear diodes and switch-model N-FETs) computes every other net from its resistors, drivers and
   diodes, in several power scenarios (all on, Pi off, USB only, each switched load off, servo buck failed high);
2. every IC and external-device pin has a kind and an abs-max expression (PINS, EXT); the script flags
   abs-max violations, back-powering of unpowered pins, floating inputs, open-drain nets without a pull-up,
   push-pull outputs that fight, single-pin nets, capacitor voltage ratings below 1.5 x, polarized parts against
   the net voltages, resistor power above rating (solved and "pin shorted to GND" worst case), FET/BJT stress;
3. every numeric claim of the design.py comments is recomputed from the part values (CLAIMS) and the claims
   left unchecked are listed.

Run: python3 workspaces/bench/pcb-audit/audit.py [--md out.md]. Needs only the standard library.
Datasheet facts carry their page in the tables below; [mem] = not re-read from the PDF in this audit.
"""
import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GEN = ROOT / "pcb/rabbit-body-c/gen"
sys.dont_write_bytecode = True
sys.path.insert(0, str(GEN))
import design  # noqa: E402

PARTS = {p["ref"]: p for p in design.PARTS}
LIVE = {r: p for r, p in PARTS.items() if p["bom"] not in ("dnp",)}
NETS = defaultdict(list)
for p in design.PARTS:
    for pad, net in p["pins"].items():
        NETS[net].append((p["ref"], pad))

# ------------------------------------------------------------------------------------------- LCSC descriptions
DESC = {}
for f in (GEN.parent / "fab/stock.json", ROOT / "data/pcb-revc/review/audit-lcsc-extra.json"):
    if f.exists():
        d = json.loads(f.read_text())
        for k, v in (d.get("parts", d)).items():
            if v:
                DESC[k] = f'{v.get("model", "")} {v.get("describe", "")}'


def desc(ref):
    p = PARTS[ref]
    return DESC.get(p["lcsc"] or "", "") + " " + (p["mpn"] or "") + " " + p["value"]


def num(s):
    m = re.match(r"^\s*([\d.]+)\s*([pnumkMR]?)", s)
    if not m:
        return None
    v = float(m.group(1))
    return v * {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "R": 1, "": 1}[m.group(2)]


def rval(ref):
    v = PARTS[ref]["value"]
    if "mR" in v:
        return float(v.split("mR")[0]) * 1e-3
    if v.startswith("NTC"):
        return 10e3
    if v.endswith(" x4"):
        v = v[:-3]
    return num(v.replace("R", "")) if not v.endswith("k") and "R" in v else num(v)


def rated_power(ref):
    m = re.findall(r"([\d.]+)\s*(m?W)\b", desc(ref))
    if not m:
        return None
    v, u = m[0]
    return float(v) * (1e-3 if u == "mW" else 1)


def rated_volt(ref):
    d = desc(ref)
    m = re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*V\b(?!\w)", d)
    return float(m[0]) if m else None


# ------------------------------------------------------------------------------------------- rails and domains
# net: (V max in normal operation, domain). Battery 4S Li-ion 16.8 V full; +5V 5.17 V + 1 % FB + 1.6 % divider.
RAILS = {
    "GND": (0, "ALWAYS"), "GND_MOT": (0, "ALWAYS"),
    "BAT_IN": (16.8, "BAT"), "BAT_F": (16.8, "BAT"),
    "SW_MID": (16.8, "VBUS"), "VBUS_RAW": (16.8, "VBUS"), "VBUS": (16.8, "VBUS"), "SH1_P": (16.8, "VBUS"),
    "SH1_N": (16.8, "VBUS"), "MOT_F": (16.8, "VBUS"), "MOT_SNS_P": (16.8, "VBUS"), "MOT_SNS_N": (16.8, "VBUS"),
    "MOT_SNS_D": (16.8, "VBUS"), "BODY_IN": (16.8, "VBUS"), "STEER_IN": (16.8, "VBUS"),
    "MOT_BUS": (17.7, "MOT"),
    "JET_EF": (16.8, "JET"), "JET_PWR": (16.8, "JET"), "SH4_P": (16.8, "JET"), "SH4_N": (16.8, "JET"),
    "SPARE_EF": (16.8, "SPARE"), "SPARE_VBAT": (16.8, "SPARE"), "SH5_P": (16.8, "SPARE"), "SH5_N": (16.8, "SPARE"),
    "+5V_BUCK": (5.3, "5V"), "+5V": (5.3, "5V"), "SH6_P": (5.3, "5V"), "SH6_N": (5.3, "5V"), "+5V17": (5.3, "5V"),
    "SH7_P": (5.3, "5V"), "SH7_N": (5.3, "5V"), "+5V_LIDAR": (5.3, "5V"),
    "+5V_PI_USBC": (5.3, "PIUSB"), "+3V3_PI": (3.4, "PI"),
    "+5V_AUX": (5.3, "AUX"), "FAN1_5V": (5.3, "FAN1"), "FAN2_5V": (5.3, "FAN2"),
    "LIDAR1_5V": (5.3, "LIDAR1"), "LIDAR2_5V": (5.3, "LIDAR2"), "LIDAR3_5V": (5.3, "LIDAR3"),
    "SERVO_BUCK": (7.45, "SBUCK"), "SERVO_RAW": (7.45, "SBUCK"), "SH3_P": (7.45, "SBUCK"), "SH3_N": (7.45, "SBUCK"),
    "SERVO_PWR": (7.45, "SERVO"), "ARM_PWR": (7.45, "ARM"), "ARM_5V": (5.05, "ARM"),
    "USB_VBUS": (5.25, "USB"), "+5V_MCU": (5.3, "MCU"), "+3V3_MCU": (3.35, "MCU"), "+3V3_MCU_A": (3.35, "MCU"),
    "+3V3_IMU": (3.35, "MCU"),
    "+3V3_TOF_BUCK": (3.35, "TOF"), "+3V3_TOF": (3.35, "TOF"),
    **{f"TOF{i}_3V3": (3.35, f"TOF{i}") for i in range(1, 7)},
    "ENC_L_3V3": (3.35, "ENCL"), "ENC_R_3V3": (3.35, "ENCR"),
    "ADC_AVDD": (2.5, "5V"), "RTC_VBAT": (3.0, "ALWAYS"), "BRK_VCC": (17.6, "MOT"),
}
# a domain is on only if all the domains it needs are on (EN lines come from the Pi's expander: Pi off -> load off)
NEEDS = {"BAT": [], "ALWAYS": [], "VBUS": ["BAT"], "MOT": ["VBUS"], "JET": ["VBUS"], "SPARE": ["VBUS", "PI"],
         "5V": ["VBUS"], "PIUSB": ["5V"], "PI": ["PIUSB"], "AUX": ["5V", "PI"], "FAN1": ["5V", "PI"],
         "FAN2": ["5V", "PI"], "LIDAR1": ["5V", "PI"], "LIDAR2": ["5V", "PI"], "LIDAR3": ["5V", "PI"],
         "SBUCK": ["VBUS", "PI"], "SERVO": ["SBUCK", "PI"], "ARM": ["SBUCK", "PI"], "USB": [], "MCU": [],
         "TOF": ["5V", "PI"], **{f"TOF{i}": ["TOF", "PI"] for i in range(1, 7)}, "ENCL": ["TOF", "PI"],
         "ENCR": ["TOF", "PI"]}

SCENARIOS = {   # name: (domains forced off, rail overrides, note)
    "all_on": ([], {}, "every rail at its maximum, every output high"),
    "pi_off": (["PI"], {}, "Pi shut down or U87 tripped while the battery latch holds +5V (MCU, MOT_BUS_OFF high)"),
    "usb_only": (["BAT"], {}, "battery out, laptop on the MCU USB-C: only +5V_MCU/+3V3_MCU"),
    "arm_off": (["ARM"], {}, "arm eFuse off, MCU still talking"),
    "servo_off": (["SBUCK"], {}, "servo buck off"),
    "tof_off": (["TOF"], {}, "ToF 3.3 V buck off"),
    "tof1_off": (["TOF1"], {}, "one ToF port off"),
    "encl_off": (["ENCL"], {}, "encoder L eFuse off"),
    "lidar1_off": (["LIDAR1"], {}, "lidar 1 eFuse off"),
    "fan1_off": (["FAN1"], {}, "fan 1 eFuse off"),
    "mot_off": (["MOT"], {}, "motor bus off"),
    "aux_off": (["AUX"], {}, "+5V_AUX off"),
    "servo_fail": ([], {"SERVO_BUCK": 16.8, "SERVO_RAW": 16.8, "SH3_P": 16.8, "SH3_N": 16.8, "SERVO_PWR": 0,
                        "ARM_PWR": 16.8},
                   "servo buck HS FET short: SERVO_RAW = VBUS; U83 OVLO opens SERVO_PWR; ARM_PWR shown at 16.8 V for "
                   "the ~0.25 ms until U90 + U88 turn-off (worst instant)"),
    "arm_charged_servo_off": (["SBUCK"], {"ARM_PWR": 7.45, "ARM_5V": 5.05},
                              "arm switched off first (C887 still charged), then the servo buck off"),
    "arm_sig_contention": ([], {"__ext_ARM_SIG": 7.45},
                           "MCU transmits a low (PB9 open drain on) while SIG is high: a servo driving the bus, or "
                           "SIG shorted to ARM_PWR (adjacent PH pins, mis-wired cable)"),
}
# scenario-specific drivers: net -> volts (overrides DRIVE_LOW / default high)
SCEN_DRIVE = {"arm_sig_contention": {"ARM_UART_M": 0.0}}
SCEN_TIE = {"arm_sig_contention": [("ARM_SIG", "__ext_ARM_SIG", 1.0)]}   # (net, fixed node, ohm)
PIN_IMAX = {"STM32G474RET6": 20e-3, "J3": 16e-3, "PCAL6524": 25e-3, "TCA6416A": 25e-3, "PCA9685PW": 25e-3}


def domains_on(off):
    on = {}

    def ok(d):
        if d in on:
            return on[d]
        on[d] = False if d in off else all(ok(x) for x in NEEDS[d])
        if d == "MCU":
            on[d] = ok("5V") or ok("USB")
        return on[d]
    for d in NEEDS:
        ok(d)
    return on


# ------------------------------------------------------------------------------------------- IC pin tables
# kind: P supply, G ground, I CMOS input (must not float), X analog/strap input, O push-pull out, OD open drain,
# IOD open-drain I/O (I2C), IO bidirectional (MCU/Pi GPIO, assumed input unless listed in OUT_NETS), A analog out,
# T power-path terminal (switch/FET), N no connect. absmax: expression over the IC's named pins (their net voltages).
# pu/pd: internal pull resistor (ohm) to the supply pin / to GND. supply: pins whose net powers the I/O.
class IC:
    def __init__(self, supply, pins, src, ioff=(), note="", any_supply=False):
        self.supply, self.pins, self.src, self.ioff, self.note = supply, pins, src, set(ioff), note
        self.any_supply = any_supply


def pin(name, kind, absmax=None, pu=None, pd=None, vout=None, sup=None):
    """pu: ohm to the supply pin, or (ohm, volts) to a fixed internal voltage; sup: the pin whose net is this pin's
    clamp rail when it differs from the IC supply (ADS7128 AIN -> AVDD)."""
    return dict(name=name, kind=kind, absmax=absmax, pu=pu, pd=pd, vout=vout, sup=sup)


def gnd(n="GND"):
    return pin(n, "G")


PINS = {}
PINS["INA238"] = IC(["6"], {
    "1": pin("A1", "X", "6"), "2": pin("A0", "X", "6"), "3": pin("ALERT", "OD", "VS+0.3"),
    "4": pin("SDA", "IOD", "6"), "5": pin("SCL", "I", "6"), "6": pin("VS", "P", "6"), "7": gnd(),
    "8": pin("VBUS", "X", "85"), "9": pin("INM", "X", "85"), "10": pin("INP", "X", "85")},
    "SLYS025B p.3 (pins), p.3 abs max", ioff=["8", "9", "10", "4", "5"])
PINS["ADS7128"] = IC(["10"], {
    **{p: pin(f"AIN{i}", "X", "AVDD+0.3", sup="7") for i, p in enumerate(("15", "16", "1", "2", "3", "4", "5", "6"))},
    "7": pin("AVDD", "P", "5.5"), "8": pin("DECAP", "A", "2.1"), "9": gnd(), "10": pin("DVDD", "P", "5.5"),
    "11": pin("ADDR", "X", "2.1"), "12": pin("ALERT", "OD", "5.5"), "13": pin("SCL", "I", "5.5"),
    "14": pin("SDA", "IOD", "5.5"), "17": gnd()},
    "SBAS868A p.4 (pins), p.5 abs max (AIN AVDD+0.3, ADDR 2.1 V), table 2 p.16 (address)")
PINS["PCAL6524"] = IC(["31"], {
    **{str(i): pin(f"P{i}", "IO", "6.5") for i in range(1, 25)}, "25": gnd(), "26": pin("ADDR", "X", "4.0"),
    "27": pin("VDDP", "P", "6.5"), "28": pin("RESET", "I", "4.0"), "29": pin("SCL", "I", "4.0"),
    "30": pin("SDA", "IOD", "4.0"), "31": pin("VDDI", "P", "4.0"), "32": pin("INT", "OD", "4.0"), "33": gnd()},
    "NXP PCAL6524 Rev.2 table 61 p.42 (limiting values), 6.6 p.26 (P port 5.5 V tolerant as input)",
    ioff=[str(i) for i in range(1, 25)], note="P port ioff: 'input may be raised above VDD(P)' p.26, unpowered case not stated")
PINS["TCA9548A"] = IC(["21"], {
    **{str(i): pin(f"SDSC{i}", "IOD", "7") for i in list(range(1, 9)) + list(range(10, 18))}, "9": gnd(),
    "18": pin("A2", "X", "VCC+0.5"), "19": pin("SCL", "IOD", "7"), "20": pin("SDA", "IOD", "7"),
    "21": pin("VCC", "P", "7"), "22": pin("A0", "X", "VCC+0.5"), "23": pin("A1", "X", "VCC+0.5"),
    "24": pin("RESET", "I", "7"), "25": gnd()},
    "SCPS207H table 4-1 p.3 (RGE pins), 5.1 p.4", ioff=[str(i) for i in range(1, 18)] + ["19", "20"])
PINS["TCA6416A"] = IC(["21"], {
    **{str(i): pin(f"P0{i - 1}", "IO", "6.5") for i in range(1, 9)}, "9": gnd(),
    **{str(i): pin(f"P1{i - 10}", "IO", "6.5") for i in range(10, 18)}, "18": pin("ADDR", "X", "6.5"),
    "19": pin("SCL", "I", "6.5"), "20": pin("SDA", "IOD", "6.5"), "21": pin("VCCP", "P", "6.5"),
    "22": pin("INT", "OD", "6.5"), "23": pin("VCCI", "P", "6.5"), "24": pin("RESET", "I", "6.5"), "25": gnd()},
    "SCPS194F fig 5-2 p.3 (RTW pins); abs max [mem]")
PINS["PCA9685PW"] = IC(["28"], {
    **{str(i): pin(f"A{i - 1}", "X", "5.5") for i in range(1, 6)}, **{str(i): pin(f"LED{i - 6}", "O", "5.5")
                                                                      for i in range(6, 14)},
    "14": gnd(), **{str(i): pin(f"LED{i - 7}", "O", "5.5") for i in range(15, 23)}, "23": pin("OE", "I", "5.5"),
    "24": pin("A5", "X", "5.5"), "25": pin("EXTCLK", "I", "5.5"), "26": pin("SCL", "I", "5.5"),
    "27": pin("SDA", "IOD", "5.5"), "28": pin("VDD", "P", "6")},
    "PCA9685 pins/limits [mem: 5.5 V tolerant I/O, VDD 6 V]")
PINS["DS3231SN"] = IC(["2"], {
    "1": pin("K32", "OD", "6"), "2": pin("VCC", "P", "6"), "3": pin("INT", "OD", "6"), "4": pin("RST", "OD", "6"),
    **{str(i): gnd() for i in range(5, 14)}, "14": pin("VBAT", "P", "6"), "15": pin("SDA", "IOD", "6"),
    "16": pin("SCL", "I", "6")}, "DS3231 [mem: -0.3..+6 V all pins]", ioff=["1", "3", "15", "16"])
PINS["TMP117"] = IC(["5"], {
    "1": pin("SCL", "I", "6"), "2": gnd(), "3": pin("ALERT", "OD", "6"), "4": pin("ADD0", "X", "6"),
    "5": pin("VP", "P", "6"), "6": pin("SDA", "IOD", "6"), "7": gnd()}, "SNOSD82D 6.1 p.5")
PINS["TMP117 0x48"] = PINS["TMP117 0x49"] = PINS["TMP117"]
PINS["MMC5983MA"] = IC(["2"], {
    "1": pin("SCL", "I", "3.6"), "2": pin("VDD", "P", "3.6"), "4": pin("CS", "I", "3.6"), "5": pin("SDO", "O", "3.6"),
    "9": gnd(), "10": pin("CAP", "P", "3.6"), "11": gnd(), "13": pin("VDDIO", "P", "3.6"), "15": pin("INT", "O"),
    "16": pin("SDA", "IOD", "3.6")}, "MMC5983MA Rev A p.11 (pins), abs max supply 3.6 V p.11")
PINS["ICM-42688-P"] = IC(["5"], {
    "1": pin("SDO", "O", "VDDIO+0.5"), "2": gnd("RESV"), "3": gnd("RESV"), "4": pin("INT1", "O", "VDDIO+0.5"),
    "5": pin("VDDIO", "P", "4"), "6": gnd(), "7": gnd("RESV"), "8": pin("VDD", "P", "4"),
    "9": pin("CLKIN", "I", "VDDIO+0.5"), "10": gnd("RESV"), "11": gnd("RESV"), "12": pin("CS", "I", "VDDIO+0.5"),
    "13": pin("SCLK", "I", "VDDIO+0.5"), "14": pin("SDI", "I", "VDDIO+0.5")},
    "DS-000347 r1.2 table 8 p.18 abs max, table 9 p.19 pins")
PINS["TCAN1044AV"] = IC(["5", "3"], {
    "1": pin("TXD", "I", "6", pu=50e3), "2": gnd(), "3": pin("VCC", "P", "6"), "4": pin("RXD", "O", "6"),
    "5": pin("VIO", "P", "6"), "6": pin("CANL", "A", "58", vout=2.6), "7": pin("CANH", "A", "58", vout=2.6),
    "8": pin("STB", "I", "6", pu=50e3), "9": gnd()}, "SLLSF55 6.1 (abs max); TXD/STB internal pull-ups [mem]",
    ioff=["6", "7"])
PINS["SN74LVC1G132"] = IC(["5"], {
    "1": pin("A", "I", "6.5"), "2": pin("B", "I", "6.5"), "3": gnd(), "4": pin("Y", "O", "VCC+0.5"),
    "5": pin("VCC", "P", "6.5")}, "SCES546E 5.1 p.4", ioff=["1", "2", "4"])
PINS["74AHCT1G125"] = IC(["5"], {
    "1": pin("OE", "I", "7"), "2": pin("A", "I", "7"), "3": gnd(), "4": pin("Y", "O", "VCC+0.5"),
    "5": pin("VCC", "P", "7")}, "SCLS378P 5.1 p.4", ioff=["1", "2"])
PINS["TLV75533"] = IC(["1"], {
    "1": pin("IN", "P", "6"), "2": gnd(), "3": pin("EN", "I", "6"), "5": pin("OUT", "T", "min(IN+0.3,6)")},
    "SBVS320D 5.1 p.4")
PINS["TLV76050"] = IC(["2"], {
    "1": pin("OUT", "T", "IN+0.3"), "2": pin("IN", "P", "35"), "3": gnd()}, "SNVSAV1A 6.1 p.4 (pins p.3)")
PINS["TLV6700"] = IC(["5"], {
    "1": pin("OUTA", "OD", "20"), "2": gnd(), "3": pin("INAP", "X", "7"), "4": pin("INBM", "X", "7"),
    "5": pin("VDD", "P", "20"), "6": pin("OUTB", "OD", "20")}, "SNVSAV2B pins p.3, 7.1 p.4",
    ioff=["1", "3", "4", "6"])
PINS["REF3425"] = IC(["4"], {
    "1": gnd(), "2": gnd(), "3": pin("EN", "I", "IN+0.3"), "4": pin("IN", "P", "13"), "5": pin("OUTS", "T", "5.5"),
    "6": pin("OUTF", "T", "5.5")}, "SBOS923 (REF34) 6.1")
PINS["TPS62826"] = IC(["6"], {
    "1": pin("EN", "I", "6"), "2": pin("PG", "OD", "6"), "3": pin("FB", "X", "6"), "4": gnd(),
    "5": pin("SW", "T", "VIN+0.3"), "6": pin("VIN", "P", "6")}, "SLVSEF9I 6.1 p.4", ioff=["1", "2"])
EF = {"1": pin("EN", "I", "6.5"), "2": pin("OVLO", "X", "6.5"), "3": pin("AUXOFF", "OD", "6.5"),
      "4": pin("FLT", "OD", "6.5"), "5": pin("IN", "P", "28"), "6": pin("OUT", "T", "min(28,IN+21)"),
      "7": pin("DVDT", "A"), "8": gnd(), "9": pin("ILM", "A", None, vout=1.25), "10": pin("ITIMER", "A", vout=2.72)}
PINS["TPS259470L"] = PINS["TPS259470A"] = IC(["5"], EF, "SLVSFC9C pins 5-1 p.5-6, 6.1 p.7, ILM G_IMON 182 uA/A p.10",
                                              ioff=["1", "2", "4"])
PINS["TPS25982"] = IC(["1"], {
    **{p: pin("IN", "P", "30") for p in ("1", "2", "3", "16", "25")},
    **{p: gnd() for p in ("4", "5", "14", "26")}, "6": pin("EN", "I", "7"), "7": pin("ITIMER", "A", vout=2.5),
    "8": pin("ILIM", "A"), "9": pin("IMON", "A", None), "10": pin("RETRY_DLY", "A"), "11": pin("NRETRY", "A"),
    "12": pin("LDSTRT", "X", "7"), "13": pin("PG", "OD", "7"), "15": pin("DVDT", "A"),
    **{str(p): pin("OUT", "T", "min(30,IN+0.3)") for p in range(17, 25)}},
    "SLVSEI3D table 5-1 p.5-6, 6.1 p.7, 6.5 p.8-10", ioff=["6", "13"])
PINS["TPS16630"] = IC(["1"], {
    **{p: pin("IN", "P", "67") for p in ("1", "2", "3", "6")}, "7": pin("UVLO", "X", "67"),
    "8": pin("OVP", "X", "5.5"), "9": gnd(), "10": pin("DVDT", "A"), "11": pin("ILIM", "A", "5.5"),
    "12": pin("MODE", "X", "5.5"), "13": pin("SHDN", "I", "5.5", pu=(270e3, 2.7)), "14": pin("IMON", "A", "5.5"),
    "15": pin("FLT", "OD", "67"), "16": pin("PGOOD", "OD", "67"), **{p: pin("OUT", "T", "67") for p in ("18", "19", "20")},
    "21": gnd()}, "SLVSET9G 6.1 p.7, pins 5-1 p.5-6", ioff=["15", "16", "13"])
PINS["TPS2121"] = IC(["7", "2"], {
    "1": pin("OUT", "T", "24"), "2": pin("IN2", "P", "24"), "3": pin("CP2", "X", "6"), "4": pin("OV2", "X", "6"),
    "5": pin("OV1", "X", "6"), "6": pin("PR1", "X", "6"), "7": pin("IN1", "P", "24"), "8": pin("OUT", "T", "24"),
    "9": pin("ST", "OD", "6"), "10": pin("ILM", "A"), "11": pin("SS", "A", vout=4.0), "12": gnd()},
    "SLVSEA3F pins p.4-5, 7.1 p.6", any_supply=True)
PINS["LM61495"] = IC(["2"], {
    "1": gnd(), "2": pin("VIN", "P", "42"), "3": pin("RBOOT", "T", "SW+5.5"), "4": pin("CBOOT", "T", "SW+5.5"),
    "5": pin("BIAS", "P", "16"), "6": pin("VCC", "A", "5.5", vout=5.0), "7": pin("FB", "X", "5.5"), "8": gnd(),
    "9": pin("RT", "A", "5.5", vout=1.0), "10": pin("RESET", "OD", "20"), "11": gnd(), "12": gnd(),
    "13": pin("EN", "X", "42"), "14": pin("VIN", "P", "42"), "15": gnd(), "16": pin("SW", "T", "VIN+0.3")},
    "SNVSBZ4A table 6-1 p.3-4, 7.1 p.6 (BIAS 16 V, FB 5.5 V)", ioff=["10"])
PINS["LM74800"] = IC(["10"], {
    "1": pin("DGATE", "A"), "2": pin("A", "T", "70"), "3": pin("VSNS", "X", "70"), "4": pin("SW", "X", "70"),
    "5": pin("OV", "X", "70"), "6": pin("EN", "X", "70"), "7": gnd(), "8": pin("HGATE", "A"),
    "9": pin("OUT", "T", "70"), "10": pin("VS", "P", "70"), "11": pin("CAP", "A"), "12": pin("C", "T", "70")},
    "SNOSDD8 table 6-1 p.3, 7.1 p.4")
PINS["LM5069-1"] = IC(["2"], {
    "1": pin("SENSE", "X", "80"), "2": pin("VIN", "P", "80"), "3": pin("UVLO", "X", "80"), "4": pin("OVLO", "X", "80"),
    "5": gnd(), "6": pin("TIMER", "A", vout=4.0), "7": pin("PWR", "A", vout=2.6), "8": pin("PGD", "OD", "80"),
    "9": pin("OUT", "T", "80"), "10": pin("GATE", "A")}, "SNVS452G pins p.3, abs max [mem: 80 V class]",
    ioff=["8"])
PINS["DRV8243H"] = IC(["4"], {
    "1": pin("nFAULT", "OD", "5.75"), "2": pin("IPROPI", "A", "5.75"), "3": pin("nSLEEP", "I", "40", pd=200e3),
    "4": pin("VM", "P", "40"), "5": pin("OUT2", "T", "VM+0.9"), "6": gnd(), "7": pin("OUT1", "T", "VM+0.9"),
    "8": pin("DRVOFF", "I", "40", pu=300e3), "9": pin("IN1", "I", "5.75", pd=300e3),
    "10": pin("IN2", "I", "5.75", pd=300e3), "11": pin("DIAG", "X", "5.75"), "12": pin("SR", "X", "5.75"),
    "13": pin("ITRIP", "X", "5.75"), "14": pin("MODE", "X", "5.75")},
    "SLVSG23E table 5-2 p.6-7, 6.1 p.10, internal pulls p.12 (nSLEEP 100-400k, IN 200-500k, DRVOFF 200-550k)",
    ioff=["1", "3", "8", "9", "10"])
PINS["LM393"] = IC(["8"], {
    "1": pin("OUT1", "OD", "36"), "2": pin("IN1M", "X", "36"), "3": pin("IN1P", "X", "36"), "4": gnd(),
    "5": pin("IN2P", "X", "36"), "6": pin("IN2M", "X", "36"), "7": pin("OUT2", "OD", "36"), "8": pin("VCC", "P", "36")},
    "onsemi LM393 [mem]", ioff=["2", "3", "5", "6"])
PINS["TL431"] = IC([], {"1": pin("K", "T", "37"), "2": pin("REF", "X", "37"), "3": gnd()}, "SLVS543N")
PINS["USBLC6-2SC6"] = IC(["5"], {"1": pin("IO1", "X", "6"), "3": pin("IO2", "X", "6"), "4": pin("IO2", "X", "6"),
                                 "6": pin("IO1", "X", "6"), "2": gnd(), "5": pin("VBUS", "P", "6")}, "ST USBLC6 [mem]")
PINS["SK9822-EC20"] = IC(["5"], {
    "1": pin("SDO", "O", "VDD+0.4"), "2": gnd(), "3": pin("SDI", "I", "VDD+0.4"), "4": pin("CKI", "I", "VDD+0.4"),
    "5": pin("VDD", "P", "6"), "6": pin("CKO", "O", "VDD+0.4")}, "Opsco SK9822-EC20 A/0 p.4 (pins), p.5 limits")
# STM32G474RET6: FT pins abs max min(VDD,VDDA)+4.0, TT and others 4.0 (DS12288 table 14 p.82)
STM = json.loads((ROOT / "data/pcb-revc/ics/stm32_pinmap.json").read_text())["pins"]
stm_pins = {}
for r in STM:
    io = (r.get("io") or "")
    kind = "P" if r["group"] == "power" or r["port"] in ("VDD", "VSS", "VDDA", "VREF+", "VBAT") else "IO"
    if r["port"] in ("VSS",) or r["net"] == "GND":
        kind = "G"
    am = "VDD+4.0" if io.startswith("FT") else "4.0"
    stm_pins[str(r["pin"])] = pin(r["port"], kind, am if kind == "IO" else "4.0")
stm_pins["7"] = pin("NRST", "IO", "4.0", pu=40e3)
stm_pins["61"] = pin("BOOT0", "I", "4.0")
PINS["STM32G474RET6"] = IC(["1"], stm_pins, "DS12288 table 12 p.57-72 (pins via stm32_pinmap.json), table 14 p.82",
                            ioff=[p for p, d in stm_pins.items() if d["absmax"] == "VDD+4.0"],
                            note="FT pins: abs max = 4.0 V while VDD = 0")
# MCU pins that are outputs (drivers) by firmware, per stm32_pinmap.md
MCU_OUT = {"MCU_ALIVE", "MCU_TX", "MCU_LED", "SERVO_MCU", "IMU_CS", "ITRIP_SEL", "CAN_TX", "DRV_L_NSLEEP",
           "DRV_R_NSLEEP", "CAN_STB", "DRV_R_IN1", "DRV_R_IN2", "DRV_L_IN1", "DRV_L_IN2", "SPI3_SCK", "SPI3_MOSI"}
MCU_OD = {"ARM_UART_M", "I2C3_SCL", "I2C3_SDA"}
MCU_IO = {"SWDIO", "SWCLK", "MCU_NRST", "OSC_IN", "OSC_OUT", "USB_DP", "USB_DM", "SPI3_MISO"}
EXP_OUT = set(design.EN_PORT) | {f"TOF{i}_LPN_X" for i in range(1, 7)}
DRIVE_LOW = {"GPIO17": "gpio-poweroff idle", "GPIO25": "Jetson on (Q7 off)", "MOT_BUS_OFF": "motor bus on",
             "CAN_STB": "CAN normal mode"}
VALUE_ALIAS = {}

# ------------------------------------------------------------------------------------------- external devices
# connector pins: (kind, domain-rail of the device, absmax expression with 'VDD' = device supply)
PI_OUT = {"GPIO4", "GPIO8", "GPIO12", "GPIO14", "GPIO17", "BUZZER_PWM", "GPIO27", "LED_DI", "LED_CI", "GPIO25",
          "EXP_RESET_N", "TOF_MUX_RESET_N", "GPIO16"}
PI_IOD = {"I2C1_SDA", "I2C1_SCL", "I2C6_SDA", "I2C6_SCL"}
PI_IN = {"GPIO5", "GPIO9", "GPIO13", "GPIO15", "EXP_INT_N", "PWR_ALERT_N", "POWER_BTN", "BUMPER_FRONT",
         "BUMPER_REAR", "GPIO0", "GPIO1"}
PI_PULLUP = {"GPIO0", "GPIO1", "GPIO4", "GPIO5", "EXP_RESET_N", "EXP_INT_N", "GPIO8"}   # BCM2711 default pulls


def ext_pins(ref, p):
    """{pad: dict(kind, rail, absmax, pu/pd, note)} for the device on the far side of a connector."""
    v, out = p["value"], {}
    pins = p["pins"]
    if not ref.startswith("J"):
        return {}
    if ref == "J3":
        for pad, net in pins.items():
            if net in ("GND",):
                continue
            if net == "+3V3_PI":
                continue
            k = "O" if net in PI_OUT else "IOD" if net in PI_IOD else "I" if net in PI_IN else "IO"
            d = dict(kind=k, rail="+3V3_PI", absmax="VDD+0.3", dev="Raspberry Pi 4 GPIO (BCM2711, not 5 V tolerant)")
            if net in ("I2C1_SDA", "I2C1_SCL"):
                d["pu"] = 1.8e3
            elif net in PI_PULLUP:
                d["pu"] = 50e3
            else:
                d["pd"] = 50e3
            out[pad] = d
    elif v.startswith("ToF"):
        n = v.split()[1]
        out = {"3": dict(kind="IOD", rail=f"TOF{n}_3V3", absmax="3.6", dev="VL53L8CX carrier"),
               "4": dict(kind="I", rail=f"TOF{n}_3V3", absmax="3.6", dev="VL53L8CX carrier"),
               "5": dict(kind="OD", rail=f"TOF{n}_3V3", absmax="3.6", dev="VL53L8CX carrier"),
               "6": dict(kind="I", rail=f"TOF{n}_3V3", absmax="3.6", pu=47e3,
                         dev="VL53L8CX carrier (LSF0204 B side; R5 47k to 1.8 V on the A side)")}
    elif v.startswith("lidar"):
        n = v.split()[1]
        out = {"2": dict(kind="O", rail=f"LIDAR{n}_5V", absmax="3.5", vhigh=3.5, dev="RPLIDAR C1 TX (0/3.5 V)"),
               "3": dict(kind="I", rail=f"LIDAR{n}_5V", absmax="3.5", dev="RPLIDAR C1 RX (max 3.5 V, DS p.12)")}
    elif v == "motor PH-6":
        s = "L" if ref == "J41" else "R"
        out = {"3": dict(kind="O", rail=f"ENC_{s}_3V3", absmax="VDD+0.3", dev="Hall encoder"),
               "4": dict(kind="O", rail=f"ENC_{s}_3V3", absmax="VDD+0.3", dev="Hall encoder")}
    elif v.startswith("servo "):
        out = {"1": dict(kind="I", rail="SERVO_PWR", absmax="VDD", dev="hobby servo PWM input")}
    elif v == "xArm bus":
        out = {"3": dict(kind="IOD", rail="ARM_PWR", absmax="VDD", dev="Hiwonder bus servo SIG (level unpublished)")}
    elif v.startswith("fan"):
        n = v.split()[1]
        out = {"3": dict(kind="OD", rail=f"FAN{n}_5V", absmax="VDD", dev="fan tach (open collector)"),
               "4": dict(kind="I", rail=f"FAN{n}_5V", absmax="VDD+0.3", pu=10e3, dev="fan PWM (internal pull-up)")}
    return out


# connectors whose far side is a switch/jumper (closed in normal operation): pairs shorted
EXT_SHORTS = [("J52", "1", "2"), ("J52", "3", "4")]
EXT_LOADS = {"J41": [("1", "6", 2.0)], "J42": [("1", "6", 2.0)]}   # motor winding ~2 ohm

# nets whose DC value is set by an IC function the solver does not model (value, reason)
FORCE = {
    "DG": (lambda V: V["BAT_F"] + 12 if V["SW_MID"] else 0, "LM74800 DGATE = A + ~12 V (DGATE-A abs max 15 V)"),
    "HG": (lambda V: V["VBUS_RAW"] + 12 if V["SW_MID"] else 0, "LM74800 HGATE = OUT + ~12 V"),
    "LM_CAP": (lambda V: V["SW_MID"] + 12 if V["SW_MID"] else 0, "LM74800 charge pump CAP = VS + ~12 V"),
    "MOT_GATE": (lambda V: V["MOT_BUS"] + 12 if V["MOT_BUS"] else 0, "LM5069 GATE = OUT + ~12 V when on"),
    "SW4": (lambda V: V["BODY_IN"], "switch node peak = VIN"), "SW6": (lambda V: V["STEER_IN"], "switch node peak = VIN"),
    "BOOT4": (lambda V: V["BODY_IN"] + 5 if V["BODY_IN"] else 0, "CBOOT = SW + VCC"),
    "BOOT6": (lambda V: V["STEER_IN"] + 5 if V["STEER_IN"] else 0, "CBOOT = SW + VCC"),
    "SW_TOF": (lambda V: V["+5V"] if V["+3V3_TOF_BUCK"] else 0, "switch node peak = VIN"),
    "BRK_REF": (lambda V: 2.495 if V["MOT_BUS"] else 0, "TL431 shunt reference"),
    "ALIVE_DET": (lambda V: 2.9 if V["+3V3_MCU"] else 0, "charge pump from the 3.3 V MCU_ALIVE square wave"),
    "OSC_IN": (lambda V: 1.65 if V["+3V3_MCU"] else 0, "crystal bias"),
    "OSC_OUT": (lambda V: 1.65 if V["+3V3_MCU"] else 0, "crystal bias"),
    "IPROPI_L": (lambda V: 5.5 if V["MOT_BUS"] else 0, "DRV8243 IPROPI clamp V_IPROPI_LIM 4.5-5.5 V (p.16)"),
    "IPROPI_R": (lambda V: 5.5 if V["MOT_BUS"] else 0, "DRV8243 IPROPI clamp"),
    "ARM_IMON_SRC": (lambda V: 246e-6 * 11.9 * 1e3 if V["ARM_PWR"] else 0,
                     "TPS25982 IMON 246 uA/A x 11.9 A (fast-trip max at R_ILIM 300) x 1k"),
    "JET_IMON_SRC": (lambda V: 27.9e-6 * 8 * 10e3 if V["JET_PWR"] else 0, "TPS16630 IMON 27.9 uA/A x ~8 A x 10k"),
    "SPARE_IMON_SRC": (lambda V: 27.9e-6 * 8 * 10e3 if V["SPARE_VBAT"] else 0, "TPS16630 IMON"),
    "U5_DVDT": (lambda V: 4.0 if V["VBUS"] else 0, "dVdT pin (abs max 5.5 V)"),
    "U7_DVDT": (lambda V: 4.0 if V["VBUS"] else 0, "dVdT pin"),
    "U5_ILIM": (lambda V: 1.2 if V["VBUS"] else 0, "ILIM pin"), "U7_ILIM": (lambda V: 1.2 if V["VBUS"] else 0, "ILIM pin"),
    "ARM_DVDT": (lambda V: V["SERVO_RAW"] + 4 if V["SERVO_RAW"] else 0, "TPS25982 dVdT cap rating VIN + 4 V (6.3)"),
    "ARM_ILIM": (lambda V: 1.0 if V["SERVO_RAW"] else 0, "ILIM pin"),
    "MOT_TMR": (lambda V: 4.0 if V["VBUS"] else 0, "LM5069 TIMER 4 V"),
    "MOT_PWR": (lambda V: 2.6 if V["VBUS"] else 0, "LM5069 PWR"),
    "MUX_ILM": (lambda V: 1.0 if V["+5V_MCU"] else 0, "TPS2121 ILM"),
    "CANH": (lambda V: 2.6 if V["+5V_MCU"] else 0, "recessive bias"), "CANL": (lambda V: 2.6 if V["+5V_MCU"] else 0, ""),
    "USB_DP": (lambda V: 3.6 if V["USB_VBUS"] else 0, "USB FS line max"),
    "USB_DM": (lambda V: 3.6 if V["USB_VBUS"] else 0, "USB FS line max"),
}
for _u, X, _in, out, *_ in design.EFUSES:
    FORCE[f"{X}_DVDT"] = ((lambda o: lambda V: V[o] + 4 if V[o] else 0)(out), "dVdT internally limited, ~VIN + 4")
    FORCE[f"{X}_ILM"] = ((lambda o: lambda V: 1.25 if V[o] else 0)(out),
                         "ILM = I x R_ILM x 182 uA/A: 0.61 V at I_LIM, 1.2 V at the 2x fast trip")
    FORCE[f"{X}_ITMR"] = ((lambda o: lambda V: 2.72 if V[o] else 0)(out), "ITIMER internal 2.57 V (max 2.72)")

DIODES = {   # value: (kind, Vf, Vbr) ; pin 1 = cathode, 2 = anode for SOD/SMx; LED 1 = K, 2 = A
    "1N4148WS": ("si", 0.7, 75), "B340A": ("sch", 0.35, 40), "B540C": ("sch", 0.4, 40), "BAT54WS": ("sch", 0.3, 30),
    "BZT52C12": ("z", 0.7, 11.4), "BZT52C8V2": ("z", 0.7, 7.79), "LED red": ("led", 1.9, 5),
    "SMBJ20A": ("tvs", 0.8, 22.2), "SMBJ20CA": ("tvs2", 22.2, 22.2),
}

# ------------------------------------------------------------------------------------------- solver


def solve_linear(adj, fixed, V):
    """Exact nodal solve, one connected component of free nets at a time (fixed nets split the graph), by Gaussian
    elimination with partial pivoting. Stiff elements (1 mOhm shorts, 1 S diodes) need no special care."""
    seen = set()
    for start in adj:
        if start in fixed or start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m, _, _ in adj[n]:
                if m not in fixed and m not in seen:
                    seen.add(m)
                    stack.append(m)
        idx = {n: i for i, n in enumerate(comp)}
        k = len(comp)
        A = [[0.0] * (k + 1) for _ in range(k)]
        for n, i in idx.items():
            for m, g, vo in adj[n]:
                A[i][i] += g
                A[i][k] += g * vo
                if m in idx:
                    A[i][idx[m]] -= g
                else:
                    A[i][k] += g * fixed[m]
        for c in range(k):
            piv = max(range(c, k), key=lambda r: abs(A[r][c]))
            A[c], A[piv] = A[piv], A[c]
            if abs(A[c][c]) < 1e-15:
                continue
            for r in range(c + 1, k):
                f = A[r][c] / A[c][c]
                if f:
                    row_r, row_c = A[r], A[c]
                    for j in range(c, k + 1):
                        row_r[j] -= f * row_c[j]
        x = [0.0] * k
        for c in range(k - 1, -1, -1):
            if abs(A[c][c]) < 1e-15:
                continue
            x[c] = (A[c][k] - sum(A[c][j] * x[j] for j in range(c + 1, k))) / A[c][c]
        for n, i in idx.items():
            V[n] = x[i]


class Model:
    def __init__(self, scen):
        off, over, self.note = SCENARIOS[scen]
        self.name = scen
        self.on = domains_on(off)
        self.V = defaultdict(float)
        self.fixed = {}
        for net, (v, dom) in RAILS.items():
            self.fixed[net] = (v if self.on[dom] else 0.0) if net not in over else over[net]
        for k, v in over.items():
            self.fixed[k] = v
        self.V.update(self.fixed)
        self.sdrive = SCEN_DRIVE.get(scen, {})
        self.el = []       # (a, b, g, voff): current a->b = g * (Va - Vb - voff)
        self.diodes = []   # (ref, a, k, vf, vbr, rev_allowed)
        self.fets = []     # (ref, g, s, d, vth)
        self.drivers = defaultdict(list)   # net -> [(who, vhigh)]
        self.pinsat = []   # (ref, pad, net, info, ic_powered)
        self.build()

    def supply_on(self, ref):
        ic = PINS.get(PARTS[ref]["value"])
        if not ic:
            return True
        f = any if ic.any_supply else all
        return f(self.V[PARTS[ref]["pins"].get(s, "GND")] > 1.0 for s in ic.supply if s in PARTS[ref]["pins"])

    def R(self, a, b, r, voff=0.0):
        self.el.append((a, b, 1.0 / max(r, 1e-3), voff))

    def build(self):
        for ref, p in LIVE.items():
            v, pins, fp = p["value"], p["pins"], p["fp"]
            pre = re.match(r"[A-Z]+", ref).group(0)
            if pre in ("R", "RT") and len(pins) == 2:
                self.R(pins["1"], pins["2"], rval(ref))
            elif pre == "R" and len(pins) == 4:   # Kelvin shunt: current pins short, sense pins on them
                a, b = (pins["1"], pins["2"]) if fp == design.SHUNT else (pins["1"], pins["4"])
                ka, kb = (pins["3"], pins["4"]) if fp == design.SHUNT else (pins["2"], pins["3"])
                self.R(a, b, max(rval(ref), 1e-3))
                self.R(a, ka, 1e-3)
                self.R(b, kb, 1e-3)
            elif pre == "RN":
                r = rval(ref)
                for k in range(1, 5):
                    if str(k) in pins and str(9 - k) in pins:
                        self.R(pins[str(k)], pins[str(9 - k)], r)
            elif pre in ("F", "L", "NT"):
                self.R(pins["1"], pins["2"], 1e-3)
            elif pre == "JP" and v == "S0 source":
                self.R(pins["1"], pins["2"], 1e-3)
            elif pre == "D" or (pre == "LED" and False):
                self.diode(ref, p)
            elif pre == "Q":
                if v in ("2N7002K", "AO3400A", "BSS138"):
                    self.fets.append((ref, pins["1"], pins["2"], pins["3"], 2.0))
                    self.diodes.append((ref + ".body", pins["2"], pins["3"], 0.7, 1e9))
                elif v.startswith("BSC"):
                    self.fets.append((ref, pins["4"], pins["1"], pins["5"], 2.5))
                    self.diodes.append((ref + ".body", pins["1"], pins["5"], 0.7, 1e9))
            elif pre == "LS":
                self.R(pins["1"], pins["2"], 1e6)
        for ref, a, b in EXT_SHORTS:
            self.R(PARTS[ref]["pins"][a], PARTS[ref]["pins"][b], 1.0)
        for net, node, r in SCEN_TIE.get(self.name, []):
            self.R(net, node, r)
        for ref, l in EXT_LOADS.items():
            for a, b, r in l:
                self.R(PARTS[ref]["pins"][a], PARTS[ref]["pins"][b], r)
        # IC pins
        for ref, p in LIVE.items():
            ic = PINS.get(p["value"])
            if ic:
                powered = self.supply_on(ref)
                sup = p["pins"].get(ic.supply[0]) if ic.supply else "GND"
                for pad, net in p["pins"].items():
                    info = ic.pins.get(pad)
                    if info is None:
                        continue
                    kind = info["kind"]
                    if p["value"] == "STM32G474RET6" and kind == "IO":
                        kind = "O" if net in MCU_OUT else "OD" if net in MCU_OD else "IO" if net in MCU_IO else "I"
                    if p["value"] in ("PCAL6524", "TCA6416A") and kind == "IO" and net in EXP_OUT:
                        kind = "O"
                    info = dict(info, kind=kind)
                    psup = p["pins"].get(info["sup"]) if info.get("sup") else sup
                    ppow = powered if not info.get("sup") else self.V[psup] > 1.0
                    self.pinsat.append((ref, pad, net, info, ppow, psup))
                    if not powered:
                        continue
                    if kind == "O":
                        self.drivers[net].append((f"{ref}.{pad}", 0.0 if net in DRIVE_LOW else self.V[sup]))
                    if kind in ("OD", "IOD") and net in self.sdrive:
                        self.drivers[net].append((f"{ref}.{pad}", self.sdrive[net]))
                    if isinstance(info.get("pu"), tuple):
                        r, vv = info["pu"]
                        self.fixed[f"__pu_{ref}.{pad}"] = vv
                        self.R(net, f"__pu_{ref}.{pad}", r)
                    elif info.get("pu"):
                        self.R(net, sup, info["pu"])
                    if info.get("pd"):
                        self.R(net, "GND", info["pd"])
                    if info.get("vout") is not None and net not in FORCE:
                        self.fixed.setdefault(net, info["vout"])
            for pad, e in ext_pins(ref, p).items():
                net = p["pins"][pad]
                rail = e["rail"]
                powered = self.V[rail] > 1.0
                info = dict(name=f"ext:{e['dev']}", kind=e["kind"], absmax=e["absmax"], pu=e.get("pu"),
                            pd=e.get("pd"))
                self.pinsat.append((ref, pad, net, info, powered, rail))
                if not powered:
                    continue
                if e["kind"] == "O":
                    self.drivers[net].append((f"{ref}.{pad}", 0.0 if net in DRIVE_LOW else e.get("vhigh", self.V[rail])))
                if e.get("pu"):
                    self.R(net, rail, e["pu"])
                if e.get("pd"):
                    self.R(net, "GND", e["pd"])
        for net, (f, why) in FORCE.items():
            if net in NETS:
                self.fixed[net] = f(self.V)
        # unpowered CMOS pins clamp to their dead supply through the ESD diode (~0.5 V at a few mA)
        self.fixed["__dead"] = 0.0
        for (ref, pad, net, info, powered, sup) in self.pinsat:
            ioff = pad in PINS[PARTS[ref]["value"]].ioff if PARTS[ref]["value"] in PINS else info["kind"] in ("OD",)
            if not powered and info["kind"] not in ("P", "G", "T") and not ioff and net not in self.fixed:
                self.diodes.append((f"{ref}.{pad}.clamp", net, "__dead", 0.5, 1e9))

    def diode(self, ref, p):
        v, pins = p["value"], p["pins"]
        if v in DIODES:
            kind, vf, vbr = DIODES[v]
            k, a = pins["1"], pins["2"]
            if kind == "tvs2":
                self.diodes.append((ref, a, k, vbr, 1e9))
                self.diodes.append((ref + "r", k, a, vbr, 1e9))
            else:
                self.diodes.append((ref, a, k, vf, vbr))
        elif v == "BAT54S":
            self.diodes.append((ref + "a", pins["1"], pins["3"], 0.3, 30))
            self.diodes.append((ref + "b", pins["3"], pins["2"], 0.3, 30))
        elif v == "TPD4E05U06":
            for io in ("1", "2", "4", "5"):
                if io in pins:
                    self.diodes.append((f"{ref}.{io}", "GND", pins[io], 0.7, 6.5))
        elif v == "TPD1E10B09":
            self.diodes.append((ref, pins["1"], pins["2"], 9.5, 1e9))
            self.diodes.append((ref + "r", pins["2"], pins["1"], 9.5, 1e9))
        elif v == "PESD2CANFD24V":
            for io in ("1", "2"):
                self.diodes.append((f"{ref}.{io}", pins[io], "GND", 25.5, 1e9))
                self.diodes.append((f"{ref}.{io}r", "GND", pins[io], 25.5, 1e9))

    def solve(self):
        fixed = dict(self.fixed)
        for net, drv in self.drivers.items():
            if net not in fixed:
                self.el.append((net, "__drv_" + net, 1 / 25.0, 0.0))
                fixed["__drv_" + net] = self.sdrive.get(net, max(v for _, v in drv))
        V = defaultdict(float, {k: v for k, v in fixed.items()})
        for n in NETS:
            if n not in fixed:
                V[n] = 0.0
        dstate = {d[0]: (False, False) for d in self.diodes}
        fstate = {f[0]: False for f in self.fets}
        for outer in range(40):
            els = list(self.el)
            for (ref, a, k, vf, vbr) in self.diodes:
                fwd, rev = dstate[ref]
                if fwd:
                    els.append((a, k, 1.0, vf))
                if rev:
                    els.append((k, a, 1.0, vbr))
            for (ref, g, s, d, vth) in self.fets:
                if fstate[ref]:
                    els.append((d, s, 1 / 2.0, 0.0))
            adj = defaultdict(list)
            for a, b, g, voff in els:
                adj[a].append((b, g, voff))
                adj[b].append((a, g, -voff))
            solve_linear(adj, fixed, V)
            changed = False
            for (ref, a, k, vf, vbr) in self.diodes:
                fwd = V[a] - V[k] > vf - 1e-6 or (dstate[ref][0] and V[a] - V[k] > vf - 0.05)
                rev = V[k] - V[a] > vbr - 1e-6 or (dstate[ref][1] and V[k] - V[a] > vbr - 0.05)
                if (fwd, rev) != dstate[ref]:
                    dstate[ref], changed = (fwd, rev), True
            for (ref, g, s, d, vth) in self.fets:
                on = V[g] - min(V[s], V[d]) > vth
                if on != fstate[ref]:
                    fstate[ref], changed = on, True
            if not changed:
                break
        self.Vs, self.dstate, self.fstate, self.adj = V, dstate, fstate, adj
        self.fixed_all = fixed
        return V

    def sourced(self):
        """nets with a conductive path to a fixed node (rail, driver, forced net)."""
        seen = set(self.fixed_all)
        stack = list(self.fixed_all)
        while stack:
            n = stack.pop()
            for m, g, _ in self.adj.get(n, []):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        return seen


# ------------------------------------------------------------------------------------------- checks
FLAGS = []


def flag(check, sev, refs, msg):
    FLAGS.append(dict(check=check, sev=sev, refs=refs, msg=msg))


def evalmax(expr, ref, V):
    ic = PINS.get(PARTS[ref]["value"])
    env = {"min": min, "max": max}
    if ic:
        for pad, info in ic.pins.items():
            if pad in PARTS[ref]["pins"]:
                env.setdefault(info["name"], V[PARTS[ref]["pins"][pad]])
        env.setdefault("VDD", V[PARTS[ref]["pins"].get(ic.supply[0], "GND")] if ic.supply else 0)
        env.setdefault("VS", env["VDD"])
    return eval(expr, env)


def check_single_pin():
    for n, l in sorted(NETS.items()):
        if len(l) < 2:
            flag("single-pin net", "info", [r for r, _ in l], f"{n}: {l}")
        live = [(r, p) for r, p in l if PARTS[r]["bom"] not in ("dnp", "none")]
        if len(l) >= 2 and len(live) < 2:
            flag("net with <2 fitted pins", "info", [r for r, _ in l], f"{n}: fitted {live}, all {l}")


def check_scenario(m):
    V = m.solve()
    src = m.sourced()
    for (ref, pad, net, info, powered, sup) in m.pinsat:
        kind, am = info["kind"], info["absmax"]
        v = V[net]
        if am:
            try:
                lim = evalmax(am, ref, V) if PARTS[ref]["value"] in PINS else eval(am, {"VDD": V[sup], "min": min})
            except (NameError, KeyError, TypeError):
                lim = None
            if not powered and ("VDD" in am or am == "VDD"):
                lim = 4.0 if "4.0" in am else None
            if lim is not None and v > lim + 0.02 and kind not in ("G",):
                flag("abs max", "check", [ref], f"[{m.name}] {ref}.{pad} {info['name']} on {net} = {v:.2f} V > "
                     f"abs max {lim:.2f} V ({am})")
        cl = f"{ref}.{pad}.clamp"
        if not powered and cl in m.dstate and m.dstate[cl][0]:
            i = (V[net] - 0.5) * 1e3
            if i > 0.02:
                flag("back-power", "check", [ref], f"[{m.name}] {ref}.{pad} {info['name']} unpowered ({sup} = 0): "
                     f"{i:.2f} mA from {net} into its clamp")
        if m.name == "all_on" and powered and kind == "I" and net not in src:
            flag("floating input", "check", [ref], f"{ref}.{pad} {info['name']} on {net}: no driver, no pull")
    # output pin current (25 ohm driver model): flag above the pin's abs-max current
    for net, drv in m.drivers.items():
        vd = m.fixed_all.get("__drv_" + net)
        if vd is None:
            continue
        i = abs(V[net] - vd) / 25.0
        for who, _ in drv:
            r = who.split(".")[0]
            lim = PIN_IMAX.get(r, PIN_IMAX.get(PARTS[r]["value"]))
            if lim and i > lim:
                flag("output pin current", "check", [r], f"[{m.name}] {who} on {net}: {i * 1e3:.0f} mA > {lim * 1e3:.0f} mA "
                     f"(net {V[net]:.2f} V vs driver {vd:.2f} V)")
    # current pushed into a rail that is off (it then feeds everything on that rail)
    for ref, p in LIVE.items():
        if re.match(r"RN?\d", ref) and ref[0] == "R":
            pins = p["pins"]
            pairs = [("1", "2")] if len(pins) == 2 else [(str(k), str(9 - k)) for k in range(1, 5)]
            for a_, b_ in pairs:
                if a_ not in pins or b_ not in pins:
                    continue
                for x, y in ((pins[a_], pins[b_]), (pins[b_], pins[a_])):
                    if y in RAILS and RAILS[y][0] > 0 and V[y] == 0 and V[x] > 0.6 and x not in RAILS:
                        i = (V[x] - 0.3) / rval(ref) * 1e3
                        if i > 0.01:
                            flag("current into an off rail", "check", [ref], f"[{m.name}] {ref} {p['value']}: {x} "
                                 f"{V[x]:.2f} V -> off rail {y}: ~{i:.2f} mA")
    if m.name == "all_on":
        for net, drv in m.drivers.items():
            if len(drv) > 1:
                flag("two push-pull drivers", "check", [d.split(".")[0] for d, _ in drv], f"{net}: {drv}")
        # open-drain nets: need a pull-up to a powered rail
        od = defaultdict(list)
        for (ref, pad, net, info, powered, sup) in m.pinsat:
            if info["kind"] in ("OD", "IOD"):
                od[net].append(f"{ref}.{pad}")
        for net, l in od.items():
            if V[net] < 1.0:
                flag("open drain without pull-up", "check", [x.split(".")[0] for x in l], f"{net}: {l}")
    # FET / BJT stress
    for ref, p in LIVE.items():
        if ref.startswith("Q"):
            pins = p["pins"]
            if p["value"] in ("2N7002K", "AO3400A", "BSS138"):
                g, s, d = (V[pins[x]] for x in "123")
                vgs, vds = {"2N7002K": (20, 60), "AO3400A": (12, 30), "BSS138": (20, 50)}[p["value"]]
            elif p["value"].startswith("BSC"):
                g, s, d = V[pins["4"]], V[pins["1"]], V[pins["5"]]
                vgs, vds = 20, 40
            else:
                b, e, c = V[pins["1"]], V[pins["2"]], V[pins["3"]]
                if b - e > 5 or e - c > 40:
                    flag("BJT stress", "check", [ref], f"[{m.name}] {ref} VBE(rev) {b - e:.1f} V, VEC {e - c:.1f} V")
                continue
            if abs(g - s) > vgs or d - s > vds:
                flag("FET stress", "check", [ref], f"[{m.name}] {ref} Vgs {g - s:.1f} V (max {vgs}), Vds {d - s:.1f} V "
                     f"(max {vds})")
    # passives
    for ref, p in LIVE.items():
        pre = re.match(r"[A-Z]+", ref).group(0)
        pins = p["pins"]
        if pre == "C" and len(pins) == 2:
            vr = rated_volt(ref)
            dv = abs(V[pins["1"]] - V[pins["2"]])
            if vr is None:
                flag("cap rating unknown", "info", [ref], f"{ref} {p['value']} {p['lcsc']}")
            elif dv * 1.5 > vr + 1e-6:
                flag("cap < 1.5x", "check", [ref], f"[{m.name}] {ref} {p['value']} rated {vr:g} V across "
                     f"{pins['1']}/{pins['2']} = {dv:.2f} V (1.5x = {1.5 * dv:.1f} V)")
            if p["fp"] in (design.CPOLY, design.CPOLY10) and V[pins["1"]] < V[pins["2"]] - 0.3:
                flag("polarity", "check", [ref], f"[{m.name}] {ref} + on {pins['1']} {V[pins['1']]:.2f} V below - "
                     f"{pins['2']} {V[pins['2']]:.2f} V")
        if pre in ("R", "RT", "RN"):
            pr = rated_power(ref)
            pairs = [("1", "2")] if len(pins) == 2 else [(str(k), str(9 - k)) for k in range(1, 5)] if pre == "RN" \
                else [("1", "2") if p["fp"] == design.SHUNT else ("1", "4")]
            for a, b in pairs:
                if a not in pins or b not in pins:
                    continue
                r = rval(ref)
                if r < 0.5:
                    continue
                pw = (V[pins[a]] - V[pins[b]]) ** 2 / r
                if pr and pw > pr:
                    flag("resistor power", "check", [ref], f"[{m.name}] {ref} {p['value']}: {pw * 1e3:.0f} mW > "
                         f"{pr * 1e3:.0f} mW ({pins[a]} {V[pins[a]]:.2f} V / {pins[b]} {V[pins[b]]:.2f} V)")
    # diodes: conduction state in the static solution (TVS/zener/clamp diodes should be off)
    for (ref, a, k, vf, vbr) in m.diodes:
        if ref.endswith(".body"):
            if m.dstate[ref][0]:
                flag("FET body diode conducts", "check", [ref.split(".")[0]], f"[{m.name}] {ref}: {a} {V[a]:.2f} V -> "
                     f"{k} {V[k]:.2f} V")
            continue
        base = re.match(r"[A-Z]+\d+", ref).group(0)
        fwd, rev = m.dstate[ref]
        val = PARTS[base]["value"]
        if (fwd or rev) and val not in ("LED red",) and not ref.endswith(".clamp"):
            flag("diode conducts (static)", "check", [base], f"[{m.name}] {ref} {val}: anode {a} {V[a]:.2f} V, "
                 f"cathode {k} {V[k]:.2f} V, {'forward' if fwd else 'reverse breakdown'}")
        if val == "LED red" and not fwd and m.name == "all_on":
            flag("LED reverse/off", "check", [base], f"{ref}: anode {a} {V[a]:.2f} V, cathode {k} {V[k]:.2f} V")
    return V


def short_to_gnd_power(V):
    """series/pull resistors on nets that leave the board: P if the connector pin is shorted to GND."""
    ext = set()
    for ref, p in LIVE.items():
        if ref.startswith("J"):
            for pad, net in p["pins"].items():
                if net not in RAILS:
                    ext.add(net)
    for ref, p in LIVE.items():
        if not ref.startswith("R") or ref.startswith("RN") or len(p["pins"]) != 2:
            continue
        a, b = p["pins"]["1"], p["pins"]["2"]
        r, pr = rval(ref), rated_power(ref)
        for x, y in ((a, b), (b, a)):
            if x in ext and y in RAILS and RAILS[y][0] > 0 and pr:
                pw = RAILS[y][0] ** 2 / r
                if pw > pr:
                    flag("resistor power (ext short)", "check", [ref], f"{ref} {p['value']} from {y} to connector net {x}: "
                         f"{pw * 1e3:.0f} mW > {pr * 1e3:.0f} mW if {x} is shorted to GND")


# ------------------------------------------------------------------------------------------- claims
def R(ref):
    return rval(ref)


def C(ref):
    return num(PARTS[ref]["value"])


def par(a, b):
    return a * b / (a + b)


CLAIMS = [   # (text in design.py, computed, unit, claimed, tolerance)
    ("TPS16630 UVLO 68k/10k = 9.36 V", lambda: 1.2 * (1 + R("R80") / R("R81")), 9.36, 0.01),
    ("TPS16630 OVP 150k/10k = 19.2 V", lambda: 1.2 * (1 + R("R82") / R("R83")), 19.2, 0.01),
    ("Jetson I_OL 18/R_ILIM = 3.53 A (5.1k)", lambda: 18 / (R("R84") / 1e3), 3.53, 0.01),
    ("spare I_OL = 3.83 A (4.7k)", lambda: 18 / (R("R184") / 1e3), 3.83, 0.01),
    ("IMON 27.9 uA/A into 10k = 0.279 V/A", lambda: 27.9e-6 * R("R85"), 0.279, 0.01),
    ("IMON 8.9 A full scale at 2.5 V", lambda: 2.5 / (27.9e-6 * R("R85")), 8.9, 0.02),
    ("LM61495 414 kHz from RT 39k (16.4/(RT+0.633))", lambda: 16.4 / (R("R406") / 1e3 + 0.633) * 1e3, 414, 0.01),
    ("LM61495 EN 100k/22k starts at 7.0 V (EN 1.263 V)", lambda: 1.263 * (1 + R("R404") / R("R405")), 7.0, 0.01),
    ("5.17 V body buck 100k/24k (FB 1.0 V)", lambda: 1.0 * (1 + R("R401") / R("R402")), 5.17, 0.01),
    ("servo 100k/20.0k = 6.000 V", lambda: 1.0 * (1 + R("R601") / R("R602")), 6.0, 0.001),
    ("servo +71.5k = 7.399 V", lambda: 1.0 * (1 + R("R601") / par(R("R602"), R("R609"))), 7.399, 0.001),
    ("LM5069 UVLO on 11.58 V (2.5 V, 21 uA hyst)", lambda: 2.5 * (1 + R("R301") / R("R302")) + 21e-6 * R("R301"),
     11.58, 0.01),
    ("LM5069 UVLO off 10.58 V", lambda: 2.5 * (1 + R("R301") / R("R302")), 10.58, 0.01),
    ("LM5069 OVLO 19.94 V off", lambda: 2.5 * (1 + R("R303") / R("R304")), 19.94, 0.01),
    ("LM5069 C_TIMER 22 nF = 1.04 ms (85 uA to 4 V, SNVS452G 9.3)", lambda: C("C302") * 4.0 / 85e-6 * 1e3, 1.04, 0.02),
    ("LM5069 R_PWR 8.45k = 17 W (R_PWR = 1.3e5 RS (P - 1.18 mV VDS/RS), VDS 16.8 V; lm5069 json eq.10)",
     lambda: R("R305") / (1.3e5 * R("R3")) + 1.18e-3 * 16.8 / R("R3"), 17, 0.01),
    ("brake on 17.67 V", lambda: 2.495 * (R("R57") + par(R("R58"), R("R59"))) / par(R("R58"), R("R59")), 17.67, 0.005),
    ("brake off 17.18 V (BRK_G 12 V)", lambda: (lambda s: s + R("R57") * (s / R("R58") - (12 - s) / R("R59")))(2.495),
     17.18, 0.005),
    ("OVLO +5V 40.2k/10k = 6.02 V", lambda: 1.2 * (1 + R("R162") / R("R163")), 6.02, 0.005),
    ("OVLO 3V3 23.2k/10k = 3.98 V", lambda: 1.2 * (1 + R("R164") / R("R165")), 3.98, 0.005),
    ("OVLO servo 61.9k/10k = 8.63 V", lambda: 1.2 * (1 + R("R166") / R("R167")), 8.63, 0.005),
    ("TPS62826 115k/25.5k = 3.306 V", lambda: 0.6 * (1 + R("R311") / R("R312")), 3.306, 0.002),
    ("DRV8243 1.5k = 0.489 V/A (A_IPROPI 3070)", lambda: R("R1101") / 3070, 0.489, 0.005),
    ("ITRIP 2.41 A (8.25k, LVL2 1.18 V)", lambda: 1.18 / (R("R1101") / 3070), 2.41, 0.01),
    ("ITRIP 4.05 A (8.25k+13.7k, LVL3 1.98 V)", lambda: 1.98 / (R("R1101") / 3070), 4.05, 0.01),
    ("ITRIP 4.73 A (R11 out, LVL4 2.31 V)", lambda: 2.31 / (R("R1101") / 3070), 4.73, 0.01),
    ("ITRIP ladder in LVL2 band 7.4-9.0k", lambda: R("R1107"), 8.2e3, 0.1),
    ("ITRIP ladder in LVL3 band 19.8-24.2k", lambda: R("R1107") + R("R1108"), 22e3, 0.1),
    ("ITRIP ladder in LVL4 band 42.3-51.7k", lambda: R("R1107") + R("R1108") + R("R1109"), 47e3, 0.1),
    ("TPS2121 OV2 45.3k/10k 5.6-6.1 V (VREF 1.06)", lambda: 1.06 * (1 + R("R324") / R("R325")), 5.86, 0.05),
    ("TPS2121 ILM 80.6k = 1.5 A (table 80k -> 1.5 A)", lambda: 1.5 * 80e3 / R("R326"), 1.5, 0.02),
    ("USB VBUS detect 22k/33k = 3.15 V at 5.25 V", lambda: 5.25 * R("R151") / (R("R150") + R("R151")), 3.15, 0.005),
    ("E-stop 100k/2.2uF ~0.29 s to the 132 VT- (0.9 V)", lambda: R("R18") * C("C18") * math.log(3.3 / 0.9), 0.29, 0.05),
    ("eFuse ToF 6.65k -> 0.5 A", lambda: 3334 / R("R701"), 0.5, 0.01),
    ("eFuse spare 5 V 1.65k -> 2 A", lambda: 3334 / R("R861"), 2.02, 0.01),
    ("eFuse Pi USB-C 887 -> 3.76 A (fixes P-6)", lambda: 3334 / R("R871"), 3.76, 0.01),
    ("design.py EFUSES comment 'Pi USB-C (3.3 A, 1k 1 %)'", lambda: 3334 / R("R871"), 3.3, 0.02),
    ("eFuse lidar 4.42k -> 0.75 A", lambda: 3334 / R("R801"), 0.75, 0.01),
    ("eFuse servo 549 -> 6.07 A", lambda: 3334 / R("R831"), 6.07, 0.005),
    ("U87 EN 100k/100k from +5V17 = 2.6 V", lambda: 5.17 * R("R878") / (R("R878") + R("R879")), 2.6, 0.01),
    ("xArm R_ILIM 300 -> 4.98 A (table 6.5 p.9)", lambda: {300: 4.98, 182: 8.13}.get(round(R("R881"))), 4.98, 0.001),
    ("xArm ITIMER 4.7 nF -> 2.2 ms (C x 0.98 V / 2.1 uA)", lambda: C("C883") * 0.98 / 2.1e-6 * 1e3, 2.2, 0.02),
    ("xArm ITIMER 1.2 ms min (0.7 V / 2.8 uA)", lambda: C("C883") * 0.7 / 2.8e-6 * 1e3, 1.2, 0.05),
    ("xArm ITIMER 4.4 ms max (1.3 V / 1.4 uA)", lambda: C("C883") * 1.3 / 1.4e-6 * 1e3, 4.4, 0.02),
    ("xArm dVdt 3.3 nF -> 1.4 V/ms (4600/C[pF])", lambda: 4600 / (C("C884") * 1e12), 1.4, 0.02),
    ("xArm IMON 246 uA/A into 1k -> 1.23 V at 5 A", lambda: 246e-6 * R("R882") * 5, 1.23, 0.005),
    ("xArm EN 3.3 V x 100k/110k (rec max 6 V)", lambda: 3.3 * R("R885") / (R("R884") + R("R885")), 3.0, 0.01),
    ("TLV6700 200k/9.53k = 8.79 V (0.400 V)", lambda: 0.4 * (1 + R("R961") / R("R962")), 8.79, 0.002),
    ("Rp 10k to 5 V advertises 3.0 A (USB-C: 10k +-5 % = 3.0 A at 5 V)", lambda: R("R531"), 10e3, 0.001),
    ("J53 header comment '56k Rp on CC1/CC2'", lambda: R("R531"), 56e3, 0.01),
]


def check_claims():
    out = []
    for text, f, claimed, tol in CLAIMS:
        try:
            v = f()
        except (KeyError, TypeError, ZeroDivisionError):
            v = None
        if v is None or claimed is None:
            out.append((text, None, claimed, "not computed"))
            continue
        ok = abs(v - claimed) <= tol * abs(claimed) + 1e-9
        out.append((text, v, claimed, "ok" if ok else "MISMATCH"))
        if not ok:
            flag("claim", "check", [], f"{text}: computed {v:.4g}, claimed {claimed:g}")
    src = (GEN / "design.py").read_text()
    found = sorted(set(re.findall(r"(?:=|->|→)\s*~?([\d.]+\s*(?:V|A|ms|kHz|W|V/A|V/ms|mA|uA/A|s))\b", src)))
    return out, found


# ------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", help="write the report as markdown")
    ap.add_argument("--net", help="print one net in every scenario")
    a = ap.parse_args()
    check_single_pin()
    sols = {}
    for s in SCENARIOS:
        m = Model(s)
        sols[s] = (m, check_scenario(m))
    short_to_gnd_power(sols["all_on"][1])
    claims, found = check_claims()
    if a.net:
        for s, (m, V) in sols.items():
            print(f"{s:12} {a.net} = {V[a.net]:.3f} V")
        return
    lines = [f"# audit.py report ({len(design.PARTS)} parts, {len(NETS)} nets, {len(SCENARIOS)} scenarios)", ""]
    lines.append("## Scenarios")
    for s, (m, V) in sols.items():
        off = [d for d, on in m.on.items() if not on]
        lines.append(f"- `{s}`: {m.note}. Domains off: {', '.join(sorted(off)) or '-'}")
    lines.append("")
    by = defaultdict(list)
    seen = {}
    for f in FLAGS:
        m_ = re.match(r"^\[(\w+)\] (.*)$", f["msg"], re.S)
        sc, body = (m_.group(1), m_.group(2)) if m_ else ("", f["msg"])
        key = (f["check"], body)
        if key in seen:
            seen[key]["scen"].append(sc)
            continue
        seen[key] = dict(f, msg=body, scen=[sc] if sc else [])
        by[f["check"]].append(seen[key])
    lines.append("## Flags")
    for c, l in by.items():
        lines.append(f"### {c} ({len(l)})")
        for f in l:
            lines.append(f"- {f['msg']}" + (f" [{', '.join(f['scen'])}]" if f["scen"] else ""))
        lines.append("")
    lines.append("## Claims recomputed")
    lines.append("| claim | computed | claimed | result |")
    lines.append("|---|---|---|---|")
    for t, v, c, r in claims:
        lines.append(f"| {t} | {'' if v is None else f'{v:.4g}'} | {c} | {r} |")
    lines.append("")
    lines.append("## Numeric values written in design.py comments (for coverage)")
    lines.append(", ".join(found))
    lines.append("")
    lines.append("## Coverage")
    ics = sorted({p["value"] for r, p in LIVE.items() if r[0] == "U" or r.startswith("LED")})
    lines.append("- IC values with a pin table: " + ", ".join(v for v in ics if v in PINS))
    lines.append("- IC values without one: " + (", ".join(v for v in ics if v not in PINS) or "none"))
    conn = [r for r in LIVE if r.startswith("J") and not ext_pins(r, PARTS[r])]
    lines.append("- connectors modelled as passive (power, switches, USB, SWD, CAN): " + ", ".join(sorted(conn)))
    lines.append("- nets set by FORCE (IC functions not solved): " + ", ".join(sorted(n for n in FORCE if n in NETS)))
    lines.append("")
    lines.append("## Key nets (all_on / pi_off / usb_only / servo_fail)")
    for n in ["ARM_EN_D", "ARM_OV_SNS", "ARM_SIG_B", "ARM_SIG", "ARM_UART_M", "MOT_BUS_OFF", "MOT_UVLO", "LM_EN",
              "HOLD_Z", "BRK_G", "BRK_SENSE", "VMOT_SENSE", "USB_PI_EN", "OVLO_SERVO", "FB6", "EXP_RESET_N",
              "IPROPI_L_M", "ITRIP_SEL", "MCU_BOOT0", "GPIO15", "LIDAR1_RX", "TOF1_SDA", "I2C6_SDA",
              "MS_ITRIP", "ML_ITRIP", "JET_SHDN", "ARM_IMON", "BTN_ON"]:
        if n in NETS:
            vals = " / ".join(f"{sols[s][1][n]:.2f}" for s in ("all_on", "pi_off", "usb_only", "servo_fail"))
            lines.append(f"- {n}: {vals}")
    txt = "\n".join(lines)
    if a.md:
        Path(a.md).write_text(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
