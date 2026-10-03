"""Labelled top view for the report: renders/top_labelled.png from renders/top.png (run with any Python + matplotlib)."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np

PRJ = Path(__file__).resolve().parents[1]
img = mpimg.imread(PRJ / "renders" / "top.png")
bg = img[5, 5, :3]
mask = (img[:, :, 1] > img[:, :, 2] + 0.06) & (img[:, :, :3].mean(axis=2) < 0.45)
ys, xs = np.where(mask)
x0, x1, y0, y1 = np.percentile(xs, 0.2), np.percentile(xs, 99.8), np.percentile(ys, 0.2), np.percentile(ys, 99.8)
sx = (x1 - x0) / 120.52
sy = (y1 - y0) / 269.94


sx = sy                       # orthographic render: one scale; the rounded shoulders bias the x extent
xc = (x0 + x1) / 2


def px(X, Y):
    return xc + X * sx, y0 + (134.97 - Y) * sy


BLOCKS = [  # (label, X0, Y0, X1, Y1, colour)
    ("POWER IN: XT60 > F1 15A >\nLM74800 ideal diode +\nswitch (Q1, Q2) > 2 mOhm", 34.0, -112.0, 58.5, -50.0, "#e4572e"),
    ("VBUS bus + spine\nto the front", 36.0, -53.5, 58.5, -34.0, "#f3a712"),
    ("MOTOR MCU\nSTM32G474RET6", -21.0, -92.0, 22.0, -58.0, "#9b5de5"),
    ("DRV8316 L", -40.0, -117.0, -18.0, -96.0, "#29335c"),
    ("DRV8316 R", 12.0, -117.0, 34.0, -96.0, "#29335c"),
    ("BRAKE\nCHOPPER", -17.5, -117.0, 11.5, -92.0, "#d62828"),
    ("MOTOR / HALL / ENC", -32.5, -135.0, 32.5, -117.5, "#29335c"),
    ("RASPBERRY PI 4\nUSB / ETH to the right edge", -29.8, -32.3, 57.5, 24.3, "#669bbc"),
    ("40-pin to Pi (ribbon)", -27.0, 25.0, 33.0, 35.0, "#669bbc"),
    ("5.17 V 10 A\nLM61495", -41.0, 33.5, -19.0, 67.0, "#2a9d8f"),
    ("JETSON\neFuse 4.6 A", -15.5, 41.0, 2.0, 60.0, "#2a9d8f"),
    ("6 V SERVO\nLM61495", 3.0, 33.5, 26.0, 67.0, "#2a9d8f"),
    ("ZED USB\ncable cut", 21.5, 64.6, 32.6, 82.6, "#8d99ae"),
    ("PCA9685, servo\nheaders, RTC", -24.0, 86.0, 21.0, 122.0, "#9b5de5"),
]
fig = plt.figure(figsize=(img.shape[1] / 150, img.shape[0] / 150), dpi=150)
ax = fig.add_axes([0, 0, 1, 1])
ax.imshow(img)
ax.axis("off")
for label, X0, Y0, X1, Y1, c in BLOCKS:
    a, b = px(X0, Y1); d, e = px(X1, Y0)
    ax.add_patch(plt.Rectangle((a, b), d - a, e - b, fill=False, ec=c, lw=2.5))
    ax.text(a + 6, b + 18, label, color="white", fontsize=9, va="top", weight="bold",
            bbox=dict(facecolor=c, alpha=0.85, pad=2, ec="none"))
for X, Y in ((-38.09, -121.89), (38.09, -121.89), (-38.09, 107.64), (38.09, 107.64), (-55.26, 84.95), (55.26, 84.95)):
    a, b = px(X, Y)
    ax.add_patch(plt.Circle((a, b), 5 * sx, fill=False, ec="#ffd166", lw=2.5))
a, b = px(0, 132)
ax.text(a, b - 40, "FRONT", color="black", fontsize=12, ha="center", weight="bold")
a, b = px(38.09, -121.89)
ax.text(a, b - 7 * sy, "deck standoff", color="#ffd166", fontsize=8, ha="center", weight="bold")
fig.savefig(PRJ / "renders" / "top_labelled.png")
print(PRJ / "renders" / "top_labelled.png", x0, x1, y0, y1)
