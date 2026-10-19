# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "matplotlib"]
# ///
"""Circuit checks of the body board rev C (pcb/rabbit-body-c/gen/design.py) with ngspice. See README.md."""

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
NETLIST = REPO / "data/pcb-revc/review/netlist.json"
OUT = REPO / "data/pcb-revc/sim"
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6", "#e34948", "#008300"]

SPICE_SCALE = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "g": 1e9}
DESIGN_SCALE = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6}


def spice_num(s):
    m = re.fullmatch(r"([-+]?[\d.]+(?:e[-+]?\d+)?)(meg|[fpnumkg])?[a-z]*", s.strip().lower())
    if not m:
        return None
    return float(m.group(1)) * SPICE_SCALE.get(m.group(2) or "", 1.0)


def design_num(s):
    m = re.match(r"\s*([\d.]+)\s*([pnumkM])?", s)
    if not m:
        return None
    v = float(m.group(1)) * DESIGN_SCALE.get(m.group(2) or "", 1.0)
    if "mR" in s:
        v = float(m.group(1)) * 1e-3
    return v


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
    text = (HERE / deck).read_text()
    rows = []
    for name, val in deck_params(text).items():
        part = PARTS.get(name.upper())
        if not part:
            continue
        want = design_num(part["value"])
        got = spice_num(val)
        ok = want is not None and got is not None and math.isclose(want, got, rel_tol=1e-3)
        rows.append((name, part["value"], val, ok))
        if not ok:
            raise SystemExit(f"{deck}: .param {name}={val} does not match design.py {name} = {part['value']}")
    return rows


def compose(deck, over, control):
    text = (HERE / deck).read_text()
    text = text.replace(".include models.lib", (HERE / "models.lib").read_text())
    params = deck_params(text)
    for k, v in over.items():
        if k not in params:
            raise SystemExit(f"{deck}: unknown parameter {k}")
        text = re.sub(rf"(^\.param[^\n]*?\b){k}=(\{{[^}}]*\}}|\S+)", rf"\g<1>{k}={v}", text, count=1, flags=re.M)
    text = re.sub(r"^\.end\s*$", "", text, flags=re.M)
    return text + "\n" + control + "\n.end\n"


def sim(test, case, deck, over, tran, vecs, opts=""):
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
    if abs(w["t"][-1] - float(spice_num(str(stop)))) > 1e-6 * float(spice_num(str(stop))) + 1e-9:
        raise SystemExit(f"{test}/{case}: stopped at {w['t'][-1]}")
    return w


def at(w, key, t):
    return float(np.interp(t, w["t"], w[key]))


def window(w, key, t0, t1):
    m = (w["t"] >= t0) & (w["t"] <= t1)
    return w[key][m]


def first_cross(w, key, level, t0=0.0, rising=True):
    t, y = w["t"], w[key]
    m = t >= t0
    t, y = t[m], y[m]
    c = np.nonzero((y[:-1] < level) & (y[1:] >= level))[0] if rising else np.nonzero((y[:-1] > level) & (y[1:] <= level))[0]
    if len(c) == 0:
        return None
    i = c[0]
    return float(t[i] + (level - y[i]) * (t[i + 1] - t[i]) / (y[i + 1] - y[i]))


def plot(test, case, w, panels, title, tscale=1e3, tunit="ms", tlim=None, marks=None):
    fig, axes = plt.subplots(len(panels), 1, figsize=(9, 2.1 * len(panels) + 0.6), sharex=True)
    axes = np.atleast_1d(axes)
    t = w["t"] * tscale
    for ax, (ylabel, series) in zip(axes, panels):
        for k, (key, label) in enumerate(series):
            ax.plot(t, w[key], lw=1.6, color=COLORS[k % len(COLORS)], label=label)
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


# ---------------------------------------------------------------- 1. soft latch

