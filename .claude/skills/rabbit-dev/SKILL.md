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
| `lib/node.py` | `RabbitNode` base: NATS connect (waits for the server at startup), `subscribe` (exceptions logged, never fatal), `publish` / `publish_json` (dropped and counted while NATS reconnects), `set_interval`, `async_task`, KV watchers, log records to `rabbit.log.<node>` with context (`set_log_context(mission_id=...)`) |
| `lib/geometry.py` | camera and rear-axle offsets, the asymmetric steering-to-curvature tables, `rear_axle_point`, `camera_point`, `rear_axle_path`, `wheel_speeds` (electronic differential) |
| `lib/safety.py` | `Footprint`, `free_distance` (the swept footprint along an arc against scan points), `bin_scan` (4th nearest point per sector), `heights_above_floor` (per-frame robust floor plane) |
| `lib/planner.py` | occupancy grid from the mesh, costmap, Hybrid A* with Dubins shots, frontier detection and ranking |
| `lib/spatial_map.py` | map chunk wire format, map file paths |
| `lib/drive.py` | command subjects, joystick parsing, `CommandArbiter` (the joystick owns the motors for 1 s after active input) |
| `node/zed.py` | camera: tracking, relocalization, spatial mapping with the persistent base layer, floor estimation, obstacle scan, IMU, preview, health |
| `node/nav.py` | missions, pure pursuit on the rear axle, collision guard, safety trips, re-anchoring |
| `node/explore.py` | frontier exploration on top of nav missions |
| `node/roboclaw.py`, `node/steering.py`, `node/ina.py`, `node/telemetry.py` | motors, servo, power monitor, Jetson, Docker and Wi-Fi |

**Tests:**

```sh
cd ~/projects/rabbit/workspaces/rabbit && uv run --no-project --python 3.10 --with pytest --with numpy python -m pytest tests -q
```

The planner tests are timing-sensitive under heavy CPU load: rerun before believing a failure. Real verification happens on the robot after a deploy.

The ZED SDK is 5.5. The pyzed API is in `src/pyzed/sl.pyi`: grep it instead of guessing names.

### Frames and conventions

- **World frame.** ZED `RIGHT_HANDED_Y_UP`: x right, y up, the camera looks along −z. Pose y is floor-relative (the camera stands 0.137 m above the floor). Heading 0 is −z (north on the HUD compass).
- **Planner angle.** `theta = atan2(z, x)`; positive curvature increases theta.
- **Signs.** `steer > 0` turns right and `curvature > 0` turns right. Right turns are wider: at steer 0.5 and 1.0 the curvature is 1.33 and 2.49 1/m, against 1.70 and 3.34 1/m to the left.
- **Two reference points.** The camera sits 0.1845 m ahead of the rear axle (`CAMERA_TO_REAR_AXLE`) and 0.06 m off the centerline (`CENTERLINE_OFFSET`).
  - Mission coordinates, pose and HUD paths use the camera point.
  - Kinematics and tracking use the rear axle: nav converts path points with `rear_axle_path`, and explore converts planner waypoints with `camera_point`.
- **Footprint** from the rear axle: front 0.2245, rear 0.07, half width 0.10, margin 0.04.

### Map chunk wire format

Map chunks travel on `rabbit.map.chunks`, and `rabbit.map.snapshot` and `room.chunks` hold them concatenated.

- **Header** `<IIIfff`: index, vertex_count, triangle_count, origin x, y, z.
- **Body:** int16 vertices in mm relative to the origin, then uint16 triangle indices, padded to 4 bytes.
- **Index ranges:** indices ≥ `1 << 20` are base chunks loaded from the saved map, and a chunk with 0 vertices is a tombstone.
- **Decoders:** `lib/spatial_map.py`, `web/src/perception/RoomMap.ts` and Forge `src/streams.ts`. Change all three together.

### Gotchas learned the hard way

- **ZED node and the GIL.** pyzed calls hold the GIL. Anything slow in the ZED process (mesh filtering, walking every chunk) freezes the event loop, and pose and obstacle publishing stall. Keep per-update work proportional to the changed chunks and measure capture gaps after changes.
- **ZED threads.** The ZED node has a grab thread, a sensors thread and a map worker. Respect the locks: `_camera_lock`, `map_lock`, `_sensors_lock`, `_pending_lock`. Publish only from the event loop.
- **Relocalization rules.** Never save the map before relocalizing. Mapping waits for relocalization. After a tracking failure the process restarts rather than re-enabling tracking in-process, because re-enabling left the SDK broken and produced poses tens of metres away. A pose with confidence 0 is not published.
- **Obstacles.** Heights are measured from a plane fitted to the floor in each frame, not from the global floor estimate. Sectors use the 4th nearest point, because single "flying pixels" inside the blind zone used to stop the robot.
- **Mission tracking.** `rabbit.nav.state.mission_id` persists after a mission ends, so use `mode`. Explore sends its own mission `id` and waits for nav to adopt it.

## Web HUD (`workspaces/web`)

React 19 with the React Compiler, Vite 8, three.js, uPlot and `@ai-sdk/react`. Commands run from `workspaces/web` with the repo's Yarn: `node ../../.yarn/releases/yarn-4.9.3.cjs <script>`.

- **Dev server** at https://localhost:3005. Start it detached, because session background tasks die after 2 hours:

  ```sh
  cd ~/projects/rabbit/workspaces/web && nohup node ../../.yarn/releases/yarn-4.9.3.cjs dev > /tmp/rabbit-web.log 2>&1 &
  ```

  Check with `curl -sk -o /dev/null -w "%{http_code}" https://localhost:3005/`. Vite hot-reloads changes.
- **Checks:** `node ../../.yarn/releases/yarn-4.9.3.cjs tsc` (`tsc --build`) and `node ../../.yarn/releases/yarn-4.9.3.cjs vite build`. There is no linter or test runner.
- **NATS.** The default is `wss://jetson.rabbit:9222`; `VITE_NATS_URL` overrides it for a local NATS.
- **Chat.** The dev server calls the robot's chat at `https://jetson.rabbit` (`VITE_CHAT_URL`). The robot build uses an empty `VITE_CHAT_URL`, so it calls the same origin.
- **Production.** The robot serves the built HUD at https://jetson.rabbit. `scripts/deploy.sh rabbit-web` rebuilds and redeploys it.

**Layout:**

| Directory | Contents |
|---|---|
| `perception/` | `Scene.ts` (render loop and pose smoothing), `RoomMap.ts` (mesh map, grouped draw calls, a worker for the minimap raster), `RobotModel.ts`, `GroundFx.ts` (compass ring), `SteerFx.ts` (steering corridor), `NavFx.ts` (mission path), `Telemetry.ts` (store), `mission.ts` |
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
