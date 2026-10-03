# 2026-10-03 Observability: structured events, node metrics, start snapshots

Visibility became a first-class requirement: any "why did it stop / turn back / reboot / lose itself / drain the battery at 03:12" must be answerable with SQL over the recorded Parquet alone. The audit, ranked gaps, convention, budget and measurements are in [reports/2026-10-03-observability.md](../reports/2026-10-03-observability.md); this entry is the short history. Done offline with the robot off; verified in the full-stack simulator.

## What was missing

Commands were recorded with their sender and sensors at full rate, but decisions were text or memory:
- nav's safety trips recorded the fault name without the current, speed, acceleration or free distance that triggered them; `free_distance = 0` meant obstacle, blind, stale scan or stale pose; a stale pose stopped the robot silently; cancels didn't say who;
- the planner's per-trip decision trail (replan triggers, waits, recoveries) was published but not stored, and rejected trips had no trip id so Forge dropped them;
- explore's choice of view (gain, cost) and abandoned frontiers lived in memory;
- `zed_health` kept 27 of ~60 fields: `relocalizing`, `map_mode`, `map_id`, the pose-filter counters and nvblox timings were lost; restart reasons were matched with `LIKE` on log text;
- the roboclaw watchdog stop and joystick takeover left no record;
- no boot or process ids, no record of the code revision or the constants in effect, no per-node CPU/RSS/event-loop stalls, no NATS slow-consumer count;
- the simulator's pose, motor, telemetry and health messages failed Forge's schemas, so sim runs recorded none of them.

## What changed

- `lib/observability.py` + `RabbitNode`: `self.event(name, reason, severity, every_s, **fields)` publishes on `rabbit.log.<node>.event` (kept by the existing `LOGS` stream, so no change to the robot's NATS) and writes the matching log line; `self.observe()` aggregates timings; `node.start` carries a snapshot (git revision from `REVISION` written by `deploy.sh`, a hash of `src/**/*.py`, versions, whitelisted environment, every upper-case constant); `node.stop` gives the reason; `rabbit.metrics.<node>` every 10 s (CPU, RSS, threads, event-loop lag from a 10 Hz probe, NATS traffic, drops, callback errors).
- Events in nav (mission lifecycle, `nav.safety_stop` with its measurement, `nav.hold` with its reason, pose jumps, odometry resets, overrides), the planner (`planner.plan` with trigger and outcome for every plan, waits, recoveries, bumps, `planner.trip_finished`, rejections with the request), explore (goal chosen with gain and cost, trip outcomes, frontiers abandoned and why), rabbit-zed (camera opened with SDK version, relocalization start/success/failure with duration and travel, tracking failure with tilt values, restarts, map save/skip/load/archive/reset/rebuild, recording, detector), roboclaw (watchdog stop, joystick ownership, port and status), telemetry (NATS `/varz`, GPU shared memory, boot id).
- Ids form a chain: explore sends `exploration_id` with each planner goal, the planner sends `trip_id` with each nav mission; nav, planner and zed set `odom_session`/`map_id` context.
- Forge: tables `events`, `node_starts`, `node_metrics`, `nats_server`; 21 new `zed_health` columns; `hold`, `mission_source`, `trip_id` in `nav_state`; `exploration_id` in `planner_state`; `timeline` lists events as decisions; slabs `decisions`, `nav_stops`, `camera_restarts`, `node_health`, `node_versions`; prompts and three evals.
- Simulator payloads complete (plus a simulated INA power monitor), sim events for camera restarts, resets, contacts, owner changes and watchdog stops; each `sim.sh start` has its own boot id. HUD stop, missions and explore start send `source: 'hud'`.

## Numbers

- Cost on the Mac: probe and metrics +0.77 ms CPU per second per node (0.077 % of a core); 75 µs per event including its log line; 13.5 µs for `event()` alone; 0.6 µs when rate-limited. Estimated on the Jetson: ≈ 0.3 % of a core per node, ≈ 2.7 % of one core for 9 nodes.
- Size: ≈ 300 B per event in JSON, 130 B per metric row in zstd Parquet; ≈ 0.5–0.6 MB/h of Forge disk for the new tables while driving, against 15–20 MiB/h in total.
- Sim run (port 14522, 6 scenarios, ~4 min): 66 events of 21 names; the last exploration reconstructed as 30 linked events; the blocked stop shows a 10 s hold at 0.14 m free before the fault; the camera restart precedes nav's odometry-reset stop by 15 ms.

## Tests

`tests/test_observability.py` (4 tests: hold and blocked stop at a wall with the mission id, stuck and collision measurements, a lost route's plan and outcome records, the rate-limit contract) and `src/ingest/jetstream.test.ts` (event routing). Robot suite 161 passed, 3 skipped; Forge `pnpm check` green (159 tests).

## Needs the robot

rabbit-zed's and telemetry's events and fields ran only through `py_compile`/pyflakes; see the roadmap and section 9 of the report.
