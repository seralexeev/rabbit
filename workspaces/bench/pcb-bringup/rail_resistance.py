"""Expected unpowered resistance from every power net of body board rev C to GND, from the resistor network of
pcb/rabbit-body-c/gen/design.py alone (bring-up plan docs/reports/2026-10-11-body-pcb-rev-c-bringup.md, step 1.4).

Shorts: shunts, fuses, 0 R, inductors, NT1 (GND_MOT = GND), JP3 (bridged 1-2). Open: capacitors, semiconductors,
ICs, DNP parts, open solder jumpers. A real meter reads lower where IC inputs and ESD diodes conduct at the meter's
test voltage, and drifts up while the capacitors charge, so the result is the value it settles towards (upper bound).

Run: uv run --with numpy python workspaces/bench/pcb-bringup/rail_resistance.py
"""
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pcb/rabbit-body-c/gen"))
import design  # noqa: E402

RAILS = ["BAT_F", "VBUS_RAW", "VBUS", "MOT_F", "MOT_BUS", "BODY_IN", "STEER_IN", "+5V", "+5V_MCU", "USB_VBUS",
         "+3V3_MCU", "+3V3_MCU_A", "+3V3_IMU", "+3V3_PI", "+3V3_TOF", "ADC_AVDD", "SERVO_RAW", "SERVO_PWR", "ARM_PWR",
         "ARM_5V", "JET_PWR", "SPARE_VBAT", "+5V_AUX", "+5V_PI_USBC", "ENC_3V3", "FAN1_5V", "FAN2_5V", "LIDAR1_5V",
         "LIDAR2_5V", "LIDAR3_5V", "BRK_VCC"]


def ohms(value):
    m = re.search(r"([\d.]+)\s*(m|k|M|R)?", value)
    if not m:
        return None
    return float(m.group(1)) * {"m": 1e-3, "k": 1e3, "M": 1e6, "R": 1.0, None: 1.0}[m.group(2)]


def main():
    shorts, res = [], []
    for p in design.PARTS:
        if p["bom"] == "dnp":
            continue
        pins, ref = p["pins"], p["ref"]
        if ref.startswith(("F", "L", "NT")) or ref == "JP3" or (ref in ("R1", "R2", "R3", "R6")):
            a = pins.get("1")
            for k in ("2", "4") if ref in ("R1", "R2", "R3", "R6") else ("2",):
                if a and pins.get(k):
                    shorts.append((a, pins[k]))
            continue
        if ref.startswith("RN"):
            r = ohms(p["value"].split()[0])
            for k in range(1, 5):
                if str(k) in pins and str(9 - k) in pins:
                    res.append((pins[str(k)], pins[str(9 - k)], r))
            continue
        if ref.startswith(("R", "RT")) and set(pins) == {"1", "2"}:
            r = ohms(p["value"])
            if r == 0:
                shorts.append((pins["1"], pins["2"]))
            elif r:
                res.append((pins["1"], pins["2"], r))
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in shorts:
        parent[find(a)] = find(b)
    nodes = sorted({find(n) for a, b, _ in res for n in (a, b)} | {find(r) for r in RAILS} | {find("GND")})
    idx = {n: i for i, n in enumerate(nodes)}
    g = np.zeros((len(nodes), len(nodes)))
    for a, b, r in res:
        i, j = idx[find(a)], idx[find(b)]
        if i != j:
            g[i, i] += 1 / r
            g[j, j] += 1 / r
            g[i, j] -= 1 / r
            g[j, i] -= 1 / r
    gnd = idx[find("GND")]
    keep = [i for i in range(len(nodes)) if i != gnd]
    gr = g[np.ix_(keep, keep)] + np.eye(len(keep)) * 1e-12
    inv = np.linalg.inv(gr)
    print("| Net | Same node as | Settles to (resistor network only) |")
    print("|---|---|---|")
    for rail in RAILS:
        n = find(rail)
        if n == find("GND"):
            out = "0 (shorted to GND)"
        else:
            r = inv[keep.index(idx[n]), keep.index(idx[n])]
            out = "open (> 10 MOhm: IC leakage only)" if r > 1e10 else (f"{r / 1e3:.1f} kOhm" if r >= 1e3 else f"{r:.0f} Ohm")
        same = sorted(x for x in RAILS if x != rail and find(x) == n)
        print(f"| {rail} | {', '.join(same) or '-'} | {out} |")


if __name__ == "__main__":
    main()
