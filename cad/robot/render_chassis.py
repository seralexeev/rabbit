"""Renders the named kit parts coloured by group: cad/robot/renders/chassis_groups_*.png."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brackets"))

from chassis import HERE, named  # noqa: E402
from common import label_png, render  # noqa: E402

COLOURS = {
    "deck": "#c9a227", "wheel": "#2b2b2b", "hub": "#ff9800", "motor": "#1e88e5",
    "steering": "#43a047", "standoff": "#8e24aa", "fastener": "#9e9e9e", "other": "#e53935",
}

if __name__ == "__main__":
    parts = named()
    items = [(s, COLOURS[g]) for s, g, _ in parts.values()]
    for p in render(items, HERE / "renders" / "chassis_groups", views=("iso", "top", "iso_rear"), edges=False):
        label_png(p, "Hiwonder Ackermann kit, named parts",
                  ["deck yellow, wheel black, hub orange, motor blue, steering green, standoff purple, fastener grey"])
        print(p)
