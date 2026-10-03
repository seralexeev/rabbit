from html import escape

POWER, REG, GND = "#c0392b", "#e67e22", "#333333"
I2C, UART, USB, ETH, CSI = "#1565c0", "#2e7d32", "#7b1fa2", "#111111", "#00838f"
GPIO, PWM, ENC, SENSE = "#6d6d6d", "#ad1457", "#8d6e63", "#d81b60"


class Sheet:
    def __init__(self, w, h, title, subtitle):
        self.w, self.h, self.out = w, h, []
        self.out.append(f'<rect width="{w}" height="{h}" fill="white"/>')
        self.text(30, 40, title, 22, "#111", weight="700")
        self.text(30, 64, subtitle, 13, "#555")

    def text(self, x, y, t, size=12, color="#222", anchor="start", weight="400"):
        self.out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{escape(t)}</text>')

    def box(self, x, y, w, h, lines, fill="#f4f6fa", stroke="#3b4a63", size=13, align="middle"):
        self.out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        tx = x + w / 2 if align == "middle" else x + 10
        ty = y + 20
        for i, t in enumerate(lines):
            self.text(tx, ty, t, size if i == 0 else size - 2, "#111" if i == 0 else "#333", align, "700" if i == 0 else "400")
            ty += 18 if i == 0 else 15

    def path(self, points, color, width=2.0, dash=None, arrow=False):
        d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(points))
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        if arrow:
            extra += f' marker-end="url(#a{color[1:]})"'
        self.out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"{extra}/>')

    def tag(self, x, y, t, color, size=11, anchor="middle"):
        width = 6.3 * len(t) * size / 11 + 10
        left = x - width / 2 if anchor == "middle" else (x if anchor == "start" else x - width)
        self.out.append(f'<rect x="{left}" y="{y - size - 2}" width="{width}" height="{size + 7}" rx="3" fill="white" stroke="{color}" stroke-width="1"/>')
        self.text(left + width / 2, y + 1, t, size, color, "middle", "700")

    def legend(self, x, y, items):
        for i, (name, color, dash, width) in enumerate(items):
            yy = y + i * 19
            self.path([(x, yy - 4), (x + 38, yy - 4)], color, width, dash)
            self.text(x + 46, yy, name, 12, "#222")

    def save(self, path):
        colors = {POWER, REG, GND, I2C, UART, USB, ETH, CSI, GPIO, PWM, ENC, SENSE}
        markers = "".join(
            f'<marker id="a{c[1:]}" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="{c}"/></marker>'
            for c in colors
        )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" font-family="Helvetica, Arial, sans-serif">'
            f"<defs>{markers}</defs>" + "".join(self.out) + "</svg>"
        )
        open(path, "w").write(svg)


LEGEND = [
    ("battery bus 12.4-16.8 V", POWER, None, 5),
    ("regulated DC (12 / 6 / 5 / 3.3 V)", REG, None, 3),
    ("ground return to the star", GND, "6,3", 2),
    ("I2C", I2C, None, 2.5),
    ("UART (TTL 3.3 V)", UART, None, 2.5),
    ("USB", USB, None, 2.5),
    ("Ethernet 1000BASE-T", ETH, None, 2.5),
    ("CSI camera ribbon", CSI, None, 2.5),
    ("GPIO / discrete line", GPIO, "5,3", 2),
    ("servo PWM", PWM, None, 2),
    ("quadrature encoder", ENC, None, 2),
    ("INA Kelvin sense pair", SENSE, "2,3", 2),
]


def base(path):
    return __file__.replace("wiring-2.0.py", path)


