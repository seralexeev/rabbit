---
name: rabbit-dev
description: Develop the Rabbit robot code (Python NATS nodes in workspaces/rabbit) and its web HUD (React/three.js in workspaces/web) - layout, conventions, coordinate frames, message contracts, tests, running the HUD and verifying changes. Use before editing workspaces/rabbit or workspaces/web.
---

# Developing Rabbit

Repo: `~/projects/rabbit` (GitHub `seralexeev/rabbit`, public), branch `main`. Deploying and operating the robot is in the `rabbit-robot` skill.

## Robot code (`workspaces/rabbit`)

Python 3.10, NATS instead of ROS 2. Each node is a container running one file in `src/node/`.

| File | Role |
|---|---|
| `lib/node.py` | `RabbitNode` base: NATS connect (waits for the server at startup), `subscribe` (exceptions logged and counted, never fatal), `publish` / `publish_json` (dropped and counted while NATS reconnects), `set_interval`, `async_task`, KV watchers, log records to `rabbit.log.<node>` with context (`set_log_context(mission_id=...)`), `event(...)` for decisions, `observe(...)` for timings, `node.start` / `node.stop`, process metrics every 10 s (`lib/observability.py`) |
| `lib/geometry.py` | camera and rear-axle offsets, the asymmetric steering-to-curvature tables, `rear_axle_point`, `camera_point`, `rear_axle_path`, `wheel_speeds` (electronic differential) |
| `lib/safety.py` | `Footprint`, `free_distance` (the swept footprint along an arc against scan points), `bin_scan` (4th nearest point per sector), `heights_above_floor` (per-frame robust floor plane) |
| `lib/planner.py` | occupancy grid from the mesh, costmaps (from occupancy, or straight from the ESDF clearance grid), Hybrid A* with Dubins and arc shots (numba), frontier detection and ranking |
| `lib/navmap.py` | the planners' map source (`USE_GRID`: the ESDF grid on `rabbit.map.grid`, or the mesh plus scan rays), scan obstacle memory, JIT warm-up |
| `lib/trip.py` | `Navigator`: the trip state machine (goal selection, path validation, replanning, recovery), pure and driven by the node or the simulator |
| `lib/spatial_map.py` | map chunk wire format, map file paths |
| `lib/drive.py` | command subjects, joystick parsing, `CommandArbiter` (the joystick owns the motors for 1 s after active input) |
| `node/zed.py` | camera: tracking, relocalization, nvblox mapping in a worker thread, map rebuilds after pose corrections, floor estimation, obstacle scan, IMU, preview, SVO recording, health |
| `native/rabbit_nvblox` | C++/CUDA extension (nanobind) over nvblox: `Mapper.integrate(depth, fx, fy, cx, cy, world_from_camera)`, `take_mesh_updates`, `save`/`load`, `save_mesh`. It converts the ZED frames (OpenGL camera, Y-up world) to nvblox (OpenCV camera, Z-up layer) and back. Built only inside the image (`docker/Dockerfile.zed`) |
| `node/loc.py`, `lib/loc.py`, `native/rabbit_rtabmap` | `rabbit-loc`, the RTAB-Map global localizer (shadow stage, compose profile `loc`, own image `docker/Dockerfile.loc`, built off the robot): keyframes from zed on `rabbit.loc.keyframe`, `map←odom` on `rabbit.loc.map_odom`. Frames, contract and policy: `docs/log/2026-10-03-rabbit-loc.md`. Offline: `python src/node/loc.py --replay <bench dump> --db x.db` inside the `rabbit-loc` image |
| `node/nav.py` | missions, path tracking on the rear axle (curvature feedforward + lateral/heading feedback), collision guard, safety trips, re-anchoring |
| `node/planner.py` | route planner: trips to objects, places and points, planned on the map and driven as nav `path` missions; saved places |
| `node/explore.py` | exploration: picks the next view with `lib/exploration.py` (unknown area visible in the 87° / 5 m camera cone ÷ travel + turn cost, views from 0.8–2.5 m off a frontier or a turn on the spot, done when no view would show 1 m²) and drives it as a planner trip |
| `node/roboclaw.py`, `node/steering.py`, `node/ina.py`, `node/telemetry.py` | motors, servo, power monitor, Jetson (jtop, plus actual CPU clocks, clock floors and soctherm over-current counters read from sysfs by `lib/jetson_clocks.py`), Docker and Wi-Fi |
| Rabbit 2.0 body (Raspberry Pi; written and simulated, not deployed yet; `docs/log/2026-10-03-body-software.md`) | `node/safety.py` + `lib/safety_loop.py` (`rabbit-safety`: 50 Hz arbiter → `rabbit.safety.drive`, caps by lidar/ToF clearance and input freshness, bumpers, E-stop line GPIO16 with a self-test, `rabbit.safety.state`; pure loop with an injected clock), `node/power.py` + `lib/power_supervisor.py` (`rabbit-power`, a host systemd service: button, LEDs, Jetson EN, battery policy, shutdown state machine; works without NATS through `RabbitNode.prepare()`), `node/lidar.py` + `lib/rplidar.py` + `lib/lidar.py` (RPLIDAR C1: protocol, binary `rabbit.lidar.scan`, point times, de-skew), `node/tof.py` + `lib/tof.py` + `lib/tof_device.py` (VL53L8CX ×4: zones to base-frame points, floor rejection, `rabbit.tof` per sensor), `node/jetson_power.py` (agent on the Jetson host). `roboclaw.py` and `steering.py` obey only `rabbit.safety.drive` with `DRIVE_INPUT=safety`. Deploy shape: `workspaces/body/` (compose, `body.env`, NATS hub), `docker/Dockerfile.body`, `scripts/deploy.sh --body`, `scripts/body-setup.sh` |
| `lib/hardware.py` | GPIO pin map, `PiGpio` (libgpiod v2), and the fake backend selected by `RABBIT_HW=fake`: `FakeGpio` (bridged to `rabbit.sim.gpio.in` / `.out` by `bridge_fake_gpio`), `FakeC1` (answers the lidar protocol and streams 5 kHz nodes), `FakeTof` in `lib/tof_device.py`. Every body node runs on the Mac with it |
| `lib/ina4235.py`, `lib/roboclaw.py`, `tools/roboclaw_config.py`, `tools/roboclaw_encoders.py` | INA calibration per channel (`INA_SHUNT_OHMS`, `clipped` at 90% of the shunt range); the RoboClaw packet-serial client (command numbers from the user manual rev 5.7); `roboclaw.py` scales duty by min(1, 12 V / supply) (`lib/drive.py` `duty_limit`); the phase-0 RoboClaw config (`read`/`plan`/`apply --yes`) and the read-only encoder check, run in the `rabbit` image with rabbit-roboclaw stopped (rabbit-robot skill, "Phase 0 on the robot") |

