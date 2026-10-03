# Offline localization bench

Tooling for replacing ZED GEN_3 area-memory localization with continuous odometry (`odom`) plus a global
localizer that provides `map→odom`. Every candidate runs on the same SVO2 recordings. This directory is
self-contained: nothing here touches `workspaces/rabbit/src` or the robot's compose services.

| Path | What |
|---|---|
| `zed_dump/zed_dump.py` | SVO2 → dump (images, NEURAL_LIGHT depth, full-rate IMU, calibration, ZED trajectories) |
| `zed_dump/depth_bench.py` | ZED depth modes on SVO frames: timing, GPU memory and depth-quality proxies |
| `cuvslam/run_cuvslam.py` | cuVSLAM 17 (stereo or stereo-inertial odometry, SLAM, map save, `localize_in_map`) on a dump |
| `rtabmap/rtab_run.cpp` | RTAB-Map (librtabmap) on a dump with external odometry: mapping, localization, multi-session |
| `eval/eval.py` | markdown tables and trajectory plots |
| `docker/Dockerfile.bench` | `rabbit-bench` = the robot's `rabbit` image + cuVSLAM 17 wheel (built on the robot, one small layer) |
| `docker/Dockerfile.rtabmap` | `rabbit-rtabmap` = Ubuntu 22.04 + g2o + RTAB-Map (pinned commit, no ROS, no Qt) + `rtab_run` |
| `scripts/` | `sync.sh` (code → robot `/root/bench/src`), `zed.sh` / `rtab.sh` (container runners), `rtab_suite.sh`, `gpu_window.sh` |

## Rules of engagement on the robot

The robot is live. The runners use `nice -n 19`, `ionice -c3`, a container `--memory` limit (2 GB by default),
and a guard: once a second it samples the host's `MemAvailable` and kills the bench container when it drops
below `BENCH_MIN_AVAIL_MB` (350). It also samples the container's GPU memory from
`/sys/kernel/debug/nvmap/iovmm/clients` (unified memory on the Jetson; `BENCH_GPU_LOG` writes the peak).

**Anything that uses the GPU or more than ~300 MB of RAM runs only in a window agreed with whoever is using the
robot** (`scripts/gpu_window.sh`). Everything CPU-only (RTAB-Map, eval) runs on the Mac.

## Dump layout

`zed_dump.py SVO OUT --images --depth neural_light` (tracking `vio` by default) writes:

| File | Content |
|---|---|
| `meta.json` | `fx fy cx cy` (rectified left, also used for right), `baseline` (m), `width height`, `T_cam_imu` (4×4, IMU in the left camera frame), serial, SVO frame count, run stats |
| `frames.csv` | `t_ns,frame,left,right,rgb,depth`: image timestamp (ns) and SVO frame index |
| `left/`, `right/` | rectified grayscale PNG, 1280×720 |
| `rgb/` | rectified left colour JPEG (q95) |
| `depth/` | NEURAL_LIGHT depth, 16-bit PNG in mm, 0 = invalid, 1280×720 |
| `imu.csv` | `t_ns,gx,gy,gz,ax,ay,az`: every IMU sample (~400 Hz, from `get_sensors_data_batch`), rad/s and m/s², in the camera's IMAGE axes; at rest `ay ≈ −9.8` |
| `zed_vio.txt` | TUM `t x y z qx qy qz qw`: GEN_3 with `enable_area_memory=False` |
| `zed_vio_status.csv` | per frame: tracking state, odometry status, spatial memory status, confidence, grab ms |

All poses everywhere in the bench are `world_from_left_camera` in the **IMAGE** convention (x right, y down,
z forward, metres), which is also cuVSLAM's convention. `rtab_run` converts to and from RTAB-Map's base frame
(x forward, z up) internally.

Other tracking modes of `zed_dump.py` (no images unless asked):
- `--tracking map --area X.area`: GEN_3 with area memory, saves the area at the end (`zed_map.txt`);
- `--tracking reloc --area X.area`: GEN_3 localization-only against an area, like the robot (`zed_reloc.txt`, `zed_reloc_status.csv`).

## Running

Images:

```sh
# on the robot (small layer over the rabbit image)
cd /root/bench/src && nice -n 19 docker build -f docker/Dockerfile.bench -t rabbit-bench .
# on the Mac; a separate colima VM, because the default one has 4 GB and the PCL-heavy units thrash it
colima start --profile build --arch aarch64 --cpu 8 --memory 14 --disk 60
DOCKER_HOST=unix://$HOME/.colima/build/docker.sock docker build --build-arg JOBS=6 -f docker/Dockerfile.rtabmap -t rabbit-rtabmap .
DOCKER_HOST=unix://$HOME/.colima/build/docker.sock docker save rabbit-rtabmap | gzip -1 | ssh rabbit 'gunzip | docker load'
```

Dumps (robot, GPU window):

```sh
scripts/sync.sh
ssh rabbit /root/bench/src/scripts/zed.sh python /bench/src/zed_dump/zed_dump.py /svo/loop1.svo2 /bench/data/loop1 --images --depth neural_light
```

Copy what RTAB-Map needs to the Mac (`data/offline/bench`, gitignored):

```sh
rsync -a --bwlimit=1500 --include='rgb/***' --include='depth/***' --include='*.csv' --include='*.txt' --include='*.json' \
  --exclude='*' rabbit:/root/bench/data/loop1/ ~/projects/rabbit/data/offline/bench/data/loop1/
```

cuVSLAM (robot, GPU window):