def overview():
    s = Sheet(1900, 1240, "Rabbit 2.0 wiring overview: every device and link",
              "Body = Raspberry Pi 4 (motors, steering, power, safety, lidar, ToF, bumpers, rear camera, Forge, HUD, tunnel). Brain = Jetson Orin Nano (ZED, perception, localization, planning). Pins and terminals: wiring-2.0-signals.svg and wiring-2.0-power.svg.")
    s.legend(1560, 96, LEGEND)

    s.box(30, 100, 220, 80, ["NEEWER PS099E", "V-mount plate, 99 Wh 4S", "12.4-16.8 V, plate 14 A max"], "#fff4e0", "#c27c0e")
    s.box(30, 210, 220, 80, ["Main fuse 15 A + switch", "Pololu Big Pushbutton HP #2813", "TVS SMBJ20A on the output"], "#fdecea", POWER)
    s.box(30, 320, 220, 60, ["Shunt 2 mOhm (INA ch1)", "battery current, Kelvin"], "#fde7ef", SENSE)
    s.box(30, 410, 220, 150, ["Fuse block, 6-way ATO", "F1 10 A  motors", "F2 7.5 A servo 6 V", "F3 5 A   Jetson 12 V", "F4 5 A   body 5 V", "F5 2 A USB hub, F6 spare"], "#fdecea", POWER, 13, "start")
    s.path([(140, 180), (140, 210)], POWER, 5, arrow=True)
    s.path([(140, 290), (140, 320)], POWER, 5, arrow=True)
    s.path([(140, 380), (140, 410)], POWER, 5, arrow=True)

    s.box(330, 100, 240, 80, ["Pololu D24V90F5 (owned)", "5 V 9 A buck", "Pi, lidar, ToF 3.3 V reg, fan"], "#eef7ee", REG)
    s.box(330, 210, 240, 90, ["Pololu D36V50F12 (owned)", "12 V buck, EN <- Pi via MOSFET", "drops out below 13.3 V in", "out via INA ch4 (10 mOhm)"], "#f3eefb", REG)
    s.box(330, 330, 240, 80, ["Pololu D36V50F6 (owned)", "6 V 5.5 A buck", "out via INA ch2 (10 mOhm)"], "#eef3fb", REG)
    s.box(330, 440, 240, 60, ["PCA9685 (Adafruit, owned)", "I2C 0x40, ch0 = steering"], "#eef3fb", I2C)
    s.box(330, 530, 240, 60, ["AGFRC A50BHL servo", "6 V, 1000-2000 us, centre 1532"], "#eef3fb", PWM)
    s.box(330, 640, 240, 100, ["RoboClaw 2x30A (owned)", "B+ from F1 via 5 mOhm (ch3)", "packet serial 0x80, 115200", "S3 = E-stop, non-latching"], "#fdecea", POWER)
    s.box(330, 800, 240, 70, ["2x Pololu 37D 70:1 12 V", "64 CPR, 4480 counts/rev"], "#f6efe9", ENC)

    s.path([(250, 430), (270, 430), (270, 140), (330, 140)], POWER, 3, arrow=True)
    s.path([(250, 455), (285, 455), (285, 255), (330, 255)], POWER, 3, arrow=True)
    s.path([(250, 480), (300, 480), (300, 370), (330, 370)], POWER, 3, arrow=True)
    s.path([(250, 505), (315, 505), (315, 690), (330, 690)], POWER, 4, arrow=True)
    s.tag(315, 618, "5 mOhm ch3", SENSE)
    s.path([(450, 410), (450, 440)], REG, 3, arrow=True)
    s.path([(450, 500), (450, 530)], PWM, 2, arrow=True)
    s.path([(430, 740), (430, 800)], POWER, 3, arrow=True)
    s.path([(490, 800), (490, 740)], ENC, 2, arrow=True)
    s.tag(395, 775, "M1/M2 AWG18", POWER)
    s.tag(530, 775, "EN1/EN2", ENC)

    s.box(30, 610, 220, 170, ["INA4235EVM (TI, owned)", "I2C 0x41, 3.3 V from the Pi", "ch1 battery  2 mOhm ext.", "ch2 servo 6 V 10 mOhm", "ch3 motors   5 mOhm ext.", "ch4 Jetson 12 V 10 mOhm", "ALERT -> Pi GPIO24", "shunt range +-81.92 mV"], "#fde7ef", SENSE, 13, "start")
    s.path([(30, 350), (15, 350), (15, 640), (30, 640)], SENSE, 2, "2,3")
    s.path([(275, 618), (262, 618), (262, 660), (250, 660)], SENSE, 2, "2,3")

    s.box(900, 330, 360, 430, [
        "Raspberry Pi 4 Model B 8 GB (body)",
        "Raspberry Pi OS 64-bit, Docker",
        "NATS hub: JetStream, websocket 9222",
        "rabbit-roboclaw, -steering, -ina",
        "rabbit-safety 50 Hz, rabbit-power (host)",
        "rabbit-lidar, -tof, -video",
        "forge (Parquet + chDB on the flash drive)",
        "rabbit-web (nginx), tunnel",
        "chrony server, DS3231",
        "",
        "I2C1 400 kHz: PCA9685 0x40, INA 0x41,",
        "DS3231 0x68",
        "I2C3/4/5/6: one ToF each (0x29)",
        "UART0: RoboClaw   UART4: lidar",
        "UART5: Jetson debug console",
        "GPIO: E-stop, Jetson EN, switch OFF,",
        "button, LEDs, bumpers, INA ALERT",
    ], "#eef7ee", "#2e7d32", 15)

    s.path([(570, 140), (1000, 140), (1000, 330)], REG, 3, arrow=True)
    s.tag(790, 140, "5 V to GPIO pins 2/4 + 6/9, AWG18 <= 20 cm", REG)
    s.path([(570, 230), (1510, 230), (1510, 330)], REG, 3, arrow=True)
    s.tag(1180, 230, "12 V barrel 5.5/2.5 mm, AWG18 <= 30 cm", REG)

    s.path([(900, 700), (570, 700)], UART, 2.5, arrow=True)
    s.tag(735, 690, "UART0 TX/RX -> S1/S2", UART)
    s.path([(900, 728), (570, 728)], GPIO, 2, "5,3", arrow=True)
    s.tag(735, 744, "E-stop RUN (GPIO16) -> S3", GPIO)
    s.path([(900, 470), (570, 470)], I2C, 2.5, arrow=True)
    s.tag(735, 460, "I2C1", I2C)
    s.path([(900, 365), (760, 365), (760, 285), (570, 285)], GPIO, 2, "5,3", arrow=True)
    s.tag(830, 365, "Jetson EN (GPIO25)", GPIO)
    s.path([(900, 395), (720, 395), (720, 195), (260, 195), (260, 250), (250, 250)], GPIO, 2, "5,3", arrow=True)
    s.tag(800, 405, "switch OFF (GPIO17)", GPIO)
    s.path([(900, 745), (880, 745), (880, 790), (250, 790), (250, 780)], I2C, 2.5, arrow=True)
    s.tag(700, 790, "I2C1 + ALERT", I2C)

    s.box(1360, 330, 300, 190, [
        "Jetson Orin Nano Super 8 GB (brain)",
        "rabbit-zed, nav, planner, explore,",
        "rabbit-loc, telemetry, odom (EKF)",
        "NATS leaf -> Pi hub",
        "chrony client of the Pi",
        "DC jack J16: 9-20 V, 3.5 A max",
        "Wi-Fi card off (phase 5)",
    ], "#f3eefb", "#6a1b9a", 14)
    s.box(1360, 590, 300, 60, ["ZED 2i", "USB 3.0 Type-C, ~2 W"], "#f3eefb", USB)
    s.path([(1510, 590), (1510, 520)], USB, 2.5, arrow=True)
    s.tag(1510, 562, "USB 3", USB)
    s.path([(1260, 420), (1360, 420)], ETH, 3)
    s.tag(1310, 410, "Cat6 0.5 m", ETH)
    s.tag(1310, 440, "10.77.0.1 / .2", ETH)
    s.path([(1260, 490), (1360, 490)], UART, 2.5)
    s.tag(1310, 482, "UART5", UART)
    s.tag(1310, 508, "J14 3/4", UART)

    right = [
        (790, ["RPLIDAR C1 (on a mast)", "UART4 460800, 5 V, 0.8 A at start"], UART, "UART4"),
        (875, ["4x VL53L8CX (Pololu #3419)", "I2C3/4/5/6, 3.3 V own regulator"], I2C, "I2C3-6"),
        (960, ["Bumpers front / rear", "NC microswitches in series"], GPIO, "GPIO20/21"),
        (1045, ["Camera Module 3 Wide (rear)", "CSI, 15-pin 1 mm FFC 300 mm"], CSI, "CSI"),
        (1130, ["Pi Flash Drive 256 GB", "USB 3: boot, Forge, JetStream"], USB, "USB 3"),
    ]
    for i, (y, lines, color, label) in enumerate(right):
        s.box(1360, y, 300, 60, lines, "#f7f7f7", color)
        px = 1110 + i * 30
        dashed = color == GPIO
        s.path([(px, 760), (px, y + 30), (1360, y + 30)], color, 2 if dashed else 2.5, "5,3" if dashed else None, arrow=True)
        s.tag(1300, y + 30, label, color)

    s.box(1700, 640, 180, 80, ["USB 3 hub", "Waveshare 4U, 7-36 V in", "from F5 (2 A)"], "#f5eefa", USB)
    s.box(1700, 760, 180, 95, ["Alfa AWUS036ACM", "USB Wi-Fi, MT7612U", "2x RP-SMA outside", "5 GHz home Wi-Fi"], "#f5eefa", USB)
    s.box(1700, 890, 180, 64, ["RoboClaw micro-USB", "Motion Studio only"], "#f5eefa", USB)
    s.path([(1260, 680), (1700, 680)], USB, 2.5, arrow=True)
    s.tag(1560, 680, "USB 3 to the hub", USB)
    s.path([(1790, 720), (1790, 760)], USB, 2.5, arrow=True)
    s.path([(1870, 720), (1870, 890)], USB, 2, arrow=True)

    left = [
        (900, ["Power button (2-pole, lit)", "pole 1: switch A (on only)", "pole 2: GPIO26, LED: GPIO27"], GPIO, 930),
        (1000, ["DS3231 RTC (Adafruit #3013)", "CR1220, I2C1 0x68"], I2C, 960),
        (1085, ["Status LED GPIO19", "ToF 3.3 V regulator off: GPIO18"], GPIO, 990),
    ]
    for y, lines, color, px in left:
        h = 80 if len(lines) == 3 else 64
        s.box(30, y, 260, h, lines, "#f7f7f7", color)
        dashed = color == GPIO
        s.path([(290, y + h / 2), (px, y + h / 2), (px, 760)], color, 2 if dashed else 2.5, "5,3" if dashed else None)

    s.text(30, 1200, "Ground: one star at the fuse block negative bus, one return wire per branch. The Jetson and the Pi share ground only through their supply returns; Ethernet is transformer-isolated.", 13, "#c0392b", weight="700")
    s.text(30, 1222, "Never open the RoboClaw B- while its USB or UART is connected: motor current would return through the logic ground (Basicmicro datasheet).", 13, "#c0392b", weight="700")
    s.save(base("wiring-2.0-overview.svg"))