**Tests:**

```sh
cd ~/projects/rabbit/workspaces/rabbit && uv run --no-project --python 3.10 --with pytest --with numpy --with pydantic --with numba --with nats-py python -m pytest tests -q
```

The planner tests are timing-sensitive under heavy CPU load: rerun before believing a failure. The first run compiles the numba kernels (~5 s on the Mac, cached in `__pycache__`). `tests/sim.py` is a kinematic simulator (bicycle model, real curvature tables, the measured delays: poses 47 ms and scans 56 ms late with their capture `ts`, 0.06 s actuation dead time and 0.05 s steering and speed lags, 0.464 m/s per duty; `latency=False` for the ideal model; a `ScannedMap` mapper with an 87° / 5 m depth cone for exploration; layouts `room_grid`, `corridor_flat`, `open_plan` and `apartment` in the tests; a ray-cast 48-sector scan with the 0.3 m blind zone) that drives the real `nav.Node` and the `Navigator` in closed loop; `tests/test_navigation.py` runs whole trips in it (multi-room route, obstacle seen only by the scan, wall found in new map data, route cut off, pushed off the path, a point behind reached in reverse, exploring an unknown flat from scans). Real verification happens on the robot after a deploy.

**Full-stack simulator** (no robot): `scripts/sim.sh start` runs a local NATS (`nats-server` from PATH, else a release binary cached in `~/.cache/rabbit`) on `nats://127.0.0.1:14222` (websocket `ws://localhost:19222`), `src/node/sim.py` as the camera and motors, and the real `nav`, `planner` and `explore` nodes. Logs go to `/tmp/rabbit-sim`; stop it with `scripts/sim.sh stop`.

- **The sim node** reads `rabbit.cmd.drive` and `rabbit.cmd.joy` through the real `CommandArbiter`, the roboclaw slew and the 0.4 s timeout. It integrates the bicycle model of `lib/simulation.py` with the measured delays and stops at walls (contacts are counted, and the current rises so `stuck` works).
- **It publishes:**
  - `rabbit.zed.pose` (map + odom + session), `rabbit.zed.obstacle`, `rabbit.zed.imu`, `rabbit.roboclaw`;
  - `rabbit.map.grid` from an 87° / 5 m camera mapper, with snapshot replies;
  - `rabbit.health.zed` (mapping, not relocalizing, `map_id` `sim-<world>`);
  - `rabbit.zed.objects` for labelled boxes in view, such as the apartment's refrigerator at (1.0, 5.5).
