# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.8"]
# ///
"""Wheel speed vs wheel torque of the drive options for docs/reports/2026-10-03-bldc-drive.md.

Run: uv run docs/reports/media/bldc-drive.py  (writes bldc-drive.svg next to this file)

Every motor is a straight speed-torque line between no-load speed and stall torque at the
voltage the controller can apply, cut by the controller current limit and by the gearbox limit.
"""

import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

WHEEL_RADIUS = 0.0375
MASS = 4.5
G = 9.81
SAG = 14.0


def rpm_to_mps(rpm: float) -> float:
    return rpm * 2 * math.pi * WHEEL_RADIUS / 60


@dataclass
class Option:
    name: str
    no_load_rpm: float
    stall_nm: float
    limit_nm: float
    color: str
    dash: str = "-"

    def curve(self):
        torque_cap = min(self.stall_nm, self.limit_nm)
        points = [(rpm_to_mps(self.no_load_rpm), 0.0)]
        rpm_at_cap = self.no_load_rpm * (1 - torque_cap / self.stall_nm)
        points.append((rpm_to_mps(rpm_at_cap), torque_cap))
        points.append((0.0, torque_cap))
        return points


def pololu(rpm12: float, stall12_kgmm: float, amps_stall12: float, volts: float, current_limit: float, nominal: float = 12.0):
    scale = volts / nominal
    stall = stall12_kgmm * 0.00981 * scale
    torque_per_amp = stall12_kgmm * 0.00981 / amps_stall12
    return rpm12 * scale, stall, torque_per_amp * current_limit


def options() -> list[Option]:
    result = []
    nl, st, lim = pololu(150, 270, 5.2, 12.0, 3.0)
    result.append(Option("Today: Pololu 37D 70:1, 12 V duty cap, RoboClaw 3 A", nl, st, min(lim, 2.45), "#52514e", "--"))
    nl, st, lim = pololu(530, 85, 5.4, 12.0, 4.0)
    result.append(Option("Fallback: Pololu 37D 19:1 (#4751), 12 V cap, 4 A", nl, st, lim, "#2a78d6"))
    nl, st, lim = pololu(330, 140, 5.6, 12.0, 4.0)
    result.append(Option("Pololu 37D 30:1 (#4752), 12 V cap, 4 A", nl, st, lim, "#eb6834"))
    result.append(Option("BLDC JGB37-3650 12 V, 18.8:1, FOC 5 A (listing)", 8000 * SAG / 12 * 0.95 / 18.8, 1.06 * SAG / 12, 0.75, "#1baf7a"))
    result.append(Option("BLDC JGB37-3625 12 V, 18.8:1, FOC (short, listing)", 6000 * SAG / 12 * 0.95 / 18.8, 0.59 * 18.8 / 30 * SAG / 12, 0.59 * 18.8 / 30 * SAG / 12, "#eda100"))
    result.append(Option("Steadywin GIM4305-10 actuator (too wide, reference)", 16.75 * SAG, 3.82, 3.82, "#4a3aa7", ":"))
    return result


def requirement_points():
    weight = MASS * G
    per_wheel = lambda force: force / 2 * WHEEL_RADIUS
    rug = 0.06 * weight
    ramp = weight * math.sin(math.radians(5))
    traction = 0.7 * 0.55 * weight
    return {
        "cruise today 0.16 m/s": (0.16, per_wheel(rug)),
        "rug + 5° ramp + 1 m/s², 0.5 m/s": (0.5, per_wheel(rug + ramp + MASS * 1.0)),
        "rug + 1 m/s² at 1.5 m/s": (1.5, per_wheel(rug + MASS * 1.0)),
        "15 mm threshold (short, with momentum)": (0.45, 0.6),
    }, per_wheel(traction)


def plot(options: list[Option], path: Path):
    points, traction = requirement_points()
    fig, ax = plt.subplots(figsize=(10, 6.2), dpi=100)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(True, color="#e6e5e0", linewidth=0.8)
    ax.axhline(traction, color="#e34948", linewidth=1.2, linestyle=":")
    ax.text(2.42, traction + 0.02, f"traction limit ≈ {traction:.2f} N·m (μ 0.7, 55% on rear axle)", ha="right", fontsize=9, color="#52514e")
    ax.axvspan(1.5, 2.5, color="#f3f2ee", zorder=0)
    ax.text(1.52, 1.42, "manual top speed target ≥ 1.5 m/s", fontsize=9, color="#52514e")
    for option in options:
        xs, ys = zip(*option.curve())
        ax.plot(xs, ys, option.dash, color=option.color, linewidth=2, label=option.name)
    for name, (x, y) in points.items():
        ax.plot([x], [y], "o", color="#0b0b0b", markersize=7, markeredgecolor="white", markeredgewidth=1.5, zorder=5)
        ax.annotate(name, (x, y), xytext=(6, 6), textcoords="offset points", fontsize=8.5, color="#0b0b0b")
    ax.set_xlim(0, 2.5)
    ax.set_ylim(0, 1.5)
    ax.set_xlabel("wheel speed, m/s (75 mm wheel)")
    ax.set_ylabel("torque per wheel, N·m")
    ax.set_title(f"Rabbit drive options at the 4S bus ({SAG:.0f} V under load): available torque vs speed", fontsize=12, loc="left")
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.93), fontsize=8.5, frameon=False)
    fig.tight_layout()
    fig.savefig(path, format="svg")


if __name__ == "__main__":
    plot(options(), Path(__file__).with_suffix(".svg"))
