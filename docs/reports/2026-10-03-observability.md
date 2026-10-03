# Observability: audit, convention and plan (2026-10-03)

Goal: answer "why did it stop / turn back / reboot / lose itself / drain the battery at 03:12" with SQL over the recorded Parquet alone (chDB through Forge, or `clickhouse local` / DuckDB over the files), without the live robot. This report audits what each node records, ranks the gaps, sets one convention for every node and records what was implemented, measured and verified. Implementation details are in [log/2026-10-03-observability.md](../log/2026-10-03-observability.md).

## 1. Audit (state before this change)

Forge recorded 24 tables. Commands were well covered (`nav_events`, `command_events`, `drive`, `joy` with `source`), as were sensors and 1–50 Hz state. Decisions were not: most of them existed only as free-text log lines, some only in memory.

| Node | Publishes → Forge table | Logs and their context | Decisions and transitions | Blind spots |
|---|---|---|---|---|
| `nav` | `rabbit.nav.state` → `nav_state` (10 Hz); `rabbit.cmd.drive` → `drive` | `mission_id` context; "Safety stop: %s" with `fault` only; "Pose jump", "Mission cancelled", "Mission arrived" | mission start/arrive/cancel/reject, 8 safety trips, guard hold/resume, pose re-anchoring, odometry reset, manoeuvre direction flips, blind-zone memory | trips recorded the fault name but no measurement (current, ground speed, acceleration, free distance); `free_distance = 0` meant obstacle, blind, stale scan or stale pose, indistinguishable; a stale pose stopped the robot silently; cancels did not say who; `mission_source`, path and queue published but not recorded; no `trip_id` on missions |
| `planner` (`lib/trip.py`) | `rabbit.planner.state` → `planner_state` (2 Hz, last replan `reason`, `message`) | `trip_id` context; "Plan ... in ms" with fields; "Trip phase: message" | trip start, plan/replan with trigger, no-route wait, detour hold, recovery (back-up), bump marking, closer view, terminal outcome | the per-trip decision trail (`events`, last 8) was published but not stored; only the last replan reason survived per 0.5 s row; rejected trips (bad place, camera unsettled, no pose) had no trip id, so `planner_state` dropped them; no link from a trip to the exploration that asked for it |
| `explore` | `rabbit.explore.state` → `explore_state` (2 Hz) | `exploration_id`, `map_session` context; start, stop, finish, frontier failures | goal choice (gain, cost), frontier abandonment, trip outcomes, map-extend request | why a view was chosen (gain cells, cost) and which frontiers were abandoned and why lived only in memory and in the 2 Hz `target`; no exploration id on the planner trips it ran |
| `rabbit-zed` | pose, imu, obstacle, objects, magnetometer, barometer, map chunks → tables; `rabbit.health.zed` → `zed_health` | `map_session` context; restart, relocalization, save, archive, load, recording, detector, slow grab, GIL stall, slow frame lines | relocalization start/success/give-up/timeout, tracking failure (tilt), implausible poses, map save/skip/fail, archive, load, mode switch, reset, rebuild, recording, detector enable | `zed_health` stored 27 of ~60 health fields: `relocalizing`, `map_mode`, `map_id`, `map_session`, `held_poses`, `odom_rejected`, `dropped_publishes`, `map_rebuilds`, nvblox timings, floor and tilt were published and lost; restart reasons only as text ("Restarting the camera process: ..."), which the chat evals matched with `LIKE`; slow grabs and GIL stalls only as warning lines above 300 ms, no distribution |
| `roboclaw` | `rabbit.roboclaw` → `roboclaw` (50 Hz) | connect, transient errors, port lost | joystick takes the motors (`CommandArbiter`), 0.4 s command watchdog zeroes the target, status bits | ownership changes and drive commands ignored while the joystick owned the motors were invisible; the watchdog stop was invisible, so "motors stopped because commands stopped" looked like a nav stop |
| `steering` | `rabbit.steering` → `steering` (20 Hz) | write failures | arbiter, 0.25 s kill switch | kill switch silent (low value: it follows every mission end) |
| `ina4235` | `rabbit.ina` → `power` (50 Hz) | read errors | none | fine; battery thresholds are queries |
| `telemetry` | `rabbit.telemetry` → `jetson`, `jetson_containers`, `wifi`; Docker events → `logs` (`docker.events`) | container lifecycle | jtop reconnect | NATS server health (slow consumers = message loss) not collected; GPU (shared) memory not recorded; container-stat errors swallowed (`except Exception: pass`); no boot id |
| `rabbit-loc` | `rabbit.loc.map_odom` → `loc` | session restarts, matches | localization status, corrections | covered by `loc` rows; events left for when it leaves shadow mode |
| `sim` | pose, obstacle, imu, roboclaw, grid, chunks, health, steering, telemetry stubs | restart, reset | camera restart, map reset, contacts | pose, roboclaw, telemetry and health payloads failed Forge's schemas, so a sim run recorded no pose, motors, power or camera health at all |
| `lib/node.py` (all) | `rabbit.log.<node>` → `logs` (LOGS JetStream, durable) | `context`, repeat suppression | callback exceptions (logged, not counted), async-task rates ("Async task capture: 28.1 tps" every 10 s) | no process metrics (CPU, RSS, loop stalls), no NATS counters, no boot or process id, no record of the code or constants that ran; `dropped_publishes` counted but never published except by zed |
| HUD (`workspaces/web`) | joy, drive stop, nav cancel, missions, planner goals, explore start, map reset | n/a | operator commands | stop button (`nav.cancel`, zero `drive`), HUD missions and explore start had no `source`; Forge defaulted them to `hud` but nav and planner reported "cancelled by operator" |
| Forge writer | `streams.ts` → Parquet | own log | run open/close | not recorded at all: `rabbit.zed.wake`, `rabbit.zed.record`, `rabbit.map.extend`, place save/delete, the planner's trip trail, explore's view gain; `nats_server` missing |

