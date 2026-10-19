# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "matplotlib"]
# ///
"""Round 4 power review sims of the body board rev C (r4_*.cir). Values are checked against gen/design.py, which equals the
routed board (data/pcb-revc/review/round4-power.md). Output: data/pcb-revc/sim/r4/."""

import argparse
import importlib.util
import json
import math
import re
import subprocess
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DESIGN = REPO / "pcb/rabbit-body-c/gen/design.py"
OUT = REPO / "data/pcb-revc/sim/r4"
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6", "#e34948", "#008300"]
SPICE_SCALE = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "g": 1e9}
DESIGN_SCALE = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6}


def spice_num(s):
    m = re.fullmatch(r"([-+]?[\d.]+(?:e[-+]?\d+)?)(meg|[fpnumkg])?[a-z]*", str(s).strip().lower())
    return None if not m else float(m.group(1)) * SPICE_SCALE.get(m.group(2) or "", 1.0)


def design_num(s):
    m = re.match(r"\s*([\d.]+)\s*([pnumkM])?", s)
    if not m:
        return None
    if "mR" in s:
        return float(m.group(1)) * 1e-3
    return float(m.group(1)) * DESIGN_SCALE.get(m.group(2) or "", 1.0)


def load_design():
    spec = importlib.util.spec_from_file_location("design_revc", DESIGN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {p["ref"].upper(): p for p in mod.PARTS}


PARTS = load_design()


def deck_params(text):
    out = {}
    for line in text.splitlines():
        if line.lower().startswith(".param"):
            for name, val in re.findall(r"(\w+)=(\{[^}]*\}|\S+)", line):
                out[name] = val
    return out


def check_refs(deck):
    """Every .param named after a reference designator must equal the board value."""
    for name, val in deck_params((HERE / deck).read_text()).items():
        part = PARTS.get(name.upper())
        if part:
            want, got = design_num(part["value"]), spice_num(val)
            if want is None or got is None or not math.isclose(want, got, rel_tol=1e-3):
                raise SystemExit(f"{deck}: .param {name}={val} does not match the board ({part['value']})")


def compose(deck, over, control):
    text = (HERE / deck).read_text().replace(".include models.lib", (HERE / "models.lib").read_text())
    params = deck_params(text)
    for k, v in over.items():
        if k not in params:
            raise SystemExit(f"{deck}: unknown parameter {k}")
        text = re.sub(rf"(^\.param[^\n]*?\b){k}=(\{{[^}}]*\}}|\S+)", rf"\g<1>{k}={v}", text, count=1, flags=re.M)
    text = re.sub(r"^\.end\s*$", "", text, flags=re.M)
    return text + "\n" + control + "\n.end\n"


def sim(test, case, deck, over, tran, vecs, opts="method=gear reltol=1e-3"):
    d = OUT / test / "raw"
    d.mkdir(parents=True, exist_ok=True)
    data = d / f"{case}.txt"
    step, stop, tmax = tran
    control = (f".options {opts}\n" if opts else "") + "\n".join([
        ".control", "set wr_singlescale", "set wr_vecnames", "option numdgt=8",
        f"tran {step} {stop} 0 {tmax} uic", f"wrdata {data} " + " ".join(vecs), "quit", ".endc"])
    cir = d / f"{case}.cir"
    cir.write_text(compose(deck, over, control))
    r = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True, cwd=d)
    log = r.stdout + r.stderr
    (d / f"{case}.log").write_text(log)
    if "aborted" in log or not data.exists():
        raise SystemExit(f"{test}/{case}: ngspice failed, see {d / (case + '.log')}")
    arr = np.loadtxt(data, skiprows=1)
    names = data.read_text().splitlines()[0].split()
    w = {"t": arr[:, 0]}
    for i, n in enumerate(names[1:], start=1):
        w[n.lower()] = arr[:, i]
    if abs(w["t"][-1] - spice_num(stop)) > 1e-6 * spice_num(stop) + 1e-9:
        raise SystemExit(f"{test}/{case}: stopped at {w['t'][-1]}")
    return w


def at(w, k, t):
    return float(np.interp(t, w["t"], w[k]))