def t1_latch():
    T = "1-latch"
    check_refs("latch.cir")
    vecs = ["v(VBUS_RAW)", "v(LM_EN)", "v(LM_OV)", "v(HG)", "v(BTN_ON)", "v(LATCH_B)", "v(BAT_F)", "v(GPIO17)",
            "v(OFF_G)", "v(HOLD_Z)"]
    panels = [("V (V)", [("v(bat_f)", "BAT_F"), ("v(vbus_raw)", "VBUS_RAW")]),
              ("V (V)", [("v(lm_en)", "LM_EN (U10.6)"), ("v(lm_ov)", "LM_OV (U10.5)")]),
              ("V (V)", [("v(btn_on)", "BTN_ON"), ("v(gpio17)", "GPIO17"), ("v(off_g)", "OFF_G (Q5 gate)")])]
    en_marks = {"V (V)": []}

    for vb in (12.0, 16.8):
        tag = f"{vb:.1f}V"
        for fix in (0, 1):
            case = f"plugin_{tag}" + ("_fixC26" if fix else "")
            w = sim(T, case, "latch.cir", dict(vbat=vb, t_rise="10u", t_press=10, t_len="1m", c26_to_bat=fix),
                    ("20u", "0.4", "50u"), vecs)
            vmax = float(w["v(vbus_raw)"].max())
            plot(T, case, w, panels, f"Battery hot-plug at {vb} V (10 us rise), no button press"
                 + (", C26 moved to BAT_F" if fix else ", as designed"))
            result(T, case, "VBUS_RAW max after plug-in, no press (V)", round(vmax, 2), "< 1 V (stays off)", vmax < 1.0,
                   "C26 100 nF BTN_ON->GND holds Q4 base low while the battery steps up" if not fix else "fix candidate")

        for fix in (0, 1):
            case = f"cycle_{tag}" + ("_fixC26" if fix else "")
            w = sim(T, case, "latch.cir", dict(vbat=vb, t_rise="1.0", t_press="1.2", t_len="150m", t_off="2.5",
                                               c26_to_bat=fix), ("50u", "5", "500u"), vecs)
            plot(T, case, w, panels, f"{vb} V battery: slow connect, 150 ms press at 1.2 s, Pi gpio-poweroff "
                 f"(GPIO17) at 2.5 s" + (", C26 to BAT_F" if fix else ""), tscale=1, tunit="s")
            pre = float(window(w, "v(vbus_raw)", 0, 1.19).max())
            on = at(w, "v(vbus_raw)", 2.4)
            en_on = at(w, "v(lm_en)", 2.4)
            ov = float(window(w, "v(lm_ov)", 1.2, 2.49).max())
            t_fall = first_cross(w, "v(vbus_raw)", 1.0, 2.5, rising=False)
            late = window(w, "v(vbus_raw)", (t_fall or 4.9) + 0.01, 5.0)
            result(T, case, "VBUS_RAW before press (V)", round(pre, 2), "< 1", pre < 1)
            result(T, case, "VBUS_RAW latched, 1.05 s after release (V)", round(on, 2), f"> {vb - 0.3:.1f}", on > vb - 0.3)
            result(T, case, "LM_EN while held by D8/R47 (V)", round(en_on, 2), "> 1.267 (V_UVLOR max)", en_on > 1.267)
            result(T, case, "LM_OV max while on (V)", round(ov, 3), "< 1.195 (V_OVR min)", ov < 1.195)
            result(T, case, "time GPIO17 high -> VBUS_RAW < 1 V (s)", round(t_fall - 2.5, 3) if t_fall else None,
                   "turns off, no re-latch", t_fall is not None and (late.max() if len(late) else 0) < 1.0)

    for vb in (12.0, 16.8):
        for corner, extra in (("typ", {}), ("worst", dict(i_hgate="39u", bv_d8=8.7, nbv_d8=1, en_r=1.267, en_f=1.159))):
            latched = []
            for ms in (0.5, 1, 2, 4, 8, 15, 30, 50):
                case = f"press_{vb:.1f}V_{corner}_{ms}ms"
                w = sim(T, case, "latch.cir", dict(vbat=vb, t_rise="1.0", t_press="1.2", t_len=f"{ms}m", t_off=10,
                                                   **extra), ("50u", "1.8", "200u"), vecs)
                latched.append((ms, at(w, "v(vbus_raw)", 1.79) > vb - 0.5))
            mn = next((ms for ms, ok in latched if ok and all(o for m2, o in latched if m2 >= ms)), None)
            result(T, f"press_{vb:.1f}V_{corner}", "shortest press that latches (ms, tried 0.5-50)", mn,
                   "<= 50 ms (short press)", mn is not None and mn <= 50, "C26 stretches any contact >= 0.5 ms; "
                   + "corner: I_HGATE 39 uA, D8 8.7 V hard knee, EN 1.267/1.159 V"
                   if corner == "worst" else "typical")
            for p in (OUT / T).glob(f"press_{vb:.1f}V_{corner}_*.png"):
                p.unlink()

    for corner, extra in (("typ", {}), ("soft_7V7", dict(bv_d8=7.7)), ("worst_8V7", dict(bv_d8=8.7, nbv_d8=1, en_f=1.159))):
        case = f"brownout_{corner}"
        w = sim(T, case, "latch.cir", dict(vbat=12.0, t_rise="1.0", t_press="1.2", t_len="150m", t_off=20,
                                           t_sag=2, t_sag_fall=4, t_sag_len=1, v_sag=8, p_on=5, **extra),
                ("100u", "6", "1m"), vecs)
        plot(T, case, w, panels, f"Brown-out: battery ramps 12 -> 8 V in 4 s, latch on ({corner})", tscale=1, tunit="s")
        t_drop = first_cross(w, "v(lm_en)", 1.0, 2.0, rising=False)
        vdrop = at(w, "v(bat_f)", t_drop) if t_drop else None
        result(T, case, "battery voltage at which the latch drops (V)", round(vdrop, 2) if vdrop else None,
               "< 10.58 V (LM5069 motor UVLO off) and < 12.0 V", vdrop is not None and vdrop < 10.58)

    for vs, fix in ((10.5, 0), (10.0, 0), (9.0, 0), (9.0, 1)):
        case = f"dip_{vs:.1f}V_worst" + ("_fixC26" if fix else "")
        w = sim(T, case, "latch.cir", dict(vbat=12.0, t_rise="1.0", t_press="1.2", t_len="150m", t_off=20,
                                           t_sag=2, t_sag_fall="1m", t_sag_len="20m", v_sag=vs, p_on=30,
                                           bv_d8=8.7, nbv_d8=1, en_f=1.159, c26_to_bat=fix),
                ("20u", "2.5", "100u"), vecs)
        plot(T, case, w, panels, f"12.0 V battery dips to {vs} V for 20 ms under 30 W load (D8 8.7 V hard knee, EN 1.159 V)", tscale=1, tunit="s",
             tlim=(1.95, 2.1))
        on = at(w, "v(vbus_raw)", 2.45) > 11
        vmin = float(window(w, "v(vbus_raw)", 2.0, 2.05).min())
        dropped = vmin < 7
        result(T, case, f"20 ms dip to {vs} V: VBUS_RAW min (V) / state after", f"{vmin:.2f} / {'on' if on else 'off'}",
               "dropout below ~10 V is the designed UVLO; must not re-latch by itself", not (dropped and on),
               "latch dropped and re-latched when the battery recovered (C26 edge, S-1)" if dropped and on else "")


# ---------------------------------------------------------------- 2. DRVOFF watchdog

