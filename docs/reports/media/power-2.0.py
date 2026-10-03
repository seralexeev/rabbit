from html import escape

W, H = 1820, 890
out = []
def box(x, y, w, h, lines, fill="#f4f6fa", stroke="#3b4a63", bold_first=True, size=14):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
    ty = y + 22
    for i, t in enumerate(lines):
        weight = "700" if (i == 0 and bold_first) else "400"
        s = size if i == 0 else size - 2
        out.append(f'<text x="{x + w/2}" y="{ty}" text-anchor="middle" font-size="{s}" font-weight="{weight}">{escape(t)}</text>')
        ty += 18 if i == 0 else 16
def line(x1, y1, x2, y2, color="#c0392b", width=3, dash=None, arrow=True):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = ' marker-end="url(#arr)"' if arrow and not dash else (' marker-end="url(#arrc)"' if arrow else "")
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"{d}{m}/>')
def label(x, y, t, size=12, color="#333", anchor="start", weight="400"):
    out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{escape(t)}</text>')

out.append(f'<rect width="{W}" height="{H}" fill="white"/>')
label(30, 40, "Rabbit 2.0 power distribution (NEEWER PS099E on the V-mount plate)", 22, "#111", weight="700")
label(30, 64, "Battery-side currents at 13.2 V (empty pack). typ = driving/idle, peak = worst short spike. Measured today (Forge, 1–3 Oct) or datasheet where marked.", 13, "#555")

# battery chain
box(30, 100, 220, 110, ["NEEWER PS099E", "V-mount, 99 Wh, 4S Li-ion", "12.4–16.8 V (14.5 V nom.)", "plate: 14 A max, 100 W rated", "pass-through charging"], fill="#fff4e0", stroke="#c27c0e")
line(250, 155, 300, 155)
box(300, 110, 170, 90, ["Main switch", "Pololu Big HP #2813", "OFF ← Pi GPIO17", "+ fuse 15 A, TVS"], fill="#fdecea", stroke="#c0392b")
line(470, 155, 520, 155)
box(520, 110, 160, 90, ["Shunt 2 mΩ → INA ch1", "battery, 41 A range", "today 10 mΩ = 8.2 A cap!", "external, Kelvin"], fill="#fde7ef", stroke="#d81b60")
line(680, 155, 730, 155, arrow=False)
# bus
out.append('<line x1="730" y1="155" x2="730" y2="745" stroke="#c0392b" stroke-width="5"/>')
label(740, 140, "BAT+ bus 12.4–16.8 V", 13, "#c0392b", weight="700")

rows = [
    (190, "MOTORS", ["Fuse 10 A", "shunt 5 mΩ → ch3"], ["RoboClaw 2x30A", "6–34 V, direct from battery", "current limit 3 A/ch, max duty 0.71", "E-stop input S3 ← Pi"], ["2× Pololu 37D 70:1 12 V", "free 0.2 A, stall 5.5 A each", "+ encoders (to be wired)"],
     "typ 0.3–0.6 A · peak ≤ 4.5 A (limited)", "#fdecea"),
    (345, "STEERING", ["Fuse 7.5 A"], ["Pololu D36V50F6", "6 V, 5.5 A buck", "out → 10 mΩ ch2 → PCA9685 V+"], ["AGFRC A50BHL", "brushless HV servo 4.8–8.4 V", "16 kg·cm @ 6 V, stall 4.2 A"],
     "typ 0.02 A · peak 3 A (5.9 A @ 6 V measured)", "#eef3fb"),
    (500, "BRAIN", ["Fuse 5 A"], ["Pololu D36V50F12", "12 V buck, EN ← Pi GPIO25 (Q1)", "out → 10 mΩ ch4 → DC jack"], ["Jetson Orin Nano Super", "carrier input 9–20 V", "+ ZED 2i (USB, ~2 W)"],
     "typ 1.0 A · peak 1.8 A (module ≤ 15 W)", "#f3eefb"),
    (655, "BODY", ["Fuse 5 A"], ["Pololu D24V90F5 (owned)", "5 V, 4-8 A buck", "short thick leads to Pi"], ["Raspberry Pi 4 8 GB (5 V pins)", "+ RPLIDAR C1, ToF 3.3 V reg,", "fan; USB hub on its own fuse"],
     "typ 0.75 A · peak 1.3 A (5 V side 2–3.5 A)", "#eef7ee"),
]
for y, name, protect, conv, load, cur, fill in rows:
    label(722, y + 50, name, 14, "#111", anchor="end", weight="700")
    line(730, y + 45, 760, y + 45)
    box(760, y + 10, 140, 70, protect, fill="#fdecea", stroke="#c0392b", size=13)
    if conv:
        line(900, y + 45, 930, y + 45)
        box(930, y + 0, 250, 92, conv, fill=fill)
        line(1180, y + 45, 1210, y + 45)
    else:
        line(900, y + 45, 1210, y + 45)
    box(1210, y + 0, 260, 92, load, fill=fill)
    label(930, y + 112, cur, 12, "#c0392b", weight="700")