## 2. Gaps ranked by debugging value

1. **Decisions without a recorded reason and measurement** (nav safety trips, guard holds, replans, recoveries, trip outcomes, exploration goal choice and abandonment). These are the "why" of almost every incident; before, they were text or memory.
2. **Ambiguous stops**: `free_distance = 0` for four different causes, silent stale-pose stops, the roboclaw watchdog and joystick ownership. "Why did it stop" could not be answered from data.
3. **Camera lifecycle as structured data**: restart reasons, relocalization outcome and duration, map archive/reset/save, and the half of `zed_health` that was dropped (`relocalizing`, `map_mode`, `map_id`, pose-filter counters). "Why did it lose itself" depended on `LIKE` over log text.
4. **Correlation ids**: no exploration → trip → mission chain, no boot id, no process id; reboots were inferred from Jetson uptime resets.
5. **What code and constants ran**: lots of uncommitted work is deployed; nothing recorded which revision or which `SAFETY_STOP` was live.
6. **Process health**: no per-node CPU/RSS, no event-loop stall measure, NATS slow consumers invisible, callback exceptions not counted.
7. **Sim parity**: the simulator produced schema-invalid messages, so the full-stack sim could not be used to check observability.
8. **Command sources** from the HUD stop button and missions.

Lower value, left for later (section 6): per-stage zed latency beyond grab/frame, explore candidate lists, steering kill switch, rabbit-loc events.

## 3. Convention

**What goes where.**
- *Event*: a decision or a state change someone may ask "why" about. `self.event(name, reason, severity=..., **fields)` in any node. Rare (≤ a few per second at worst).
- *Periodic state*: values that change continuously (pose, nav state, health) stay on their own subjects and tables, at their rate.
- *Metric*: timings and counters aggregated per 10 s window by `self.observe(name, value)`, published in `node_metrics.values` as `<name>_max/_mean/_count`.
- *Log line*: narrative and debugging detail, exceptions with tracebacks. Every event also writes one log line (same text as before where one existed), so `docker logs` and log search keep working.

