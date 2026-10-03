"""Rev B design numbers: dividers, thresholds, timings, copper widths, thermal estimates.

Run with any Python 3: python3 gen/calc.py. The report docs/reports/2026-10-03-body-pcb-rev-b.md quotes these.
Datasheet references are in the report (page numbers); the constants here are copied from them.
"""
import math

E96 = [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50,
       1.54, 1.58, 1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10, 2.15, 2.21, 2.26, 2.32,
       2.37, 2.43, 2.49, 2.55, 2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24, 3.32, 3.40, 3.48, 3.57,
       3.65, 3.74, 3.83, 3.92, 4.02, 4.12, 4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49,
       5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65, 6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45,
       8.66, 8.87, 9.09, 9.31, 9.53, 9.76]


def e96(x):
    d = 10 ** math.floor(math.log10(x))
    return min((v * d for v in E96 + [10.0]), key=lambda v: abs(v - x))


def par(*r):
    return 1 / sum(1 / x for x in r)


def ipc_current(width_mm, oz=1.0, rise=20.0, k=0.024):
    """IPC-2152 conservative fit (the IPC-2221 internal-layer curve, used for every layer)."""
    area_mil2 = width_mm / 0.0254 * oz * 1.378
    return k * rise ** 0.44 * area_mil2 ** 0.725


def ipc_width(current, oz=1.0, rise=20.0, k=0.024):
    area = (current / (k * rise ** 0.44)) ** (1 / 0.725)
    return area / (oz * 1.378) * 0.0254