- **Options:**
  - `SIM_WORLD=apartment|corridor|open-plan` or a decoded real map (`data/offline/replay/*.npz`; unknown cells become walls);
  - `SIM_START=x,z,heading_deg`;
  - `SIM_KNOWN_MAP=1` publishes the whole world as already mapped;
  - `--hud` also starts the HUD dev server with `VITE_NATS_URL` pointed at the sim (only if :3005 is free).
- **Test hooks:** `rabbit.sim.state` (request: pose, coverage, contacts), `rabbit.sim.restart` (a camera restart: new odometry session) and `rabbit.sim.setup` (request: `robot` `[x, z, heading_deg]` teleports, `blocks` `[[x0, z0, x1, z1, height_m]]` adds obstacles with a height, `lidar`/`tof`/`bumpers` switch the simulated body sensors).
- **Rabbit 2.0 body:** `SIM_BODY=1 scripts/sim.sh start` also runs the real `safety` and `power` nodes (`RABBIT_HW=fake`); the sim then publishes `rabbit.lidar.scan` (10 Hz, things at least as tall as the 230 mm scan plane), `rabbit.tof` (4 sensors, 3D zone rays against the floor and cell heights), presses the bumper pins over `rabbit.sim.gpio.in` (cells ≥ 23 mm within 12 mm of a bumper), drives from `rabbit.safety.drive` instead of `rabbit.cmd.*`, and brakes and sets the RoboClaw E-stop status bit while the fake E-stop line (`rabbit.sim.gpio.out`) is low. Without `SIM_BODY` the sim behaves as before (no lidar, so nav keeps the camera-only guard).
- **For the HUD:**
  - mesh chunks on `rabbit.map.chunks`, plus `rabbit.map.snapshot` replies, in the real wire format: one chunk per 40 cm block of what the camera has seen, floor quads plus 5 cm columns (walls 1.2 m, labelled objects at their height). They feed the voxel map and the minimap.
  - `rabbit.map.reset` clears the map with tombstones;
  - full ZED health fields, `rabbit.steering`, and a `rabbit.telemetry` stub (WiFi `SIM`, `simulated: true`), so the link shows LINK.
- **`scripts/sim.sh restart <node>`** restarts one node, for example `sim` after a code change. It uses the current environment, not the original `SIM_*` values.
- **End-to-end tests:** `RABBIT_E2E=1 … pytest tests/test_e2e.py` (~2.5 min, random ports) explores 60 s and checks coverage, drives to the refrigerator, cancels a trip, restarts the camera mid-trip (nav must fault `odometry reset`), and with `SIM_BODY=1` reverses into a wall with lidar and ToF, with ToF only, and into a 3 cm threshold only the bumper catches (stops 4–12 cm off the wall without contact; bumper → zero command ≤ 50 ms), then kills the safety process mid-drive (the motors stop on the 0.4 s command timeout).
- **Shared code:** worlds, robot dynamics, scan and mapper live in `src/lib/simulation.py`, shared with `tests/sim.py`.

`tests/test_nvblox_mapper.py` is skipped on the Mac. It needs the built extension, so run it on the robot:

```sh
ssh -i ~/.ssh/rabbit_id_rsa root@192.168.1.53 'docker run --rm --runtime nvidia -v /root/rabbit/workspaces/rabbit:/rabbit -w /rabbit --entrypoint bash rabbit:latest -c "uv pip install -q --target /tmp/pt pytest && PYTHONPATH=src:/opt/rabbit_nvblox:/tmp/pt /rabbit/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_nvblox_mapper.py"'
```

The ZED SDK is 5.5. The pyzed API is in `src/pyzed/sl.pyi`: grep it instead of guessing names.

### Observability

Every new behaviour, decision, failure path or state change must be answerable from Forge alone: what happened, why, with which ids and numbers. Conventions and budget: `docs/reports/2026-10-03-observability.md`.

