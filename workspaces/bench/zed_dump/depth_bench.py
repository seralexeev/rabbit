import argparse
import json
import resource
import time
from pathlib import Path

import cv2
import numpy as np
import pyzed.sl as sl

DEPTH_SIZE = (640, 360)
RANGE_BINS = (1, 2, 3, 4, 5)


def parse_args():
    p = argparse.ArgumentParser(description="ZED depth mode benchmark on SVO frames (robot settings)")
    p.add_argument("svo")
    p.add_argument("out", help="output JSON")
    p.add_argument("--mode", choices=("neural_light", "neural", "neural_plus"), default="neural_light")
    p.add_argument("--precision", choices=("fp16", "int8"), default="fp16")
    p.add_argument("--frames", type=int, default=0, help="frames to process from the start (0 = all)")
    p.add_argument("--static", default="", help="frame range 'a:b' where the camera stands still (temporal noise)")
    p.add_argument("--save-every", type=int, default=0, help="also save every Nth depth map as 16-bit mm PNG")
    return p.parse_args()


def open_camera(args):
    init = sl.InitParameters()
    init.set_from_svo_file(args.svo)
    init.svo_real_time_mode = False
    init.camera_resolution = sl.RESOLUTION.HD720
    init.coordinate_units = sl.UNIT.METER
    init.coordinate_system = sl.COORDINATE_SYSTEM.IMAGE
    init.depth_mode = {"neural_light": sl.DEPTH_MODE.NEURAL_LIGHT, "neural": sl.DEPTH_MODE.NEURAL,
                       "neural_plus": sl.DEPTH_MODE.NEURAL_PLUS}[args.mode]
    init.depth_precision = sl.DEPTH_PRECISION.INT8 if args.precision == "int8" else sl.DEPTH_PRECISION.FP16
    init.depth_stabilization = 0
    zed = sl.Camera()
    t0 = time.monotonic()
    status = zed.open(init)
    if status != sl.ERROR_CODE.SUCCESS:
        raise SystemExit(f"open failed: {status}")
    return zed, time.monotonic() - t0


def fit_plane(pts):
    c = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    n = vt[2]
    return n, -n @ c


def ransac_plane(pts, rng, accept, iters=150, thr=0.03):
    best, best_count = None, 0
    if len(pts) < 500:
        return None
    for _ in range(iters):
        s = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(s[1] - s[0], s[2] - s[0])
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n /= norm
        if not accept(n):
            continue
        d = -n @ s[0]
        count = int(np.sum(np.abs(pts @ n + d) < thr))
        if count > best_count:
            best, best_count = (n, d), count
    if best is None:
        return None
    inl = np.abs(pts @ best[0] + best[1]) < thr
    n, d = fit_plane(pts[inl])
    return n, d, best_count


def plane_noise(pts, ranges, plane, out):
    n, d = plane[0], plane[1]
    r = pts @ n + d
    band = np.abs(r) < 0.10
    for b in RANGE_BINS:
        m = band & (np.abs(ranges - b) < 0.25)
        if m.sum() >= 200:
            out.setdefault(b, []).append(float(1.4826 * np.median(np.abs(r[m] - np.median(r[m])))))


def flying_pixels(depth, floor_mask):
    valid = np.isfinite(depth) & (depth > 0)
    d = np.where(valid, depth, 0).astype(np.float32)
    k = np.ones((5, 5), np.uint8)
    dmax = cv2.dilate(d, k)
    dmin = cv2.erode(np.where(valid, d, 1e6).astype(np.float32), k)
    span = dmax - dmin
    between = (d - dmin > 0.15 * span) & (dmax - d > 0.15 * span)
    flying = valid & ~floor_mask & (span > 0.3 * np.maximum(dmin, 0.1)) & between
    neighbours = cv2.filter2D(valid.astype(np.float32), -1, np.ones((3, 3), np.float32)) - valid
    isolated = valid & (neighbours < 3)
    nv = max(int(valid.sum()), 1)
    return 1000.0 * flying.sum() / nv, 1000.0 * isolated.sum() / nv


