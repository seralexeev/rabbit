# Full-stack simulator on the Mac

Date: 2026-10-03, ~03:50–04:20 UTC. The robot was off. Uncommitted.

## Why

`tests/sim.py` drives `nav.Node` and the `Navigator` in-process with a fake clock. The real processes, their NATS contracts and their timing (planner thread, explore loop, KV and JetStream, reconnects) could only be checked on the robot.

## What

- **`src/lib/simulation.py`** holds the parts that `tests/sim.py` and the node share:
  - the worlds: `room_grid`, `apartment`, `corridor_flat`, `open_plan`;
  - the bicycle model with the measured delays (0.06 s dead time, 0.05 s steering and speed lags, 0.464 m/s per unit duty);
  - the 48-sector scan, the 87° / 5 m camera mapper and the body collision check.
- **`src/node/sim.py`** (`rabbit-sim`) plays the camera and the motors.
  - Commands go through the real `CommandArbiter`, the roboclaw slew (accelerate 1.5/s, brake 5/s) and the 0.4 s timeout.
  - Physics runs at 100 Hz; the robot stops at walls.
  - Published, each with the measured delay in its `ts`:
    - pose (30 Hz, map + odom + session);
    - scan (15 Hz);
    - clearance grid (1 Hz, plus snapshot replies);
    - health, imu (gravity only), roboclaw currents (higher at a contact, so `stuck` fires);
    - objects in view.
  - `rabbit.sim.restart` changes the odometry session; `rabbit.sim.state` reports pose, coverage and contacts.
- **`scripts/sim.sh start|stop|status`.**
  - Starts NATS on 14222/19222 with JetStream, then creates the `rabbit` KV and a `LOGS` stream with the Python client (no `nats` CLI needed).
  - Then starts sim, nav, planner and explore under `nohup`, plus the HUD dev server with `--hud`.
  - Docker (colima) was not running on the Mac, so the script uses `nats-server` from PATH or downloads the release binary into `~/.cache/rabbit`.

## Checks

- **First run, exploring the apartment for 60 s:** coverage 0.18 → 0.55, no contacts; the planner was ready in 0.3 s with a warm numba cache.
- **`tests/test_e2e.py`** (opt-in with `RABBIT_E2E=1`, 103 s), all over NATS:
  - exploration for 60 s gives coverage ≥ 0.45 and no contacts;
  - a planner trip to the refrigerator object arrives within 1.6 m;
  - an operator cancel ends the trip, nav goes idle and the robot stops;
  - a simulated camera restart mid-trip makes nav fault `odometry reset`, and the trip fails.

## HUD support (same night)

- **Map chunks.** The voxel map and the minimap were empty because the sim published only the planner's clearance grid. It now also publishes `rabbit.map.chunks`, plus `rabbit.map.snapshot` replies, with `encode_chunk`. Each 40 cm block the camera has seen is sent once and again when it changes: a floor quad per free cell and a 5 cm column per occupied cell (walls 1.2 m, labelled objects at their height). `rabbit.map.reset` sends tombstones and clears the mapper.
- **Health and telemetry.**
  - Health carries the fields the ZED panel shows (fps, capture time, pose state, drops, exposure/gain/WB, temperatures, mapping state, chunks, points, bytes).
  - `rabbit.telemetry` is a stub marked `simulated` (WiFi `SIM`), so the link indicator says LINK.
  - `rabbit.steering` and the roboclaw fields fill the drive panels.
- **ZedPanel.tsx** treats every health field as optional: `—` instead of `undefined/0`, `—K` or `NaNK`. `tsc` passes.
- **EXPLORE START is not gated on anything the sim lacks.** It is a two-step `ConfirmButton`: the second click must come within 4 s, otherwise it silently disarms. Clicked twice in time from the browser, exploration started ("Exploration started" in the HUD console and in the explore log).
- **Screenshots:** `data/offline/sim-shots/hud-3rd-exploring.jpg`, `hud-top-exploring.jpg`. They show the voxel walls and floor, the minimap floor plan, the route, LINK, and the ZED panel with 178 chunks / 424 KB.
- **Tooling fixes:**
  - `sim.sh stop` stopped NATS first. Nodes kept reconnecting, and an orphaned sim joined the next stack on the same port: two map sessions and a spurious `odometry reset`, which nav correctly faulted on. Now the nodes stop first (with a 5 s wait and kill -9), NATS last.
  - The e2e tests pick a free port for each stack.

## Not done

- Forge chat against the simulator: it would need `FORGE_NATS_URL` pointed at it and its own storage.
- The HUD with `--hud` was not opened in a browser in this session.
