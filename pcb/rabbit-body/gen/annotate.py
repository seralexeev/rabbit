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
    ("POWER IN\nXT60 > F1 15A >\nswitch > 2 mOhm", 37.5, -112.0, 58.5, -37.0, "#e4572e"),
    ("FUSES F2-F7\nVBUS bar", 13.5, -108.5, 37.0, -48.5, "#f3a712"),
    ("ROBOCLAW 2x30A\nterminals to the rear", -56.5, -109.5, -3.0, -34.5, "#29335c"),
    ("MOTOR B+/B- \n+ 1000 uF", -37.0, -127.0, 8.0, -110.0, "#e4572e"),
    ("RASPBERRY PI 4\nUSB / ETH to the right edge", -29.8, -32.3, 57.5, 24.3, "#669bbc"),
    ("5 V 9 A\n(Pi, lidar, ToF)", -54.5, -24.7, -33.5, 16.7, "#2a9d8f"),
    ("40-pin to Pi\n(ribbon)", -27.0, 25.0, 33.0, 35.0, "#669bbc"),
    ("12 V Jetson\n+ 10 mOhm", -42.0, 37.5, -4.0, 80.0, "#2a9d8f"),
    ("6 V servo\n+ 10 mOhm", 4.0, 37.5, 41.0, 63.5, "#2a9d8f"),
    ("ZED USB\ncable cut", 21.5, 64.6, 32.6, 82.6, "#8d99ae"),
    ("PCA9685 + servo\nheaders, RTC", -24.0, 86.0, 21.0, 123.0, "#9b5de5"),
    ("INA4235", 15.0, -46.0, 28.0, -36.0, "#d62828"),
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
