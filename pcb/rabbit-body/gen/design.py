"""Rabbit 2.0 body board: parts, nets and placement (the netlist source of truth).

Follows docs/reports/2026-10-03-architecture-2.0-wiring.md. Board frame: mm, origin at the deck centre,
+X = robot right, +Y = robot front, top view. `rot` is the KiCad footprint orientation in degrees.
`bom`: "smt" = JLCPCB assembly, "tht" = hand-soldered part supplied by JLCPCB/LCSC or the owner,
"module" = existing module mounted on the board, "none" = mechanical only.
"""

K = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/"

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
LED0603 = "LED_SMD:LED_0603_1608Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"

LCSC_R = {"100": "C22775", "220": "C22962", "330": "C23138", "1k": "C21190", "1.5k": "C22843", "4.7k": "C23162",
          "10k": "C25804", "100k": "C25803"}
LCSC_C = {"100nF": "C14663", "1uF": "C15849", "10nF": "C57112", "10uF": "C15850"}

PARTS = []


def part(ref, fp, value, at, rot=0, pins=None, bom="smt", lcsc=None, mpn=None, label=None):
    PARTS.append(dict(ref=ref, fp=fp, value=value, at=at, rot=rot, pins=pins or {}, bom=bom, lcsc=lcsc,
                      mpn=mpn or value, label=label))


def res(ref, value, at, a, b, rot=0):
    part(ref, R0603, value, at, rot, {"1": a, "2": b}, "smt", LCSC_R[value], f"0603 {value} 1%")


def cap(ref, value, at, a, b, rot=0, fp=C0603):
    part(ref, fp, value, at, rot, {"1": a, "2": b}, "smt", LCSC_C[value], f"{value} X7R/X5R")


def led(ref, at, anode, rot=0, lcsc="C12624"):
    part(ref, LED0603, "LED green", at, rot, {"1": "GND", "2": anode}, "smt", lcsc, "KT-0603G")


def mosfet(ref, at, gate, drain, rot=0):
    part(ref, SOT23, "AO3400A", at, rot, {"1": gate, "2": "GND", "3": drain}, "smt", "C20917", "AO3400A")


# ---------------------------------------------------------------- mechanical
for i, (x, y, d) in enumerate([(-38.0916, -121.8873, 4.3), (38.0916, -121.8873, 4.3), (-38.0916, 107.636, 4.3),
                               (38.0916, 107.636, 4.3), (-55.2597, 84.9505, 3.2), (55.2597, 84.9505, 3.2)]):
    fp = "MountingHole:MountingHole_4.3mm_M4" if d > 4 else "MountingHole:MountingHole_3.2mm_M3"
    part(f"H{i + 1}", fp, "deck standoff M4" if d > 4 else "deck standoff M3", (x, y), bom="none")

part("MOD1", "rabbit_body:RaspberryPi4_Standoffs", "Raspberry Pi 4", (13.0, -4.0), 0, bom="module",
     mpn="Raspberry Pi 4 Model B + 4x M2.5x6 standoffs")
part("U1", "rabbit_body:RoboClaw_2x30A", "RoboClaw 2x30A", (-29.9, -72.0), 180, bom="module",
     mpn="Basicmicro RoboClaw 2x30A + 4x M3x6 standoffs")

# ---------------------------------------------------------------- power input chain
part("J1", "Connector_AMASS:AMASS_XT60-M_1x02_P7.20mm_Vertical", "XT60 BAT", (50.0, -99.3), 270,
     {"1": "BAT_IN", "2": "GND"}, "tht", "C19268037", "AMASS XT60PB-M vertical", "BATTERY")
part("F1", "rabbit_body:Fuseholder_ATO_Keystone_3557x2", "ATO 15A", (50.0, -82.0), 90,
     {"1": "BAT_IN", "2": "BAT_FUSED"}, "tht", "C2680614", "2x Keystone 3557 + ATO 15A", "F1 MAIN 15A")
part("U2", "rabbit_body:Pololu_BigPushbutton_HP", "Pololu 2813", (47.9, -57.8), 0,
     {"VIN": "BAT_FUSED", "VOUT": "SW_OUT", "GND": "GND", "A": "BTN_ON", "OFF": "SW_OFF"}, "module",
     mpn="Pololu Big Pushbutton Power Switch HP #2813")