HEADER = [
    (1, "3V3", "3V3 -> PCA9685 VCC, DS3231 VIN, pull-ups", REG),
    (2, "5V", "5V IN <- D24V90F5 VOUT", REG),
    (3, "GPIO2", "I2C1 SDA -> PCA9685, INA4235, DS3231", I2C),
    (4, "5V", "5V IN <- D24V90F5 VOUT", REG),
    (5, "GPIO3", "I2C1 SCL -> PCA9685, INA4235, DS3231", I2C),
    (6, "GND", "GND <- D24V90F5 GND", GND),
    (7, "GPIO4", "I2C3 SDA -> ToF FL", I2C),
    (8, "GPIO14", "UART0 TX -> RoboClaw S1 (RX)", UART),
    (9, "GND", "GND <- D24V90F5 GND", GND),
    (10, "GPIO15", "UART0 RX <- RoboClaw S2 (TX)", UART),
    (11, "GPIO17", "SWITCH_OFF -> Pololu switch OFF", GPIO),
    (12, "GPIO18", "TOF_PWR_OFF -> Q2 gate", GPIO),
    (13, "GPIO27", "BTN_LED -> Q3 gate", GPIO),
    (14, "GND", "GND -> RoboClaw S1/S2/S3 header", GND),
    (15, "GPIO22", "I2C6 SDA -> ToF RR", I2C),
    (16, "GPIO23", "I2C6 SCL -> ToF RR", I2C),
    (17, "3V3", "3V3 -> INA4235EVM 3V3", REG),
    (18, "GPIO24", "INA_ALERT <- INA4235 ALERT", GPIO),
    (19, "GPIO10", "I2C5 SDA -> ToF RL", I2C),
    (20, "GND", "GND -> INA4235EVM GND", GND),
    (21, "GPIO9", "UART4 RX <- lidar TX", UART),
    (22, "GPIO25", "JETSON_OFF -> Q1 gate", GPIO),
    (23, "GPIO11", "I2C5 SCL -> ToF RL", I2C),
    (24, "GPIO8", "UART4 TX -> lidar RX", UART),
    (25, "GND", "GND -> lidar, rear ToF", GND),
    (26, "GPIO7", "I2C4 SCL -> ToF FR", I2C),
    (27, "GPIO0", "ID_SD: leave free (spare)", "#999999"),
    (28, "GPIO1", "ID_SC: leave free (spare)", "#999999"),
    (29, "GPIO5", "I2C3 SCL -> ToF FL", I2C),
    (30, "GND", "GND -> front ToF", GND),
    (31, "GPIO6", "I2C4 SDA -> ToF FR", I2C),
    (32, "GPIO12", "UART5 TX -> 1k -> Jetson J14-3", UART),
    (33, "GPIO13", "UART5 RX <- 1k <- Jetson J14-4", UART),
    (34, "GND", "GND -> Jetson J14-7", GND),
    (35, "GPIO19", "STATUS_LED -> 330R -> LED", GPIO),
    (36, "GPIO16", "ESTOP_RUN -> RoboClaw S3", GPIO),
    (37, "GPIO26", "POWER_BTN <- button pole 2", GPIO),
    (38, "GPIO20", "BUMPER_FRONT <- NC chain", GPIO),
    (39, "GND", "GND -> bumpers, button, LEDs", GND),
    (40, "GPIO21", "BUMPER_REAR <- NC chain", GPIO),
]


