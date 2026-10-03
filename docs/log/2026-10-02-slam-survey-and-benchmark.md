# SLAM survey and the localization benchmark (in progress)

Dates: survey 2026-10-02 22:15–22:27 UTC; benchmark from 2026-10-02 22:31 UTC, still running on 2026-10-03 00:20 UTC. Reports: `docs/reports/2026-10-03-slam-survey.md`, `docs/reports/localization-bench/results.md`. Bench tooling: `workspaces/bench/` (untracked).

## Question

"Are we reinventing the wheel?" after a day of relocalization failures.

## Survey verdict

- **Localization: yes.** `relocalization.py`, `JumpGate`, the millimetre filter, timeouts, `.area` archiving, map resets and the planner's relocalization gate all patch one black-box pose that serves as both odometry and global fix. ZED GEN_3 relocalizes through loop closure (the robot must revisit a known place), accumulates keyframes standing still, and GEN_1 in SDK 5.5 cannot relocalize from a `.area`.
- **Navigation: no.** Keep the own Hybrid A* (asymmetric curvature, camera-goal check, 30–80 ms on the Jetson), pure pursuit with the scan guard and blind-zone memory, frontier exploration and object viewpoints. Nav2's Smac planner supports one turning radius; MPPI for Ackermann has an open issue; Nav2 has no object viewpoints or blind-zone memory. Keep nvblox as a library.
- **Semantics:** YOLOE + object memory in ClickHouse + an LLM is close to OK-Robot/DynaMem; nothing ready-made exists for the Orin Nano.
- **Candidates:** cuVSLAM / PyCuVSLAM v17 (open source, aarch64 cp310 wheel, no ROS; odometry about 2 ms/frame; localization needs a prior pose, place recognition only in a draft PR) and RTAB-Map 0.23.8 (BSD, no ROS needed; bag-of-words global relocalization and multi-session maps; CPU, ~1 Hz). Rejected: ORB-SLAM3 (GPL, unmaintained), OpenVINS, VINS-Fusion, Kimera, Basalt, neural SLAM (too heavy next to the stack), Spectacular AI / Slamcore (paid on ARM, no ZED). Full ROS 2 + Isaac ROS + Nav2 reportedly does not fit in 8 GB.
- **Recommendation:** no ROS; ZED stays the camera and depth source; odometry from cuVSLAM or ZED VIO without area memory; global map and `map→odom` from RTAB-Map; nav in `odom`, planner and explore in `map`. Estimated to remove 400–700 lines of scaffolding. The `odom`/`map` split was done right away (`2026-10-02-odom-map-split.md`).
- **Switch criteria:** ≥ 90 % of wake-ups localized within 10 s and 1 m of travel, error ≤ 0.15 m at floor markers, zero false localizations beyond 0.5 m, total CPU not above GEN_3. Then a shadow run on the robot.

## Owner's mandate (22:29 UTC)

"Давай все перепишем… у тебя есть свобода экспериментировать… робот не в продакшене, мы можем ломать." The owner offered physical help: numbered tape crosses on the floor and placing the robot on them.

## Benchmark so far (results.md, 2026-10-02 23:46 UTC)

Two HD720 recordings with IMU: `loop1` (552 frames, 32.4 s, 3.91 m path) and `loop2` (1121 frames, 71.4 s, about 9 m). No ground truth yet: errors are against ZED VIO, so they measure consistency, not accuracy.

| Odometry | loop1 start–end gap | loop2 start–end gap | Tracker time p50 / p95 | RSS |
|---|---|---|---|---|
| ZED VIO | 0.67 m | 0.17 m | — | — |
| cuVSLAM stereo | 0.64 m | 0.19 m | 2.5 / 9 ms | about 255 MB |
| cuVSLAM inertial | 0.65 m | 0.32 m | 4.2 / 52 ms | about 290 MB |

All systems show the same 0.65 m gap on loop1, so the loop probably does not close in that recording.

| Localization | First match | Result |
|---|---|---|
| RTAB-Map, loop1 in the loop2 map | 2.6–4.3 s | 66–71 % of frames, 0 jumps > 0.5 m, 144–151 ms p50, ~1.3 cores, ~285 MB |
| ZED GEN_3, loop1 in loop2 | 6.7 s | 79 % |
| RTAB-Map, loop2 in the loop1 map | 0.5 s | 52–54 % |
| **ZED GEN_3, loop2 in loop1** | never | 0 % |
| RTAB-Map merge of both sessions | 0–1 s | 27–29 links between sessions, 0 jumps |
| RTAB-Map wake-up simulation (start every 5 s, 15 s window) | median 2.1 s / 5.8 s | 6/6 and 14/14 starts localized, 0 wrong; max 14 s |

RTAB-Map agrees with ZED's own relocalization to 0.015 m / 0.27°. RTAB-Map timings were measured on the Mac (arm64 container); Jetson timings are pending.

## Recordings for the next round

- `map-0930.svo2` (22:30 UTC, short: explore ended at "no reachable frontiers").
- `mapping-manual.svo2` (23:02 UTC, about 70 s): ended when `rabbit-zed` crashed with a CUDA out-of-memory in nvblox (RAM 6.2–6.5 of 7.4 GB).
- `mapping-manual2.svo2` (23:53–00:01 UTC, about 8 minutes, 2.6 GB), driven manually by the owner despite a Wi-Fi drop.

## Open at the time of writing

A GPU window with `rabbit-zed` stopped (from 2026-10-03 00:01 UTC) for cuVSLAM variants, cuVSLAM `localize_in_map` with RTAB-Map priors, RTAB-Map timing on the Jetson and depth modes (NEURAL_LIGHT, NEURAL FP16/INT8, NEURAL_PLUS); floor markers; wake-up sessions in different light; the integration itself.
