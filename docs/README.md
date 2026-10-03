# Engineering log

Notes for people and agents who pick up this project later: what the system looks like now, how it got there, what was tried and dropped, the measurements behind decisions and the incidents with their root causes. The how-to material (deploying, operating, developing) lives in `AGENTS.md`, `.claude/skills/*` and `workspaces/forge/README.md`; this folder is the history and the reasoning.

Open questions, unresolved problems and on-robot checks: [open-issues.md](open-issues.md). What to do next: [roadmap.md](roadmap.md).

Conventions: dates in file names and timestamps are UTC unless marked otherwise; the robot and its owner are in Sydney (AEST, UTC+10, AEDT from 4 October 2026). Commit hashes refer to this repository. Everything after commit `b36435d` (2026-10-02 00:49 UTC) was uncommitted when these notes were written (2026-10-03); those entries name files instead of commits. Reports referred to as `~/projects/rabbit/data/offline/...` are kept outside the repo because they contain maps and data of the flat.

What's next: [roadmap.md](roadmap.md).

## Index

| Entry | Topic |
|---|---|
| [2025-05-18 hardware and stack history](log/2025-05-18-hardware-and-stack-history.md) | hardware, the move from Raspberry Pi to Jetson, ROS 2 → NATS, state after five months off |
| [2026-10-01 revival and telemetry](log/2026-10-01-revival-and-telemetry.md) | node rewrite, RoboClaw/INA/IMU telemetry, `jetson_clocks`, TLS and Chrome |
| [2026-10-01 ZED spatial mapping](log/2026-10-01-zed-spatial-mapping.md) | SDK 5.5, room map, memory, quality tuning, mesh filter, chunk format (superseded) |
| [2026-10-01 driving, nav and safety](log/2026-10-01-driving-nav-and-safety.md) | nav node, missions, swept-arc guard, wall crash, calibration, rear-axle tracking |
| [2026-10-01 exploration and Hybrid A*](log/2026-10-01-exploration-and-hybrid-astar.md) | frontier exploration and the planner kernels |
| [2026-10-01 Forge](log/2026-10-01-forge.md) | ClickHouse writer, slabs, MCP, chat agent, anomalies, moving onto the robot |
| [2026-10-01 HUD](log/2026-10-01-hud.md) | 3D HUD, chat panel, minimap, voxel map, objects |
| [2026-10-01 lag and Wi-Fi](log/2026-10-01-lag-and-wifi.md) | the lag hunt, Wi-Fi drops, TX power |
| [2026-10-01 public access](log/2026-10-01-public-access.md) | Cloudflare tunnel, access links, HTTP/2 |
| [2026-10-01 map resets](log/2026-10-01-map-resets.md) | every map reset or loss and its cause |
| [2026-10-01 deploy and agent workflow](log/2026-10-01-deploy-and-agent-workflow.md) | deploy script, parallel agent sessions |
| [2026-10-02 Jetson performance](log/2026-10-02-jetson-performance.md) | clocks, IRQs, headless, the clock-floor incident, OC3, JetPack assessment |
| [2026-10-02 ZED optimisation](log/2026-10-02-zed-optimisation.md) | CPU, GIL, frame rates, depth, GEN_3 keyframe leak, map modes |
| [2026-10-02 nvblox](log/2026-10-02-nvblox.md) | nvblox extension, clearance grid, reflections, debris |
| [2026-10-02 floor estimation](log/2026-10-02-floor-estimation.md) | floor origin, per-frame floor plane, robot on a table |
| [2026-10-02 route planner](log/2026-10-02-route-planner.md) | `rabbit-planner`: trips to points, places and objects; replay |
| [2026-10-02 object detector](log/2026-10-02-object-detector.md) | YOLOE in the ZED SDK, filtering, objects in Forge |
| [2026-10-02 voice agent](log/2026-10-02-voice-agent.md) | Realtime voice, spoken approvals, robot prompt |
| [2026-10-02 relocalization](log/2026-10-02-relocalization.md) | millimetre poses, false relocalization, give-up rules |
| [2026-10-02 odom/map split](log/2026-10-02-odom-map-split.md) | nav on continuous odometry |
| [2026-10-02 operator heartbeat removal](log/2026-10-02-operator-heartbeat-removal.md) | the HUD is a viewer |
| [2026-10-02 NATS/Docker latency](log/2026-10-02-nats-docker-latency.md) | latency audit and NATS settings |
| [2026-10-02 SLAM survey and benchmark](log/2026-10-02-slam-survey-and-benchmark.md) | cuVSLAM / RTAB-Map vs ZED GEN_3 (in progress) |
| [2026-10-03 motor slew limit](log/2026-10-03-motor-slew-limit.md) | smoothing bursty joystick commands |
| [2026-10-03 Forge on Parquet and chDB](log/2026-10-03-forge-parquet-chdb.md) | ClickHouse server replaced by Parquet files and embedded chDB: design, parity, memory |
| [2026-10-03 Jetson diet and Python 3.12](log/2026-10-03-jetson-diet.md) | trimming host services, journald, logrotate, image pruning; Python 3.12 patch |
| [2026-10-03 field session](log/2026-10-03-field-session.md) | boot after a move, recordings, nav safety trips, far-floor phantom obstacles |
| [2026-10-03 power rails](log/2026-10-03-power-rails.md) | battery, motor, servo and Jetson currents from telemetry; the motor buck at its limit, the battery shunt near its range |
| [2026-10-03 Rabbit 2.0 made buildable](log/2026-10-03-architecture-2.0-detail.md) | Pi 4 body: BOM, pinout and buses, fail-safe E-stop, NATS hub + leaf, INA4235 channels and shunts, wiring diagrams |
| [2026-10-03 nav replay](log/2026-10-03-nav-replay.md) | offline replay of the day's trips: recovery along the trail, turnaround loops, `stuck`, IMU thresholds |
| [2026-10-03 full-stack simulator](log/2026-10-03-full-stack-sim.md) | `rabbit-sim` + local NATS + the real nav/planner/explore on the Mac, end-to-end tests |
| [2026-10-03 observability](log/2026-10-03-observability.md) | structured events with reasons and ids, node metrics, start snapshots, `events` / `node_starts` / `node_metrics` / `nats_server` in Forge |
| [2026-10-03 phase 0 tools](log/2026-10-03-phase-0-tools.md) | INA per-channel shunts and `clipped`, duty cap 12 V / V_supply, RoboClaw config tool (3 A, NVM), encoder check |
| [2026-10-03 printed mounts](log/2026-10-03-printed-mounts.md) | Rabbit 2.0 brackets in `cad/brackets/`: ToF pairs, compliant bumpers with D2F switches, lidar mast (scan plane 220 mm), button pod, rear camera mount; fit checks against the chassis STEP |
| [2026-10-03 body PCB](log/2026-10-03-body-pcb.md) | deck-2 board for Rabbit 2.0 generated by code (KiCad 10 + Freerouting): Pi, RoboClaw, regulators, fuses, INA4235, PCA9685; stack heights, current paths, DRC clean, JLCPCB outputs |

