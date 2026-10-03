import argparse
import json
import math
import resource
import time
from pathlib import Path

import cv2
import numpy as np
import pyzed.sl as sl

TRACKING = ("none", "vio", "map", "reloc")


def parse_args():
    p = argparse.ArgumentParser(description="Dump an SVO2 into the bench layout (see README).")
    p.add_argument("svo")
    p.add_argument("out")
    p.add_argument("--images", action="store_true", help="write left/right gray PNG, left RGB JPEG")
    p.add_argument("--depth", choices=("none", "neural_light", "neural"), default="none")
    p.add_argument("--every", type=int, default=1, help="write images/depth every Nth frame (IMU and poses always)")
    p.add_argument("--tracking", choices=TRACKING, default="vio",
                   help="vio: GEN_3 without area memory; map: GEN_3 with area memory, saves --area at the end; "
                        "reloc: GEN_3 localization-only against --area")
    p.add_argument("--area", help="area file to save (map) or load (reloc)")
    p.add_argument("--start", type=int, default=0, help="first SVO frame")
    p.add_argument("--frames", type=int, default=0, help="max frames (0 = all)")
    p.add_argument("--imu-fusion", type=int, default=1)
    return p.parse_args()


def open_camera(args):
    init = sl.InitParameters()
    init.set_from_svo_file(args.svo)
    init.svo_real_time_mode = False
    init.coordinate_units = sl.UNIT.METER
    init.coordinate_system = sl.COORDINATE_SYSTEM.IMAGE
    init.depth_mode = {"none": sl.DEPTH_MODE.NONE, "neural_light": sl.DEPTH_MODE.NEURAL_LIGHT,
                       "neural": sl.DEPTH_MODE.NEURAL}[args.depth]
    init.depth_maximum_distance = 10.0
    zed = sl.Camera()
    status = zed.open(init)
    if status != sl.ERROR_CODE.SUCCESS:
        raise SystemExit(f"open failed: {status}")
    if args.tracking != "none":
        tp = sl.PositionalTrackingParameters()
        tp.mode = sl.POSITIONAL_TRACKING_MODE.GEN_3
        tp.enable_imu_fusion = bool(args.imu_fusion)
        tp.enable_area_memory = args.tracking in ("map", "reloc")
        if args.tracking == "reloc":
            tp.area_file_path = args.area
            tp.enable_localization_only = True
        status = zed.enable_positional_tracking(tp)
        if status != sl.ERROR_CODE.SUCCESS:
            raise SystemExit(f"tracking failed: {status}")
    if args.start:
        zed.set_svo_position(args.start)
    return zed


def calibration(zed):
    info = zed.get_camera_information()
    conf = info.camera_configuration
    cal = conf.calibration_parameters
    left, right = cal.left_cam, cal.right_cam
    imu = info.sensors_configuration.camera_imu_transform
    return {
        "serial": info.serial_number,
        "model": str(info.camera_model),
        "width": conf.resolution.width,
        "height": conf.resolution.height,
        "fps": conf.fps,
        "fx": left.fx, "fy": left.fy, "cx": left.cx, "cy": left.cy,
        "right": {"fx": right.fx, "fy": right.fy, "cx": right.cx, "cy": right.cy},
        "baseline": cal.get_camera_baseline(),
        "T_cam_imu": imu.m.tolist(),
        "svo_frames": zed.get_svo_number_of_frames(),
    }


