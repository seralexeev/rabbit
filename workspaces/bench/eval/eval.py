"""Tables and plots from bench results.

uv run --with numpy --with matplotlib python eval/eval.py RESULTS_DIR OUT_DIR

RESULTS_DIR/<session>/ holds trajectories (TUM, IMAGE frame) and summaries written by the runners:
  zed_vio.txt + meta.json (from zed_dump), cuvslam_<name>_odom.txt + _summary.json,
  rtab_<name>.csv + _poses.txt + _summary.json, zed_reloc_<name>_status.csv + zed_reloc_<name>.txt
"""
import csv
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load_tum(path):
    d = np.loadtxt(path, ndmin=2)
    return d if d.size else np.zeros((0, 8))


def path_length(p):
    return float(np.sum(np.linalg.norm(np.diff(p[:, 1:4], axis=0), axis=1))) if len(p) > 1 else 0.0


def associate(a, b, tol=0.02):
    idx = np.searchsorted(b[:, 0], a[:, 0])
    ia, ib = [], []
    for i, j in enumerate(idx):
        best = None
        for k in (j - 1, j):
            if 0 <= k < len(b) and abs(b[k, 0] - a[i, 0]) <= tol and (best is None or
                                                                      abs(b[k, 0] - a[i, 0]) < abs(b[best, 0] - a[i, 0])):
                best = k
        if best is not None:
            ia.append(i)
            ib.append(best)
    return np.array(ia, dtype=int), np.array(ib, dtype=int)


def umeyama(src, dst):
    mu_s, mu_d = src.mean(0), dst.mean(0)
    cov = (dst - mu_d).T @ (src - mu_s) / len(src)
    u, _, vt = np.linalg.svd(cov)
    s = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        s[2, 2] = -1
    r = u @ s @ vt
    return r, mu_d - r @ mu_s


def quat_to_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def yaw_of(q):
    f = quat_to_mat(q) @ np.array([0, 0, 1.0])
    return math.degrees(math.atan2(f[0], f[2]))


def ape_vs(ref, est):
    ia, ib = associate(est, ref)
    if len(ia) < 10:
        return None, None
    r, t = umeyama(est[ia, 1:4], ref[ib, 1:4])
    aligned = (r @ est[:, 1:4].T).T + t
    err = np.linalg.norm(aligned[ia] - ref[ib, 1:4], axis=1)
    return float(np.sqrt(np.mean(err ** 2))), aligned