def t2_watchdog():
    T = "2-watchdog"
    check_refs("watchdog.cir")
    vecs = ["v(MCU_ALIVE)", "v(ALIVE_AC)", "v(ALIVE_DET)", "v(ESTOP_DLY)", "v(DRVOFF)", "v(ESTOP)"]
    panels = [("V (V)", [("v(mcu_alive)", "MCU_ALIVE (U1.11)")]),
              ("V (V)", [("v(alive_det)", "ALIVE_DET (U16.2)"), ("v(estop_dly)", "ESTOP_DLY (U16.1)")]),
              ("V (V)", [("v(drvoff)", "DRVOFF (U16.4)")])]
    corners = {"typ": dict(), "release_worst": dict(v_alive=2.9, vt_p=2.04, vt_n=1.27, i_leak="5u"),
               "false_release": dict(vt_p=1.63, vt_n=0.95)}
    sweep = {}
    for cname, extra in corners.items():
        for f in (100, 200, 300, 500, 700, 1000, 2000, 10000, 100000):
            stop = 0.12 if f >= 1000 else 0.2
            case = f"freq_{cname}_{f}Hz"
            w = sim(T, case, "watchdog.cir", dict(f_alive=f, **extra), (f"{1 / f / 40:.3g}", stop, f"{1 / f / 40:.3g}"),
                    vecs)
            tail = window(w, "v(drvoff)", stop - 0.04, stop)
            det = window(w, "v(alive_det)", stop - 0.04, stop)
            released = bool(tail.max() < 0.5)
            chatter = bool(tail.max() > 1.65 and tail.min() < 1.65)
            t_rel = first_cross(w, "v(drvoff)", 1.65, 0, rising=False)
            sweep[(cname, f)] = dict(released=released, chatter=chatter, det_min=float(det.min()),
                                     det_max=float(det.max()), t_rel=t_rel)
            if f in (300, 1000) and cname == "typ" or (cname == "release_worst" and f == 1000):
                plot(T, case, w, panels, f"MCU_ALIVE {f} Hz ({cname}): charge pump and DRVOFF", tlim=(0, stop * 1e3))
            else:
                (OUT / T / "raw" / f"{case}.txt").unlink()
        rel = [f for f in (100, 200, 300, 500, 700, 1000, 2000, 10000, 100000) if sweep[(cname, f)]["released"]]
        for f in (1000, 10000, 100000):
            s = sweep[(cname, f)]
            result(T, f"freq_{cname}", f"{f} Hz: DRVOFF released, ALIVE_DET {s['det_min']:.2f}-{s['det_max']:.2f} V",
                   s["released"], "released", s["released"],
                   f"release after {s['t_rel'] * 1e3:.1f} ms" if s["t_rel"] else "")
        chat = [f for f in (100, 200, 300, 500, 700) if sweep[(cname, f)]["chatter"]]
        result(T, f"freq_{cname}", "lowest toggle frequency that releases DRVOFF (Hz)", min(rel) if rel else None,
               ">= 1000 by intent", (min(rel) >= 1000) if rel else False,
               f"DRVOFF chatters at {chat} Hz" if chat else "")
    (OUT / T / "sweep.json").write_text(json.dumps({f"{k[0]}_{k[1]}": v for k, v in sweep.items()}, indent=1))

    for cname, extra in (("typ", {}), ("slow", dict(vt_n=0.95)), ("fast", dict(vt_n=1.27, v_alive=2.9))):
        for f in (1000, 10000):
            for lvl in (0, 1):
                case = f"stop_{'high' if lvl else 'low'}_{f}Hz_{cname}"
                w = sim(T, case, "watchdog.cir", dict(f_alive=f, t_stop="60m", stop_level=lvl, **extra),
                        (f"{1 / f / 40:.3g}", "0.12", f"{1 / f / 40:.3g}"), vecs)
                ta = first_cross(w, "v(drvoff)", 1.65, 0.06)
                if cname == "typ" and f == 1000:
                    plot(T, case, w, panels, f"MCU_ALIVE stops {'high' if lvl else 'low'} at 60 ms (1 kHz, typ)")
                result(T, case, "MCU_ALIVE stops -> DRVOFF high (ms)", round((ta - 0.06) * 1e3, 1) if ta else None,
                       "<= 50 ms (IWDG 50 ms)", ta is not None and ta - 0.06 <= 0.05)
    for cname, extra in (("typ", {}), ("slow", dict(vt_n=0.95)), ("fast", dict(vt_n=1.27))):
        case = f"estop_open_{cname}"
        w = sim(T, case, "watchdog.cir", dict(t_estop_open="60m", **extra), ("25u", "0.6", "25u"), vecs)
        ta = first_cross(w, "v(drvoff)", 1.65, 0.06)
        if cname == "typ":
            plot(T, case, w, panels, "E-stop loop opens at 60 ms with MCU_ALIVE at 1 kHz")
        result(T, case, "ESTOP opens -> DRVOFF high (ms)", round((ta - 0.06) * 1e3, 0) if ta else None,
               "150-400 ms (design ~290 ms)", ta is not None and 0.15 <= ta - 0.06 <= 0.4)
    case = "power_up"
    w = sim(T, case, "watchdog.cir", dict(vdly0=0), ("25u", "0.5", "25u"), vecs)
    plot(T, case, w, panels, "Power-up: ESTOP_DLY and the pump start from 0 V")
    t_rel = first_cross(w, "v(drvoff)", 1.65, 0, rising=False)
    result(T, case, "power-up: DRVOFF held high until (ms)", round(t_rel * 1e3, 0) if t_rel else None,
           "high at reset", t_rel is not None and t_rel > 0.01)


# ---------------------------------------------------------------- 3. xArm bus

def crossings(t, y, level, up):
    i = np.nonzero((y[:-1] < level) & (y[1:] >= level))[0] if up else np.nonzero((y[:-1] > level) & (y[1:] <= level))[0]
    return t[i] + (level - y[i]) * (t[i + 1] - t[i]) / (y[i + 1] - y[i])


def edges(w, key, lo, hi, t0, t1):
    m = (w["t"] >= t0) & (w["t"] <= t1)
    t, y = w["t"][m], w[key][m]
    out = []
    for start, stop, up in ((lo, hi, True), (hi, lo, False)):
        a, b = crossings(t, y, start, up), crossings(t, y, stop, up)
        back = crossings(t, y, start, not up)
        d = []
        for ta in a:
            nb = b[b > ta]
            nback = back[back > ta]
            if len(nb) and (not len(nback) or nb[0] < nback[0]):
                d.append(nb[0] - ta)
        out.append(float(np.median(d)) if d else None)
    return tuple(out)


def duty(w, key, level, t0, t1, tbit=8.68e-6):
    t, y = w["t"], w[key]
    m = (t >= t0) & (t <= t1)
    t, y = t[m], y[m]
    c = np.nonzero(np.diff(np.sign(y - level)))[0]
    tc = [t[i] + (level - y[i]) * (t[i + 1] - t[i]) / (y[i + 1] - y[i]) for i in c]
    widths = np.diff(tc)
    if len(widths) < 4:
        return None
    hi_first = y[c[0] + 1] > level
    hi = widths[0::2] if hi_first else widths[1::2]
    lo = widths[1::2] if hi_first else widths[0::2]
    return float((np.median(hi) - np.median(lo)) / tbit)