**Adding an event:**
1. Call `self.event(name, reason, severity=..., **fields)` where the decision is made (any thread). `name` is `<area>.<what>` in snake_case: a past participle for transitions (`nav.mission_started`), a noun for decisions (`nav.safety_stop`, `planner.plan`). `reason` says why in words. `severity`: info, warning (handled), error (work or data lost), critical (node cannot continue).
2. Fields: the numbers that justify the decision, with the unit in the key (`free_distance_m`, `motor_current_a`, `blocked_s`, `plan_ms`); text such as `source`, `mode` and `outcome` lands in `labels`. Never pass secrets. `snapshot` is reserved; ids (`mission_id`, `trip_id`, `exploration_id`, `odom_session`, `map_id`, `map_session`) go to their own columns and normally come from `set_log_context`, so set the context when a mission, trip, exploration or session starts and clear it when it ends.
3. Replace the log line it duplicates and keep its text with `message=` (evals and slabs match some messages, e.g. `Restarting the camera process: ...`). The event writes that line itself.
4. Anything that can repeat in a loop gets `every_s` (per name and reason); the next admitted event carries `suppressed`. Never emit per control tick or per frame: continuous values belong in the node's state message, timings in `self.observe(name, ms)` (10 s max/mean/count in `node_metrics.values`).
5. Pure libraries (`lib/trip.py`) don't import the node: collect `(name, reason, severity, fields)` in an outbox (`Navigator.record`) and let the node drain it.
6. Pin a decision that matters with a test on `node.event_queue` (see `tests/test_observability.py`).

**Adding a field to a state message or a new subject:** the Forge side is the forge-dev checklist (zod schema in `streams.ts`, column with unit in `schema.sql`, README, slab). Optional fields keep older senders parsing; the simulator must send every field Forge requires, or Forge drops the whole message.

**Checking observability in the simulator** (pick a free port: 14222 is the default, 14322 belongs to `tests/test_e2e.py`, and other agents may run their own):

```sh
SIM_RUN_DIR=$SCRATCH/sim SIM_NATS_PORT=14522 SIM_WS_PORT=19522 scripts/sim.sh start
# Forge reads only its .env when one exists, so run a copy without it
F=$SCRATCH/forge-sim && mkdir -p $F && cp -R workspaces/forge/{src,slabs,graph,package.json,tsconfig.json} $F/ && ln -sfn $PWD/workspaces/forge/node_modules $F/node_modules
(cd $F && FORGE_NATS_URL=nats://127.0.0.1:14522 FORGE_DATA_DIR=$F/data nohup node --liftoff-only src/cli.ts writer > $F/writer.log 2>&1 &)
# drive the scenario on the sim NATS (planner goals, nav missions, rabbit.sim.restart, rabbit.nav.explore), wait 10 s for the flush
(cd $F && FORGE_DATA_DIR=$F/data node --liftoff-only src/cli.ts query "SELECT ts, node, name, reason, values FROM events ORDER BY ts")
(cd $F && FORGE_DATA_DIR=$F/data node --liftoff-only src/cli.ts slab run decisions)
```

Check the writer log: `rows/s` lists `events` and every table you touched, and `malformed` must not grow. Stop with `scripts/sim.sh stop` (same `SIM_RUN_DIR`) and `kill` the writer. Each `sim.sh start` gets its own `boot_id`.

### Frames and conventions

- **World frame.** ZED `RIGHT_HANDED_Y_UP`: x right, y up, the camera looks along −z. Everything zed publishes (pose, obstacles, objects, mesh) is shifted by one floor offset (`encoded_floor_y`), so the room floor is y = 0 and a robot on the floor has pose y ≈ 0.137. `lib/floor.py` follows slow drift of the floor but ignores jumps (the robot lifted onto a table stays at table height above the room floor) until the robot has driven 1 m on the new level. Heading 0 is −z (north on the HUD compass).
- **Reflections.** Stereo depth sees a mirrored room below glossy floors and glass. The nvblox depth kernel clips every ray at the floor plane and snaps points less than 3 cm above it onto it (when that moves them < 15 cm along the ray), so the floor stays flat; beyond 2 m it drops points lower than 3 cm + 2 cm per metre of range above the floor, because a 1° pose pitch error lifts the floor 7 cm at 4 m and turned the far floor into phantom obstacles (`MAX_INTEGRATION_DISTANCE` 5 m relies on this). After loading a map everything below the floor is cleared. HUD voxels are offset by half a cell vertically, so floor noise of ±2.5 cm stays in one row drawn with its top at y = 0.
- **Planner angle.** `theta = atan2(z, x)`; positive curvature increases theta.
- **Signs.** `steer > 0` turns right and `curvature > 0` turns right. Right turns are wider: at steer 0.5 and 1.0 the curvature is 1.33 and 2.49 1/m, against 1.70 and 3.34 1/m to the left.
- **Two reference points.** The camera sits 0.1845 m ahead of the rear axle (`CAMERA_TO_REAR_AXLE`) and 0.06 m off the centerline (`CENTERLINE_OFFSET`).
  - Mission coordinates, pose and HUD paths use the camera point.
  - Kinematics and tracking use the rear axle: nav converts path points with `rear_axle_path`, and explore converts planner waypoints with `camera_point`.