part("D1", "Diode_SMD:D_SMB", "SMBJ20A", (55.5, -40.0), 90, {"1": "SW_OUT", "2": "GND"}, "smt", "C151922", "SMBJ20A")
# switch input TVS (Pololu: TVS across the input against LC spikes); bidirectional so a reversed battery is
# blocked by the switch instead of blowing F1
part("D7", "Diode_SMD:D_SMB", "SMBJ20CA", (42.1, -82.2), 270, {"1": "BAT_FUSED", "2": "GND"}, "smt", "C151921",
     "SMBJ20CA")
part("R1", "rabbit_body:R_Shunt_2512_Kelvin", "2mR 3W", (45.6, -40.6), 180,
     {"1": "SW_OUT", "2": "VBUS", "3": "INA_IN1P", "4": "INA_IN1N"}, "smt", "C154685", "LR2512-23R002F4")

FUSES = [("F2", "ATO 10A", "MOT_FUSED", "F2 MOTORS 10A"), ("F3", "ATO 5A", "BODY_IN", "F3 BODY 5V 5A"),
         ("F4", "ATO 5A", "BRAIN_IN", "F4 JETSON 5A"), ("F5", "ATO 7.5A", "STEER_IN", "F5 SERVO 7.5A"),
         ("F6", "ATO 2A", "HUB_PWR", "F6 USB HUB 2A"), ("F7", "ATO (spare)", "RES_PWR", "F7 SPARE")]
for i, (ref, val, out, label) in enumerate(FUSES):
    part(ref, "rabbit_body:Fuseholder_ATO_Keystone_3557x2", val, (24.0, -103.0 + 10.0 * i), 180,
         {"1": "VBUS", "2": out}, "tht", "C2680614", f"2x Keystone 3557 + {val}", label)

# motor branch
part("R3", "rabbit_body:R_Shunt_2512_Kelvin", "5mR 3W", (8.6, -103.0), 180,
     {"1": "MOT_FUSED", "2": "MOT_BAT", "3": "INA_IN3P", "4": "INA_IN3N"}, "smt", "C154688", "LR2512-23R005F4")
part("C1", "Capacitor_THT:CP_Radial_D12.5mm_P5.00mm", "1000uF 35V", (-2.5, -119.0), 0,
     {"1": "MOT_BAT", "2": "GND_MOT"}, "tht", "C346962", "NXB 35V 1000uF 12.5x25 (or Panasonic EEU-FR1V102)")
part("J2", "rabbit_body:WirePads_2x_AWG14_P8.4mm", "RoboClaw B+/B-", (-30.0, -114.0), 0,
     {"1": "MOT_BAT", "2": "GND_MOT"}, "none", label=None)
part("NT1", "rabbit_body:NetTie_3.5mm", "star GND", (41.5, -106.5), 0, {"1": "GND_MOT", "2": "GND"}, "none")

# INA4235, channel 1 battery, 2 servo 6 V, 3 motors, 4 Jetson 12 V; address 0x41 (A1 = GND, A0 = VS)
part("U3", "rabbit_body:TI_DSBGA-16_YBJ_1.5x1.5mm_P0.4mm", "INA4235", (22.0, -41.5), 0,
     {"A1": "INA_IN2P", "A2": "INA_IN1N", "A3": "INA_IN1P", "A4": "+3V3_PI", "B1": "INA_IN2N", "B3": "+3V3_PI",
      "B4": "GND", "C1": "INA_IN3N", "C2": "+3V3_PI", "C3": "GND", "C4": "I2C1_SCL", "D1": "INA_IN3P",
      "D2": "INA_IN4N", "D3": "INA_IN4P", "D4": "I2C1_SDA"}, "smt", "C33440856", "INA4235AIYBJR")
cap("C2", "100nF", (24.6, -37.6), "+3V3_PI", "GND", 0)
res("R31", "10k", (18.0, -38.0), "INA_ALERT", "+3V3_PI", 0)

# ---------------------------------------------------------------- branch outputs
part("J19", "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical", "USB hub 7-36V", (5.0, -58.0), 0,
     {"1": "HUB_PWR", "2": "GND"}, "tht", "C158012", "JST B2B-XH-A", "USB HUB PWR")
part("J20", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal", "spare out",
     (4.0, -48.0), 0, {"1": "RES_PWR", "2": "GND"}, "tht", "C474952", "KF128-5.08-2P", "SPARE BAT OUT")