def main():
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.images:
        for d in ("left", "right", "rgb"):
            (out / d).mkdir(exist_ok=True)
    if args.depth != "none":
        (out / "depth").mkdir(exist_ok=True)

    zed = open_camera(args)
    meta = calibration(zed)
    meta.update(svo=args.svo, tracking=args.tracking, depth_mode=args.depth, every=args.every, start=args.start,
                coordinate_system="IMAGE (x right, y down, z forward), meters; poses are world_from_left_camera",
                imu_units="gyro rad/s, accel m/s^2, as returned by the SDK (IMAGE coordinates)")

    runtime = sl.RuntimeParameters()
    left, right, rgb, depth = sl.Mat(), sl.Mat(), sl.Mat(), sl.Mat()
    pose = sl.Pose()
    trajectory_name = {"vio": "zed_vio", "map": "zed_map", "reloc": "zed_reloc"}.get(args.tracking)
    traj = open(out / f"{trajectory_name}.txt", "w") if trajectory_name else None
    status_log = open(out / f"{trajectory_name}_status.csv", "w") if trajectory_name else None
    if status_log:
        status_log.write("t_ns,frame,state,odometry,spatial_memory,confidence,grab_ms\n")
    dump = args.images or args.depth != "none"
    frames = open(out / "frames.csv", "w") if dump else None
    imu = open(out / "imu.csv", "w") if dump else None
    if dump:
        frames.write("t_ns,frame,left,right,rgb,depth\n")
        imu.write("t_ns,gx,gy,gz,ax,ay,az\n")

    last_imu = 0
    n = 0
    grab_ms = []
    cpu0 = time.process_time()
    wall0 = time.monotonic()
    while True:
        if args.frames and n >= args.frames:
            break
        write = n % args.every == 0
        runtime.enable_depth = args.depth != "none" and write
        t0 = time.monotonic()
        err = zed.grab(runtime)
        dt = (time.monotonic() - t0) * 1000
        if err == sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
            break
        if err != sl.ERROR_CODE.SUCCESS:
            print(f"grab {n}: {err}")
            n += 1
            continue
        grab_ms.append(dt)
        t_ns = zed.get_timestamp(sl.TIME_REFERENCE.IMAGE).get_nanoseconds()
        frame = zed.get_svo_position()

        batch = []
        if imu and zed.get_sensors_data_batch(batch) == sl.ERROR_CODE.SUCCESS:
            for s in batch:
                ts = s.get_imu_data().timestamp.get_nanoseconds()
                if ts <= last_imu:
                    continue
                last_imu = ts
                g = np.radians(s.get_imu_data().get_angular_velocity())
                a = s.get_imu_data().get_linear_acceleration()
                imu.write(f"{ts},{g[0]:.6f},{g[1]:.6f},{g[2]:.6f},{a[0]:.5f},{a[1]:.5f},{a[2]:.5f}\n")

        if traj:
            state = zed.get_position(pose, sl.REFERENCE_FRAME.WORLD)
            st = zed.get_positional_tracking_status()
            tr = pose.get_translation(sl.Translation()).get()
            q = pose.get_orientation(sl.Orientation()).get()
            status_log.write(f"{t_ns},{frame},{state.name},{st.odometry_status.name},"
                             f"{st.spatial_memory_status.name},{pose.pose_confidence},{dt:.1f}\n")
            if state == sl.POSITIONAL_TRACKING_STATE.OK and all(math.isfinite(v) for v in tr):
                traj.write(f"{t_ns / 1e9:.9f} {tr[0]:.5f} {tr[1]:.5f} {tr[2]:.5f} "
                           f"{q[0]:.6f} {q[1]:.6f} {q[2]:.6f} {q[3]:.6f}\n")

        names = ["", "", "", ""]
        if write and args.images:
            names[:3] = [f"left/{t_ns}.png", f"right/{t_ns}.png", f"rgb/{t_ns}.jpg"]
            zed.retrieve_image(left, sl.VIEW.LEFT_GRAY)
            zed.retrieve_image(right, sl.VIEW.RIGHT_GRAY)
            zed.retrieve_image(rgb, sl.VIEW.LEFT)
            cv2.imwrite(str(out / names[0]), left.get_data())
            cv2.imwrite(str(out / names[1]), right.get_data())
            cv2.imwrite(str(out / names[2]), cv2.cvtColor(rgb.get_data(), cv2.COLOR_BGRA2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
        if write and args.depth != "none":
            names[3] = f"depth/{t_ns}.png"
            zed.retrieve_measure(depth, sl.MEASURE.DEPTH)
            d = np.nan_to_num(depth.get_data(), nan=0.0, posinf=0.0, neginf=0.0)
            cv2.imwrite(str(out / names[3]), np.clip(d * 1000.0, 0, 65535).astype(np.uint16))
        if frames:
            frames.write(f"{t_ns},{frame},{','.join(names)}\n")

        n += 1
        if n % 300 == 0:
            print(f"{n} frames, grab p50 {np.median(grab_ms[-300:]):.1f} ms", flush=True)

    if args.tracking == "map" and args.area:
        zed.save_area_map(args.area)
        while zed.get_area_export_state() == sl.AREA_EXPORTING_STATE.RUNNING:
            time.sleep(0.1)
        meta["area_export"] = str(zed.get_area_export_state())

    wall = time.monotonic() - wall0
    meta["run"] = {
        "frames": n,
        "wall_s": round(wall, 2),
        "cpu_s": round(time.process_time() - cpu0, 2),
        "cpu_cores_avg": round((time.process_time() - cpu0) / wall, 2) if wall else 0,
        "grab_ms_p50": round(float(np.median(grab_ms)), 2) if grab_ms else None,
        "grab_ms_p95": round(float(np.percentile(grab_ms, 95)), 2) if grab_ms else None,
        "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }
    (out / ("meta.json" if dump else f"meta_{args.tracking}.json")).write_text(
        json.dumps(meta, indent=2))
    for f in (traj, status_log, frames, imu):
        if f:
            f.close()
    zed.close()
    print(json.dumps(meta["run"]))


if __name__ == "__main__":
    main()