- **Footprint** from the rear axle: front 0.2245, rear 0.07, half width 0.10, margin 0.04. The 2.0 body (bumpers on) is front 0.2452, rear 0.072, half width 0.102; `rabbit-safety` already uses it (`safety_loop.BODY_2_0`).
- **Body sensor frame** (lidar, ToF, safety): rear-axle centre on the floor, x forward, y **left**, z up (`free_distance` takes x forward, y right: `lidar.to_safety_frame`). RPLIDAR angles grow clockwise seen from above and 0° is opposite the cable, so the cable-forward mast means mount yaw 180° (`LIDAR_MOUNT=x,y,z,yaw`, lidar 0.1597 m ahead, plane 0.23 m). ToF mounts (`lib/tof.py` `MOUNTS`, from `cad/brackets/README.md`): front 0.2246 m ahead, rear 0.0514 m behind, ±0.019 m, 0.0578 m high, yaw ±22° / 180 ∓ 22°, pitch +15°, roll 90°; zone order and distance convention are config (`TOF_FLIP_*`, `TOF_ROLL_DEG`, `TOF_DISTANCE`) until checked on the sensor.

### Map chunk wire format

Map chunks travel on `rabbit.map.chunks`, and `rabbit.map.snapshot` holds them concatenated. Each chunk is one nvblox block (40 cm cube), in the Y-up world with the floor estimate subtracted.

- **Header** `<IIIfff`: index, vertex_count, triangle_count, origin x, y, z.
- **Body:** int16 vertices in mm relative to the origin, then uint16 triangle indices, padded to 4 bytes.
- **Indices** are assigned per session to nvblox blocks; a chunk with 0 vertices is a tombstone (the block disappeared after a map rebuild).
- **Decoders:** `lib/spatial_map.py`, `web/src/perception/RoomMap.ts` and Forge `src/streams.ts`. Change all three together.

### Gotchas learned the hard way