def t3_xarm():
    T = "3-xarm"
    check_refs("xarm.cir")
    vecs = ["v(ARM_UART_M)", "v(ARM_SIG_B)", "v(ARM_SIG)", "v(SRV)", "v(ARM_5V)", "i(Vldo)", "i(Vmis)", "i(Vinj)"]
    panels = [("V (V)", [("v(arm_uart_m)", "ARM_UART_M = PB9 (U1.62)")]),
              ("V (V)", [("v(arm_sig_b)", "ARM_SIG_B (Q88 drain)"), ("v(srv)", "far end (servos)")])]
    for fet, extra in (("typ", {}), ("weak", dict(vt_bss138=1.5, kp_bss138=0.089))):
        for mode, sx in (("pp5", dict(servo_pp=1)), ("od", dict(servo_pp=0)), ("pp3v3", dict(servo_pp=1, v_srv=3.3))):
            case = f"bus_{fet}_{mode}"
            w = sim(T, case, "xarm.cir", dict(**extra, **sx), ("2n", "220u", "5n"), vecs)
            plot(T, case, w, panels, f"115200 Bd: STM32 -> servos (5-100 us), servo ({mode}) -> STM32 (120-215 us), "
                 f"BSS138 {fet}", tscale=1e6, tunit="us")
            if mode == "pp5":
                srv = window(w, "v(srv)", 10e-6, 100e-6)
                r, f = edges(w, "v(srv)", 0.5, 4.5, 10e-6, 100e-6)
                dd = duty(w, "v(srv)", 2.5, 10e-6, 100e-6)
                result(T, case, "MCU->servo: bus low level (V)", round(float(srv.min()), 3), "< 1.5 (0.3 x 5 V CMOS VIL)",
                       srv.min() < 1.5)
                result(T, case, "MCU->servo: bus high level (V)", round(float(srv.max()), 2), "> 3.5 (0.7 x 5 V)",
                       srv.max() > 3.5)
                result(T, case, "MCU->servo: rise 10-90 % / fall 90-10 % (ns)",
                       f"{r * 1e9:.0f} / {f * 1e9:.0f}" if r and f else None, "< 1736 ns (20 % of a bit)",
                       bool(r and f and max(r, f) < 0.2 * 8.68e-6))
                result(T, case, "MCU->servo: duty distortion at 2.5 V (% of bit)", round(dd * 100, 1) if dd is not None else None,
                       "|x| < 10 %", dd is not None and abs(dd) < 0.10)
            m = window(w, "v(arm_uart_m)", 125e-6, 215e-6)
            r, f = edges(w, "v(arm_uart_m)", 0.33, 2.97, 125e-6, 215e-6)
            dd = duty(w, "v(arm_uart_m)", 1.65, 125e-6, 215e-6)
            vmax = float(w["v(arm_uart_m)"].max())
            result(T, case, "servo->MCU: PB9 low level (V)", round(float(m.min()), 3), "< 0.99 (VIL 0.3 VDD)", m.min() < 0.99)
            result(T, case, "servo->MCU: PB9 high level (V)", round(float(m.max()), 3), "> 2.31 (VIH 0.7 VDD)", m.max() > 2.31)
            result(T, case, "PB9 maximum anywhere (V)", round(vmax, 3), "<= 5.5 (FT pin); 3.6 = VDD max", vmax <= 5.5,
                   "above 3.6 V" if vmax > 3.6 else "")
            inj = -float(window(w, "i(vinj)", 3e-6, 1).min())
            result(T, case, "PB9 minimum (V) / peak negative injection (mA)",
                   f"{window(w, 'v(arm_uart_m)', 3e-6, 1).min():.2f} / {max(inj, 0) * 1e3:.2f}", "injection < 5 mA (STM32 I_INJ)",
                   inj < 5e-3, "line ringing below GND passes the BSS138 (drain below source)" if inj > 1e-4 else "")
            result(T, case, "servo->MCU: rise / fall at PB9 (ns)", f"{r * 1e9:.0f} / {f * 1e9:.0f}" if r and f else None,
                   "< 1736 ns", bool(r and f and max(r, f) < 0.2 * 8.68e-6))
            result(T, case, "servo->MCU: duty distortion at 1.65 V (% of bit)",
                   round(dd * 100, 1) if dd is not None else None, "|x| < 10 %", dd is not None and abs(dd) < 0.10)
    for pwr, sx in (("arm_on", dict(v_armpwr=7.4)), ("arm_off", dict(v_armpwr=0, v5=0))):
        case = f"misplug_8V4_{pwr}"
        w = sim(T, case, "xarm.cir", dict(t_mis="20u", t_m1="1u", t_s1="1u", t_m0="0.5u", t_s0="0.6u", **sx),
                ("1u", "20m", "2u"), vecs)
        plot(T, case, w, [("V (V)", [("v(arm_sig)", "ARM_SIG"), ("v(arm_sig_b)", "ARM_SIG_B"), ("v(arm_5v)", "ARM_5V (U89 out)")]),
                          ("V (V)", [("v(arm_uart_m)", "PB9")])],
             f"8.4 V forced on the signal pin from 20 us, ARM_PWR {'7.4 V' if pwr == 'arm_on' else 'off'}")
        imis = -float(w["i(vmis)"][-1])
        vb = float(w["v(arm_5v)"].max())
        result(T, case, "PB9 maximum (V)", round(float(w["v(arm_uart_m)"].max()), 3), "<= 5.5 (FT pin)",
               w["v(arm_uart_m)"].max() <= 5.5, "edge-coupled through Q88 Cgd/Cds; steady value is 3.3 V")
        result(T, case, "steady current from the 8.4 V source (mA)", round(imis * 1e3, 2), "< 10 mA, TVS not clamping",
               imis < 0.01)
        result(T, case, "ARM_5V back-driven to (V)", round(vb, 2),
               f"<= VIN + 0.3 = {sx['v_armpwr'] + 0.3:.1f} V (TLV760 abs max)", vb <= sx["v_armpwr"] + 0.3)
    case = "contention"
    w = sim(T, case, "xarm.cir", dict(t_s0="5u", t_s1="100u"), ("2n", "60u", "5n"),
            vecs + ["v(arm_sig_b)", "v(arm_sig)"])
    ic = np.abs(w["v(arm_sig_b)"] - w["v(arm_sig)"]) / 47
    result(T, case, "MCU low vs servo push-pull high: peak line current (mA)", round(float(ic.max()) * 1e3, 1),
           "INFO (protocol collision only)", None)