# 5 V body regulator (Pi, lidar, ToF LDO, fan)
part("U4", "rabbit_body:Pololu_D24V90F5", "D24V90F5", (-44.0, -4.0), 0,
     {"VIN": "BODY_IN", "VOUT": "+5V", "GND": "GND"}, "module", mpn="Pololu D24V90F5 #2866")
cap("C9", "10uF", (-28.5, 31.5), "+5V", "GND", 270, C0805)
cap("C13", "10uF", (-28.5, 27.2), "+3V3_PI", "GND", 90, C0805)
res("R36", "1k", (-31.7, 0.0), "+5V", "LED5_A", 90)
led("D2", (-31.7, 3.5), "LED5_A", 90)

# Jetson 12 V
part("U5", "rabbit_body:Pololu_D36V50Fx", "D36V50F12", (-17.0, 50.5), 0,
     {"VIN": "BRAIN_IN", "VOUT": "12V_RAW", "GND": "GND", "EN": "JET_EN"}, "module", mpn="Pololu D36V50F12 #4095")
part("R4", "rabbit_body:R_Shunt_2512_Kelvin", "10mR 2W", (-35.5, 47.0), 90,
     {"1": "12V_RAW", "2": "JET_12V", "3": "INA_IN4P", "4": "INA_IN4N"}, "smt", "C105366", "FMF25FPJR010-LH")
part("J21", "Connector_AMASS:AMASS_XT30PW-F_1x02_P2.50mm_Horizontal", "XT30 JETSON", (-27.5, 72.0), 90,
     {"1": "JET_12V", "2": "GND"}, "tht", "C2913282", "AMASS XT30PW-F", "JETSON 12V")
mosfet("Q1", (0.0, 44.0), "Q1_G", "JET_EN", 0)
res("R20", "1k", (0.0, 40.0), "GPIO25", "Q1_G", 0)
res("R21", "100k", (0.0, 48.0), "Q1_G", "GND", 0)
res("R38", "4.7k", (-38.6, 58.0), "JET_12V", "LED12_A", 90)
led("D4", (-38.6, 61.5), "LED12_A", 90)

# servo 6 V
part("U6", "rabbit_body:Pololu_D36V50Fx", "D36V50F6", (17.0, 50.5), 0,
     {"VIN": "STEER_IN", "VOUT": "6V_RAW", "GND": "GND"}, "module", mpn="Pololu D36V50F6 #4092")
part("R2", "rabbit_body:R_Shunt_2512_Kelvin", "10mR 2W", (35.5, 47.0), 90,
     {"1": "6V_RAW", "2": "SERVO_6V", "3": "INA_IN2P", "4": "INA_IN2N"}, "smt", "C105366", "FMF25FPJR010-LH")
res("R37", "1.5k", (38.6, 58.0), "SERVO_6V", "LED6_A", 90)
led("D3", (38.6, 61.5), "LED6_A", 90)

# ToF 3.3 V (TPS73733, EN pulled to 5 V, Q2 pulls it low when GPIO18 is high)
part("U7", "Package_TO_SOT_SMD:SOT-223-6", "TPS73733", (-6.0, 71.0), 0,
     {"1": "+5V", "2": "+3V3_TOF", "3": "GND", "4": "TPS_NR", "5": "TOF_EN", "6": "GND"}, "smt", "C31334", "TPS73733DCQR")
cap("C6", "10uF", (-12.5, 69.0), "+5V", "GND", 90, C0805)
cap("C7", "10uF", (0.5, 69.0), "+3V3_TOF", "GND", 90, C0805)
cap("C8", "10nF", (-10.0, 75.5), "TPS_NR", "GND", 0)
res("R26", "100k", (-10.0, 78.0), "TOF_EN", "+5V", 0)
mosfet("Q2", (-1.5, 77.0), "Q2_G", "TOF_EN", 0)
res("R22", "1k", (3.0, 76.0), "GPIO18", "Q2_G", 90)
res("R23", "100k", (-1.5, 80.6), "Q2_G", "GND", 0)
res("R40", "330", (5.0, 70.5), "+3V3_TOF", "LED33_A", 90)
led("D6", (5.0, 74.0), "LED33_A", 90)