def fmt(v, digits=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def odometry_rows(session_dir):
    rows, plots = [], []
    ref = None
    vio = session_dir / "zed_vio.txt"
    meta = json.loads((session_dir / "meta.json").read_text()) if (session_dir / "meta.json").exists() else {}
    if vio.exists():
        ref = load_tum(vio)
        run = meta.get("run", {})
        rows.append(dict(name="ZED GEN_3 VIO (no area)", traj=ref, lost=None, ms_p50=None, ms_p95=None,
                         cpu=None, rss=None))
        plots.append(("ZED VIO", ref[:, 1:4]))
    if (session_dir / "zed_map.txt").exists():
        rows.append(dict(name="ZED GEN_3 with area memory (mapping)", traj=load_tum(session_dir / "zed_map.txt"),
                         lost=None, ms_p50=None, ms_p95=None, cpu=None, rss=None))
    for summ in sorted(session_dir.glob("cuvslam_*_summary.json")):
        name = summ.name[len("cuvslam_"):-len("_summary.json")]
        s = json.loads(summ.read_text())
        for kind in ("odom", "slam_all"):
            f = session_dir / f"cuvslam_{name}_{kind}.txt"
            if not f.exists() or f.stat().st_size == 0:
                continue
            tr = load_tum(f)
            label = f"cuVSLAM {name}" + (" (SLAM)" if kind == "slam_all" else "")
            cpu = s.get("cpu_cores_realtime")
            gpu_file = session_dir / f"cuvslam_{name}_gpu.json"
            gpu = json.loads(gpu_file.read_text()).get("gpu_peak_mb") if gpu_file.exists() else None
            rows.append(dict(name=label, traj=tr, lost=s.get("lost"), ms_p50=s.get("track_ms_p50"),
                             ms_p95=s.get("track_ms_p95"), cpu=cpu, rss=s.get("max_rss_mb"), gpu=gpu))
    out = []
    for r in rows:
        tr = r["traj"]
        gap = float(np.linalg.norm(tr[-1, 1:4] - tr[0, 1:4])) if len(tr) else None
        length = path_length(tr)
        rmse, aligned = ape_vs(ref, tr) if ref is not None and r["traj"] is not ref else (None, None)
        if aligned is not None:
            plots.append((r["name"], aligned))
        out.append([r["name"], len(tr), fmt(length), fmt(gap), fmt(100 * gap / length if length else None, 1),
                    fmt(rmse, 3), fmt(r["lost"]), fmt(r["ms_p50"], 1), fmt(r["ms_p95"], 1), fmt(r["cpu"]),
                    fmt(r["rss"], 0), fmt(r.get("gpu"))])
    return out, plots


def localization_rows(session_dir):
    out, plots = [], []
    for summ in sorted(session_dir.glob("rtab_*_summary.json")):
        name = summ.name[len("rtab_"):-len("_summary.json")]
        s = json.loads(summ.read_text())
        rows = list(csv.DictReader(open(session_dir / f"rtab_{name}.csv")))
        if not rows:
            continue
        t0 = int(rows[0]["t_ns"])
        matched = [r for r in rows if int(r["loop_id"]) or int(r["proximity_id"])]
        first = (int(matched[0]["t_ns"]) - t0) / 1e9 if matched else None
        after = [r for r in rows if matched and int(r["t_ns"]) >= int(matched[0]["t_ns"])]
        frac = len([r for r in after if int(r["loop_id"]) or int(r["proximity_id"])]) / len(after) if after else 0
        jumps, prev = 0, None
        for r in matched:
            p = np.array([float(r["map_x"]), float(r["map_z"])])
            if prev is not None and np.linalg.norm(p - prev[0]) > 0.5 and int(r["t_ns"]) - prev[1] < 5e9:
                jumps += 1
            prev = (p, int(r["t_ns"]))
        corr = np.array([[float(r["corr_norm"]), float(r["corr_yaw_deg"])] for r in matched]) if matched else None
        spread = float(np.ptp(corr[:, 0])) if corr is not None and len(corr) > 1 else None
        cpu = s["cpu_s"] / s["wall_s"] if s.get("wall_s") else None
        out.append([f"RTAB-Map {name}", s["mode"], s["processed"], fmt(first, 1), fmt(100 * frac, 0),
                    s.get("inter_session", 0), jumps, fmt(spread), fmt(s["process_ms_p50"], 0),
                    fmt(s["process_ms_p95"], 0), fmt(cpu), fmt(s["max_rss_mb"], 0)])
        poses = session_dir / f"rtab_{name}_poses.txt"
        if poses.exists() and name.startswith("loc_in"):
            plots.append((f"RTAB-Map {name}", load_tum(poses)[:, 1:4]))
    for summ in sorted(session_dir.glob("cuvslam_*_summary.json")):
        s = json.loads(summ.read_text())
        if not s.get("localize"):
            continue
        name = summ.name[len("cuvslam_"):-len("_summary.json")]
        loc = s["localize"]
        cpu = s["cpu_s"] / s["wall_s"] if s.get("wall_s") else None
        out.append([f"cuVSLAM {name}", "localize_in_map", s["frames"], fmt(s.get("localized_after_s"), 1),
                    "—", "—", "—", f"{loc['attempts']} attempts", fmt(s["track_ms_p50"], 1),
                    fmt(s["track_ms_p95"], 1), fmt(cpu), fmt(s["max_rss_mb"], 0)])
        f = session_dir / f"cuvslam_{name}_slam.txt"
        if f.exists() and f.stat().st_size:
            plots.append((f"cuVSLAM {name}", load_tum(f)[:, 1:4]))
    for st in sorted(session_dir.glob("zed_reloc*_status.csv")):
        name = st.name[:-len("_status.csv")]
        rows = list(csv.DictReader(open(st)))
        if not rows:
            continue
        t0 = int(rows[0]["t_ns"])
        good = {"KNOWN_MAP", "LOOP_CLOSED", "MAP_UPDATE", "OK"}
        first = next(((int(r["t_ns"]) - t0) / 1e9 for r in rows if r["spatial_memory"] in good), None)
        frac = sum(r["spatial_memory"] in good for r in rows) / len(rows)
        grab = np.array([float(r["grab_ms"]) for r in rows])
        traj = session_dir / f"{name}.txt"
        jumps = 0
        if traj.exists():
            tr = load_tum(traj)
            if len(tr) > 1:
                step = np.linalg.norm(np.diff(tr[:, [1, 3]], axis=0), axis=1)
                jumps = int(np.sum(step > 0.5))
                plots.append((f"ZED {name}", tr[:, 1:4]))
        out.append([f"ZED GEN_3 {name}", "area localization", len(rows), fmt(first, 1), fmt(100 * frac, 0), "—",
                    jumps, "—", fmt(float(np.median(grab)), 0), fmt(float(np.percentile(grab, 95)), 0), "—", "—"])
    return out, plots


def to_mat(row):
    m = np.eye(4)
    m[:3, :3] = quat_to_mat(row[4:8])
    m[:3, 3] = row[1:4]
    return m


def map_from_odom(map_poses, odom, after_ns=0):
    """Median map<-odom over frames after after_ns (translation median, rotation of the median-yaw frame)."""
    ts = []
    for r in map_poses:
        if r[0] * 1e9 < after_ns:
            continue
        o = odom[np.argmin(np.abs(odom[:, 0] - r[0]))]
        ts.append(to_mat(r) @ np.linalg.inv(to_mat(o)))
    if not ts:
        return None
    yaws = np.array([math.atan2(t[0, 2], t[2, 2]) for t in ts])
    m = ts[int(np.argsort(yaws)[len(yaws) // 2])].copy()
    m[:3, 3] = np.median([t[:3, 3] for t in ts], axis=0)
    return m


def diff(a, b):
    d = np.linalg.inv(a) @ b
    ang = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(d[:3, :3]) - 1) / 2))))
    return f"{np.linalg.norm(d[:3, 3]):.3f} m / {ang:.2f}°"