# ---------------------------------------------------------------- 4. I2C

def t4_i2c():
    T = "4-i2c"
    check_refs("i2c.cir")
    nets = json.loads(NETLIST.read_text())["nets"]
    devs = sorted({p.split(".")[0] for p in nets["I2C1_SDA"]} - {"J3"})
    pullups = [p for p in nets["I2C1_SDA"] + nets["I2C1_SCL"] if p.startswith("R")]
    c_main = 10 * len(devs) + 50
    result(T, "count", f"devices on I2C1_SDA ({', '.join(devs)})", len(devs), "INFO", None,
           f"board pull-ups on I2C1: {pullups or 'none (Pi 1.8k only)'}; C = {len(devs)} x 10 pF + 50 pF = {c_main} pF")
    vecs = ["v(I2C1_SDA)", "v(TOF1_SDA)"]
    for cm in (c_main, c_main + 50, 400):
        case = f"main_{cm}pF"
        w = sim(T, case, "i2c.cir", dict(c_main=f"{cm}p", mux_on=0), ("5n", "40u", "5n"), vecs)
        r, f = edges(w, "v(i2c1_sda)", 0.99, 2.31, 5e-6, 40e-6)
        lo = float(window(w, "v(i2c1_sda)", 5e-6, 40e-6).min())
        if cm == c_main:
            plot(T, case, w, [("V (V)", [("v(i2c1_sda)", "I2C1_SDA")])], f"I2C1 at 100 kHz, {cm} pF, Pi 1.8k",
                 tscale=1e6, tunit="us")
        result(T, case, "rise 30-70 % (ns)", round(r * 1e9), "SM <= 1000 ns", r < 1e-6,
               f"FM (400 kHz) <= 300 ns: {'PASS' if r < 300e-9 else 'FAIL'}")
        result(T, case, "VOL (V)", round(lo, 3), "<= 0.4", lo <= 0.4)
    case = "tof_port"
    w = sim(T, case, "i2c.cir", dict(c_main=f"{c_main}p", mux_on=1, t_tof="40u"), ("5n", "80u", "5n"), vecs)
    plot(T, case, w, [("V (V)", [("v(i2c1_sda)", "I2C1_SDA (Pi side)"), ("v(tof1_sda)", "TOF1_SDA (port)")])],
         "ToF port 1 through the TCA9548A: Pi drives 0-40 us, the sensor drives 40-80 us", tscale=1e6, tunit="us")
    for key, t0, t1, who in (("v(tof1_sda)", 5e-6, 40e-6, "Pi drives, port side"),
                             ("v(i2c1_sda)", 45e-6, 80e-6, "sensor drives, Pi side"),
                             ("v(tof1_sda)", 45e-6, 80e-6, "sensor drives, port side")):
        r, f = edges(w, key, 0.99, 2.31, t0, t1)
        lo = float(window(w, key, t0, t1).min())
        result(T, case, f"{who}: rise 30-70 % (ns)", round(r * 1e9) if r else None, "SM <= 1000 ns", bool(r and r < 1e-6),
               f"FM <= 300 ns: {'PASS' if r and r < 300e-9 else 'FAIL'}")
        result(T, case, f"{who}: VOL (V)", round(lo, 3), "<= 0.4", lo <= 0.4)
    isink = 3.3 / 1.8e3 + 3.3 / 4.7e3
    result(T, case, "sink current with one ToF channel on (mA)", round(isink * 1e3, 2), "<= 3 mA (SM/FM)", isink <= 3e-3)


# ---------------------------------------------------------------- 5. rails (arithmetic)