# ---------------------------------------------------------------- Pi header (40-pin IDC, ribbon to the Pi)
PI_PINS = {1: "+3V3_PI", 2: "+5V", 3: "I2C1_SDA", 4: "+5V", 5: "I2C1_SCL", 6: "GND", 7: "TOF_FL_SDA", 8: "GPIO14",
           9: "GND", 10: "GPIO15", 11: "GPIO17", 12: "GPIO18", 13: "GPIO27", 14: "GND", 15: "TOF_RR_SDA",
           16: "TOF_RR_SCL", 17: "+3V3_PI", 18: "INA_ALERT", 19: "TOF_RL_SDA", 20: "GND", 21: "GPIO9", 22: "GPIO25",
           23: "TOF_RL_SCL", 24: "GPIO8", 25: "GND", 26: "TOF_FR_SCL", 29: "TOF_FL_SCL", 30: "GND",
           31: "TOF_FR_SDA", 32: "GPIO12", 33: "GPIO13", 34: "GND", 35: "GPIO19", 36: "GPIO16", 37: "POWER_BTN",
           38: "BUMPER_FRONT", 39: "GND", 40: "BUMPER_REAR"}
part("J3", "Connector_IDC:IDC-Header_2x20_P2.54mm_Vertical", "Pi 40-pin", (-21.13, 28.73), 90,
     {str(k): v for k, v in PI_PINS.items()}, "tht", "C48687632", "BH254V-40P box header", "RASPBERRY PI 40-PIN (ribbon)")

# UART / control series resistors, pulls
res("R10", "100", (-31.7, -20.0), "GPIO14", "RC_S1", 90)
res("R11", "100", (-31.7, -16.5), "RC_S2", "GPIO15", 90)
res("R16", "100", (-31.7, -13.0), "GPIO16", "ESTOP_A", 90)
res("R17", "100k", (-31.7, -9.5), "GPIO16", "GND", 90)
res("R18", "1k", (14.0, -38.0), "GPIO17", "SW_OFF", 0)
res("R19", "100k", (14.0, -40.0), "SW_OFF", "GND", 0)
res("R12", "100", (-23.0, 81.0), "GPIO8", "LIDAR_RX", 90)
res("R13", "100", (-21.0, 81.0), "LIDAR_TX", "GPIO9", 90)
res("R14", "1k", (-19.0, 81.0), "GPIO12", "JET_UART_RX", 90)
res("R15", "1k", (-17.0, 81.0), "JET_UART_TX", "GPIO13", 90)

# RoboClaw harness (2x5 to the RoboClaw S / EN headers) and the external E-stop loop
part("J4", "Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical", "RoboClaw I/O", (-50.0, -31.5), 90,
     {"1": "RC_S1", "2": "RC_S2", "3": "ESTOP_RC", "4": "GND", "5": "ENC1_A", "6": "ENC1_B", "7": "ENC2_A",
      "8": "ENC2_B", "9": "RC_5V", "10": "GND"}, "tht", "C225520", "2x5 2.54 pin header", "ROBOCLAW I/O")
part("J5", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", "E-stop loop", (-36.0, -31.5), 90,
     {"1": "ESTOP_A", "2": "ESTOP_RC"}, "tht", "C53055672", "1x2 header + jumper", "E-STOP")
part("J6", "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical", "ENC left", (-27.75, -129.5), 0,
     {"1": "RC_5V", "2": "GND", "3": "ENC1_A", "4": "ENC1_B"}, "tht", "C144395", "JST B4B-XH-A", "ENC L (M1)")
part("J7", "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical", "ENC right", (8.5, -129.5), 0,
     {"1": "RC_5V", "2": "GND", "3": "ENC2_A", "4": "ENC2_B"}, "tht", "C144395", "JST B4B-XH-A", "ENC R (M2)")

# ToF x4 (VL53L8CX on Pololu 3419): VIN, GND, SCL, GND, SDA
for ref, at, pre, label in (("J8", (-22.0, 129.0), "TOF_FL", "TOF FL"), ("J9", (14.0, 129.0), "TOF_FR", "TOF FR"),
                            ("J10", (-55.0, -114.5), "TOF_RL", "TOF RL"), ("J11", (23.5, -129.5), "TOF_RR", "TOF RR")):
    part(ref, "Connector_JST:JST_PH_B5B-PH-K_1x05_P2.00mm_Vertical", "ToF", at, 0,
         {"1": "+3V3_TOF", "2": "GND", "3": f"{pre}_SCL", "4": "GND", "5": f"{pre}_SDA"}, "tht", "C157993",
         "JST B5B-PH-K-S", label)

