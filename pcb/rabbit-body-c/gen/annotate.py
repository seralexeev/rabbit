"""Labelled views for the report: renders/top_labelled.png and renders/bottom_labelled.png from the kicad-cli renders
(run with any Python + matplotlib). The bottom render looks at the board from below, so its X axis is mirrored."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np

PRJ = Path(__file__).resolve().parents[1]
H = 269.94   # board outline height, mm (gen/outline.json)

TOP = [  # (label, X0, Y0, X1, Y1, colour)
    ("POWER IN: XT60 > F1 15A >\nLM74800 switch > 2 mOhm\n(INA238 0x40)", 33.5, -112.0, 58.5, -34.5, "#e4572e"),
    ("MOTOR BUS SWITCH\nLM5069 + F2 10A\n(INA238 0x41)", 1.0, -57.0, 37.5, -33.5, "#f3a712"),
    ("MOTOR MCU STM32G474\n+ E-stop NAND, LDO, SWD", -27.0, -90.0, 25.0, -57.5, "#9b5de5"),
    ("BULK + BRAKE CHOPPER\nMicro-Fit options (DNP)", -35.0, -118.0, 37.5, -90.5, "#d62828"),
    ("USB-C MCU\n+ TPS2121", 5.5, -135.0, 33.0, -116.5, "#3a86ff"),
    ("CAN-FD", -34.0, -135.0, -14.0, -117.0, "#3a86ff"),
    ("E-STOP", -58.0, -116.0, -40.0, -100.0, "#d62828"),
    ("IMU", -23.5, -48.5, -6.0, -42.5, "#9b5de5"),
    ("RASPBERRY PI 4\non M2.5 standoffs", -29.5, -32.0, 55.5, 24.0, "#669bbc"),
    ("PI 40-PIN (ribbon)", -27.0, 26.0, 33.0, 37.0, "#669bbc"),
    ("5.17 V BUCK\n(INA238 0x47)", -42.0, 35.0, -10.0, 69.0, "#2a9d8f"),
    ("SERVO BUCK 6.0/7.4 V\n(INA238 0x43)", 4.0, 35.0, 37.0, 69.0, "#2a9d8f"),
    ("LIDAR PORTS x3", -47.0, 86.0, 3.0, 94.0, "#8338ec"),
    ("RTC + CR1220", -45.0, 69.0, -5.0, 86.0, "#9b5de5"),
    ("SERVO eFuse + 2 x 470 uF", -45.0, 93.0, 30.0, 111.0, "#2a9d8f"),
    ("SERVO x8 + PCA9685", -16.0, 99.0, 16.0, 123.0, "#ff006e"),
    ("STATUS LEDs SK9822 x8", -30.0, 123.5, 30.0, 134.5, "#ffbe0b"),
    ("BUTTON\nBUZZER", 32.0, 66.0, 51.0, 100.0, "#8d99ae"),
    ("FAN1, PI USB-C,\n5V OUT", -58.0, -30.0, -36.0, 22.0, "#8d99ae"),
]
BOTTOM = [
    ("ToF x3", -23.0, 123.0, 23.0, 135.0, "#ffbe0b"),
    ("LIDAR eFuses x3\n+ INA238 0x4D", -44.0, 69.0, 20.0, 87.0, "#8338ec"),
    ("3V3 ToF BUCK\n+ INA238 0x4F", -34.0, 45.0, 4.0, 56.0, "#2a9d8f"),
    ("TCA9548A\nTCA6416A", 12.0, 43.0, 29.0, 52.0, "#ffbe0b"),
    ("INA238 Pi", -39.0, 36.0, -26.0, 44.0, "#669bbc"),
    ("eFuses: ToF x8, enc x2,\nfans, 5V out, Pi USB-C", -20.0, -17.0, 32.0, 18.0, "#2a9d8f"),
    ("ADS7128 x3\n+ REF3425", 34.0, -8.0, 57.0, 22.0, "#e4572e"),
    ("PCAL6524 x2", -19.5, -31.0, 18.0, -19.0, "#9b5de5"),
    ("JETSON + SPARE VBAT\nTPS16630, INA238, XT30", -58.5, -77.0, -4.0, -33.0, "#f3a712"),
    ("DRV8243 L\n+ PH motor L", -32.0, -99.0, -9.0, -76.0, "#29335c"),
    ("DRV8243 R\n+ PH motor R", 14.0, -99.0, 37.0, -76.0, "#29335c"),
    ("ToF", -59.0, 7.0, -48.0, 21.0, "#ffbe0b"), ("ToF", -59.0, -97.0, -48.0, -83.0, "#ffbe0b"),
    ("ToF", 48.0, -21.0, 59.0, -7.0, "#ffbe0b"), ("ToF", 48.0, -77.0, 59.0, -63.0, "#ffbe0b"),
    ("ToF", -21.0, -135.0, -7.0, -124.0, "#ffbe0b"),
]
HOLES = ((-38.09, -121.89), (38.09, -121.89), (-38.09, 107.64), (38.09, 107.64), (-55.26, 84.95), (55.26, 84.95))


def label(name, blocks, mirror):
    img = mpimg.imread(PRJ / "renders" / f"{name}.png")
    mask = (img[:, :, 1] > img[:, :, 2] + 0.06) & (img[:, :, :3].mean(axis=2) < 0.45)
    ys, xs = np.where(mask)
    x0, x1, y0, y1 = np.percentile(xs, 0.2), np.percentile(xs, 99.8), np.percentile(ys, 0.2), np.percentile(ys, 99.8)
    s = (y1 - y0) / H              # orthographic render: one scale
    xc = (x0 + x1) / 2
    sg = -1 if mirror else 1

    def px(X, Y):
        return xc + sg * X * s, y0 + (H / 2 - Y) * s

    fig = plt.figure(figsize=(img.shape[1] / 150, img.shape[0] / 150), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(img)
    ax.axis("off")
    for lbl, X0, Y0, X1, Y1, c in blocks:
        (a, b), (d, e) = px(X0, Y1), px(X1, Y0)
        a, d = min(a, d), max(a, d)
        ax.add_patch(plt.Rectangle((a, b), d - a, e - b, fill=False, ec=c, lw=2.5))
        ax.text(a + 6, b + 18, lbl, color="white", fontsize=8, va="top", weight="bold",
                bbox=dict(facecolor=c, alpha=0.85, pad=2, ec="none"))
    for X, Y in HOLES:
        a, b = px(X, Y)
        ax.add_patch(plt.Circle((a, b), 5 * s, fill=False, ec="#ffd166", lw=2.5))
    a, b = px(0, 132)
    ax.text(a, b - 40, "FRONT" + ("  (seen from below)" if mirror else ""), color="black", fontsize=12, ha="center",
            weight="bold")
    out = PRJ / "renders" / f"{name}_labelled.png"
    fig.savefig(out)
    print(out)


label("top", TOP, False)
label("bottom", BOTTOM, True)