def win(w, k, t0, t1):
    m = (w["t"] >= t0) & (w["t"] <= t1)
    return w[k][m]


def first_cross(w, k, level, t0=0.0, rising=True):
    t, y = w["t"], w[k]
    m = t >= t0
    t, y = t[m], y[m]
    c = np.nonzero((y[:-1] < level) & (y[1:] >= level))[0] if rising else np.nonzero((y[:-1] > level) & (y[1:] <= level))[0]
    if len(c) == 0:
        return None
    i = c[0]
    return float(t[i] + (level - y[i]) * (t[i + 1] - t[i]) / (y[i + 1] - y[i]))


def duration(w, mask):
    t = w["t"]
    return float(np.sum(np.diff(t)[mask[:-1]]))


def plot(test, case, w, panels, title, tscale=1e3, tunit="ms", tlim=None, marks=None):
    fig, axes = plt.subplots(len(panels), 1, figsize=(9, 2.1 * len(panels) + 0.6), sharex=True)
    axes = np.atleast_1d(axes)
    t = w["t"] * tscale
    for ax, (ylabel, series) in zip(axes, panels):
        for k, (key, label) in enumerate(series):
            ax.plot(t, w[key], lw=1.5, color=COLORS[k % len(COLORS)], label=label)
        for lv, lab in (marks or {}).get(ylabel, []):
            ax.axhline(lv, color="#52514e", lw=0.8, ls="--")
            ax.annotate(lab, (t[0], lv), xytext=(2, 2), textcoords="offset points", fontsize=7, color="#52514e")
        ax.set_ylabel(ylabel, fontsize=8)
        ax.grid(True, color="#e6e5e0", lw=0.6)
        ax.tick_params(labelsize=8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        if len(series) > 1:
            ax.legend(fontsize=7, frameon=False, loc="best")
    axes[-1].set_xlabel(f"time ({tunit})", fontsize=8)
    if tlim:
        axes[-1].set_xlim(*tlim)
    axes[0].set_title(title, fontsize=9, loc="left")
    fig.tight_layout()
    p = OUT / test / f"{case}.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p.relative_to(REPO).as_posix()


RESULTS = []


def result(test, case, metric, value, limit, ok, note=""):
    RESULTS.append(dict(test=test, case=case, metric=metric, value=value, limit=limit,
                        verdict=("PASS" if ok else "FAIL") if ok is not None else "INFO", note=note))


# ------------------------------------------------------------------ MOSFET SOA (BSC010N04LS, datasheet/Infineon p.7)
# Diagram 3, Tc = 25 C: in the linear-mode region every pulse line has slope -2 (I ~ V^-2). Read at V_DS = 40 V:
# 100 us 10.4 A, 1 ms 0.85 A, 10 ms 0.18 A, DC 0.077 A. Derated linearly to 0 at Tj 175 C (Tc 25 C -> 150 K headroom).
SOA_T = np.array([1e-4, 1e-3, 1e-2, 1e0])
SOA_I40 = np.array([10.4, 0.85, 0.18, 0.077])


def soa_current(vds, t, tc=25.0):
    i40 = 10 ** np.interp(np.log10(max(t, 1e-4)), np.log10(SOA_T), np.log10(SOA_I40))
    return i40 * (40.0 / max(vds, 1.0)) ** 2 * (175.0 - tc) / 150.0


def soa_margin(w, ik, vk, tc=25.0, windows=(1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2)):
    """Worst ratio (SOA current at the window's mean V_DS) / (mean current) over all windows of the listed lengths."""
    t, i, v = w["t"], np.abs(w[ik]), np.abs(w[vk])
    tu = np.linspace(t[0], t[-1], 20000)
    iu, vu = np.interp(tu, t, i), np.interp(tu, t, v)
    dt = tu[1] - tu[0]
    worst = (math.inf, None, None, None, None)
    for T in windows:
        n = max(1, int(T / dt))
        if n >= len(tu):
            continue
        k = np.ones(n) / n
        im, vm = np.convolve(iu, k, "valid"), np.convolve(vu, k, "valid")
        for j in np.argsort(im * vm)[-50:]:
            if im[j] < 1e-3:
                continue
            r = soa_current(vm[j], T, tc) / im[j]
            if r < worst[0]:
                worst = (r, T, float(vm[j]), float(im[j]), float(tu[j]))
    return worst


# ------------------------------------------------------------------ TPS259470 time to TSD (SLVSFC9C fig. 6-37 p.18)
TSD_P = np.array([4, 5, 6, 7, 10, 15, 20, 23])
TSD_25 = np.array([950, 350, 220, 130, 55, 20, 9, 7]) * 1e-3
TSD_P85 = np.array([2.1, 3, 4, 5, 6, 10, 15, 20, 23])
TSD_85 = np.array([1000, 280, 120, 70, 40, 13, 5, 2.5, 1.7]) * 1e-3


def t_tsd(p, ta=25):
    P, T = (TSD_P, TSD_25) if ta == 25 else (TSD_P85, TSD_85)
    if p < P[0]:
        return math.inf
    return float(10 ** np.interp(np.log10(p), np.log10(P), np.log10(T)))


# ================================================================== test S: servo rail
def t_servo():
    T = "servo"
    deck = "r4_servo.cir"
    check_refs(deck)
    vecs = ["v(SERVO_BUCK)", "v(SERVO_RAW)", "v(SERVO_PWR)", "v(ARM_PWR)", "i(VL)", "i(Vst_m)", "i(Varm_m)",
            "v(OVLO_SERVO)", "v(hon)", "v(xu88.itm)", "v(xu88.lim)", "v(xu83.itm)", "v(xu83.lim)", "v(sov)"]
    panels = [("V (V)", [("v(servo_raw)", "SERVO_RAW"), ("v(servo_pwr)", "SERVO_PWR (steering)"),
                         ("v(arm_pwr)", "ARM_PWR")]),
              ("I (A)", [("i(vl)", "L6 (buck)"), ("i(varm_m)", "U88 arm"), ("i(vst_m)", "U83 steering")]),
              ("flags", [("v(xu88.itm)", "U88 ITIMER (V)"), ("v(xu88.lim)", "U88 limiting"), ("v(hon)", "buck on"),
                         ("v(sov)", "OVLO")])]
    # corners: typ = I_LS/I_SC average 14.4 A (SNVSBZ4A p.25), I_LIM typ, ITIMER 1.51 V / 1.8 uA;
    # worst = buck limited to I_LS min 9.8 A (low VIN), I_LIM max (x 4.84/4.452), longest ITIMER 1.741 V / 1.2 uA
    corners = {"typ": dict(ilim_b=14.4, vin=16.8),
               "worst": dict(ilim_b=9.8, vin=12.0, arm_k=round(4.84 / 4.452, 4), st_k=round(6.60 / 6.068, 4),
                             i_itm="1.2u", dv_itm=1.741)}
    rows = []
    for mode, vs in (("7V4", 7.4), ("6V0", 6.0)):
        for cn, cp in corners.items():
            for ist in (6, 8, 10, 12, 20):
                case = f"stall_{mode}_{cn}_{ist}A"
                over = dict(vset0=vs, vset1=7.4, vset_ic=vs, i_stall=ist, i_steer=1.0, t_stall="5m", **cp)
                w = sim(T, case, deck, over, ("2u", "80m", "20u"), vecs)
                m = w["t"] > 5e-3
                vmin = float(w["v(servo_pwr)"][m].min())
                t_low = duration(w, (w["v(servo_pwr)"] < 0.9 * vs) & m)
                ia = w["i(varm_m)"]
                lim = (w["v(xu88.lim)"] > 0.5) & m
                p_lim = (w["v(servo_raw)"] - w["v(arm_pwr)"]) * ia
                plim = float(np.median(p_lim[lim])) if lim.any() else 0.0
                t_first_lim = first_cross(w, "v(xu88.lim)", 0.5, 5e-3)
                hic = bool((w["v(hon)"][m] < 0.5).any())
                rows.append((case, vmin, t_low, plim, t_first_lim, hic, float(ia[m].max())))
                if ist in (8, 12) or cn == "worst":
                    plot(T, case, w, panels, f"Arm stall {ist} A (at 7.4 V) on SERVO_RAW, {mode}, {cn} corner, steering 1 A",
                         tlim=(3, 80))
                ok = vmin >= 0.9 * vs or t_low < 1e-3
                result(T, case, "SERVO_PWR min (V) / time below 90 % (ms)", f"{vmin:.2f} / {t_low * 1e3:.1f}",
                       f">= {0.9 * vs:.2f} or < 1 ms", ok,
                       f"U88 peak {ia[m].max():.1f} A, limiting from {((t_first_lim or 0) - 5e-3) * 1e3:.1f} ms, "
                       f"P in limit {plim:.1f} W -> TSD in {t_tsd(plim) * 1e3:.0f} ms (25 C) / {t_tsd(plim, 85) * 1e3:.0f} ms (85 C)"
                       f"{', buck hiccup' if hic else ''}")
    # normal arm move: 0.3 -> 4 A step, steering 1 A
    for mode, vs in (("7V4", 7.4), ("6V0", 6.0)):
        case = f"armstep_{mode}"
        w = sim(T, case, deck, dict(vset0=vs, vset1=7.4, vset_ic=vs, i_stall=3.7, t_stall="5m", t_stall_len="20m"),
                ("1u", "40m", "10u"), vecs)
        m = (w["t"] > 5e-3)
        dv = vs - float(w["v(servo_pwr)"][m].min())
        plot(T, case, w, panels, f"Arm load step 0.3 -> 4.0 A and back, {mode}, steering 1 A", tlim=(3, 40))
        result(T, case, "SERVO_PWR dip on a 3.7 A arm step (mV)", round(dv * 1e3), "< 5 % of the rail", dv < 0.05 * vs)
    # 6.0 -> 7.4 V switch with both eFuses on and loaded
    case = "switch_6to7V4"
    w = sim(T, case, deck, dict(vset0=6.0, vset1=7.4, vset_ic=6.0, t_sel="5m", i_stall=1, t_stall="1"),
            ("1u", "30m", "5u"), vecs)
    st_pk = float(w["i(vst_m)"].max())
    raw_pk = float(w["v(servo_raw)"].max())
    plot(T, case, w, panels, "SERVO_7V4 0 -> 1 (6.0 -> 7.4 V) with U83 and U88 on", tlim=(3, 30))
    result(T, case, "U83 peak current while the rail steps up (A)", round(st_pk, 2),
           "< U83 fast trip 2.01 x 5.40 = 10.9 A min", st_pk < 10.9, f"SERVO_RAW peak {raw_pk:.2f} V (OVLO min 8.51 V)")
    # arm fast trip while the steering eFuse is off: SERVO_RAW overshoot vs OVLO
    for vs, cn in ((7.4, "typ"), (6.0, "typ"), (7.4, "worst")):
        case = f"armtrip_steeroff_{vs:.1f}V_{cn}"
        # fast trip at 2 x I_LIM: the HFET is off for ~30 us (SLVSFC9C p.34), i.e. a 9 A load step to zero
        w = sim(T, case, deck, dict(vset0=vs, vset1=7.4, vset_ic=vs, i_stall=1, t_stall="1", st_en_t=1,
                                    i_arm0=round(2.01 * 4.452 * vs / 7.4, 2), arm_off_t="5m", **corners[cn]),
                ("0.2u", "12m", "2u"), vecs)
        pk = float(win(w, "v(servo_raw)", 5e-3, 12e-3).max())
        ov = bool((w["v(sov)"] > 0.5).any())
        plot(T, case, w, panels, f"Arm fast trip (9 A -> 0) with the steering eFuse off, {vs} V, {cn}", tlim=(4.8, 6))
        result(T, case, "SERVO_RAW overshoot after the arm load is removed (V)", round(pk, 2), "< 8.51 V OVLO min",
               pk < 8.51, "OVLO trips (U83/U88 off for ~90 us, restart current-limited)" if ov else "")
    # owner-accepted case: steering and arm heavy at the same time, worst corner
    case = "both_heavy_worst"
    w = sim(T, case, deck, dict(vset0=7.4, vset1=7.4, vset_ic=7.4, i_stall=5.5, t_stall="5m", i_steer=1.0, i_steer2=5.0,
                                t_steer2="5m", **corners["worst"]), ("2u", "80m", "20u"), vecs)
    m = w["t"] > 5e-3
    vmin = float(w["v(servo_pwr)"][m].min())
    plot(T, case, w, panels, "Steering +5 A and arm 5.5 A together, worst corner (owner-accepted case)", tlim=(3, 80))
    result(T, case, "SERVO_PWR min (V) / time below 90 % (ms)",
           f"{vmin:.2f} / {duration(w, (w['v(servo_pwr)'] < 6.66) & m) * 1e3:.1f}", "accepted by the owner", None)
    return rows


# ================================================================== test P: battery hot-plug, button press, power-up order
def t_press():
    T = "press"
    deck = "r4_press.cir"
    check_refs(deck)
    vecs = ["v(BAT_F)", "v(SW_MID)", "v(VBUS_RAW)", "v(VBUS)", "v(HG)", "i(Vq2)", "v(JET)", "v(r5)", "v(P5V_MCU)",
            "v(P3V3_MCU)", "v(MOT_UVLO)", "v(MOT_TMR)", "v(insd)", "v(gen)", "v(MOT_GATE)", "v(MOT_BUS)", "i(Vtv)",
            "i(Vlb)"]
    # hot-plug with the latch off (no press): lead ringing into C22 / C21 and the TVS
    for vb, lead in ((16.8, "0.6u"), (16.8, "1.5u"), (12.0, "0.6u")):
        case = f"hotplug_{vb:.1f}V_L{lead}"
        w = sim(T, case, deck, dict(vbat=vb, l_lead=lead, press=0, t_rise="1u"), ("5n", "0.6m", "20n"), vecs)
        pk = float(w["v(bat_f)"].max())
        itv = float(np.abs(w["i(vtv)"]).max())
        plot(T, case, w, [("V (V)", [("v(bat_f)", "BAT_F"), ("v(sw_mid)", "SW_MID"), ("v(vbus)", "VBUS")]),
                          ("I (A)", [("i(vlb)", "battery lead"), ("i(vtv)", "D7 TVS")])],
             f"Battery hot-plug {vb} V, lead {lead}H, latch off (no press)", tscale=1e6, tunit="us", tlim=(150, 260))
        result(T, case, "BAT_F peak (V) / TVS peak current (A)", f"{pk:.1f} / {itv:.1f}",
               "< 40 V (Q1/Q2 V_DS), < 65 V (LM74800 A)", pk < 40, f"VBUS max {w['v(vbus)'].max():.2f} V (stays off)")
    # press: VBUS ramp into all bulk caps with the Pi/MCU (5 V buck) and Jetson loads, then the LM5069 insertion race
    corners = {
        "typ": dict(),
        "fast": dict(i_hgate="75u", C23="47n", t_en4="0.82m", t_ss4="1.7m"),
        "slow": dict(i_hgate="39u", t_en4="1.2m", t_ss4="2.7m"),
    }
    race = {"typ": dict(),
            "worst": dict(i_ins="8u", v_tmrh=3.76, t_set="5m", sr_mux=600, vth_q31=2.5, t_en4="1.2m", t_ss4="2.7m",
                          i_hgate="75u")}
    rows = []
    for vb in (16.8, 12.0):
        for cn, cp in corners.items():
            for jet in ("jet", "nojet"):
                case = f"press_{vb:.1f}V_{cn}_{jet}"
                over = dict(vbat=vb, t_press="5m", **cp)
                if jet == "nojet":
                    over["p_jet"] = 0
                    over["c_jet"] = "1u"
                w = sim(T, case, deck, {k: v for k, v in over.items() if k != "C23"}, ("2u", "60m", "20u"), vecs)
                ipk = float(win(w, "i(vq2)", 5e-3, 60e-3).max())
                w["vds_q2"] = w["v(sw_mid)"] - w["v(vbus_raw)"]
                w["p_q2"] = w["vds_q2"] * w["i(vq2)"]
                t90 = first_cross(w, "v(vbus)", 0.9 * vb, 5e-3)
                e = float(np.trapezoid(np.clip(w["p_q2"], 0, None), w["t"]))
                r, Tw, vm, im, tw = soa_margin(w, "i(vq2)", "vds_q2", tc=25.0)
                r60 = r * (175 - 60) / 150
                rows.append((case, ipk, t90, e, r))
                plot(T, case, w, [("V (V)", [("v(bat_f)", "BAT_F"), ("v(vbus)", "VBUS"), ("v(jet)", "JET_PWR"),
                                             ("v(r5)", "+5V"), ("v(p3v3_mcu)", "+3V3_MCU")]),
                                  ("Q2", [("i(vq2)", "I (A)"), ("p_q2", "P (W)")]),
                                  ("LM5069", [("v(mot_tmr)", "TIMER (V)"), ("v(mot_uvlo)", "UVLO (V)"), ("v(gen)", "gate enabled"),
                                              ("v(mot_bus)", "MOT_BUS (V)")])],
                     f"Button press at {vb} V, {cn} corner, {'Jetson 220 uF + 6 W' if jet == 'jet' else 'no Jetson'}", tlim=(4, 60))
                result(T, case, "Q2 inrush peak (A) / VBUS 10-90 % (ms) / Q2 energy (mJ)",
                       f"{ipk:.2f} / {(t90 - 5e-3) * 1e3 if t90 else float('nan'):.1f} / {e * 1e3:.0f}", "SOA", r60 > 1,
                       f"SOA margin {r:.2f}x at Tc 25 C ({r60:.2f}x at Tc 60 C), worst window {Tw * 1e3:.1f} ms at "
                       f"{vm:.1f} V / {im:.2f} A")
    for rc, rp in race.items():
        for vb in (16.8, 12.0):
            case = f"race_{vb:.1f}V_{rc}"
            w = sim(T, case, deck, dict(vbat=vb, t_press="5m", **rp), ("2u", "60m", "20u"), vecs)
            t_q31 = first_cross(w, "v(p3v3_mcu)", rp.get("vth_q31", 1.6), 5e-3)
            t_ins = first_cross(w, "v(insd)", 0.5, 5e-3)
            on = bool((w["v(gen)"] > 0.5).any())
            mb = float(w["v(mot_bus)"].max())
            plot(T, case, w, [("V (V)", [("v(vbus)", "VBUS"), ("v(r5)", "+5V"), ("v(p5v_mcu)", "+5V_MCU"),
                                         ("v(p3v3_mcu)", "+3V3_MCU")]),
                              ("LM5069", [("v(mot_tmr)", "TIMER (V)"), ("v(mot_uvlo)", "UVLO (V)"), ("v(gen)", "gate enabled"),
                                          ("v(mot_bus)", "MOT_BUS (V)")])],
                 f"Power-up order at {vb} V, {rc}: +3V3_MCU / Q31 vs the LM5069 insertion timer", tlim=(4, 60))
            result(T, case, "Q31 on (ms after press) / insertion end (ms) / MOT_BUS max (V)",
                   f"{(t_q31 - 5e-3) * 1e3 if t_q31 else float('nan'):.1f} / "
                   f"{(t_ins - 5e-3) * 1e3 if t_ins else float('nan'):.1f} / {mb:.3f}",
                   "MOT_BUS < 0.5 V (motor bus stays off)", mb < 0.5,
                   f"gate enabled for {duration(w, w['v(gen)'] > 0.5) * 1e3:.1f} ms before Q31 (gate reaches "
                   f"{w['v(mot_gate)'].max():.2f} V, Q30 V_GS(th) >= 1.2 V)" if on else "Q31 first")
    return rows


# ================================================================== test M: motor bus start and hard short
def t_motbus():
    T = "motbus"
    deck = "r4_motbus.cir"
    check_refs(deck)
    vecs = ["v(VBUS)", "v(MOT_BUS)", "v(MOT_GATE)", "v(MOT_DVC)", "i(Viq)", "v(MOT_TMR)", "v(flt)", "v(lerr)", "v(pw)",
            "v(vds)", "v(cb)"]
    panels = [("V (V)", [("v(vbus)", "VBUS"), ("v(mot_bus)", "MOT_BUS"), ("v(mot_gate)", "GATE"), ("v(mot_dvc)", "C303")]),
              ("Q30", [("i(viq)", "I (A)"), ("v(pw)", "P (W)")]),
              ("LM5069", [("v(mot_tmr)", "TIMER (V)"), ("v(flt)", "latched off"), ("v(cb)", "breaker")])]
    for vb in (16.8, 12.0):
        for gc, ig in (("typ", "16u"), ("fast", "22u")):
            case = f"start_{vb:.1f}V_{gc}"
            w = sim(T, case, deck, dict(vbus=vb, i_gate=ig), ("20u", "250m", "100u"), vecs)
            w["i_q30"] = w["i(viq)"]
            ipk = float(w["i_q30"].max())
            tmr = float(w["v(mot_tmr)"].max())
            t90 = first_cross(w, "v(mot_bus)", 0.9 * vb)
            r, Tw, vm, im, tw = soa_margin(w, "i_q30", "v(vds)", tc=25.0, windows=(1e-3, 1e-2, 3e-2, 1e-1))
            plot(T, case, w, panels, f"Motor bus start at {vb} V, gate current {ig}A", tlim=(0, 250))
            result(T, case, "inrush peak (A) / 90 % time (ms) / TIMER max (V)",
                   f"{ipk:.3f} / {(t90 - 1e-3) * 1e3 if t90 else float('nan'):.0f} / {tmr:.3f}",
                   "TIMER < 3.76 V (no fault on start), SOA", tmr < 3.76 and r > 1,
                   f"Q30 SOA margin {r:.1f}x (Tc 25 C) worst window {Tw * 1e3:.0f} ms at {vm:.1f} V / {im:.3f} A")
    # running motors (2 x 2.41 A ITRIP) then a hard short on MOT_BUS; P limit corners (PWRLIM 19-31 mV)
    for vb in (16.8, 12.0):
        for kc, kp, it in (("typ", 1.0, "85u"), ("hiP_slowT", 1.24, "51u")):
            case = f"short_{vb:.1f}V_{kc}"
            over = dict(vbus=vb, t_load="200m", i_load=4.8, t_short="210m", kp_lim=kp, i_tmr=it)
            if kc != "typ":
                over["v_tmrh"] = 4.16
            w = sim(T, case, deck, over, ("1u", "250m", "5u"), vecs)
            w["i_q30"] = w["i(viq)"]
            m = w["t"] > 210e-3
            ipk = float(w["i_q30"][m].max())
            tlat = first_cross(w, "v(flt)", 0.5, 210e-3)
            e = float(np.trapezoid(np.clip((w["v(vds)"] * w["i_q30"])[m], 0, None), w["t"][m]))
            ww = {k: v[m] for k, v in w.items()}
            r, Tw, vm, im, tw = soa_margin(ww, "i_q30", "v(vds)", tc=25.0, windows=(1e-5, 1e-4, 3e-4, 1e-3, 2e-3))
            plot(T, case, w, panels, f"Hard short on MOT_BUS at {vb} V (motors at 4.8 A), {kc}", tlim=(209, 250))
            result(T, case, "peak current (A) / latch-off after (ms) / Q30 energy (mJ)",
                   f"{ipk:.0f} / {(tlat - 210e-3) * 1e3 if tlat else float('nan'):.2f} / {e * 1e3:.1f}", "SOA",
                   r * (175 - 85) / 150 > 1,
                   f"Q30 SOA margin {r:.1f}x at Tc 25 C, {r * 0.6:.1f}x at Tc 85 C; worst window {Tw * 1e3:.2f} ms at "
                   f"{vm:.1f} V / {im:.2f} A")


TESTS = {"servo": t_servo, "press": t_press, "motbus": t_motbus}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tests", nargs="*", default=list(TESTS))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for t in a.tests:
        TESTS[t]()
    lines = ["| test | case | metric | value | limit | verdict | note |", "|---|---|---|---|---|---|---|"]
    for r in RESULTS:
        lines.append(f"| {r['test']} | {r['case']} | {r['metric']} | {r['value']} | {r['limit']} | {r['verdict']} | {r['note']} |")
    name = "_".join(a.tests)
    (OUT / f"results_{name}.md").write_text("\n".join(lines) + "\n")
    (OUT / f"results_{name}.json").write_text(json.dumps(RESULTS, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