part("J12", "Connector_JST:JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical", "lidar C1", (-33.0, 95.0), 0,
     {"1": "+5V", "2": "GND", "3": "LIDAR_TX", "4": "LIDAR_RX"}, "tht", "C131334", "JST B4B-PH-K-S", "LIDAR 5V TX RX")
part("J13", "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical", "bumpers front", (-1.25, 129.0), 0,
     {"1": "BUMPER_FRONT", "2": "GND"}, "tht", "C158012", "JST B2B-XH-A", "BUMP F")
part("J14", "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical", "bumpers rear", (-9.0, -129.5), 0,
     {"1": "BUMPER_REAR", "2": "GND"}, "tht", "C158012", "JST B2B-XH-A", "BUMP R")
res("R29", "4.7k", (6.0, 121.0), "BUMPER_FRONT", "+3V3_PI", 0)
cap("C11", "100nF", (6.0, 123.0), "BUMPER_FRONT", "GND", 0)
res("R30", "4.7k", (-15.0, -124.0), "BUMPER_REAR", "+3V3_PI", 0)
cap("C12", "100nF", (-15.0, -126.0), "BUMPER_REAR", "GND", 0)

# power button (2-pole, lit), status LED, Pi fan, Jetson console
part("J15", "Connector_JST:JST_XH_B5B-XH-A_1x05_P2.50mm_Vertical", "button", (37.5, 90.0), 0,
     {"1": "BTN_ON", "2": "GND", "3": "POWER_BTN", "4": "+5V", "5": "BTN_LED_K"}, "tht", "C157991", "JST B5B-XH-A",
     "BUTTON")
res("R28", "10k", (30.0, 95.0), "POWER_BTN", "+3V3_PI", 0)
cap("C10", "100nF", (30.0, 97.0), "POWER_BTN", "GND", 0)
mosfet("Q3", (30.0, 87.5), "Q3_G", "BTN_LED_K", 0)
res("R24", "1k", (26.0, 87.5), "GPIO27", "Q3_G", 90)
res("R25", "100k", (30.0, 84.0), "Q3_G", "GND", 0)
part("J16", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", "status LED", (40.0, 98.0), 0,
     {"1": "STATUS_LED_A", "2": "GND"}, "tht", "C131337", "JST B2B-PH-K-S", "LED")
res("R27", "330", (34.0, 101.0), "GPIO19", "STATUS_LED_A", 0)
part("J17", "Connector_JST:JST_PH_B3B-PH-K_1x03_P2.00mm_Vertical", "Jetson UART", (-34.0, 87.5), 0,
     {"1": "JET_UART_RX", "2": "JET_UART_TX", "3": "GND"}, "tht", "C131339", "JST B3B-PH-K-S", "JETSON J14 3/4/7")
part("J18", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", "Pi fan 5V", (-52.0, 22.0), 0,
     {"1": "+5V", "2": "GND"}, "tht", "C131337", "JST B2B-PH-K-S", "FAN 5V")

# ---------------------------------------------------------------- PCA9685 + servo headers
pca = {str(i): "GND" for i in (1, 2, 3, 4, 5, 14, 23, 24, 25)}
pca.update({"6": "PCA_LED0", "7": "PCA_LED1", "8": "PCA_LED2", "9": "PCA_LED3", "26": "I2C1_SCL", "27": "I2C1_SDA",
            "28": "+3V3_PI"})
part("U8", "Package_SO:TSSOP-28_4.4x9.7mm_P0.65mm", "PCA9685PW", (8.0, 93.0), 0, pca, "smt", "C2678753", "PCA9685PW,118")
cap("C3", "100nF", (12.5, 99.0), "+3V3_PI", "GND", 0)
cap("C4", "10uF", (12.5, 87.0), "+3V3_PI", "GND", 0, C0805)
for i in range(4):
    res(f"R{32 + i}", "220", (-6.0 + 4.0 * i, 101.0), f"PCA_LED{i}", f"PWM{i}", 90)
    part(f"J{22 + i}", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", f"servo {i}",
         (-6.0 + 4.0 * i, 112.0), 0, {"1": f"PWM{i}", "2": "SERVO_6V", "3": "GND"}, "tht", "C49257",
         "1x3 2.54 pin header", "SERVO S0-S3" if i == 0 else None)