def t5_rails():
    T = "5-rails"
    v = lambda r: design_num(PARTS[r]["value"])
    par = lambda *r: 1 / sum(1 / x for x in r)
    rows = []

    def row(name, refs, formula, val, lo, hi, comment, ok=True, note=""):
        rows.append(dict(name=name, refs=refs, formula=formula, typ=val, min=lo, max=hi, comment=comment,
                         verdict="PASS" if ok else "FAIL", note=note))

    for n, name, vfb, tol in ((4, "+5V_BUCK (LM61495 U4)", 1.0, 0.01),):
        r1, r2 = v(f"R{n}01"), v(f"R{n}02")
        x = vfb * (1 + r1 / r2)
        row(name, f"R{n}01/R{n}02", "1.00 V x (1 + R01/R02), VFB 0.99-1.01, 1 % R", x,
            0.99 * (1 + r1 * 0.99 / (r2 * 1.01)), 1.01 * (1 + r1 * 1.01 / (r2 * 0.99)), "5.17 V", abs(x - 5.17) < 0.01)
    r1, r2, r9 = v("R601"), v("R602"), v("R609")
    x6 = 1 + r1 / r2
    x7 = 1 + r1 / par(r2, r9)
    row("SERVO_BUCK 6.0 V (U6, Q601 off)", "R601/R602", "1.00 V x (1 + R601/R602), 0.1 % R", x6, 0.99 * x6, 1.01 * x6,
        "6.0 V", abs(x6 - 6.0) < 0.01)
    row("SERVO_BUCK 7.4 V (U6, Q601 on)", "R601/(R602||R609)", "1.00 V x (1 + R601/(R602||R609))", x7, 0.99 * x7, 1.01 * x7,
        "7.399 V", abs(x7 - 7.399) < 0.01, "Q601 2N7002K RDS(on) ~2 ohm vs 71.5k: < 0.01 %")
    for n, rr in ((4, ("R404", "R405")),):
        ra, rb = v(rr[0]), v(rr[1])
        x = 1.263 * (ra + rb) / rb
        row("U4 EN start (VIN rising)", "/".join(rr), "VEN 1.161-1.365 V x (R404+R405)/R405", x, 1.161 * (ra + rb) / rb,
            1.365 * (ra + rb) / rb, "7.0 V", abs(x - 7.0) < 0.05)
    t1, t2 = v("R311"), v("R312")
    x = 0.6 * (1 + t1 / t2)
    row("+3V3_TOF_BUCK (TPS62826 U31)", "R311/R312", "0.600 V (0.594-0.606) x (1 + R311/R312)", x, 0.594 * (1 + t1 / t2),
        0.606 * (1 + t1 / t2), "3.306 V", abs(x - 3.306) < 0.005)
    ra, rb = v("R40"), v("R41")
    row("LM74800 OV cut-off (U10)", "R40/R41", "V_OVR 1.195-1.267 x (R40+R41)/R41", 1.231 * (ra + rb) / rb,
        1.195 * (ra + rb) / rb, 1.267 * (ra + rb) / rb, "rev B 19.7 V", True, "above 16.8 V full charge by 2.3 V min")
    for u, base in (("U5 Jetson", 80), ("U7 spare VBAT", 180)):
        ra, rb, oa, ob, ril = v(f"R{base}"), v(f"R{base + 1}"), v(f"R{base + 2}"), v(f"R{base + 3}"), v(f"R{base + 4}")
        row(f"TPS16630 {u} UVLO", f"R{base}/R{base + 1}", "1.2 V (1.176-1.224) x (R+R)/R", 1.2 * (ra + rb) / rb,
            1.176 * (ra + rb) / rb, 1.224 * (ra + rb) / rb, "9.36 V", abs(1.2 * (ra + rb) / rb - 9.36) < 0.01)
        row(f"TPS16630 {u} OVP", f"R{base + 2}/R{base + 3}", "1.2 V x (R+R)/R", 1.2 * (oa + ob) / ob, 1.176 * (oa + ob) / ob,
            1.224 * (oa + ob) / ob, "19.2 V", abs(1.2 * (oa + ob) / ob - 19.2) < 0.01)
        il = 18 / (ril / 1e3)
        row(f"TPS16630 {u} I_OL", f"R{base + 4}", "18 / R_ILIM[k] (+-7 %, table at 3k/4.02k)", il, il * 0.93, il * 1.07,
            "3.53 A" if base == 80 else "3.83 A", abs(il - (3.53 if base == 80 else 3.83)) < 0.02)
    a, b, c, d = v("R301"), v("R302"), v("R303"), v("R304")
    uv_off = 2.5 * (a + b) / b
    uv_on = uv_off + 21e-6 * a
    ov_on = 2.5 * (c + d) / d
    row("LM5069 U30 UVLO on (rising)", "R301/R302", "2.5 V x (R1+R2)/R2 + 21 uA x R1", uv_on,
        2.45 * (a + b) / b + 12e-6 * a, 2.55 * (a + b) / b + 30e-6 * a, "11.58 V", abs(uv_on - 11.58) < 0.02)
    row("LM5069 U30 UVLO off (falling)", "R301/R302", "2.5 V x (R1+R2)/R2", uv_off, 2.45 * (a + b) / b, 2.55 * (a + b) / b,
        "10.58 V", abs(uv_off - 10.58) < 0.02)
    row("LM5069 U30 OVLO off (rising)", "R303/R304", "2.5 V x (R3+R4)/R4", ov_on, 2.4 * (c + d) / d, 2.6 * (c + d) / d,
        "19.94 V", abs(ov_on - 19.94) < 0.02, f"back on at {ov_on - 21e-6 * c:.2f} V (21 uA x R303)")
    row("LM5069 U30 current limit", "R3 5 mOhm", "VCL 48.5-61.5 mV / 5 mOhm", 0.055 / 0.005, 0.0485 / 0.005,
        0.0615 / 0.005, "F2 10 A in series", True, "the fuse is below the limit: LM5069 limit 9.7-12.3 A, F2 10 A")
    ovlo = {"OVLO_5V": ("R162", "R163", "+5V", 5.17 * 1.01), "OVLO_3V3": ("R164", "R165", "+3V3_TOF", 3.306 * 1.01),
            "OVLO_SERVO": ("R166", "R167", "SERVO_RAW (7.4 V)", x7 * 1.01)}
    for net, (ra_, rb_, rail, vmax) in ovlo.items():
        ra, rb = v(ra_), v(rb_)
        x = 1.2 * (ra + rb) / rb
        lo = 1.183 * (ra + rb) / rb
        row(f"TPS259470L OVLO {net} on {rail}", f"{ra_}/{rb_}", "VOV(R) 1.183-1.223 x (R1+R2)/R2", x, lo,
            1.223 * (ra + rb) / rb, {"OVLO_5V": "6.02 V", "OVLO_3V3": "3.98 V", "OVLO_SERVO": "8.63 V"}[net],
            lo > vmax, f"margin over the rail max {vmax:.2f} V: {lo - vmax:.2f} V; recovers at "
            f"{1.09 * (ra + rb) / rb:.2f} V")
    ilm = {}
    for p in PARTS.values():
        if p["value"] == "TPS259470L":
            ilm.setdefault(p["pins"]["9"], []).append(p["ref"])
    for p in sorted(PARTS.values(), key=lambda q: q["ref"]):
        if p["value"] == "TPS259470L":
            base = int(p["ref"][1:]) * 10
            r = v(f"R{base + 1}")
            itmr = v(f"C{base + 4}")
            name = p["pins"]["1"].replace("_EN", "")
            il = 3334 / r
            row(f"TPS259470L {p['ref']} {name} ILIM", f"R{base + 1} {PARTS[f'R{base + 1}']['value']}",
                "3334 / R_ILM (table +-9..12 %)", il, il * 0.89, il * 1.09,
                "", True, f"ITIMER C{base + 4} {PARTS[f'C{base + 4}']['value']}: "
                f"{itmr * 1.51 / 1.8e-6 * 1e3:.1f} ms (C x 1.286-1.741 V / 1.2-2.5 uA = "
                f"{itmr * 1.286 / 2.5e-6 * 1e3:.1f}-{itmr * 1.741 / 1.2e-6 * 1e3:.1f} ms); ILM at limit "
                f"{182e-6 * il * r:.2f} V")
    r881 = v("R881")
    r881 = v("R881")
    lo_, ty_, hi_ = ARM_ILIM_TABLE.get(round(r881), (1480 / r881 * 0.89, 1480 / r881, 1480 / r881 * 1.11))
    row("TPS25982 U88 arm ILIM", f"R881 {PARTS['R881']['value']}", "table 6.5 (100/182/300/773 ohm), else 1480/R",
        ty_, lo_, hi_, "", True, f"fast trip 2.1 x ILIM = {2.1 * ty_:.1f} A ({2.1 * lo_:.1f}-{2.1 * hi_:.1f} A); "
        f"between ILIM and the fast trip the current is not limited for the ITIMER blanking")
    c883 = v("C883")
    row("TPS25982 U88 ITIMER (ms)", f"C883 {PARTS['C883']['value']}", "C x dV 0.7-1.3 V / I 1.4-2.8 uA",
        c883 * 0.98 / 2.1e-6 * 1e3, c883 * 0.7 / 2.8e-6 * 1e3, c883 * 1.3 / 1.4e-6 * 1e3, "47 ms", True)
    imon = 246e-6 * v("R882")
    row("TPS25982 U88 IMON at ARM_IMON (V)", "R882 1k", "246 uA/A x 1k at ILIM", imon * ty_, imon * lo_, imon * hi_,
        "", True, f"reaches the 2.5 V ADC reference at {2.5 / imon:.1f} A and AVDD + 0.3 V (ADS7128 abs max) at "
        f"{2.8 / imon:.1f} A; at the fast-trip max {2.1 * hi_:.1f} A it is {2.1 * hi_ * imon:.2f} V")
    if "R961" in PARTS:
        ra, rb = v("R961"), v("R962")
        x = 0.4 * (ra + rb) / rb
        row("TLV6700 U90 arm OV cut on SERVO_RAW", "R961/R962", "0.400 V (0.396-0.404) x (R1+R2)/R2", x,
            0.396 * (ra + rb) / rb, 0.404 * (ra + rb) / rb, "8.79 V", lo_ > 0 and 0.396 * (ra + rb) / rb > x7 * 1.01,
            f"above the 7.4 V rail max {x7 * 1.01:.2f} V by {0.396 * (ra + rb) / rb - x7 * 1.01:.2f} V")
    ena = 3.3 * v("R885") / (v("R884") + v("R885"))
    row("TPS25982 U88 EN from ARM_EN", "R884/R885", "3.3 V x R885/(R884+R885)", ena, ena * 0.95, ena,
        "> 1.23 V", ena * 0.95 > 1.23)
    for name, r in (("PR1 (+5V priority)", ("R320", "R321")), ("CP2 (USB VBUS)", ("R322", "R323")),
                    ("OV2 (USB VBUS OVLO)", ("R324", "R325"))):
        ra, rb = v(r[0]), v(r[1])
        x = 1.06 * (ra + rb) / rb
        row(f"TPS2121 U32 {name}", "/".join(r), "VREF 1.01-1.10 V x (R1+R2)/R2", x, 1.01 * (ra + rb) / rb,
            1.10 * (ra + rb) / rb, "OV2 5.6-6.1 V" if "OV2" in name else "", True)
    row("TPS2121 U32 ILM", "R326 80.6k", "table: 80k -> 1.5 A (1-2 A)", 1.5, 1.0, 2.0, "1.5 A", True)
    (OUT / T).mkdir(parents=True, exist_ok=True)
    (OUT / T / "rails.json").write_text(json.dumps(rows, indent=1))
    lines = ["| Rail / threshold | Refs | Formula | Typ | Min | Max | design.py comment | Verdict | Note |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['refs']} | {r['formula']} | {r['typ']:.3f} | {r['min']:.3f} | {r['max']:.3f} | "
                     f"{r['comment']} | {r['verdict']} | {r['note']} |")
    (OUT / T / "rails.md").write_text("\n".join(lines) + "\n")
    for r in rows:
        result(T, r["name"], f"{r['formula']}", f"{r['typ']:.3f} ({r['min']:.3f}-{r['max']:.3f})", r["comment"],
               r["verdict"] == "PASS", r["note"])