sense = "#d81b60"
box(1500, 75, 300, 785, ["INA4235 (TI INA4235EVM)", "I2C 0x41 → Pi I2C1, VS 3.3 V", "ALERT → Pi GPIO24 (latched)", "shunt range ±81.92 mV"], fill="#fff7fa", stroke=sense)
cells = [
    (160, ["ch1 BATTERY", "2 mΩ external Kelvin", "range 41.0 A, LSB 1.25 mA", "alert < 12.8 V, > 13 A"], (600, 110), None),
    (281, ["ch3 MOTORS", "5 mΩ external Kelvin", "range 16.4 A, LSB 1 mA", "alert > 8 A"], (830, 270), 318),
    (436, ["ch2 SERVO 6 V", "10 mΩ on the EVM pad", "range 8.19 A (as today)", "6 V side: sees servo sag"], (1200, 390), 473),
    (591, ["ch4 JETSON 12 V", "10 mΩ on the EVM pad", "range 8.19 A, LSB 1 mA", "alert < 11 V (buck limit)"], (1200, 545), 628),
    (748, ["Pi branch: not measured", "≈ ch1 minus the others", "Pi reports undervoltage", "itself (get_throttled)"], None, None),
]
for cy, lines, src, ry in cells:
    box(1515, cy, 270, 78, lines, fill="#fde7ef" if src else "#f4f4f4", stroke=sense if src else "#999999", size=12)
    if src and ry is None:
        x0, y0 = src
        out.append(f'<path d="M{x0},{y0} L{x0},95 L1490,95 L1490,{cy + 39} L1515,{cy + 39}" fill="none" stroke="{sense}" stroke-width="2" stroke-dasharray="2,3"/>')
    elif src:
        x0, y0 = src
        out.append(f'<path d="M{x0},{y0} L{x0},{ry} L1490,{ry} L1490,{cy + 39} L1515,{cy + 39}" fill="none" stroke="{sense}" stroke-width="2" stroke-dasharray="2,3"/>')
label(1500, 880, "Dotted: Kelvin sense pairs, AWG26 twisted", 12, sense)

# control lines from Pi
c = "#1565c0"
label(30, 300, "Control (Pi = body + safety)", 15, c, weight="700")
for i, t in enumerate([
    "• power button → Pi: long press = stop motors,",
    "  Jetson saves the map and halts, then Pi",
    "  halts and pulls the main switch OFF pin",
    "• Pi GPIO → Jetson buck EN: power-cycle a hung Jetson",
    "• Pi GPIO → RoboClaw S3 E-stop: hardware stop",
    "  independent of any software on the Jetson",
    "• Pi I2C1: INA4235 + PCA9685; INA ALERT → GPIO24:",
    "  12.8 V or overcurrent → stop, orderly shutdown",
    "• ground: star point at the fuse block, one return",
    "  per branch; motor return never through logic GND",
]):
    label(30, 326 + i * 19, t, 13, "#223")

label(30, 540, "Budget at the battery", 15, "#111", weight="700")
tbl = [("", "today", "2.0"), ("idle median", "21.6 W", "~31 W"), ("driving median", "29.7 W", "~38 W"),
       ("measured peak", "104 W / 7.6 A", "—"), ("worst-case sum", "—", "~10.4 A (137 W)"),
       ("runtime idle (89 Wh)", "~4.1 h", "~2.9 h"), ("runtime driving", "~3.0 h", "~2.3 h")]
for r, row in enumerate(tbl):
    for k, cell in enumerate(row):
        label(30 + [0, 200, 340][k], 566 + r * 21, cell, 13, "#111" if r else "#555", weight="700" if r == 0 else "400")
label(30, 730, "Plate limit 14 A: OK only with RoboClaw current limits.", 13, "#c0392b", weight="700")
label(30, 750, "Without them two stalled motors at 16.8 V draw ~15 A.", 13, "#c0392b")
label(30, 790, "Wire: AWG16 battery/motors, AWG18 ≤ 30 cm to Jetson,", 13, "#223")
label(30, 809, "AWG18 to Pi 5 V (Pi undervolts below 4.63 V).", 13, "#223")

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">'
       '<defs><marker id="arr" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="10" refX="11" refY="5" orient="auto"><path d="M0,0 L12,5 L0,10 z" fill="#c0392b"/></marker>'
       '<marker id="arrc" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#1565c0"/></marker></defs>'
       + "".join(out) + "</svg>")
open(__file__.replace(".py", ".svg"), "w").write(svg)