- **ZED node and the GIL.** pyzed calls hold the GIL. Anything slow in the ZED process (mesh filtering, walking every chunk) freezes the event loop, and pose and obstacle publishing stall. Keep per-update work proportional to the changed chunks and measure capture gaps after changes. The node logs `Slow grab` (the SDK's `grab()` itself, GIL released), `GIL stall` (a watchdog thread woke late, so Python code or a pyzed call held the GIL) and `Slow frame processing` with a per-step breakdown, all above 300 ms. GEN_3 stalls `grab()` for 2–3 s once a few seconds after relocalizing and occasionally while mapping; nav stops on a pose older than 0.5 s and resumes, so these cost a pause, not safety. `save_area_map` holds the GIL for about 0.6 s, which is why saves happen only when idle.
- **ZED threads.** The ZED node has a grab thread, a sensors thread and a map worker. Respect the locks: `_camera_lock` (SDK calls), `mapper_lock` (nvblox), `map_lock` (encoded chunks and the pending update). The grab thread only hands the latest depth, pose and timestamp to the map worker and never waits for nvblox. Publish only from the event loop.
- **ZED CPU.** Nearly all of `rabbit-zed`'s CPU is inside the SDK, mostly the GEN_3 tracking optimizer, which grows with keyframes; our Python is ~15% of a core. Hence `compute_preference = PREFER_GPU`, depth on every second frame, and lower rates while idle: 30 fps while anything moves (nav motion, joystick or drive command, pose motion, `rabbit.zed.wake {seconds}`), 5 fps idle with a HUD heartbeat, 1 fps idle and unwatched, and full rate for the first 60 s of a relocalization. A 15 fps cap saved no CPU and added 55 ms of pose latency, so it was removed. Explore and the planner publish `rabbit.zed.wake` before they need fresh poses. While recording an SVO (`rabbit.zed.record {name}`, LOSSLESS on the CPU; Orin Nano has no NVENC) the detector and nvblox integration pause; the log line on stop gives frames and fps — check it is ≥ 14 fps. GEN_3 in SDK 5.5.0 keeps adding keyframes even standing still (a known SDK bug, ~50/min at first, slowing down), and its optimizer thread takes 0.5–1 core whatever the frame rate. GEN_1 runs at about half that, but in 5.5 it doesn't relocalize against a saved `.area`, so the map couldn't survive restarts; revisit when Stereolabs fixes GEN_3. `enable_2d_ground_mode` and `enable_localization_only` saved nothing measurable. ZED spatial mapping was replaced by nvblox: same CPU, but it held ~2 GB of RAM and never corrected its mesh after loop closures. Never attach gdb to the live process.
- **rabbit-loc.** Relocalization runs in RTAB-Map localization mode (never writes the DB); a first fix or a jump needs 2 agreeing appearance matches; `map←odom` is in the raw ZED world (not floor-shifted) and is valid only for the `odom_session` it carries. zed's `LOC_MODE` (`off`/`shadow`) only sends keyframes and reports `gen3_from_loc` (constant when both agree) in health and `data/loc/shadow.jsonl`. `LOC_MODE=apply` makes RTAB-Map the map frame (`lib/map_frame.py`): GEN_3 area memory, `.area` save/load and the relocalization state machine are off; the published pose, obstacles, objects and the floor use `C·odom` (C = map←odom, `odom` stays as is); nvblox integrates frames at `C·odom` into `data/map/loc.nvblx` (tagged with the loc `map_id` in `loc.nvblx.id`); depth frames are kept with their odom pose and the map is rebuilt from the file plus those frames when C moves more than 5 cm / 2°; while loc is not localized (relocalizing, lost or silent 5 s) nothing is integrated, health says `relocalizing`, and the waiting frames go in with the next C; a new loc `map_id` archives `loc.nvblx` and starts an empty map.
- **Relocalization rules.** Never save the map before relocalizing. Mapping waits for relocalization. After a tracking failure the process restarts rather than re-enabling tracking in-process, because re-enabling left the SDK broken and produced poses tens of metres away. A pose with confidence 0 is not published. Relocalization counts only after a localized status (KNOWN_MAP, MAP_UPDATE, LOOP_CLOSED) holds for 10 s (`lib/relocalization.py`): the SDK reports KNOWN_MAP, re-initialises 5–8 s later and only then settles, and LOST right after start is not a relocalization. Health has `relocalizing`. In that window the SDK also returns translations in millimetres for a few seconds (sometimes for a whole session); `plausible_position` drops them, and the process restarts if they last 15 s outside relocalization.
- **Obstacles.** Heights are measured from a plane fitted to the floor in each frame, not from the global floor estimate. Sectors use the 4th nearest point, because single "flying pixels" inside the blind zone used to stop the robot.
- **Object detector.** The SDK's boxes for custom YOLO models are cubes (depth = width) and its track IDs churn. `lib/detector.py` sets per-class confidence thresholds (35, or 50 for small classes the open-vocabulary model hallucinates), publishes a track only after 3 detections and rebuilds each box with a per-class depth along the view ray. The HUD merges same-label detections that overlap and forgets a remembered object once it is in the camera's view for 2.5 s without being detected.
- **Mission tracking.** `rabbit.nav.state.mission_id` persists after a mission ends, so use `mode`. The planner sends its own mission ids (`<trip_id>.<n>`) and waits for nav to adopt them; a different id in nav state means someone else took over.

### Route planning

- **Flow.** `rabbit.planner.goal` (request-reply) `{id?, source, x, z, heading_deg?, tolerance?} | {object: {label, x, z, width, length, seen_from?}} | {place: name}`, plus `preview: true` to plan without driving. Refused while `rabbit.health.zed` reports `relocalizing` or memory INITIALIZING/SEARCHING (poses are in a temporary frame then); LOST after relocalizing is fine. It picks a goal, plans with Hybrid A*, smooths and sends the route as one nav `path` step. It publishes `rabbit.planner.state` at 2 Hz during a trip (phase, target, goal, remaining path, replans, recoveries, reason, message), every 2 s otherwise. Forge, the HUD GO TO click and explore all go through it; `rabbit.nav.cancel` from anyone but the planner ends the trip.
- **Goals.** Objects: the detector's centre snaps to the nearest obstacle cluster within 0.6 m, candidate viewpoints face it at 0.3–1.5 m and are scored by the distance along the view ray to the first obstacle cell (0.5 m preferred, at least 0.4 m so nav's stop doesn't block the last metre), reach cost, unknown cells and clearance; tiers prefer line of sight through mapped cells, a free 0.3 m straight approach behind the viewpoint, and `seen_from` spots (where the robot saw it, from Forge) within 1.2 m as a tie-break. When a viewpoint goes bad on a replan, its replacement pays 0.5 per metre away from it. On arrival more than 0.9 m from the surface it looks again for a closer view (twice at most). Points: the camera lands on the point whichever way the robot faces (the search checks the camera, not the axle), or the nearest roomy reachable cell when the point is inside furniture. Heading goals end with a 0.3 m straight approach so the tracker settles the heading; tolerance 30° for object views, 15° for places.
- **Replanning** (4 Hz tick, at most every 0.75 s): the remaining path is re-checked against the newest map plus the scan obstacle memory (one point per 5 cm cell, hits up to 3 m, kept 6 s, cleared when a later ray passes through), and replanned when it gets closer to an obstacle than when planned, when the robot is 0.35 m off it, after a pose jump, when nav is `blocked` for 1.5 s, or when nav arrives short of the goal. After two blocked replans, or a nav `blocked` / `step timeout` / `stuck` fault, it backs up to 0.35 m along its own trail and replans, at most 3 times. The trail is kept in the odometry frame, dropped when the robot is lifted or the camera session changes, and only the part driven forward in the last 120 s, up to the last gear change, through cells the map knows are free, is used. A recovery is cancelled after 3 s + length/0.08 m/s or once it is more than its length + 0.15 m from its start; a block within 0.3 m of an earlier recovery spot fails the trip. `stuck` marks the contact point (front, or rear when reversing) as an obstacle for the rest of the trip. A first plan whose goal the robot already meets (0.3 m, 50°) ends the trip as arrived without driving. Nav blocked or faulted within 0.5 m of the goal counts as arrived, and so does reaching a viewpoint's position facing more than 50° off after two corrective replans (an Ackermann robot can't turn on the spot). Before a detour longer than max(2× the remaining route, remaining + 3 m) it stops and waits 4 s once, so a person passing doesn't send it around the flat. No route mid-trip: stop and retry every 3 s, failing after 3 attempts. A plan job (all goal candidates) gets 1.2 s. Safety faults (collision, stall, odometry reset) end the trip.
- **Costs.** A pose collides when any of the three footprint circles has less than 0.18 m of clearance (radius 0.12 plus the 5 cm cell). Inside 0.35 m beyond that the cost per metre rises linearly to 4×, so the route keeps to the middle and prefers wide gaps; unknown cells cost 2× (optimistic: the map is sparse, and the reactive guard plus replanning handle surprises). Reverse costs 4× along the corridor the robot's body swept in the last 120 s and up to 10× outside it, a gear switch 2 m, and reverse moves never enter unmapped cells, because the scan only covers the front. Primitives use at most 70% of full lock, so pursuit keeps steering to correct errors, and each goal is first tried with a 0.07 m larger footprint margin. The costmap is cropped to the robot, the target and the route plus 8 m (a stray block far away once made a 200 m wide grid), and padded with unknown space where the map does not reach, since the ESDF grid only covers the observed bounding box.
- **Search.** The heuristic is a Dijkstra cost-to-go from the goal on a 10 cm grid with the same costs, stopped once it passes the start; an unreachable goal fails in milliseconds without searching. States are 10 cm × 5°, primitives 0.15 m arcs at five steering levels per gear; analytic shots (Dubins for poses, a single arc for points) are tried within 4 m and accepted only within 10% of the heuristic, so they don't cut through tight gaps. Kernels are numba (`nogil`) and compile on first use: each node calls `navmap.warm_up()` at start (~30 s cold on the Jetson after a code change, 0.5 s from the cache).
- **Measured on the Jetson** (archived real map, warm): fridge trip 32 ms, 12 m cross-apartment route 76 ms, mesh fallback 68 ms; replans reuse the chosen goal. Plans run in a thread so the node keeps reading telemetry.
- **Frames in nav.** Pose messages carry the map pose and `odom` (camera-frame deltas chained since start, so relocalization and loop-closure jumps don't appear in it). Nav steers in the odom frame: mission coordinates arrive in the map frame and are converted at step start with the current map←odom transform; published goal and path are converted back. Without `odom` nav falls back to the map frame and re-anchors missions on pose jumps.
- **Nav's guard** stops at 0.15 m of free travel (or at what is left of the current path segment + 3 cm, if less, so it reaches gear switches planned next to obstacles) (it already creeps at minimum speed below 0.6 m) and resumes at 0.25 m. The camera can't see closer than ~0.3 m, so remembered scan points that are within 0.4 m of the camera never expire while they stay there; otherwise a robot held in front of a wall would forget it after 4 s and drive on (pinned by a sim test). A path or goto step blocked within 0.12 m of its end counts as arrived, and a path counts as finished only when less than the lookahead remains along it (a turnaround loop ending next to its start used to finish instantly). Other trips: `collision` when the horizontal IMU acceleration averaged over 50 ms exceeds 5 m/s² (single samples reach 8–10 m/s² on the floor joints), `stall` at > 1.8 A without ground speed, and `stuck` when nav commands motion but the pose hasn't moved for 2.5 s (backing into an unseen wall at low duty draws only 0.5–0.7 A). The HUD is a viewer: nothing depends on its heartbeat. Motor commands are slew-limited in rabbit-roboclaw (accelerate 1.5/s, brake 5/s) and stop 0.4 s after the last command.
- **Offline replay.** `workspaces/bench/replay/` (its inputs, the flat's maps, live in the gitignored `data/offline/`) decodes saved `.nvblx` files (sqlite: the ESDF slice is in the z = 0 blocks, layers 3–4, 20-byte voxels) into clearance grids and replays every recorded trip from `planner_state` through the simulator.
- **Places** are saved by the planner in `data/map/places.json` with the zed `map_id`; places from another map are refused. Objects are not stored on the robot: Forge finds them in ClickHouse.

## Web HUD (`workspaces/web`)

React 19 with the React Compiler, Vite 8, three.js, uPlot and `@ai-sdk/react`. Commands run from `workspaces/web` with the repo's Yarn: `node ../../.yarn/releases/yarn-4.9.3.cjs <script>`.

- **Dev server** at https://localhost:3005. Start it detached, because session background tasks die after 2 hours:

  ```sh
  cd ~/projects/rabbit/workspaces/web && nohup node ../../.yarn/releases/yarn-4.9.3.cjs dev > /tmp/rabbit-web.log 2>&1 &
  ```

  Check with `curl -sk -o /dev/null -w "%{http_code}" https://localhost:3005/`. Vite hot-reloads changes.
- **Checks:** `node ../../.yarn/releases/yarn-4.9.3.cjs tsc` (`tsc --build`) and `node ../../.yarn/releases/yarn-4.9.3.cjs vite build`. There is no linter or test runner.
- **NATS.** The default is `wss://jetson.rabbit:9222`; `VITE_NATS_URL` overrides it for a local NATS. The robot build sets it empty, so the HUD connects to `/nats` on whatever address served it (the LAN name or the tunnel).
- **Chat.** The dev server calls the robot's chat at `https://jetson.rabbit` (`VITE_CHAT_URL`); if the browser hasn't accepted that self-signed certificate the chat fails with `Failed to fetch`, so use https://jetson.rabbit itself for chat screenshots. The robot build uses an empty `VITE_CHAT_URL`, so it calls the same origin.
- **Production.** The robot serves the built HUD at https://jetson.rabbit. `scripts/deploy.sh rabbit-web` rebuilds and redeploys it.

**Layout:**

| Directory | Contents |
|---|---|
| `perception/` | `Scene.ts` (render loop and pose smoothing), `RoomMap.ts` (the room map in two styles: VOX, 5 cm voxels from `voxelMesh.ts` with only exposed faces and per-corner ambient occlusion, the default; SURF, shaded mesh; grouped draw calls, ceiling cut per view, cleared on `rabbit.map.reset`; a worker for the minimap raster), `RobotModel.ts`, `GroundFx.ts` (compass ring), `SteerFx.ts` (steering corridor), `NavFx.ts` (mission path), `Telemetry.ts` (store; `trip` is `rabbit.planner.state`), `mission.ts` |
| `hud/` | panels with uPlot charts, minimap, indicators |
| `chat/` | Forge chat and result widgets |
| `controller/` | gamepad and keyboard driving on `rabbit.cmd.joy` |
| `camera/` | preview feed |
| `app/NatsProvider.tsx` | connection and stale-link detection |

- **Style.** Keep the existing HUD look (opaque panels, Crysis-like) and English UI text. Avoid per-frame allocations and React re-renders at telemetry rate: the store batches, and panels write to the DOM directly.
- **Verifying visually.** Use the claude-in-chrome tools on https://localhost:3005: create your own tab, screenshot, then close it. A tab in the background doesn't run `requestAnimationFrame`, so frame timing can't be measured there.
- **Don't click to set goals** on the live robot without the user's go-ahead (the G / GO TO arming step).

## Committing

Conventional commits on `main`, staging explicit paths. Never stage `cert/*.pem`. The deploy script is `scripts/deploy.sh`.