[lessons.md](lessons.md) collects the hard-won rules in one list.

## Current state of the system (2026-10-03)

### Hardware

Jetson Orin Nano Super 8 GB (MAXN_SUPER, clocks pinned, headless), ZED 2i on USB, RoboClaw 2x30A on the UART, PCA9685 steering servo, INA4235 power monitor, 99 Wh 4S Li-ion pack, Wi-Fi only. Wheel encoders do not count; speed comes from the camera pose. Details in the hardware entry.

### Services (`workspaces/compose.yaml`)

| Service | Role |
|---|---|
| `nats`, `nats-init`, `nats-dashboard` | message bus; KV bucket `rabbit`, JetStream `LOGS` (7 days) |
| `rabbit-zed` | the only camera process: GEN_3 tracking and relocalization, depth (NEURAL_LIGHT, every 2nd frame), nvblox mapping (C++/CUDA extension), floor estimation, obstacle scan, YOLOE object detection, preview, SVO recording, health |
| `rabbit-nav` | missions (`move`, `turn`, `goto`, `path`), path tracking on the rear axle in the odometry frame (curvature feedforward + feedback), swept-footprint collision guard with blind-zone memory, stall and bump trips |
| `rabbit-planner` | Hybrid A* trips to points, saved places and objects; replanning and recovery |
| `rabbit-explore` | exploration by expected information gain per metre, through planner trips |
| `rabbit-roboclaw`, `rabbit-steering` | motors (electronic differential, slew limiting, kill switch) and the servo |
| `rabbit-ina`, `rabbit-telemetry` | power at 50 Hz; Jetson, containers and Wi-Fi at 1 Hz |
| `forge` | NATS → Parquet writer, compaction, chDB queries, chat/voice agent API, in one process |
| `rabbit-web` | nginx: the built HUD, `/api` → chat, `/nats` → NATS websocket, access-link gate |
| `tunnel` | Cloudflare tunnel (HTTP/2) to https://live.rabbit0.dev |

All `rabbit-*` nodes share one image with the code bind-mounted; a code change needs a container recreate, not a rebuild.

### Main NATS contracts