part("C14", "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm", "470uF 16V", (14.0, 108.0), 0,
     {"1": "SERVO_6V", "2": "GND"}, "tht", "C19270651", "470uF 16V polymer 8x12")

# ---------------------------------------------------------------- RTC
rtc = {str(i): "GND" for i in range(5, 14)}
rtc.update({"2": "+3V3_PI", "14": "RTC_VBAT", "15": "I2C1_SDA", "16": "I2C1_SCL"})
part("U9", "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm", "DS3231SN", (-14.0, 95.0), 0, rtc, "smt", "C9866", "DS3231SN#T&R")
cap("C5", "100nF", (-8.0, 89.0), "+3V3_PI", "GND", 0)
part("BT1", "Battery:BatteryHolder_Keystone_3001_1x12mm", "CR1220", (-22.0, 113.0), 0,
     {"1": "RTC_VBAT", "2": "GND"}, "tht", None, "Keystone 3001 holder (not at LCSC: Digi-Key or Mouser) + CR1220 cell")

# ---------------------------------------------------------------- test points, rail LED
for i, (net, at) in enumerate([("VBUS", (33.5, -43.5)), ("+5V", (-31.7, -5.5)), ("SERVO_6V", (35.5, 56.0)),
                               ("JET_12V", (-40.0, 52.5)), ("+3V3_TOF", (8.0, 66.0)), ("GND", (-1.0, -37.0)),
                               ("GND", (-8.0, 86.0)), ("INA_ALERT", (15.0, -35.0))]):
    part(f"TP{i + 1}", "TestPoint:TestPoint_THTPad_D1.5mm_Drill0.7mm", net, at, 0, {"1": net}, "none",
         label={"VBUS": "VBUS", "+5V": "5V", "SERVO_6V": "6V", "JET_12V": "12V", "+3V3_TOF": "3V3T", "GND": "GND", "INA_ALERT": "ALERT"}[net])
res("R39", "10k", (31.0, -40.0), "VBUS", "LEDB_A", 90)
led("D5", (31.0, -37.0), "LEDB_A", 270)


# label placement tweaks: ref -> (dx, dy, "top" | "bottom")
LABEL_POS = {"J4": (0.0, 0.0, "top"), "J5": (1.5, 0.0, "top"), "J22": (6.0, 0.0, "top"), "TP7": (0.0, 0.0, "bottom"), "F1": (0.0, 0.0, "right"),
             "J19": (0.0, 0.0, "bottom"), "J20": (0.0, 0.0, "top"), "J17": (0.0, 0.0, "top"),
             "J12": (0.0, 0.0, "top"), "J15": (0.0, 0.0, "top"), "J16": (0.0, 0.0, "top")}

# extra silkscreen text: (text, X, Y, size, layer "F"/"B")
SILK = [("RABBIT 2.0 BODY  rev A  2026-10", -30.0, -60.0, 1.6, "B"),
        ("4L 1.6 mm, 1 oz outer; deck of the Red Ackerman kit", -30.0, -64.0, 1.0, "B"),
        ("FRONT ^", 0.0, 120.0, 1.4, "F"),
        ("+", 44.0, -99.3, 1.4, "F"), ("-", 55.8, -106.5, 1.4, "F"),
        ("STAR GND", 41.0, -102.6, 1.0, "F")]


# cable passthrough cut in the board, aligned with the front-right slot of the kit plate (deck 2) under it:
# ZED USB 3 cable from deck 3 down to the Jetson on deck 1: 11.1 x 18 mm passes a moulded USB-A plug (~16 x 8);
# the kit slot it lines up with is 10.3 x 23.9
CUTOUTS = [[(21.5, 64.6), (32.6, 64.6), (32.6, 82.6), (21.5, 82.6)]]


def nets():
    s = set()
    for p in PARTS:
        s.update(p["pins"].values())
    return sorted(s)


# power nets laid out by hand (zones and wide tracks); the autorouter skips nothing but these get wide rules
POWER_HI = ["BAT_IN", "BAT_FUSED", "SW_OUT", "VBUS", "MOT_FUSED", "MOT_BAT", "GND_MOT"]
POWER_5V = ["+5V"]
POWER_MID = ["BRAIN_IN", "BODY_IN", "STEER_IN", "HUB_PWR", "RES_PWR", "12V_RAW", "JET_12V", "6V_RAW",
             "SERVO_6V", "+3V3_TOF"]
POWER_LO = ["+3V3_PI", "RC_5V"]