def device(s, x, y, w, title, rows, color, note=None, col=150):
    h = 30 + 17 * len(rows) + (17 * len(note) if note else 0) + 8
    s.out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="#fbfbfb" stroke="{color}" stroke-width="1.8"/>')
    s.text(x + 10, y + 20, title, 14, "#111", weight="700")
    yy = y + 40
    for left, right, c in rows:
        s.text(x + 10, yy, left, 12, "#111", weight="700")
        s.text(x + col, yy, right, 12, c)
        yy += 17
    for line in note or []:
        s.text(x + 10, yy, line, 11, "#666")
        yy += 17
    return y + h + 14


def signals():
    s = Sheet(2100, 1240, "Rabbit 2.0 signal wiring: Raspberry Pi 4 header and every device connector",
              "Net names match on both ends. GPIO numbers are BCM. All logic is 3.3 V. Pins with a boot default pull-down (GPIO9-27) carry the fail-safe outputs, so a booting or dead Pi means: E-stop on, Jetson on, switch on.")
    s.legend(30, 96, LEGEND[1:2] + LEGEND[2:5] + LEGEND[8:12])

    cx, top, step = 1050, 130, 27
    s.out.append(f'<rect x="{cx - 50}" y="{top - 18}" width="100" height="{20 * step + 10}" rx="6" fill="#2b2b2b"/>')
    s.text(cx, top - 26, "40-pin header (pin 1 at the SD-card end)", 13, "#111", "middle", "700")
    for pin, name, net, color in HEADER:
        row = (pin - 1) // 2
        y = top + row * step
        odd = pin % 2 == 1
        label = net if not name.startswith("GPIO") else (f"{net}  ({name})" if odd else f"({name})  {net}")
        px = cx - 22 if odd else cx + 22
        s.out.append(f'<circle cx="{px}" cy="{y}" r="9" fill="{color}" stroke="white" stroke-width="1.5"/>')
        s.text(px, y + 4, str(pin), 9, "white", "middle", "700")
        if odd:
            s.path([(px - 10, y), (cx - 70, y)], color, 2)
            s.text(cx - 76, y + 4, label, 12, color if color != GND else "#333", "end", "700")
        else:
            s.path([(px + 10, y), (cx + 70, y)], color, 2)
            s.text(cx + 76, y + 4, label, 12, color if color != GND else "#333", "start", "700")

    L, R, W = 30, 1460, 610
    y = 300
    y = device(s, L, y, W, "RoboClaw 2x30A: signal headers", [
        ("S1 (RX)", "<- pin 8  GPIO14  UART0 TX", UART),
        ("S2 (TX)", "-> pin 10 GPIO15  UART0 RX", UART),
        ("S3 (E-stop in)", "<- pin 36 GPIO16  ESTOP_RUN; 1 kOhm S3 -> GND at this header", GPIO),
        ("S header GND", "<- pin 14 GND (centre +5V pins: not connected)", GND),
        ("EN1 A / B", "<- left motor encoder yellow / white", ENC),
        ("EN2 A / B", "<- right motor encoder yellow / white", ENC),
        ("encoder + / -", "-> both encoders blue (Vcc 5 V) / green (GND)", ENC),
        ("micro-USB", "-> USB hub (Motion Studio, fallback port)", USB),
    ], POWER, ["Config: packet serial 115200, address 0x80; S3 = E-Stop (non-latching);",
               "M1/M2 max current 3 A, write to NVM; serial timeout 0.5 s (set by the node);",
               "duty capped on the host at 12 V / battery V (0.71 at 16.8 V)."])
    y = device(s, L, y, W, "PCA9685 16-ch servo board (Adafruit), I2C 0x40", [
        ("VCC", "<- pin 1  3V3", REG),
        ("GND", "<- pin 14 GND (shared with the S-header GND run)", GND),
        ("SDA / SCL", "<- pin 3 / pin 5  I2C1", I2C),
        ("OE", "leave open (on-board pull-down = outputs enabled)", GPIO),
        ("V+ terminal", "<- 6 V from INA ch2 IN- (AWG18)", REG),
        ("ch0 PWM / V+ / GND", "-> A50BHL servo signal / red / black", PWM),
    ], I2C)
    y = device(s, L, y, W, "INA4235EVM (TI), I2C 0x41", [
        ("J3 3V3 / GND", "<- pin 17 3V3 / pin 20 GND", REG),
        ("J3 SDA / SCL", "<- pin 3 / pin 5  I2C1", I2C),
        ("J3 ALERT", "-> pin 18 GPIO24 INA_ALERT (open drain, Pi pull-up on)", GPIO),
        ("SW1 / SW0", "A1 = GND, A0 = VS -> address 0x41 (as today)", GPIO),
        ("J6", "jumper 1-2: EN = 3V3", GPIO),
        ("ch1 IN+ / IN-", "<- Kelvin pair from the 2 mOhm battery shunt", SENSE),
        ("ch2 IN+ / IN-", "6 V current through on-board 10 mOhm (R pad)", SENSE),
        ("ch3 IN+ / IN-", "<- Kelvin pair from the 5 mOhm motor shunt", SENSE),
        ("ch4 IN+ / IN-", "12 V current through on-board 10 mOhm (R pad)", SENSE),
        ("J1/J5 GND", "-> star ground (thin wire, reference only)", GND),
    ], SENSE, ["Shunt pads take 2512 resistors (R12, R1, R13, R9: check which is which on", "the silkscreen). Terminals J1/J5 carry 10 A at most."])
    y = device(s, L, y, W, "DS3231 RTC (Adafruit #3013), I2C 0x68", [
        ("VIN / GND", "<- pin 1 3V3 / pin 9 GND", REG),
        ("SDA / SCL", "<- pin 3 / pin 5  I2C1", I2C),
    ], I2C, ["CR1220 cell. config.txt: dtoverlay=i2c-rtc,ds3231"])

    y2 = 300
    y2 = device(s, R, y2, W, "RPLIDAR C1 (5-pin cable from the kit)", [
        ("VCC 5V / GND", "<- 5 V rail (D24V90F5), 0.8 A at start / star", REG),
        ("TX", "-> pin 21 GPIO9  UART4 RX", UART),
        ("RX", "<- pin 24 GPIO8  UART4 TX", UART),
    ], UART, ["460800 baud, 3.3 V TTL; needs a start command (rabbit-lidar)."])
    y2 = device(s, R, y2, W, "4x VL53L8CX on Pololu #3419, one I2C bus each", [
        ("VIN / GND", "<- ToF 3.3 V regulator (not 5 V: I/O follows VIN)", REG),
        ("SPI/I2C", "-> GND on every board (selects I2C)", GND),
        ("FL  SDA / SCL", "<- pin 7 GPIO4 / pin 29 GPIO5  (I2C3)", I2C),
        ("FR  SDA / SCL", "<- pin 31 GPIO6 / pin 26 GPIO7  (I2C4)", I2C),
        ("RL  SDA / SCL", "<- pin 19 GPIO10 / pin 23 GPIO11  (I2C5)", I2C),
        ("RR  SDA / SCL", "<- pin 15 GPIO22 / pin 16 GPIO23  (I2C6)", I2C),
        ("LPn, INT, SYNC", "not connected (board defaults)", GPIO),
    ], I2C, ["All at 0x29. Twisted SDA+GND and SCL+GND, <= 40 cm.", "ToF 3.3 V regulator EN <- Q2 drain (GPIO18 high = all ToF off, power-cycle)."])
    y2 = device(s, R, y2, W, "Bumpers (Omron D2F-01L, 2 front + 2 rear)", [
        ("front", "COM -> GND, NC in series -> pin 38 GPIO20", GPIO),
        ("rear", "COM -> GND, NC in series -> pin 40 GPIO21", GPIO),
        ("each input", "4.7 kOhm to 3V3 + 100 nF to GND at the Pi", GPIO),
    ], GPIO, ["Rest = LOW. Pressed or broken wire = HIGH = stop."])
    y2 = device(s, R, y2, W, "Power button: 2-pole momentary, LED ring", [
        ("pole 1", "switch A <-> GND (press = ON only)", GPIO),
        ("pole 2", "pin 37 GPIO26 <-> GND; 10 kOhm to 3V3, 100 nF", GPIO),
        ("LED + / -", "<- 5 V (series R if not built in) / Q3 drain", GPIO),
        ("status LED", "pin 35 GPIO19 -> 330 Ohm -> LED -> GND", GPIO),
    ], GPIO)
    y2 = device(s, R, y2, W, "Pololu Big Pushbutton Power Switch HP #2813", [
        ("OFF", "<- pin 11 GPIO17 (gpio-poweroff pulses after halt)", GPIO),
        ("A", "<- button pole 1 (to GND)", GPIO),
        ("ON, CTRL", "not connected", GPIO),
    ], POWER)

    mx, my = 680, 700
    my = device(s, mx, my, 740, "MOSFET helpers (logic-level N-channel, e.g. 2N7000 / BSS138)", [
        ("Q1 Jetson", "gate <- pin 22 GPIO25 via 1k, 100k gate-GND; drain -> D36V50F12 EN", GPIO),
        ("Q2 ToF power", "gate <- pin 12 GPIO18 via 1k, 100k; drain -> ToF regulator EN", GPIO),
        ("Q3 button LED", "gate <- pin 13 GPIO27 via 1k, 100k; drain -> LED cathode", GPIO),
        ("sources", "-> GND", GND),
    ], GPIO, ["Regulator EN has a 100 kOhm pull-up to VIN, so the default is ON; GPIO high turns it off.",
              "Never drive EN straight from a GPIO: the pull-up to 16.8 V would feed the Pi pin."], col=130)
    my = device(s, mx, my, 740, "Jetson Orin Nano dev kit", [
        ("J14 pin 3 UART2_RXD", "<- 1k <- pin 32 GPIO12 UART5 TX (debug console, 115200)", UART),
        ("J14 pin 4 UART2_TXD", "-> 1k -> pin 33 GPIO13 UART5 RX", UART),
        ("J14 pin 7 GND", "<- pin 34 GND", GND),
        ("J15 RJ45", "<-> Pi RJ45, Cat6 0.5 m (10.77.0.2 / 10.77.0.1)", ETH),
        ("USB 3 Type-A", "-> ZED 2i (its USB 3 cable, screw-locked)", USB),
        ("J16 DC jack", "<- 12 V from INA ch4 IN-, 5.5/2.5 mm, centre +", REG),
        ("J3 RTC", "not fitted on the dev kit: optional SMD mod, CR1225", GND),
    ], "#6a1b9a", col=190)
    my = device(s, mx, my, 740, "Raspberry Pi 4 ports", [
        ("USB 3 port 1", "-> Raspberry Pi Flash Drive 256 GB (boot, Forge, JetStream)", USB),
        ("USB 3 port 2", "-> USB 3 hub upstream (Wi-Fi adapter, RoboClaw USB)", USB),
        ("CSI", "<- Camera Module 3 Wide, 15-pin 1 mm FFC 300 mm", CSI),
        ("RJ45", "<-> Jetson J15", ETH),
        ("USB-C power", "not used: never together with the 5 V pin feed", REG),
    ], "#2e7d32", col=130)
    s.text(680, my + 6, "config.txt: dtoverlay=disable-bt  dtoverlay=uart4  dtoverlay=uart5  dtparam=i2c_arm=on,i2c_arm_baudrate=400000", 12, "#111", weight="700")
    s.text(680, my + 24, "dtoverlay=i2c3,pins_4_5  dtoverlay=i2c4,pins_6_7  dtoverlay=i2c5,pins_10_11  dtoverlay=i2c6,pins_22_23  (baudrate=400000, try 1000000)", 12, "#111", weight="700")
    s.text(680, my + 42, "dtoverlay=i2c-rtc,ds3231  dtoverlay=gpio-poweroff,gpiopin=17  dtparam=watchdog=on  (systemd RuntimeWatchdogSec=15)", 12, "#111", weight="700")
    s.save(base("wiring-2.0-signals.svg"))