def main():
    out = []
    p = out.append

    # LM74800 (SNOSDD8): EN/UVLO rising 1.231 V, falling 1.132 V (p.5); OV rising 1.231, falling 1.13 (p.5)
    ov_top, ov_bot = 150e3, 10e3
    p(f"LM74800 OV cut-off: {1.231 * (1 + ov_top / ov_bot):.1f} V rising, {1.13 * (1 + ov_top / ov_bot):.1f} V falling")
    # inrush: C_dVdT = I_HGATE x C_OUT / I_INRUSH (p.16), I_HGATE 55 uA
    c_out, c_dvdt = 3 * 220e-6 + 12 * 10e-6 + 10 * 22e-6, 47e-9
    slew = 55e-6 / c_dvdt
    p(f"VBUS capacitance ~{c_out * 1e6:.0f} uF; HGATE slew {slew:.0f} V/s; inrush {c_out * slew:.2f} A; "
      f"ramp to 16.8 V in {16.8 / slew * 1e3:.0f} ms (DRV8316 VM limit 4 V/us, SLVSF16B p.6)")
    # soft latch: EN = 220k to GND; button path PNP collector -> 47k; hold path VBUS -> 8.2 V zener -> 47k
    r_pd, r_on, r_hold, vz = 220e3, 47e3, 47e3, 8.2
    en_hold = (16.8 - vz) * r_pd / (r_pd + r_hold)
    v_release = vz + 1.132 * (r_pd + r_hold) / r_pd
    p(f"latch: EN held at {en_hold:.1f} V at 16.8 V; releases when VBUS < {v_release:.1f} V")
    en_btn = (16.8 - 0.2) * par(r_pd, r_hold) / (r_on + par(r_pd, r_hold))
    p(f"latch: button press puts EN at {en_btn:.1f} V with VBUS = 0 (threshold 1.231 V)")
    tau_off = 1e6 * 1e-6
    t_hold = tau_off * math.log((3.3 - 0.3) / 1.0)
    p(f"OFF FET gate held > 1.0 V for {t_hold:.2f} s after the Pi dies (1 uF, 1 MOhm, BAT54 drop 0.3 V)")
    c_bus = c_out + 2 * 470e-6
    p(f"VBUS fall 16.8 -> {v_release:.1f} V at 50 mA (Pi halted): {c_bus * (16.8 - v_release) / 0.05 * 1e3:.0f} ms")

    # LM61495 (SNVSBZ4A): VFB 1.0 V (p.14 eq.1), EN rising 1.263 V (p.6)
    for name, rbot in (("5V body", 24e3), ("6V servo", 20e3)):
        p(f"LM61495 {name}: RFBT 100k, RFBB {rbot / 1e3:.1f}k -> {1.0 * (1 + 100e3 / rbot):.3f} V")
    p(f"LM61495 EN divider 100k/22k: starts at {1.263 * 122 / 22:.1f} V")

    # TPS16630 (SLVSET9G): UVLO/OVP rising 1.2 V (p.8), I_OL = 18 / R_ILIM[kOhm] (p.20 eq.6), t_dVdT eq.2 (p.17)
    p(f"TPS16630 UVLO 68k/10k: {1.2 * (1 + 68 / 10):.2f} V; OVP 150k/10k: {1.2 * (1 + 15):.1f} V")
    for name, rilim, cdvdt in (("Jetson", 3.9, 47e-9),):
        p(f"TPS16630 {name}: R_ILIM {rilim}k -> {18 / rilim:.2f} A, t_dVdT at 16.8 V = {20.8e3 * 16.8 * cdvdt * 1e3:.1f} ms")

    # brake chopper: LM393 on MOT_BUS, TL431 2.495 V, output pull-up to a 12 V zener-clamped gate
    vref, r2, vg = 2.495, 10e3, 12.0
    best = None
    for r1 in (e96(x * 1e3) for x in range(55, 70)):
        for rh in (1.0e6, 1.2e6, 1.5e6, 2.0e6):
            on = vref * (r1 + par(r2, rh)) / par(r2, rh)
            g = 1 / r1 + 1 / r2 + 1 / rh
            off = r1 * (vref * g - vg / rh)
            err = abs(on - 17.6) + abs(off - 17.2)
            if best is None or err < best[0]:
                best = (err, r1, rh, on, off)
    _, r1, rh, on, off = best
    p(f"brake: R1 {r1 / 1e3:.1f}k, R2 10k, Rh {rh / 1e3:.0f}k -> on {on:.2f} V, off {off:.2f} V")
    rb = 39.0 / 4
    p(f"brake resistor 4 x 39 Ohm = {rb:.2f} Ohm: {17.6 / rb:.2f} A, {17.6 ** 2 / rb:.1f} W while on; "
      f"14 J (stop from 2.5 m/s) in {14 / (17.6 ** 2 / rb):.2f} s, {14 / 4:.1f} J per 2512")

    # E-stop timing: 100k x 2.2 uF into a Schmitt NAND (SN74LVC1G132 at 3 V: VT- 0.84-1.14 V, VT+ 1.5-1.87 V, p.6)
    lo, hi = (100e3 * 2.2e-6 * math.log(3.3 / v) * 1e3 for v in (1.14, 0.84))
    p(f"E-stop -> DRVOFF delay {lo:.0f}-{hi:.0f} ms (TIM BKIN brakes at once)")

    # copper (1 oz outer, 0.5 oz inner), 20 C rise
    for net, amps in (("battery/VBUS", 14), ("motor branch", 8), ("Jetson", 4.5), ("5 V Pi", 4), ("6 V servo", 6),
                      ("phase", 8), ("VBUS spine", 10)):
        p(f"IPC-2152 {net} {amps} A: {ipc_width(amps):.1f} mm on one 1 oz layer, {ipc_width(amps / 2):.1f} mm on each of two")

    # as built (routing.py): narrowest section of each power path, layers, required current
    for name, width, layers, need in (("BAT_IN / BAT_F / SW_MID pours", 9.2, 2, 14), ("VBUS_RAW pour", 6.4, 2, 14),
                                      ("VBUS spine under the Pi", 7.5, 2, 10), ("MOT_F", 6.1, 2, 8),
                                      ("MOT_BUS corridor", 2.7, 2, 4), ("MOT_BUS bar (F only, DRV L)", 5.0, 1, 4),
                                      ("phase track F + B", 1.5, 2, 3), ("+5 V to the Pi header", 2.0, 1, 2.5),
                                      ("6 V to the servo shunt", 3.0, 1, 3), ("SERVO_6V pour (B)", 6.0, 1, 6),
                                      ("JET_OUT pour (F)", 3.0, 1, 3.5), ("JET_PWR pour (F + B)", 4.0, 2, 4.5),
                                      ("GND_MOT island (In1 0.5 oz alone, F.Cu fill not counted)", 20.0, 1, 6)):
        cap = ipc_current(width, 0.5 if name.startswith("GND_MOT") else 1.0) * layers
        p(f"as built {name}: {width} mm x {layers} -> {cap:.1f} A at +20 C (needs {need} A)")

    # thermal
    # DRV8316 FOC losses (SLVSF16B p.85, table 11-1): 3 I^2 Rds (95 mOhm HS+LS -> 47.5 per FET, x1.5 hot)
    # + 3 I V t_rise f_pwm (200 V/us -> ~100 ns, 25 kHz) + standby 12 mA from VM
    for irms in (1.45, 3.0, 4.3):
        pcon = 3 * irms ** 2 * 0.0475 * 1.5
        psw = 3 * irms * 16.8 * 100e-9 * 25e3
        ptot = pcon + psw + 16.8 * 0.012
        p(f"DRV8316 at {irms} A rms: ~{ptot:.2f} W -> +{ptot * 25.7:.0f} C (RthJA 25.7 C/W, p.7)")
    for name, vout, iout, eff in (("5V", 5.17, 3.5, 0.92), ("6V", 6.0, 2.0, 0.92), ("6V peak", 6.0, 6.0, 0.88)):
        pin = vout * iout / eff
        loss = pin - vout * iout
        ic = loss * 0.65
        p(f"LM61495 {name} {iout} A: loss {loss:.2f} W, IC ~{ic:.2f} W -> +{ic * 30:.0f} C (RthJA ~30 C/W, EVM 21.6, p.6)")
    for name, amps in (("battery 14 A", 14), ("typical 4 A", 4)):
        pq = amps ** 2 * 1.5e-3
        p(f"LM74800 FETs BSC010N04LS at {name}: {pq:.2f} W each (1.0 mOhm max at 10 V x 1.5 hot)")
    p(f"TPS16630 Jetson at 3.5 A: {3.5 ** 2 * 0.031:.2f} W -> +{3.5 ** 2 * 0.031 * 32.2:.0f} C (31 mOhm, RthJA 32.2)")
    print("\n".join(out))


if __name__ == "__main__":
    main()
