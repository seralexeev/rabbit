import argparse
import json
import math
import resource
import threading
import time
from pathlib import Path

import cuvslam
import cv2
import numpy as np


def parse_args():
    p = argparse.ArgumentParser(description="cuVSLAM on a bench dump (see README)")
    p.add_argument("dump")
    p.add_argument("out", help="output prefix")
    p.add_argument("--mode", choices=("stereo", "inertial"), default="inertial")
    p.add_argument("--slam", action="store_true", help="OdometryWithSlam (loop closures, map)")
    p.add_argument("--save-map", help="folder to save the SLAM map to at the end")
    p.add_argument("--localize", help="saved map folder to localize in")
    p.add_argument("--guess", help="prior for --localize: 'x y z qx qy qz qw' (IMAGE frame) or a TUM file "
                                   "(the pose nearest to the localization time is used)")
    p.add_argument("--guess-noise", type=float, nargs=2, default=(0.0, 0.0), metavar=("M", "DEG"),
                   help="perturb the prior by M metres (horizontal) and DEG degrees (yaw)")
    p.add_argument("--loc-radius", type=float, default=1.0)
    p.add_argument("--loc-step", type=float, default=0.25)
    p.add_argument("--loc-angle-deg", type=float, default=10.0)
    p.add_argument("--loc-start", type=float, default=0.0, help="seconds into the dump of the first attempt")
    p.add_argument("--loc-retry", type=float, default=2.0, help="seconds between attempts")
    p.add_argument("--async-slam", action="store_true")
    p.add_argument("--async-sba", action="store_true", help="bundle adjustment in a background thread (live default)")
    p.add_argument("--imu-noise", type=float, nargs=4, default=(2.0e-4, 4.0e-6, 1.6e-3, 2.0e-4),
                   metavar=("GYR_N", "GYR_RW", "ACC_N", "ACC_RW"))
    p.add_argument("--frames", type=int, default=0)
    return p.parse_args()


def pose_from_matrix(m):
    m = np.asarray(m, dtype=float)
    r = m[:3, :3]
    w = math.sqrt(max(0.0, 1 + r[0, 0] + r[1, 1] + r[2, 2])) / 2
    x = math.copysign(math.sqrt(max(0.0, 1 + r[0, 0] - r[1, 1] - r[2, 2])) / 2, r[2, 1] - r[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1 - r[0, 0] + r[1, 1] - r[2, 2])) / 2, r[0, 2] - r[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1 - r[0, 0] - r[1, 1] + r[2, 2])) / 2, r[1, 0] - r[0, 1])
    return cuvslam.Pose(rotation=[x, y, z, w], translation=m[:3, 3].tolist())


def make_rig(meta, args):
    cams = []
    for i in range(2):
        c = cuvslam.Camera()
        c.size = [meta["width"], meta["height"]]
        c.focal = [meta["fx"], meta["fy"]]
        c.principal = [meta["cx"], meta["cy"]]
        if i == 1:
            c.rig_from_camera = cuvslam.Pose(rotation=[0, 0, 0, 1], translation=[meta["baseline"], 0, 0])
        cams.append(c)
    imus = []
    if args.mode == "inertial":
        imu = cuvslam.ImuCalibration()
        imu.rig_from_imu = pose_from_matrix(meta["T_cam_imu"])
        imu.gyroscope_noise_density, imu.gyroscope_random_walk, imu.accelerometer_noise_density, \
            imu.accelerometer_random_walk = args.imu_noise
        imu.frequency = 400
        imus.append(imu)
    return cuvslam.Rig(cams, imus)


def tum(t_ns, pose):
    t, q = pose.translation, pose.rotation
    return f"{t_ns / 1e9:.9f} {t[0]:.5f} {t[1]:.5f} {t[2]:.5f} {q[0]:.6f} {q[1]:.6f} {q[2]:.6f} {q[3]:.6f}\n"