def power():
    s = Sheet(2000, 1200, "Rabbit 2.0 power wiring: terminals, fuses, shunts and wire gauges",
              "Positive side drawn; every branch has its own return wire of the same gauge to the star ground (fuse block negative bus). Currents: typical / peak on the battery side unless marked.")
    s.legend(40, 420, [LEGEND[0], LEGEND[1], LEGEND[2], LEGEND[8], LEGEND[11]])

    s.box(30, 230, 210, 110, ["NEEWER PS099E", "on the V-mount plate", "12.4-16.8 V, 14 A max", "plate pigtail + / - AWG14"], "#fff4e0", "#c27c0e")
    s.box(280, 245, 130, 80, ["Main fuse", "15 A ATO", "inline holder"], "#fdecea", POWER)
    s.box(450, 220, 240, 130, ["Pololu Big Pushbutton", "Power Switch HP #2813", "VIN <- fuse, VOUT -> shunt", "GND <- star", "OFF <- Pi GPIO17, A <- button", "TVS SMBJ20A VOUT-GND"], "#fdecea", POWER)
    s.box(730, 245, 170, 80, ["Shunt 2 mOhm", "INA ch1 BATTERY", ">= 1 W, Kelvin taps"], "#fde7ef", SENSE)
    s.path([(240, 285), (280, 285)], POWER, 5, arrow=True)
    s.tag(260, 270, "XT60", POWER)
    s.path([(410, 285), (450, 285)], POWER, 5, arrow=True)
    s.path([(690, 285), (730, 285)], POWER, 5, arrow=True)
    s.path([(900, 285), (960, 285)], POWER, 5, arrow=True)
    s.tag(930, 270, "AWG14", POWER)

    s.box(960, 100, 230, 620, [], "#fdecea", POWER)
    s.text(1075, 125, "Fuse block, 6-way ATO", 14, "#111", "middle", "700")
    s.text(1075, 143, "with negative bus (Blue Sea 5025)", 12, "#333", "middle")
    s.text(1075, 690, "negative bus = STAR GROUND", 13, "#c0392b", "middle", "700")
    s.text(1075, 706, "all returns end here", 12, "#333", "middle")
    s.text(975, 300, "BAT+ in", 12, "#c0392b", weight="700")

    rows = [
        (180, "F1 10 A", "MOTORS"),
        (300, "F2 7.5 A", "SERVO"),
        (420, "F3 5 A", "BRAIN"),
        (540, "F4 5 A", "BODY 5 V"),
        (630, "F5 2 A", "USB HUB"),
    ]
    for y, fuse, name in rows:
        s.text(1180, y - 8, fuse, 13, "#111", "end", "700")
        s.text(1180, y + 10, name, 11, "#555", "end")
    s.text(1180, 662, "F6 spare (4G / arm)", 11, "#555", "end")

    s.path([(1190, 180), (1240, 180)], POWER, 4, arrow=True)
    s.box(1240, 150, 140, 60, ["Shunt 5 mOhm", "INA ch3 MOTORS"], "#fde7ef", SENSE)
    s.path([(1380, 180), (1420, 180)], POWER, 4, arrow=True)
    s.box(1420, 120, 270, 120, ["RoboClaw 2x30A", "B+ / B- screw terminals, AWG16 <= 25 cm", "1000 uF 35 V low-ESR across B+/B-", "limit 3 A/ch, duty <= 12 V / Vbat", "typ 0.3-0.6 A, peak <= 6.5 A"], "#fdecea", POWER)
    s.path([(1690, 180), (1730, 180)], POWER, 3, arrow=True)
    s.box(1730, 120, 240, 120, ["2x Pololu 37D 70:1 12 V", "M1A/M1B -> left (red/black)", "M2A/M2B -> right, reversed", "AWG18, twisted pairs", "stall 5.5 A at 12 V each"], "#f6efe9", ENC)

    s.path([(1190, 300), (1240, 300)], POWER, 3, arrow=True)
    s.box(1240, 265, 160, 70, ["D36V50F6 (owned)", "6 V 5.5 A, EN open"], "#eef3fb", REG)
    s.path([(1400, 300), (1730, 300)], REG, 3, arrow=True)
    s.tag(1565, 300, "6 V via EVM ch2 (10 mOhm), AWG18", SENSE)
    s.box(1730, 265, 240, 70, ["PCA9685 V+ terminal", "-> A50BHL, typ 0.02 A, peak 5.9 A @ 6 V"], "#eef3fb", REG)

    s.path([(1190, 420), (1240, 420)], POWER, 3, arrow=True)
    s.box(1240, 380, 160, 80, ["D36V50F12 (owned)", "12 V, EN <- Q1 (Pi)", "dropout < 13.3 V in"], "#f3eefb", REG)
    s.path([(1400, 420), (1730, 420)], REG, 3, arrow=True)
    s.tag(1565, 420, "12 V via EVM ch4 (10 mOhm), AWG18 <= 30 cm", SENSE)
    s.box(1730, 380, 240, 80, ["Jetson J16 DC jack", "5.5/2.5 mm, centre +, 9-20 V", "typ 1.0 A, peak 1.8 A"], "#f3eefb", REG)

    s.path([(1190, 540), (1240, 540)], POWER, 3, arrow=True)
    s.box(1240, 500, 160, 80, ["D24V90F5 (owned)", "5 V, 4-8 A", "in 5-38 V"], "#eef7ee", REG)
    s.path([(1400, 540), (1440, 540)], REG, 3, arrow=True)
    s.box(1440, 480, 530, 130, [
        "5 V distribution (terminal strip next to the Pi)",
        "Pi pins 2+4 (+) and 6+9 (-): two AWG20 pairs <= 20 cm, 2.54 mm crimp housings",
        "RPLIDAR C1: 5 V, 0.8 A at start, 0.26 A running",
        "ToF 3.3 V regulator (~1 A, EN <- Q2) -> 4x VL53L8CX VIN, ~0.1-0.15 A each",
        "Pi fan 5 V (always on), button LED ring 5 V",
        "total 5 V side: typ 2 A, peak 3.5 A",
    ], "#eef7ee", REG, 13, "start")

    s.path([(1190, 630), (1440, 630), (1440, 650)], POWER, 2.5, arrow=True)
    s.box(1440, 650, 530, 64, ["Waveshare USB3.2-Gen1-HUB-4U, 7-36 V terminal (AWG20)", "-> Alfa AWUS036ACM, RoboClaw micro-USB; upstream USB 3 to the Pi"], "#f5eefa", USB, 13, "start")

    s.box(30, 760, 640, 200, [
        "INA4235EVM (TI), I2C 0x41 on the Pi I2C1, 3.3 V from the Pi",
        "ch1 BATTERY   2 mOhm external Kelvin   range 41.0 A   CURRENT_LSB 1.25 mA",
        "ch2 SERVO 6 V 10 mOhm on the EVM pad   range 8.19 A   CURRENT_LSB 1 mA",
        "ch3 MOTORS    5 mOhm external Kelvin   range 16.4 A   CURRENT_LSB 1 mA",
        "ch4 JETSON 12 V 10 mOhm on the EVM pad range 8.19 A   CURRENT_LSB 1 mA",
        "shunt range +-81.92 mV (ADCRANGE 0), common mode -0.3..48 V: fine for 16.8 V",
        "bus voltage is read on each IN- pin (1.6 mV LSB)",
        "ALERT (open drain) -> Pi GPIO24: ch1 under 12.8 V, ch1 over 13 A,",
        "ch3 over 8 A, ch4 under 11 V; latched, the Pi reads FLAGS (0x22)",
        "EVM terminals J1/J5 carry 10 A max: ch1 and ch3 use external shunts",
        "Pi branch is not measured: about ch1 minus the others",
    ], "#fde7ef", SENSE, 13, "start")
    s.path([(815, 325), (815, 740), (560, 740), (560, 760)], SENSE, 2, "2,3")
    s.tag(815, 600, "ch1 sense pair", SENSE)
    s.path([(1310, 210), (1310, 236), (1225, 236), (1225, 745), (600, 745), (600, 760)], SENSE, 2, "2,3")
    s.tag(1225, 600, "ch3 sense pair", SENSE)

    s.box(700, 760, 1270, 320, [], "#ffffff", "#999999")
    s.text(715, 785, "Wires and connectors", 14, "#111", weight="700")
    table = [
        ("Segment", "Wire", "Connector", "Current"),
        ("plate -> fuse -> switch -> shunt -> fuse block", "AWG14 silicone", "XT60 at the plate, ferrules / ring lugs", "14 A plate limit"),
        ("F1 -> 5 mOhm -> RoboClaw B+/B-", "AWG16, <= 25 cm", "ferrules into the screw terminals", "10 A fuse"),
        ("RoboClaw -> motors", "AWG18 twisted pairs", "XT30 or JST-VH per motor", "5.5 A stall"),
        ("F2 -> 6 V buck -> EVM ch2 -> PCA9685 V+", "AWG18", "screw terminals", "7.5 A fuse"),
        ("F3 -> 12 V buck -> EVM ch4 -> Jetson J16", "AWG18, <= 30 cm", "5.5/2.5 mm barrel plug >= 5 A", "3.5 A jack max"),
        ("F4 -> 5 V buck -> Pi pins 2/4 + 6/9", "AWG18 in, 2x AWG20 out <= 20 cm", "2.54 mm crimp housings, 2 pins each", "5 A fuse"),
        ("5 V -> lidar, ToF regulator, fan", "AWG22", "JST-XH / lidar kit cable", "0.8 A start"),
        ("F5 -> USB hub terminal", "AWG20", "screw terminal", "2 A fuse"),
        ("Kelvin sense pairs to the EVM", "AWG26 twisted", "solder at the shunt pads' inner edges", "~0 A"),
        ("logic signals (I2C, UART, GPIO)", "AWG24-26", "Dupont / JST-XH, twisted with GND", "mA"),
    ]
    xs = [715, 1080, 1290, 1610]
    for r, row in enumerate(table):
        for k, cell in enumerate(row):
            s.text(xs[k], 810 + r * 22, cell, 12, "#111" if r else "#555", weight="700" if r == 0 else "400")
    s.text(715, 1062, "Silicone wire, single in free air (Cooner): AWG22 11 A, AWG18 20 A, AWG16 26 A at 105 C. Fuses protect the wire and the plate, not the electronics.", 12, "#555")

    s.text(30, 1110, "Grounding rules", 14, "#c0392b", weight="700")
    for i, t in enumerate([
        "Star point = fuse block negative bus. Each branch returns on its own wire; motor current never flows through the Pi, the EVM or a signal cable.",
        "Never fuse or switch a negative line, and never open the RoboClaw B- while its USB or UART is connected (Basicmicro datasheet: damage).",
        "Shunts are on the high side; the EVM GND is only a reference wire to the star. The Jetson and the Pi meet only at the star (Ethernet is isolated).",
    ]):
        s.text(30, 1132 + i * 20, t, 12, "#222")
    s.save(base("wiring-2.0-power.svg"))


if __name__ == "__main__":
    overview()
    signals()
    power()
