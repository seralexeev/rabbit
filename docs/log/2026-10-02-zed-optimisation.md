# ZED SDK optimisation: CPU, GIL, frame rates, depth and map modes

Date: 2026-10-02, 06:07–12:07 UTC, with follow-ups to 2026-10-03 00:01 UTC. Uncommitted at the time of writing.

## Starting point

`rabbit-zed` at 185 % CPU standing (176 % average, p95 269 % over 30 h in Forge), 3.4–4.6 GB RSS; load grew with the map (2726 chunks, 372k triangles before a reset); in heavy hours capture p99 38–41 ms and minimum fps in 5-minute buckets down to 3.7.

## Where the CPU goes

- `top -H`: one native thread at 85–96 % of a core. py-spy (`--nonblocking`) showed Python work (JPEG, obstacle scan, copies) under 10 %. The hot thread is the GEN_3 tracking optimizer (`sl_ceres::Solver::Solve`), not mapping or depth.
- **gdb incident** (06:08 UTC): `gdb -p <pid> -batch "thread apply all bt"` hung past the tool timeout and left the process in tracing stop; the camera froze for about 2 minutes (3779 frames dropped). Recovered with `kill -CONT`. A second gdb attempt in a throwaway container hung for over 10 minutes loading CUDA/TensorRT symbols. Rule: never gdb the camera process; use py-spy or `top -H`.
- Conclusion: rewriting the node in C++ would buy little, because the cost is inside the SDK. That plan was dropped at 07:05 UTC in favour of a thin C++/CUDA extension for nvblox only.

## Settings tried (60 s windows, robot standing)

| Config | zed CPU | Hottest thread | GPU | Note |
|---|---|---|---|---|
| baseline | 185 % | 96 % | 27 % | |
| `compute_preference = PREFER_GPU` | 157 % | 69 % | 28 % | kept |
| + `depth_stabilization=0`, `enable_image_validity_check=0`, `allow_depth_cuda_graph=True` | 197 % | 75 % + new 35 % thread | 19 % | cuda graph dropped |
| same without the cuda graph | 104 % | 20 % | 26 % | kept; measurement partly contaminated by someone driving the robot from the public HUD |
| GEN_1 tracking (08:22–08:34) | 62–70 %, later 116–135 % | | | rejected: in SDK 5.5 GEN_1 does not relocalize against a saved `.area` (pose reset to the origin), so the map does not survive a restart |
| `enable_2d_ground_mode`, `enable_localization_only` as a static setting | no measurable change | | | |
| `grab_compute_capping_fps = 15` | same CPU | | | removed at 11:12 UTC: pose latency p50 105.6 ms vs 49.0 ms at 30 fps |
| depth on every 2nd frame (12:01) | 217 → 219.5 % (awake) | | 34 → 19 % | kept: −1.2 W, same pose latency |

## GEN_3 keyframe leak and map modes

- Standing still at 5 fps, keyframes grew 0 → 265 in 9 minutes and CPU rose from 31 % to about 135 %; `room.area` swelled to 70–83 MB (earlier files were 3–10 MB). Stereolabs forum: a known SDK 5.5.0 GEN_3 bug, no fix yet.
- `enable_localization_only=True` kept keyframes flat and CPU fell 76 → 21 %.
- Implemented as `map_mode` (10:38 UTC): **localization** by default (the area is used, never extended), **mapping** for a fresh map or after `rabbit.map.extend` (request/reply, refused unless localized in the saved map; explore sends it). The switch saves and restarts the camera process (about 20 s without pose). It switches back after 3 minutes idle, but only when localized for a minute and with more than 1.2 m of open view (11:34 UTC: the switch happened facing a white wall corner and the camera stayed INITIALIZING for over an hour until the map was reset).

## Frame rates

- 30 fps while anything moves (nav driving, joystick or drive commands, pose motion, or `rabbit.zed.wake {seconds ≤ 60}`), 5 fps idle with a HUD open (`rabbit.operator.heartbeat`), 1 fps idle and unwatched. Full rate for the first minute after start and while relocalizing (relocalization took 64 s at low fps, 16–19 s at full rate).
- Depth on every 2nd frame feeds the obstacle scan (15 Hz), nvblox (15 Hz) and the detector (every 4th frame).
- The SDK downscales the preview to 640×360 itself (`retrieve_image` with a size): JPEG encode 15.5 → 2.3 ms.
- The obstacle scan runs on a single-worker thread pool so the pose is published right after tracking.

## Stalls

- `Slow grab`, `GIL stall` (a watchdog thread waking > 300 ms late) and `Slow frame processing` with a per-step breakdown are logged above 300 ms (12:42 UTC). A 2.4 s pose gap during exploration was a stall inside `grab()`; GEN_3 stalls `grab()` for 2–3 s once a few seconds after relocalizing and occasionally while mapping. The IMU kept flowing, so the USB link was fine. nav stops on a pose older than 0.5 s and resumes.
- `save_area_map` holds the GIL for about 0.6 s, so autosaves happen only when idle.

## Results (2026-10-02)

| Metric | Morning | Evening |
|---|---|---|
| zed CPU standing | 134–185 % | 17–45 % (localization mode) |
| zed CPU driving | 175–189 % | about 175 % at 30 fps; up to 280 % exploring in mapping mode |
| zed RSS | 3.4–4.6 GB | 1.25–1.7 GB (nvblox instead of ZED mapping) |
| pose latency driving | p50 105 ms | p50 49 ms |
| pose gaps driving | up to 2.1 s | 76–274 ms max (excluding SDK stalls) |

Later the same night: `SENSOR_PUBLISH_S` 0.05 → 0.01 s (IMU batching added 26–33 ms p50), and a CUDA out-of-memory crash in nvblox during an SVO recording with RAM at 6.2–6.5 of 7.4 GB (2026-10-02 23:03 UTC); making the camera process survive an nvblox OOM is open.

## Research notes (2026-10-02 06:33 UTC)

Depth modes on Orin Nano 8 GB per Stereolabs: NEURAL_LIGHT 30 fps / GPU 36 %, NEURAL 30 fps / GPU 88 %, NEURAL_PLUS 8 fps. A depth-mode benchmark on recorded data (NEURAL_LIGHT, NEURAL FP16/INT8, NEURAL_PLUS) was queued in the localization bench and had no results at the time of writing. CUDA IPC does not work on Orin; nvJPEG encode is not supported on Orin Nano; a CuPy obstacle scan was 2.4× more CPU than numpy.