def loc_transform(results, session, mapped, odom_name):
    csv_path = results / session / f"rtab_loc_in_{mapped}_{odom_name}.csv"
    poses = results / session / f"rtab_loc_in_{mapped}_{odom_name}_poses.txt"
    odom = results / session / ("zed_vio.txt" if odom_name == "vio" else f"{odom_name}_odom.txt")
    if not (csv_path.exists() and poses.exists() and odom.exists()):
        return None
    rows = [r for r in csv.DictReader(open(csv_path)) if int(r["loop_id"]) or int(r["proximity_id"])]
    if not rows:
        return None
    return map_from_odom(load_tum(poses), load_tum(odom), int(rows[0]["t_ns"]))


def cross_checks(results):
    sessions = sorted(p.name for p in results.iterdir() if p.is_dir())
    rows = []
    for a in sessions:
        for b in sessions:
            if a >= b:
                continue
            for odom_name in ("vio", "cuvslam_stereo", "cuvslam_inertial"):
                ab, ba = loc_transform(results, a, b, odom_name), loc_transform(results, b, a, odom_name)
                if ab is not None and ba is not None:
                    rows.append([f"RTAB-Map {a} in {b} ∘ {b} in {a} ({odom_name})", "identity", diff(ab @ ba, np.eye(4))])
            for x, y in ((a, b), (b, a)):
                rt = loc_transform(results, x, y, "cuvslam_inertial")
                for summ in sorted((results / x).glob(f"cuvslam_loc_in_{y}_*_summary.json")):
                    name = summ.name[:-len("_summary.json")]
                    sl, od = results / x / f"{name}_slam.txt", results / x / f"{name}_odom.txt"
                    loc = json.loads(summ.read_text()).get("localize") or {}
                    if rt is None or not loc.get("done") or not sl.exists() or sl.stat().st_size == 0:
                        rows.append([f"cuVSLAM {name[len('cuvslam_'):]}", f"RTAB-Map {x} in {y}", "not localized"])
                        continue
                    cu = map_from_odom(load_tum(sl), load_tum(od), loc["finished_ns"])
                    rows.append([f"cuVSLAM {name[len('cuvslam_'):]}", f"RTAB-Map {x} in {y} (cuvslam_inertial)",
                                 diff(rt, cu)])
            for x, y in ((a, b), (b, a)):
                zed_status = results / x / f"zed_reloc_in_{y}_status.csv"
                rt = loc_transform(results, x, y, "vio")
                if not zed_status.exists() or rt is None:
                    continue
                st = list(csv.DictReader(open(zed_status)))
                known = [int(r["t_ns"]) for r in st if r["spatial_memory"] == "KNOWN_MAP"]
                if not known:
                    continue
                z = map_from_odom(load_tum(results / x / f"zed_reloc_in_{y}.txt"), load_tum(results / x / "zed_vio.txt"),
                                  known[0] + 5e9)
                rows.append([f"RTAB-Map {x} in {y} (vio)", f"ZED GEN_3 {x} in {y}", diff(rt, z)])
    return rows