def load_guess(spec, t_ns):
    vals = spec.split()
    if len(vals) == 7:
        v = [float(x) for x in vals]
        return cuvslam.Pose(translation=v[:3], rotation=v[3:])
    data = np.loadtxt(spec, ndmin=2)
    row = data[np.argmin(np.abs(data[:, 0] - t_ns / 1e9))]
    return cuvslam.Pose(translation=row[1:4].tolist(), rotation=row[4:8].tolist())


def perturb(pose, metres, degrees, rng):
    a = rng.uniform(0, 2 * math.pi)
    t = np.array(pose.translation) + metres * np.array([math.cos(a), 0, math.sin(a)])
    yaw = math.radians(degrees) * rng.choice([-1, 1])
    dq = np.array([0, math.sin(yaw / 2), 0, math.cos(yaw / 2)])
    x1, y1, z1, w1 = dq
    x2, y2, z2, w2 = pose.rotation
    q = [w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
         w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2]
    return cuvslam.Pose(translation=t.tolist(), rotation=q)


def mem_available_mb():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024
    return 0.0


def main():
    args = parse_args()
    dump = Path(args.dump)
    meta = json.loads((dump / "meta.json").read_text())
    frames = [line.strip().split(",") for line in (dump / "frames.csv").read_text().splitlines()[1:]]
    frames = [f for f in frames if f[2] and f[3]]
    if args.frames:
        frames = frames[:args.frames]
    imu = np.loadtxt(dump / "imu.csv", delimiter=",", skiprows=1, ndmin=2) if args.mode == "inertial" else None

    mem0 = mem_available_mb()
    odom_cfg = cuvslam.Tracker.OdometryConfig(
        odometry_mode=cuvslam.Tracker.OdometryMode.Inertial if args.mode == "inertial"
        else cuvslam.Tracker.OdometryMode.Multicamera,
        rectified_stereo_camera=True, async_sba=args.async_sba, enable_final_landmarks_export=False)
    slam_cfg = None
    if args.slam or args.save_map or args.localize:
        slam_cfg = cuvslam.Tracker.SlamConfig(sync_mode=not args.async_slam, max_map_size=0)
    tracker = cuvslam.Tracker(make_rig(meta, args), odom_cfg, slam_cfg)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    odom_f = open(f"{out}_odom.txt", "w")
    slam_f = open(f"{out}_slam.txt", "w") if slam_cfg else None
    events = []
    rng = np.random.default_rng(0)
    loc_lock = threading.Lock()
    loc = {"pending": False, "done": False, "result": None, "requested_ns": 0, "attempts": 0, "finished_ns": 0}
    settings = cuvslam.Tracker.SlamLocalizationSettings(
        horizontal_search_radius=args.loc_radius, vertical_search_radius=0.25, horizontal_step=args.loc_step,
        vertical_step=0.25, angular_step_rads=math.radians(args.loc_angle_deg))

    track_ms, lost, cpu_track = [], 0, 0.0
    imu_i = 0
    t_first = int(frames[0][0])
    last_attempt = -1e9
    mem_min = mem0
    cpu0, wall0 = time.process_time(), time.monotonic()
    for k, f in enumerate(frames):
        t_ns = int(f[0])
        c0 = time.process_time()
        if imu is not None:
            while imu_i < len(imu) and imu[imu_i, 0] <= t_ns:
                m = cuvslam.ImuMeasurement()
                m.timestamp_ns = int(imu[imu_i, 0])
                m.angular_velocities = imu[imu_i, 1:4].tolist()
                m.linear_accelerations = imu[imu_i, 4:7].tolist()
                tracker.register_imu_measurement(0, m)
                imu_i += 1
        cpu_track += time.process_time() - c0
        images = [cv2.imread(str(dump / f[2]), cv2.IMREAD_GRAYSCALE),
                  cv2.imread(str(dump / f[3]), cv2.IMREAD_GRAYSCALE)]
        t0, c0 = time.perf_counter(), time.process_time()
        est, slam_pose = tracker.track(t_ns, images)
        track_ms.append((time.perf_counter() - t0) * 1000)
        cpu_track += time.process_time() - c0
        if est.world_from_rig is None:
            lost += 1
            events.append({"t": (t_ns - t_first) / 1e9, "event": "lost"})
            continue
        odom_f.write(tum(t_ns, est.world_from_rig.pose))
        with loc_lock:
            localized = loc["done"] and loc["result"] is not None
        if slam_f and (not args.localize or localized):
            slam_f.write(tum(t_ns, slam_pose))

        elapsed = (t_ns - t_first) / 1e9
        if args.localize and not localized:
            with loc_lock:
                ready = not loc["pending"]
            if ready and elapsed >= args.loc_start and elapsed - last_attempt >= args.loc_retry:
                last_attempt = elapsed
                guess = load_guess(args.guess, t_ns)
                if args.guess_noise[0] or args.guess_noise[1]:
                    guess = perturb(guess, *args.guess_noise, rng)
                with loc_lock:
                    loc.update(pending=True, requested_ns=t_ns, attempts=loc["attempts"] + 1)

                def finish(pose, message, t_req=t_ns):
                    with loc_lock:
                        loc["pending"] = False
                        loc["finished_ns"] = t_req
                        if pose is not None:
                            loc.update(done=True, result=pose)
                        events.append({"t": (t_req - t_first) / 1e9, "event": "localize",
                                       "ok": pose is not None, "message": message,
                                       "pose": [[float(x) for x in pose.translation],
                                                [float(x) for x in pose.rotation]] if pose else None})

                tracker.localize_in_map(args.localize, t_ns, guess, images, settings, lambda: None, finish)
        if k % 50 == 0:
            mem_min = min(mem_min, mem_available_mb())
        if k % 300 == 0:
            print(f"{k}/{len(frames)} track p50 {np.median(track_ms[-300:]):.1f} ms lost {lost}", flush=True)

    wall = time.monotonic() - wall0
    if slam_cfg and not args.localize:
        slam_f.close()
        with open(f"{out}_slam_all.txt", "w") as fa:
            for ps in tracker.get_all_slam_poses():
                fa.write(tum(ps.timestamp_ns, ps.pose))
    if args.save_map:
        saved = threading.Event()
        result = {}
        tracker.save_map(args.save_map, lambda ok: (result.update(ok=ok), saved.set()))
        saved.wait(120)
        events.append({"event": "save_map", "ok": result.get("ok")})
    summary = {
        "mode": args.mode, "slam": bool(slam_cfg), "frames": len(frames), "lost": lost,
        "track_ms_p50": round(float(np.median(track_ms)), 2),
        "track_ms_p95": round(float(np.percentile(track_ms, 95)), 2),
        "track_ms_max": round(float(np.max(track_ms)), 2),
        "wall_s": round(wall, 1), "cpu_s": round(time.process_time() - cpu0, 1),
        "duration_s": round((int(frames[-1][0]) - t_first) / 1e9, 1),
        "cpu_track_s": round(cpu_track, 1),
        "cpu_cores_realtime": round(cpu_track / ((int(frames[-1][0]) - t_first) / 1e9), 2),
        "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "system_mem_drop_mb": round(mem0 - mem_min, 0),
        "localize": {k: v for k, v in loc.items() if k != "result"} if args.localize else None,
        "events": [e for e in events if e["event"] != "lost"][:50],
        "lost_times": [e["t"] for e in events if e["event"] == "lost"][:50],
    }
    if args.localize and loc["done"]:
        ok = [e for e in events if e["event"] == "localize" and e["ok"]]
        summary["localized_after_s"] = ok[0]["t"] if ok else None
    Path(f"{out}_summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("events", "lost_times")}, default=float))
    for f in (odom_f, slam_f):
        if f and not f.closed:
            f.close()


if __name__ == "__main__":
    main()