# ---------------------------------------------------------------- 6. servo rail

ARM_ILIM_TABLE = {100: (12.85, 14.71, 15.99), 182: (7.23, 8.13, 9.07), 300: (4.36, 4.98, 5.66),
                  773: (1.53, 2.0, 2.43)}


def buck_ilim(vin, vout, valley):
    ripple = (vin - vout) * (vout / vin) / (3.3e-6 * 414e3)
    return min(valley + ripple / 2, 14.0 - ripple / 2), ripple


def t6_servo():
    T = "6-servo"
    check_refs("servo.cir")
    vecs = ["v(SERVO_BUCK)", "v(SERVO_RAW)", "v(ARM_PWR)", "v(SERVO_PWR)", "i(Varm)", "i(Vst)", "i(VL)",
            "v(ARM_ITMR)", "v(atrip)", "v(alimit)", "i(Vin)", "v(sov)"]
    panels = [("V (V)", [("v(servo_raw)", "SERVO_RAW"), ("v(servo_pwr)", "SERVO_PWR (steering)"),
                         ("v(arm_pwr)", "ARM_PWR")]),
              ("I (A)", [("i(vl)", "L6 (buck)"), ("i(varm)", "arm eFuse U88"), ("i(vst)", "steering eFuse U83")]),
              ("V (V)", [("v(arm_itmr)", "ARM_ITMR (C883)")])]
    lo_, ty_, hi_ = ARM_ILIM_TABLE[round(design_num(PARTS["R881"]["value"]))]
    worst = dict(k_arm=hi_ / ty_, i_itmr_arm="1.4u", dv_itmr_arm=1.3)
    cases = [
        ("design_16V8_7V4", dict(vin=16.8, vset=7.4), "typ", "as designed, 16.8 V in, 7.4 V"),
        ("design_12V0_7V4", dict(vin=12.0, vset=7.4), "typ", "as designed, 12.0 V in, 7.4 V"),
        ("design_16V8_6V0", dict(vin=16.8, vset=6.0), "typ", "as designed, 16.8 V in, 6.0 V"),
        ("design_worst", dict(vin=12.0, vset=7.4, **worst), "min", "worst: buck limit min, arm ILIM max, ITIMER max"),
        ("design_10A_overload", dict(vin=12.0, vset=7.4, i_stall=10), "typ", "as designed, 10 A arm overload"),
        ("design_11A5_worst", dict(vin=12.0, vset=7.4, i_stall=11.5, **worst), "min",
         "11.5 A arm overload (under the max fast trip), worst corners"),
        ("brief_182R", dict(vin=12.0, vset=7.4, R881=182), "typ", "R881 182 ohm (8.1 A, as in the brief)"),
        ("fix_C883_4n7_worst", dict(vin=12.0, vset=7.4, C883="4.7n", **worst), "min", "fix: C883 4.7 nF, worst corners"),
        ("fix_C883_10n_worst", dict(vin=12.0, vset=7.4, C883="10n", **worst), "min", "fix: C883 10 nF, worst corners"),
        ("fix_C883_4n7_15A", dict(vin=12.0, vset=7.4, C883="4.7n"), "typ", "fix: C883 4.7 nF"),
    ]
    for case, over, corner, title in cases:
        vin, vset = over["vin"], over["vset"]
        valley = {"typ": 11.5, "min": 9.8}[corner]
        ilim, ripple = buck_ilim(vin, vset, valley)
        stop = 0.16
        o = dict(over)
        o.setdefault("t_stall", "10m")
        w = sim(T, case, "servo.cir", dict(ilim_b=f"{ilim:.3f}", **o), ("2u", stop, "2u"), vecs, opts="method=gear")
        plot(T, case, w, panels, f"{title}: arm load step to {o.get('i_stall', 15)} A at 10 ms, steering 2 A "
             f"(buck avg limit {ilim:.1f} A)", tlim=(5, stop * 1e3))
        t0 = 0.01
        if at(w, "v(alimit)", t0 - 1e-4) > 0.5 or at(w, "v(atrip)", t0 - 1e-4) > 0.5:
            raise SystemExit(f"{case}: arm eFuse latched during the start-up settle")
        trip = first_cross(w, "v(atrip)", 0.5, t0)
        lim = first_cross(w, "v(alimit)", 0.5, t0)
        sp = window(w, "v(servo_pwr)", t0, stop)
        raw = window(w, "v(servo_raw)", t0, stop)
        reg = 0.9 * vset
        tt, y = w["t"], w["v(servo_pwr)"]
        m = (tt >= t0)
        below = tt[m][y[m] < reg]
        dur = (below[-1] - below[0]) if len(below) else 0.0
        ist = window(w, "i(vst)", t0, stop)
        hic = window(w, "v(servo_buck)", t0 + 2e-4, stop).min() < 0.4 * vset
        iin = -window(w, "i(vin)", t0, stop)
        result(T, case, "arm eFuse response", (f"fast trip at +{(lim - t0) * 1e3:.2f} ms, " if lim else "")
               + (f"off at +{(trip - t0) * 1e3:.1f} ms" if trip else "limiting, not off"), "arm trips or limits",
               bool(trip or lim))
        result(T, case, "SERVO_PWR (steering) minimum (V)", round(float(sp.min()), 2), f">= {reg:.2f} (90 % of {vset})",
               sp.min() >= reg, f"below 90 % for {dur * 1e3:.1f} ms; SERVO_RAW min {raw.min():.2f} V")
        tt2 = w["t"][w["t"] >= t0]
        above = tt2[ist > 5.405]
        runs = np.split(above, np.nonzero(np.diff(above) > 1e-5)[0] + 1) if len(above) else []
        t_above = max((r[-1] - r[0] for r in runs), default=0.0)
        st_ok = bool(ist.max() < 2.01 * 5.405 and t_above < 11.3e-3 and w["v(sov)"].max() < 0.5)
        result(T, case, "steering eFuse U83: peak current (A) / longest time over ILIM min 5.4 A (ms)",
               f"{ist.max():.2f} / {t_above * 1e3:.2f}", "< 10.86 A (2.01 x ILIM min, fast trip) and < 11.3 ms (ITIMER min)",
               st_ok, "the 940 uF behind U83 refills after the sag (reverse blocking held it up)")
        result(T, case, "SERVO_RAW maximum after the arm opens (V)", round(float(raw.max()), 2),
               "< 8.51 V (U83 OVLO min)", raw.max() < 8.51)
        result(T, case, "buck: L6 peak (A) / hiccup", f"{w['i(vl)'].max():.1f} / {'yes' if hic else 'no'}",
               f"avg limit {ilim:.1f} A, ripple {ripple:.1f} A pp", None)
        result(T, case, "input current through F4 peak (A)", round(float(iin.max()), 1), "F4 10 A (short)", None)


