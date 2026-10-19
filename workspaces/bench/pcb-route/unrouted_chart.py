"""Unrouted connections per fastroute pass for the rev C routing experiments (numbers from the router logs)."""
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

RUNS = [
    ("6 layers, 763 parts, pours as obstacles (fastroute 0.1.7, ~4 h)", [582, 1147, 437, 412, 362, 347]),
    ("8 layers, pours after routing (~75 min)", [303, 412, 196, 147, 133, 114, 103, 99, 98, 94, 91]),
    ("+ split power plane, 2 oz power on outer layers (~25 min)", [250, 745, 143, 112, 92, 83, 86, 78, 80, 76, 78, 76]),
    ("671 parts, fastroute 0.1.13 (~15 min)", [255, 818, 149, 114, 98, 95, 89, 92, 90, 86, 85]),
    ("+ board +30% area, tuned router rules (~50 min)", [207, 247, 732, 97, 76, 67, 64, 63, 62, 57, 58, 56, 56]),
    ("+ floorplan by Fable (~25 min)", [176, 254, 66, 41, 35, 34, 31, 32, 29, 29, 27, 29, 27, 29, 27, 29, 27, 29, 27,
                                        29, 27, 29]),
]

fig, ax = plt.subplots(figsize=(11, 6), dpi=160)
for name, ys in RUNS:
    ax.plot(range(1, len(ys) + 1), ys, marker="o", ms=3.5, lw=2, label=name)
ax.set_yscale("log")
ax.set_ylim(20, 1300)
ax.set_xlabel("Autorouter pass")
ax.xaxis.set_major_locator(MaxNLocator(integer=True))
ax.set_ylabel("Unrouted connections (log)")
ax.set_title("Rabbit body board rev C: unrouted connections per autorouter pass")
ax.grid(True, which="both", alpha=0.3)
ax.legend(fontsize=8.5, loc="upper right")
fig.tight_layout()
fig.savefig(sys.argv[1] if len(sys.argv) > 1 else "unrouted.png")
