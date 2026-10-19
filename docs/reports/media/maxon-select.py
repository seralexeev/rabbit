import json, math, re, sys

D = sys.argv[1]
motors = json.load(open(f"{D}/motors.json"))
gears = json.load(open(f"{D}/gearheads.json"))

V_NOM, V_LOW, FOC = 14.5, 13.2, 0.95
WHEEL_D = 0.075
T_CONT, T_PEAK = 0.2, 0.6
V_TARGET = 1.25
I_PEAK_MAX = 8.0
MAX_DIA = 32


def gear_key(name):
    name = re.sub(r"^\d+_", "", name)
    return re.sub(r"\s+", " ", name.upper().replace("/", " ")).strip()


def stages_ok(spec, n):
    if not spec:
        return True
    nums = set()
    for a, b in re.findall(r"(\d)\s*[–-]\s*(\d)", spec):
        nums |= set(range(int(a), int(b) + 1))
    nums |= {int(x) for x in re.findall(r"\d", spec)}
    return n in nums


def compatible(motor, gear):
    g = gear_key(gear["name"])
    fam = g.split()[0] + " " + g.split()[1]
    for mg in motor.get("gears") or []:
        n = gear_key(mg["name"] if isinstance(mg, dict) else mg)
        if not n.startswith(fam):
            continue
        tail_m = set(n.split()[2:])
        tail_g = set(g.split()[2:])
        if (not tail_g or not tail_m or tail_g & tail_m) and stages_ok(mg.get("stages") if isinstance(mg, dict) else None, gear.get("stages")):
            return True
    return False


def speed(m, V, Tm_mNm):
    return m["Kv"] * V * FOC - m["grad"] * Tm_mNm


rows = []
for m in motors:
    if not m.get("Kv") or not m.get("grad") or not m.get("Kt"):
        continue
    if m.get("dia_mm", 99) > MAX_DIA:
        continue
    for g in gears:
        if g.get("dia_mm", 99) > MAX_DIA or not compatible(m, g):
            continue
        eta = (g.get("eff_max") or 80) / 100
        for i in g.get("ratios") or []:
            Tm = T_CONT / (i * eta) * 1000
            Tm_pk = T_PEAK / (i * eta) * 1000
            n_lim = min(x for x in (g.get("n_in_cont"), m.get("max_speed_rpm")) if x)
            n_lim_int = min(x for x in (g.get("n_in_int") or g.get("n_in_cont"), m.get("max_speed_rpm")) if x)
            n_m = min(speed(m, V_NOM, Tm), n_lim)
            n_m_int = min(speed(m, V_NOM, Tm), n_lim_int)
            n_m_low = min(speed(m, V_LOW, Tm), n_lim)
            v = n_m / i * math.pi * WHEEL_D / 60
            v_int = n_m_int / i * math.pi * WHEEL_D / 60
            v_low = n_m_low / i * math.pi * WHEEL_D / 60
            I0 = (m.get("I0_mA") or 0) / 1000
            I_cont = Tm / m["Kt"] + I0
            I_pk = Tm_pk / m["Kt"] + I0
            T_wheel_cont = min(m["TN_mNm"] / 1000 * i * eta, g.get("T_cont_Nm") or 0)
            ok = (
                v_low >= V_TARGET
                and I_cont <= m["IN_A"]
                and T_wheel_cont >= T_CONT
                and (g.get("T_int_Nm") or g.get("T_cont_Nm") or 0) >= T_PEAK
                and I_pk <= min(I_PEAK_MAX, m.get("Ist_A") or 99)
            )
            rows.append({
                "motor": f'{m["family"]} {m["V"]:g}V', "page_m": m["page"], "dia_m": m["dia_mm"],
                "gear": g["name"], "page_g": g["page"], "dia_g": g["dia_mm"], "stages": g.get("stages"),
                "i": i, "L1": g.get("L1_mm"), "v_low": round(v_low, 2), "v": round(v, 2), "v_int": round(v_int, 2),
                "I_cont": round(I_cont, 2), "IN": m["IN_A"], "I_pk": round(I_pk, 2),
                "T_cont_wheel": round(T_wheel_cont, 2), "T_int_gear": g.get("T_int_Nm"),
                "margin_cont": round(T_wheel_cont / T_CONT, 2), "speed_cap": n_m >= n_lim - 1,
                "shaft": g.get("shaft"), "sensors": m.get("sensors"), "ok": ok,
            })

json.dump(rows, open(f"{D}/combos.json", "w"), indent=1)
ok = [r for r in rows if r["ok"]]
print(len(rows), "combos,", len(ok), "pass")
ok.sort(key=lambda r: (-min(r["margin_cont"], 3), -r["v_low"]))
for r in ok[:60]:
    print(f'{r["motor"][:34]:34} | {r["gear"][:14]:14} {r["stages"]}st {r["i"]:>6} | v {r["v_low"]:.2f}/{r["v"]:.2f}/{r["v_int"]:.2f} | I {r["I_cont"]:.2f}/{r["IN"]:.2f} pk {r["I_pk"]:.1f} | Tc {r["T_cont_wheel"]:.2f} Ti {r["T_int_gear"]} | L1 {r["L1"]} | Ø{r["dia_m"]:g}/{r["dia_g"]:g}')

MOTOR_LEN = {156: 40, 158: 56, 159: 56, 160: 56, 161: 42.5, 162: 42.5, 164: 58, 165: 58, 167: 44.5, 168: 44.5,
             169: 44.5, 170: 60, 171: 60, 172: 60, 177: 32, 178: 48.5, 182: 35, 183: 35, 186: 48, 187: 48, 188: 60,
             189: 60, 193: 47, 194: 58.5, 195: 82, 214: 14, 215: 17.2, 216: 17, 217: 20.2, 218: 16.2, 219: 16.2,
             220: 16.2, 221: 18.7, 222: 22.2}
INTEGRATED_ENCODER = set(range(155, 173)) | {193, 194, 195}
LENGTH_BUDGET = 67


def encoder_len(page):
    if 213 <= page <= 217:
        return 1.2
    if 218 <= page <= 222:
        return 1.1
    return 0 if page in INTEGRATED_ENCODER else 8.5


fit = []
for r in ok:
    p = int(r["page_m"])
    if p in MOTOR_LEN and r["L1"]:
        r["len"] = round(r["L1"] + MOTOR_LEN[p] + encoder_len(p), 1)
        if r["len"] <= LENGTH_BUDGET:
            fit.append(r)
print(f"\n{len(fit)} pass and fit {LENGTH_BUDGET} mm behind the plate")
for r in sorted(fit, key=lambda r: (max(r["dia_m"], r["dia_g"]), -r["T_cont_wheel"]))[:40]:
    print(f'{r["motor"][:36]:36} | {r["gear"][:12]:12} {r["stages"]}st {r["i"]:>5} | v {r["v_low"]:.2f}/{r["v"]:.2f} | Tc {r["T_cont_wheel"]:.2f} | len {r["len"]} | Ø{max(r["dia_m"], r["dia_g"]):g}')