**Events.** Subject `rabbit.log.<node>.event`, captured by the existing `LOGS` JetStream stream (durable through writer restarts, no change on the robot's NATS), routed by Forge into `events`.
- `name`: `<area>.<what>` in snake_case. Areas: `node`, `nav`, `planner`, `explore`, `camera`, `map`, `mapping`, `detector`, `motors`, `drive`, `telemetry`, `sim`. Transitions use a past participle (`nav.mission_started`, `camera.relocalized`), decisions a noun (`nav.safety_stop`, `nav.hold`, `planner.plan`, `planner.recovery`).
- `reason`: why, in words a human would write (`stall`, `path blocked 1.2 m ahead`, `cancelled by hud`, `no relocalization within 45 s, starting a new map`).
- `severity`: info, warning (something went wrong but the system handled it), error (a failure that loses work or data), critical (the node cannot continue).
- Fields: numbers go to `values`, text to `labels`; the unit is in the key (`_m`, `_s`, `_ms`, `_a`, `_v`, `_mps`, `_mps2`, `_deg`, `_pct`); frame-dependent coordinates name the frame or use the map frame of the pose.
- Message: pass `message=` when a log line already exists so its text stays (evals and slabs match some of them).

**Correlation ids** on every event: `mission_id`, `trip_id`, `exploration_id`, `odom_session`, `map_id`, `map_session` from the node's log context (`set_log_context`) or the call, plus `boot_id` (`/proc/sys/kernel/random/boot_id`, or `RABBIT_BOOT_ID` in the simulator) and `instance_id` (process start time and pid). The chain is explicit: explore sends `exploration_id` with each planner goal, the planner sends `trip_id` with each nav mission, so `trip_id`/`exploration_id` are set on nav events too.

**Start snapshot.** Each node emits `node.start` once connected, with `snapshot`: host, pid, `code_hash` (SHA-1 of `src/**/*.py`, so uncommitted edits show), `git_rev` (`REVISION` written by `deploy.sh`, else `git describe --dirty`), Python and package versions, whitelisted environment (`SIM_*`, `LOC_*`, `USE_*`, `ROBOCLAW_*`, `RABBIT_*`, `NATS_URL`; never keys or tokens) and every upper-case constant of the node class and the `lib.*` modules it loaded. Forge stores it in `node_starts`. `node.stop` on exit says `signal`, `crash` or the node's own `stop_reason` (rabbit-zed: `camera restart: <reason>`); a boot without `node.stop` rows ended in a power loss or a hard reset.

**Rate limits.** `every_s` limits an event per (name, reason) and the next admitted one carries `suppressed`; use it for anything that can repeat in a loop (`nav.hold` 2 s, `motors.command_timeout` 1 s, `drive.command_ignored` 5 s, `camera.grab_failed` 5 s, `sim.contact` 2 s, `map.save_skipped` 60 s). A node-wide token bucket (20/s, burst 100) drops the excess and counts it in `node_metrics.events_dropped`, which should stay 0. The queue holds at most 2000 events between publishes (every 0.5 s).

**Budget** (section 5 has the measurements): ≤ 0.5 % of one Jetson core per node for events, metrics and the loop probe; ≤ 1 kB/s of NATS per node on average; ≤ 1 MB/h of Forge disk for `events`, `node_metrics`, `node_starts` and `nats_server` together (2–5 % of the 15–20 MiB/h a driving hour costs today). Stay inside it by keeping events to decisions (never per tick), aggregating timings with `observe` instead of events, and keeping snapshots to start-up.

## 4. What was implemented

Robot (`workspaces/rabbit`):
- `lib/observability.py` (limiter, metric window, snapshot, process stats) and `lib/node.py`: `event`, `observe`, `node.start`/`node.stop`, 10 Hz event-loop lag probe, `rabbit.metrics.<node>` every 10 s, callback-error counter, `NatsLogHandler.dropped_total`.
- `nav`: `nav.mission_started/arrived/cancelled/rejected`, `nav.safety_stop` with the measurement behind each fault (stall current and duration, stuck time, collision acceleration, blocked time, step time, manoeuvre flips, control error), `nav.hold` with reason (obstacle ahead/behind, blind, no fresh scan, no fresh pose), `nav.manual_override`, `nav.pose_jump`, `nav.odometry_reset`, `nav.blocked_at_goal`; `hold` and `trip_id` in `rabbit.nav.state`; `odom_session`/`trip_id` context; `control_ms`, `control_period_ms` metrics.
- `lib/trip.py` (`Navigator.record`, drained by the planner node): `planner.trip_started`, `planner.plan` (every plan with trigger, outcome, length, time, expansions, goals, clearance), `planner.waiting` (no route, long detour), `planner.recovery` (backing up, no trail, out of recoveries, same spot), `planner.recovery_ended`, `planner.bump`, `planner.trip_finished` (outcome, reason, duration, replans, recoveries). Planner node: `planner.trip_rejected` with the request and camera state, `map.session_changed`, places saved/deleted, `planner.ready`; `exploration_id` in state and context; `plan_ms`, `map_build_ms` metrics.
- `explore`: `explore.started/stopped/finished`, `explore.goal_chosen` (frontier, view, gain cells, cost, frontiers left, planning time), `explore.trip_outcome`, `explore.frontier_abandoned` (unreachable, blocked twice, visited twice, failed), `explore.map_extend`; `exploration_id` in planner goals.
- `rabbit-zed`: `camera.opened` (SDK version, model, serial, firmware, map mode), `camera.relocalization_started/relocalized/relocalization_failed`, `camera.tracking_failed` (tilt values), `camera.restart` (reason, archive, uptime, map mode, memory), `camera.implausible_poses`, `camera.grab_failed`, recording events, `map.saved/save_skipped/save_failed/loaded/load_failed/archived/reset/rebuilt/extend_requested/loc_switched`, `mapping.enabled/failed`, detector events; `grab_ms`, `frame_ms`, `gil_gap_ms` metrics; `odom_session`/`map_id` context.
- `roboclaw`: `motors.connected/connect_failed/port_lost/status_changed/command_timeout`, `drive.owner_changed`, `drive.command_ignored` (via `CommandArbiter.owner()`).
- `telemetry`: NATS server `/varz` every 5 s (connections, slow consumers, traffic, memory, CPU), jtop shared RAM (GPU memory), `boot_id`, container-stat errors as `telemetry.container_stats_failed`.
- `sim`: payloads complete for Forge (pose, roboclaw, a simulated INA power monitor, telemetry, health), `camera.restart`, `map.reset`, `sim.contact`, `drive.owner_changed`, `motors.command_timeout`; `scripts/sim.sh` gives each start its own boot id.
- HUD: stop button, missions and explore start carry `source: 'hud'`.
- `scripts/deploy.sh` writes `workspaces/rabbit/REVISION` (`git describe --always --dirty`, gitignored).

Forge (`workspaces/forge`): tables `events`, `node_starts`, `node_metrics`, `nats_server`; new columns in `nav_state` (`hold`, `mission_source`, `trip_id`), `planner_state` (`exploration_id`), `jetson` (`ram_shared_bytes`, `boot_id`) and `zed_health` (21 fields: `relocalizing`, `map_mode`, `map_id`, `map_session`, pose-filter counters, nvblox timings, floor, tilt); the log consumer routes `.event` subjects; `timeline` shows events as decisions; slabs `decisions`, `nav_stops`, `camera_restarts`, `node_health`, `node_versions`; agent prompt and MCP instructions point at them; three chat evals (skipped until the store has events).

Tests: `tests/test_observability.py` pins that a wall ahead produces a `nav.hold` with its reason and then a `nav.safety_stop` `blocked` with the hold, both with the mission id; that stuck and collision trips carry the measurement behind them; that a trip which loses its route records each failed plan and exactly one `planner.trip_finished` with the trip's message; and the rate-limit contract (`suppressed` count, node-wide drops). Forge `src/ingest/jetstream.test.ts` pins the event → `events`/`node_starts` routing.

## 5. Overhead

Measured on the Mac (M-series), on an idle node connected to the sim NATS, 60 s each (`time.process_time`):

| Configuration | CPU |
|---|---|
| node without probe and metrics | 0.25 ms/s |
| with the 10 Hz loop probe and 10 s metrics | 1.01 ms/s (+0.077 % of a core) |
| plus 10 events/s | 1.76 ms/s (+75 µs per event, including its log line and both publishes) |

`event()` alone costs 13.5 µs; a rate-limited (suppressed) call 0.6 µs; the start snapshot 23 ms once. The Jetson's A78AE cores are roughly 3–4× slower per operation, so the estimate there is ≈ 0.3 % of a core per node for probe and metrics and ≈ 0.25 ms per event; for 9 nodes ≈ 2.7 % of one core, 0.45 % of the 6-core CPU. Measure on the robot with `node_health` and `jetson_containers` after deploy.

Size, from the sim run (4 nodes, 233 s of trips and a 60 s exploration, 66 events): events average ≈ 300 bytes of JSON; metrics messages 300–770 bytes; zstd Parquet after merging 14.6 kB for 66 events (≈ 100–150 kB/h at the ≈ 1000 events/h of continuous driving), 17.6 kB for 136 metric rows (≈ 130 B/row; 9 nodes × 360 rows/h ≈ 420 kB/h), 2.5 kB per node start. NATS: ≈ 75 B/s per node for metrics plus ≈ 0.3 kB per event. Together about 0.5–0.6 MB/h on disk, inside the budget.

## 6. Verification in the simulator

The recorded store, the scenario script and its output are kept in the gitignored `data/offline/observability-sim-2026-10-03/`. `scripts/sim.sh` on NATS port 14522 (apartment world) with a local Forge writer (a copy of `workspaces/forge` without `.env`, `FORGE_DATA_DIR` in the session scratchpad). Scenarios: a planner trip to the refrigerator (arrived, 1 replan), a 3 m move into a wall (hold `obstacle ahead` at 0.14 m free, `blocked` after 10 s), a planner trip with `rabbit.sim.restart` mid-way (`camera.restart` → `nav.odometry_reset` → `nav.safety_stop odometry reset` → `planner.trip_finished failed`), a trip cancelled by `hud`, a mission rejected for a 9 m move, an unknown place, and a 60 s exploration (4 goals, 3 arrived, 8.2 m, ended by the time limit). Recorded: 66 events of 21 names, 136 `node_metrics` rows, 5 `node_starts`, `hold` in `nav_state`, `exploration_id` in `planner_state`, `relocalizing`/`map_mode`/`map_id`/`map_session` in `zed_health`, `pose`, `roboclaw` and `power` from the sim. The queries in section 7 returned:

- the last exploration as one chain of 30 events (`explore.goal_chosen` with gain and cost → `planner.trip_started` → `planner.plan` → `nav.mission_started` → `nav.mission_arrived` → `planner.trip_finished` → `explore.trip_outcome`, ending in `explore.finished: time limit reached`);
- `nav_stops`: the blocked stop with free distance 0.12 m after a 10 s hold, the odometry reset with the camera restart 15 ms before it, the cancels with their sender (`hud`, `explore`), the rejected mission;
- `camera_restarts`: one boot, 5 node starts, 1 camera restart with its reason, 3 odometry sessions;
- `node_versions`: `nav.Node.SAFETY_STOP=0.15`, revision `b36435d-dirty`, code `03a53bc84440`;
- power and throttling per second around the blocked stop (battery 15.73 V, 15.70 V once the next trip started backing up; CPU floor 1728 MHz);
- `node_health`: nav 1.9 % CPU mean and worst loop stall 25 ms, planner 1.7 % and 116 ms, explore 1.0 % and 59 ms, sim 6.1 % and 92 ms (on the Mac; RSS there is the process peak, `/proc` gives the current value on the robot).

## 7. Ready queries

They are in the forge-dev skill ("Investigation queries"): last mission or exploration timeline with every decision, why nav stopped, camera restarts and relocalizations per boot, power and throttling around an event, which code and constants ran, process health. Run them with `pnpm forge query` (the SQL gate applies) or over MCP; the Parquet files are also readable directly with `clickhouse local` (`file('<dir>/events/**/*.parquet', Parquet)`).

## 8. Left out, deliberately

- No tracing spans or per-message latency: the 10 s `observe` windows cover loop timing at a fraction of the cost.
- No events per control tick or per frame; continuous values stay in state tables.
- Steering kill switch, rabbit-loc and ina events (low value or covered by their state rows).
- Explore's full candidate list per plan (hundreds of views); only the chosen view, its gain and cost.
- `rabbit.zed.wake`, `rabbit.zed.record` and the place commands as `command_events`: their effects are now events, the raw commands would add little.
- `rabbit.map.grid` (2D clearance grid) is still not stored: 5 cm int16 grids every 2 s are megabytes per minute; the map can be replayed from `.nvblx` files offline (`workspaces/bench/replay`).
- HUD-side events (clicks, panels): the HUD is a viewer and its commands are already recorded with their source.

## 9. Needs the robot

After `scripts/deploy.sh rabbit-zed rabbit-nav rabbit-planner rabbit-explore rabbit-roboclaw rabbit-steering rabbit-ina rabbit-telemetry rabbit-web` (and Forge after the cutover, since the new tables and routing are in the Parquet writer):
- every node's `node.start` arrives and `node_starts.git_rev` shows the deployed revision; `node.stop` reasons on a `docker restart`;
- rabbit-zed events (camera.opened with SDK 5.5, relocalized with its duration, map.saved, camera.restart on a map reset) — this code ran only through `py_compile` and pyflakes on the Mac;
- `nats_server` rows from `http://127.0.0.1:8222/varz` (telemetry runs with host networking) and `jetson.ram_shared_bytes` from jtop;
- `node_metrics` on the Jetson: probe and metrics CPU per node (`node_health`), event rate, `events_dropped = 0`;
- `motors.command_timeout` and `drive.owner_changed` with the real RoboClaw and a gamepad;
- `zed_health` new columns filled from the real health message;
- the three new chat evals with `pnpm forge eval why_nav_stopped camera_restarts_per_boot exploration_decisions` once the store has events.