def depth_rows(results):
    rows = []
    for f in sorted((results / "depth").glob("*.json")) if (results / "depth").exists() else []:
        if f.name.endswith("_gpu.json"):
            continue
        d = json.loads(f.read_text())
        g = results / "depth" / f"{f.stem}_gpu.json"
        gpu = json.loads(g.read_text()).get("gpu_peak_mb") if g.exists() else None

        def bins(key, field):
            v = d.get(key, {})
            return " / ".join(fmt(v.get(str(b), {}).get(field), 0) for b in (1, 2, 3, 4, 5))

        rows.append([f"{d['mode']} {d['precision_requested']}", d["precision_used"].split(".")[-1], d["frames"],
                     fmt(d["open_s"], 0), fmt(d["grab_retrieve_ms_p50"], 1), fmt(d["grab_retrieve_ms_p95"], 1),
                     fmt(gpu), fmt(d["valid_pct"], 1), bins("floor_rms", "sigma_mm_median"),
                     bins("wall_rms", "sigma_mm_median"), fmt(d["flying_per_mille"]),
                     bins("temporal", "std_mm_median")])
    return rows


def wake_rows(results):
    wake = results.parent / "results_wake"
    groups = {}
    for summ in sorted(wake.glob("*_summary.json")) if wake.exists() else []:
        stem = summ.name[:-len("_summary.json")]
        head, off = stem.rsplit("_", 1)
        groups.setdefault(head, []).append((int(off), stem))
    rows = []
    for head, runs in sorted(groups.items()):
        q, rest = head.split("_in_", 1)
        m, odom_name = rest.split("_", 1)
        ref = loc_transform(results, q, m, odom_name)
        odom = results / q / ("zed_vio.txt" if odom_name == "vio" else f"{odom_name}_odom.txt")
        firsts, wrong, never, per = [], 0, 0, []
        for off, stem in sorted(runs):
            rr = [r for r in csv.DictReader(open(wake / f"{stem}.csv")) if int(r["loop_id"]) or int(r["proximity_id"])]
            if not rr:
                never += 1
                per.append(f"{off}:—")
                continue
            t0 = int(next(csv.DictReader(open(wake / f"{stem}.csv")))["t_ns"])
            first = (int(rr[0]["t_ns"]) - t0) / 1e9
            firsts.append(first)
            mo = map_from_odom(load_tum(wake / f"{stem}_poses.txt")[:], load_tum(odom), int(rr[0]["t_ns"]))
            bad = False
            if ref is not None and mo is not None:
                d = np.linalg.inv(ref) @ mo
                ang = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(d[:3, :3]) - 1) / 2))))
                bad = np.linalg.norm(d[:3, 3]) > 0.3 or ang > 10
            wrong += bad
            per.append(f"{off}:{first:.1f}" + ("✗" if bad else ""))
        rows.append([f"{q} in {m} ({odom_name})", len(runs), len(runs) - never, fmt(float(np.median(firsts)) if firsts else None, 1),
                     fmt(float(np.max(firsts)) if firsts else None, 1), wrong, " ".join(per)])
    return rows


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def plot(plots, title, path):
    fig, ax = plt.subplots(figsize=(7, 7))
    for name, p in plots:
        ax.plot(p[:, 0], -p[:, 2], label=name, lw=1.2)
        ax.plot(p[0, 0], -p[0, 2], "o", ms=4, color=ax.lines[-1].get_color())
    ax.set_aspect("equal")
    ax.set_xlabel("x, m (right)")
    ax.set_ylabel("−z, m")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def main():
    results, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    md = ["# Localization bench", "",
          "Poses are in the IMAGE frame (x right, y down, z forward); plots are top-down (x, −z). cuVSLAM and ZED "
          "runs are on the Jetson; RTAB-Map runs are on the Mac (arm64 container) unless named `jetson_*`. "
          "CPU cores = CPU seconds per second (cuVSLAM: tracker only, per second of recording).", ""]
    odo_header = ["candidate", "poses", "path m", "start–end m", "start–end %", "APE vs ZED VIO m", "lost",
                  "ms p50", "ms p95", "CPU cores", "RSS MB", "GPU MB"]
    loc_header = ["candidate", "mode", "frames", "first loc s", "localized %", "inter-session links",
                  "jumps >0.5 m", "map→odom spread m", "ms p50", "ms p95", "CPU cores", "RSS MB"]
    for session in sorted(p for p in results.iterdir() if p.is_dir()):
        odo, odo_plots = odometry_rows(session)
        loc, loc_plots = localization_rows(session)
        if not odo and not loc:
            continue
        md += [f"## {session.name}", ""]
        if odo:
            md += ["### Odometry", "", table(odo_header, odo), "", f"![odometry]({session.name}_odometry.png)", ""]
            plot(odo_plots, f"{session.name}: odometry (aligned to ZED VIO)", out / f"{session.name}_odometry.png")
        if loc:
            md += ["### Localization", "", table(loc_header, loc), ""]
            if loc_plots:
                md += [f"![localization]({session.name}_localization.png)", ""]
                plot(loc_plots, f"{session.name}: map frame", out / f"{session.name}_localization.png")
    depth = depth_rows(results)
    if depth:
        md += ["## ZED depth modes (loop1, HD720, depth at 640×360, robot runtime settings)", "",
               table(["mode", "precision used", "frames", "open s", "grab+retrieve ms p50", "p95", "GPU MB",
                      "valid %", "floor σ mm @1/2/3/4/5 m", "wall σ mm @1/2/3/4/5 m (noisy)", "flying ‰",
                      "temporal σ mm @1/2/3/4/5 m"], depth), "",
               "`precision used` is what `get_init_parameters()` returns; for the INT8 run it says FP16, but the SDK log "
               "says `INT8 requested, INT8 in use` (separate `neural_depth_5.4` INT8 engine). `open s` includes the "
               "one-off TensorRT engine build. grab+retrieve includes lossless SVO decoding on the CPU. GPU MB is the "
               "nvmap peak of the container. Check the run log for other GPU work overlapping the timings.", ""]
    wake = wake_rows(results)
    if wake:
        md += ["## Wake-up simulation (RTAB-Map localization started every 5 s into the session, 15 s each)", "",
               "Wrong = map←odom more than 0.3 m or 10° from the full-session reference. Per start: `offset s:first match s`.", "",
               table(["query in map", "starts", "localized", "first match s median", "max", "wrong", "per start"], wake), ""]
    checks = cross_checks(results)
    if checks:
        md += ["## Cross-checks of map←odom (agreement between independent localizations)", "",
               table(["localization", "compared with", "difference"], checks), ""]
    (out / "results.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