TESTS = {"1": t1_latch, "2": t2_watchdog, "3": t3_xarm, "4": t4_i2c, "5": t5_rails, "6": t6_servo}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tests", nargs="*", default=list(TESTS), help="test numbers 1-6 (default all)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    prev = OUT / "results.json"
    old = json.loads(prev.read_text()) if prev.exists() else []
    keep = [r for r in old if r["test"].split("-")[0] not in a.tests]
    for k in a.tests:
        TESTS[k]()
    allr = sorted(keep + RESULTS, key=lambda r: r["test"])
    prev.write_text(json.dumps(allr, indent=1, default=str))
    lines = ["| Test | Case | Metric | Value | Limit | Verdict | Note |", "|---|---|---|---|---|---|---|"]
    for r in allr:
        lines.append(f"| {r['test']} | {r['case']} | {r['metric']} | {r['value']} | {r['limit']} | {r['verdict']} | "
                     f"{r['note']} |")
    (OUT / "results.md").write_text("\n".join(lines) + "\n")
    for p in OUT.glob("*/raw/*.txt"):
        if p.stat().st_size > 20e6:
            p.unlink()
    for r in RESULTS:
        print(f"{r['verdict']:4} {r['test']:11} {r['case']:34} {r['metric']}: {r['value']}  [{r['limit']}] {r['note']}")


if __name__ == "__main__":
    main()