def main():
    args = parse_args()
    zed, open_s = open_camera(args)
    used = zed.get_init_parameters()
    res = sl.Resolution(*DEPTH_SIZE)
    cam = zed.get_camera_information(res).camera_configuration.calibration_parameters.left_cam
    fx, fy, cx, cy = cam.fx, cam.fy, cam.cx, cam.cy
    u, v = np.meshgrid(np.arange(DEPTH_SIZE[0]), np.arange(DEPTH_SIZE[1]))
    rays = np.stack([(u - cx) / fx, (v - cy) / fy, np.ones_like(u, dtype=float)], -1)

    runtime = sl.RuntimeParameters()
    runtime.confidence_threshold = 95
    runtime.texture_confidence_threshold = 100
    depth = sl.Mat()
    static = tuple(int(x) for x in args.static.split(":")) if args.static else None
    stack = []
    grab_ms, retrieve_ms, valid_frac, flying, isolated = [], [], [], [], []
    floor_rms, wall_rms = {}, {}
    rng = np.random.default_rng(0)
    out_dir = Path(args.out).with_suffix("")
    if args.save_every:
        out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    while not args.frames or n < args.frames:
        t0 = time.perf_counter()
        err = zed.grab(runtime)
        t1 = time.perf_counter()
        if err == sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
            break
        if err != sl.ERROR_CODE.SUCCESS:
            n += 1
            continue
        zed.retrieve_measure(depth, sl.MEASURE.DEPTH, sl.MEM.CPU, res)
        d = depth.get_data().copy()
        t2 = time.perf_counter()
        grab_ms.append((t1 - t0) * 1000)
        retrieve_ms.append((t2 - t1) * 1000)
        frame = zed.get_svo_position()

        batch = []
        up = np.array([0.0, -1.0, 0.0])
        if zed.get_sensors_data_batch(batch) == sl.ERROR_CODE.SUCCESS and batch:
            a = np.mean([s.get_imu_data().get_linear_acceleration() for s in batch], axis=0)
            if np.linalg.norm(a) > 5:
                up = a / np.linalg.norm(a)

        valid = np.isfinite(d) & (d > 0)
        valid_frac.append(float(valid.mean()))
        pts = rays[valid] * d[valid][:, None]
        ranges = np.linalg.norm(pts, axis=1)
        floor_mask = np.zeros_like(valid)
        if len(pts) > 2000:
            sub = rng.choice(len(pts), min(len(pts), 20000), replace=False)
            below = pts[sub][pts[sub] @ up < -0.05]
            floor = ransac_plane(below, rng, lambda nn: abs(nn @ up) > 0.97)
            if floor:
                plane_noise(pts, ranges, floor, floor_rms)
                on_floor = np.abs(pts @ floor[0] + floor[1]) < 0.05
                floor_mask[valid] = on_floor
                rest = pts[sub][np.abs(pts[sub] @ floor[0] + floor[1]) > 0.08]
            else:
                rest = pts[sub]
            wall = ransac_plane(rest, rng, lambda nn: abs(nn @ up) < 0.15)
            if wall and wall[2] > 1500:
                plane_noise(pts, ranges, wall, wall_rms)
        f, i = flying_pixels(d, floor_mask)
        flying.append(f)
        isolated.append(i)
        if static and static[0] <= frame < static[1]:
            stack.append(np.where(valid, d, np.nan).astype(np.float32))
        if args.save_every and n % args.save_every == 0:
            cv2.imwrite(str(out_dir / f"{frame:06d}.png"),
                        np.clip(np.nan_to_num(d, nan=0, posinf=0, neginf=0) * 1000, 0, 65535).astype(np.uint16))
        n += 1

    temporal = {}
    if len(stack) >= 10:
        s = np.stack(stack)
        ok = np.mean(np.isfinite(s), axis=0) >= 0.8
        mean = np.nanmean(s, axis=0)
        std = np.nanstd(s, axis=0)
        for b in RANGE_BINS:
            m = ok & (np.abs(mean - b) < 0.25)
            if m.sum() >= 200:
                temporal[b] = {"std_mm_median": round(float(np.median(std[m])) * 1000, 1), "pixels": int(m.sum())}
        temporal["frames"] = len(stack)
        temporal["valid_flicker_pct"] = round(100 * float(np.mean((np.mean(np.isfinite(s), 0) > 0)
                                                                  & (np.mean(np.isfinite(s), 0) < 1))), 2)

    def agg(d):
        return {b: {"sigma_mm_median": round(1000 * float(np.median(v)), 1), "frames": len(v)} for b, v in sorted(d.items())}

    total = np.array(grab_ms) + np.array(retrieve_ms)
    result = {
        "svo": args.svo, "mode": args.mode, "precision_requested": args.precision,
        "precision_used": str(used.depth_precision), "depth_mode_used": str(used.depth_mode), "frames": n,
        "open_s": round(open_s, 1),
        "grab_ms_p50": round(float(np.median(grab_ms)), 1), "grab_ms_p95": round(float(np.percentile(grab_ms, 95)), 1),
        "grab_retrieve_ms_p50": round(float(np.median(total)), 1),
        "grab_retrieve_ms_p95": round(float(np.percentile(total, 95)), 1),
        "valid_pct": round(100 * float(np.mean(valid_frac)), 1),
        "flying_per_mille": round(float(np.mean(flying)), 2), "isolated_per_mille": round(float(np.mean(isolated)), 2),
        "floor_rms": agg(floor_rms), "wall_rms": agg(wall_rms), "temporal": temporal,
        "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    zed.close()


if __name__ == "__main__":
    main()