- Sensors: `rabbit.zed.pose` (map pose plus an `odom` sub-object; floor at y = 0, camera at y ≈ 0.137), `rabbit.zed.imu`, `rabbit.zed.obstacle` (48-bin scan over ±60°, obstacles 4–45 cm above a per-frame floor plane), `rabbit.zed.objects`, `rabbit.health.zed` (fps, `spatial_memory_status`, `relocalizing`, `map_mode`, `map_id`, nvblox timings), `rabbit.roboclaw`, `rabbit.ina`, `rabbit.steering`, `rabbit.telemetry`.
- Commands: `rabbit.cmd.joy` (owns the motors for 1 s), `rabbit.cmd.drive`, `rabbit.nav.mission`, `rabbit.nav.cancel`, `rabbit.nav.explore`, `rabbit.planner.goal` (request/reply, `preview`), `rabbit.planner.places*`, `rabbit.zed.wake`, `rabbit.zed.record`.
- Map: `rabbit.map.chunks` / `rabbit.map.snapshot` (mesh blocks, `<IIIfff` header, int16 mm vertices relative to a per-chunk origin), `rabbit.map.grid` / `.snapshot` (int16 mm clearance, 5 cm cells), `rabbit.map.save`, `rabbit.map.reset`, `rabbit.map.extend` (request/reply).
- State: `rabbit.nav.state` (10 Hz), `rabbit.planner.state`, `rabbit.explore.state`, logs on `rabbit.log.<node>`.
- `rabbit.operator.heartbeat` only raises the idle camera rate; nothing depends on the HUD being open.

### Map and localization pipeline

ZED depth + GEN_3 pose → plausibility filter (millimetre poses, jump gate) → floor estimator → nvblox TSDF/ESDF on the GPU (5 cm voxels, rays clipped at the floor, integration up to 5 m) → mesh blocks for the HUD and the 2D clearance grid for the planner. The SDK area memory (`room.area`) provides relocalization after restarts; `map_mode` keeps it in localization by default and extends it only for a new map or exploration (GEN_3 keeps adding keyframes otherwise). Saved state in `data/map/`: `room.area`, `room.nvblx`, `room.id`, `room.ply`, `archive/` (last 5). Relocalization counts after 10 s of a localized status; it gives up after 3 m of travel or 45 s and starts a new map.

### Planner

Hybrid A* (numba) on the clearance grid with asymmetric curvature tables, costs that keep to the middle of gaps, reverse only into mapped space, Dijkstra heuristic; plans in 5–80 ms typically on the Jetson. Trips replan on new obstacles, pose jumps and blocks, back up along their own trail, and hold before long detours. Object goals come from Forge's object memory.

### Forge

Parquet files on the robot (one file per table and hour every 10 s, merged hourly), queried in-process with chDB; one container of about 300 MB instead of ClickHouse, writer and chat (600–850 MB). See [2026-10-03 Forge on Parquet and chDB](log/2026-10-03-forge-parquet-chdb.md). Slabs, a static SQL gate plus EXPLAIN, a metric graph with `investigate`, Chronos-2 anomaly detection, MCP tools, a chat agent (OpenAI via the Vercel AI SDK) and a Realtime voice agent, both with approval cards for motion. Every node records its decisions as structured events with a reason, ids and the measured values (`events`), its start snapshot (`node_starts`) and its process health (`node_metrics`); conventions in [reports/2026-10-03-observability.md](reports/2026-10-03-observability.md).

### HUD

React/three.js at https://jetson.rabbit (LAN) and https://live.rabbit0.dev (access link required): 3D view with a voxel or surface map, minimap, objects, panels with uPlot charts, gamepad/keyboard driving, AI LINK chat with voice.

### In progress / open

- **Forge storage cutover to Parquet + chDB is staged but not switched** (runbook: `reports/2026-10-03-forge-cutover-runbook.md`). Until it's done, don't run `scripts/deploy.sh` without arguments or with `forge-*`: the working tree's Forge code no longer runs in the old alpine containers. Deploying `rabbit-*` services is safe. `forge-shadow` (the new writer) starts on boot.
- Localization replacement: odometry from cuVSLAM or ZED VIO plus RTAB-Map as the global localizer, being benchmarked on recorded SVOs; ground-truth floor markers and wake-up sessions still to record.
- Commit the work since `b36435d` (planner node, nvblox extension, detector, voice, access links, relocalization fixes, odom split).
- Make `rabbit-zed` survive an nvblox CUDA out-of-memory.
- Wi-Fi in the far part of the flat (router RSSI settings, antennas or another card).
- Actual clocks and OC counters in Forge; Python 3.12; Docker image cleanup; RTC battery and persistent journal.
- `pose` Euler angles in Forge: rows recorded before the writer fix of 2026-10-03 hold yaw in `pitch_deg`, roll in `yaw_deg` and pitch in `roll_deg` (ZED `euler_deg` is rotation about x, y, z in the Y-up frame: pitch, yaw, roll); newer rows are correct.
- Encoders read 0; the magnetometer is not calibrated.