```sh
Z=/root/bench/src/scripts/zed.sh; C=/bench/src/cuvslam/run_cuvslam.py
$Z python $C /bench/data/loop1 /bench/results/loop1/cuvslam_inertial --mode inertial          # odometry
$Z python $C /bench/data/loop1 /bench/results/loop1/cuvslam_stereo --mode stereo
$Z python $C /bench/data/loop1 /bench/results/loop1/cuvslam_inertial_slam --mode inertial --slam --save-map /bench/results/loop1/cuvslam_map
$Z python $C /bench/data/loop2 /bench/results/loop2/cuvslam_loc_in_loop1 --mode inertial \
   --localize /bench/results/loop1/cuvslam_map --guess PRIOR.txt --guess-noise 0.5 20 --loc-radius 1.0
```

Outputs: `<prefix>_odom.txt`, `_slam.txt` / `_slam_all.txt` (TUM), `_summary.json` (track ms, lost frames,
CPU of the tracker per second of recording, RSS, localization attempts and result).

RTAB-Map (Mac, or robot via `scripts/rtab.sh`):

```sh
RUN="docker run --rm -v $HOME/projects/rabbit/data/offline/bench:/bench rabbit-rtabmap" \
  ODOMS="vio cuvslam_stereo cuvslam_inertial" scripts/rtab_suite.sh loop1 loop2
```

For each odometry source the suite maps both sessions, localizes each in the other's map (`Mem/IncrementalMemory=false`,
`Mem/InitWMWithAllNodes=true`, every processed frame is tried), and merges B into a copy of A's database (multi-session).
`rtab_run` writes `<prefix>.csv` (per frame: process ms, loop/proximity id, inter-session flag, hypothesis, inliers,
WM size, RSS, map-frame position, `map→odom` norm and yaw), `_poses.txt` (`map→odom · odom`, TUM, IMAGE frame),
`_graph.txt` (mapping: optimized nodes with map ids) and `_summary.json`. Extra parameters: `--param Key=Value`
or `RTAB_PARAMS="--param Vis/MinInliers=25"` for the suite. Odometry covariance: `--lin-var/--ang-var` (1e-4).

Evaluation (Mac):

```sh
rsync -a --exclude cuvslam_map --exclude zed_areas rabbit:/root/bench/results/ ~/projects/rabbit/data/offline/bench/results/
uv run --with numpy --with matplotlib python eval/eval.py ~/projects/rabbit/data/offline/bench/results ~/projects/rabbit/data/offline/bench
```

Result layout read by `eval.py`: `results/<session>/` with `zed_vio.txt`, `meta.json`, `zed_map.txt`,
`zed_reloc_in_<map>.txt` + `_status.csv`, `cuvslam_*`, `rtab_*`; `results/depth/*.json`. It writes `results.md`
and `<session>_odometry.png` / `_localization.png`.

Metrics:
- **odometry**: path length, start–end gap (a loop recording that returns to its start), APE against ZED VIO
  after a rigid alignment (a consistency measure, not ground truth), lost frames, per-frame time, CPU, RAM, GPU;
- **localization**: time to the first match, the share of frames matched after it, inter-session links (merge),
  jumps of the map position > 0.5 m within 5 s (false localizations), spread of `map→odom` after localizing;
- **cross-checks**: the median `map→odom` of "A in B" composed with "B in A" must be the identity, and RTAB-Map
  must agree with ZED's own relocalization when ZED succeeds. Until the floor tape markers arrive this is the
  best evidence that a localization is right.

## Depth modes

`depth_bench.py SVO OUT.json --mode neural_light|neural|neural_plus --precision fp16|int8 --static A:B` opens
the SVO with the robot's settings (HD720, `depth_stabilization=0`, `confidence_threshold=95`,
`texture_confidence_threshold=100`, depth retrieved at 640×360). It reports grab+retrieve time, the precision
actually used, valid pixels, floor-plane σ by range (RANSAC plane with the normal along the IMU's gravity,
robust σ = 1.4826·MAD of residuals within ±10 cm), wall σ (largest vertical plane; sparse, so noisy), flying
pixels (values between foreground and background at depth edges, floor excluded, per mille of valid pixels),
and temporal σ per pixel over the static frames `A:B`. The first run of a new mode downloads the model and
builds its TensorRT engine into `/root/bench/zed/resources` (a copy, not the live camera's directory); `open_s`
shows that cost.

## Recording sessions for the localization benchmark

`scripts/record_session.py NAME [SECONDS]` starts an SVO2 recording on the robot (`rabbit.zed.record`), keeps the camera at full rate, stops it and checks the frame rate from rabbit-zed's `Recording stopped` log line (LOSSLESS compression runs on the CPU; the camera pauses the detector and nvblox while recording, but a slow recording still means the data is unusable). It exits non-zero below 14 fps.

```sh
uv run -q --no-project --with nats-py python workspaces/bench/scripts/record_session.py mapping-3 480
```

Protocol (needs the owner):

1. **Markers.** 6–8 masking-tape crosses on the floor in different rooms, numbered. The robot is always placed the same way: rear axle centre on the cross, nose along one arm of the tape. Repeated starts on one marker must localize to the same pose, which gives a ground truth for consistency without measuring the flat.
2. **Mapping drive** (`mapping-N`, ~8 min): slow gamepad drive through every room the robot should know, looking into corners, ending on marker 1.
3. **Wake sessions** (`wake-mK-N`, 45–60 s each): place the robot on marker K, restart `rabbit-zed` (or power-cycle), record without moving for 30 s, then drive ~1 m straight. Repeat each marker in two lighting conditions (day and evening lamps) and with a person walking in view once.
4. After each session the script prints the fps; re-record anything under 14 fps. Then run the dump in a GPU window (`scripts/gpu_window.sh`) and the RTAB-Map suite on the Mac (`scripts/rtab_wake.sh`).
