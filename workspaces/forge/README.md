# Forge

Forge turns the telemetry of Rabbit, a small rover (this monorepo), into answers an agent can trust. It records every NATS stream, every command with its sender, the robot's configuration changes and the logs of all its nodes into Parquet files on one clock, tagged by run, queries them with chDB (ClickHouse embedded in the Node process), keeps a library of reviewed queries called **slabs**, guards every ad-hoc query with a static SQL gate and an EXPLAIN, and serves all of it to coding agents over MCP, plus an `ask` agent that answers questions in plain language.

It is a small, standalone version of the ideas behind Sherpa in Nexus: curated queries with grain and measure metadata, a fast path that runs a reviewed query, and a heavy path where a sub-agent writes new SQL that must pass validation before it runs.

## Architecture

```
Rabbit (NATS 192.168.1.53:4222)
  │  rabbit.roboclaw, rabbit.ina, rabbit.steering, rabbit.zed.{imu,pose,magnetometer,barometer},
  │  rabbit.zed.obstacle, rabbit.nav.{state,goal,mission,cancel,explore}, rabbit.cmd.{drive,joy},
  │  rabbit.explore.state, rabbit.operator.heartbeat, rabbit.map.{chunks,save},
  │  rabbit.health.zed, rabbit.telemetry
  │  JetStream: LOGS (rabbit.log.>, durable, 7 days on the robot), KV_rabbit (camera settings and other config)
  ▼
writer ── one Parquet file per table and hour every 10 s (temp file, fsync, rename) ──► data/<table>/date=…/hour=…/*.parquet
       logs: durable pull consumer, acked after the file is committed       compaction: hourly files; retention
                                                                          ▲ chDB views forge.<table> = file(glob, Parquet, schema)
CLI ─┬─ run start / stop / list                                           │
     ├─ slab list / search / run / check  ────────────────────────────────┤
     ├─ query (static gate + EXPLAIN)  ───────────────────────────────────┤
     └─ ask ── fast path: search_slabs → run_slab                         │
             └ heavy path: write_query → SQL sub-agent → finalize (gate + EXPLAIN) → run
MCP server (stdio): list_runs, search_slabs, run_slab, query, describe_schema, detect_anomalies, metric_graph, investigate,
                    timeline, search_logs, logs_around, list_metrics, ask
detect_anomalies ── resample in ClickHouse ──► tsfm.ai (Chronos-2, joint targets, graph-picked covariates) + run-wide reference
investigate ── graph/metrics.yml upstream walk ──► per-link anomaly, co-movement and lead-lag scores ──► ranked causal chains
```

One service, `forge`, runs the writer, the compaction and the chat API in one Node process (`node src/cli.ts serve --writer`) with `restart: unless-stopped`. There is no database server: the writer writes Parquet files into the `forge-data` volume and every query runs in chDB inside the same process. The image (`Dockerfile`) is Node from `.nvmrc` on Debian slim, because chDB ships only glibc builds (`@chdb/lib-linux-arm64-gnu`, about 500 MB unpacked), with production dependencies installed from the lockfile and no secrets. Node runs with `--liftoff-only`: the SQL gate's parser is a 25 MB WebAssembly module, and V8's optimizing tier kept about 170 MB of compiled code for it; the baseline compiler costs nothing measurable (0.77 instead of 0.70 ms per query) and keeps about 30 MB.

## Run it

In normal use Forge runs on the robot itself: `forge` is a service in the monorepo's `workspaces/compose.yaml`, deployed with `scripts/deploy.sh`, and the HUD reaches the chat through `https://jetson.rabbit/api`. On the Mac the CLI, the MCP server and the evals read a mirror of the robot's Parquet files (see Storage). The commands below also run the whole service on a laptop for development.

Requires Node 26 (`.nvmrc`), pnpm and Docker.

```sh
pnpm install
pnpm forge sync                      # mirror the robot's Parquet files into data/forge (FORGE_SYNC_FROM)
docker compose up -d --build --wait  # optional: the whole service on the laptop, chat on 127.0.0.1:18080, its own data volume
docker compose logs -f forge         # rows/s every 10 s, with the NATS state (connecting, connected, disconnected)
pnpm forge run start --name hard-launch --note "five full-throttle starts"
pnpm forge run stop
pnpm forge run list
pnpm forge slab run battery_sag --param bucket_s=5
pnpm forge query "SELECT max(temp_tj) AS tj FROM jetson WHERE run_id = {run_id:String}" --param run_id=latest
pnpm forge detect battery_voltage,motor_current --param run_id=latest --param "from=2026-10-01 11:02:30" --param "to=2026-10-01 11:06:00"
pnpm forge graph motor_current --param hops=2
pnpm forge investigate reboots --param at=11:00
pnpm forge ask "What was the average battery voltage and total motor current in the last run?"
```

The writer starts without the robot: it removes files a crash left unfinished, then keeps reconnecting to NATS every 2 s until the robot is up, and reconnects indefinitely after a drop. The healthcheck asks `/api/health` whether the embedded engine answers. Rows that cannot be stored land in `dead_letters/`.

`pnpm forge serve` alone serves the chat on the laptop over the mirror; never run a second writer against the robot's NATS with the same log consumer (`FORGE_LOG_CONSUMER`, default `forge`): two writers would split the log stream between them.

`ask`, `write-query` and `serve` need `OPEN_AI_KEY` in `.env`, and `detect` needs `TSFM_KEY` (see `.env.example`). When `.env` exists Forge reads every setting from that file only, never from the shell environment; without it (the containers, which receive `.env` through `env_file`) it reads the process environment. Settings: `FORGE_DATA_DIR` (default `data/forge` at the repository root; `/app/data` in the container), `FORGE_SYNC_FROM` (the robot's data directory over SSH; set on the Mac, empty on the robot), `FORGE_MAX_DATA_GB` (size cap, default 50), `FORGE_LOG_CONSUMER` (default `forge`), `FORGE_NATS_URL` and `FORGE_CHAT_LISTEN_HOST` (default `127.0.0.1`; the container listens on `0.0.0.0`). The agent uses OpenAI `gpt-6-luna` with low reasoning effort through the Vercel AI SDK.

Ingest: the writer subscribes once per subject and parses each message once, buffers rows in memory and every 10 s writes one Parquet file per table and hour (see Storage). A write retried after a transient error (disk full, a file error, memory) reuses its file id, so it replaces its own file and never duplicates rows; the first failure of a batch is logged and retries back off up to 30 s. A batch the engine rejects is split in half until the bad rows are isolated. Those rows, anything unsent 10 s into shutdown, and buffer overflow go to `dead_letters/<table>.jsonl`: at most 1 M rows wait in memory across all tables, and beyond that the oldest tenth of the cap is taken from the largest table at once.

## Storage

Each table is a directory of Parquet files, `data/<table>/date=YYYY-MM-DD/hour=HH/<from>-<to>.parquet`, partitioned by the hour of the row's `ts` (`at` for `run_events`), zstd-compressed, sorted by the table's `ORDER BY`, with row groups of 65,536 rows. `src/store/schema.sql` is the schema: the CREATE TABLE statements (types, defaults, comments, sort key) are created in an in-memory `forge_schema` database at start, and every table becomes a view `forge.<table>` = `SELECT * FROM file('<table>/*/*/*.parquet', Parquet, '<columns with their exact types>')`, so slabs, the graph, the tools and the agent's SQL keep the ClickHouse dialect and the table names. Old files that lack a column read it as its type's default (`input_format_parquet_allow_missing_columns`). Engine settings and the reader limits are in `src/store/engine.ts`.

- **Writing.** A batch goes through an in-memory staging table (`ENGINE = Memory`, built from the schema, so DEFAULT and MATERIALIZED columns such as `imu.g` and `logs.fingerprint` are computed as before), then `INSERT INTO FUNCTION file('<name>.parquet.tmp', Parquet)`, `fsync`, `rename` and an fsync of the directory. Readers glob `*.parquet`, so they never see an unfinished file, and a hard power-off loses at most the last 10 s that were still in memory. The file name is the writer's flush id (milliseconds, strictly increasing across restarts).
- **Freshness.** Rows are queryable once their file is committed, at most 10 s after they arrive, as with the old ClickHouse inserts; there is no in-memory tail to merge.
- **Compaction** (every minute, in the writer): a closed hour (2 minutes past its end) is merged into one file; an open hour merges its 10 s files once 30 have piled up. The merged file is named after the range of ids it covers, `<from>-<to>.parquet`. Tables declared `ReplacingMergeTree` in the schema (`logs`, `kv_changes`) drop duplicate sorting keys while merging, which is when ClickHouse used to drop them. Renaming the merged file and deleting its inputs happen under a lock that queries in the process share, so a query never sees both; after a crash between the two, the next start deletes every file whose id range lies inside another file's (`recover`).
- **Retention** (hourly): `logs` older than 30 days keep only warnings and worse, and are dropped after 180 days; above `FORGE_MAX_DATA_GB` the oldest hours of the other tables are dropped until the store is under 90 % of the cap. `run_events` is never dropped.
- **Reading.** chDB runs in the process: one writer session and four reader sessions (`readonly=2`, 30 s, 300 MB per query with sorting and GROUP BY spilling to disk above 100 MB, 200 M rows or 4 GB read, 10k result rows, two threads), a 900 MB cap for the engine as a whole. Queries are served by the next free session, so a slow one does not block the others.
- **The Mac.** `pnpm forge sync` rsyncs the robot's files (`FORGE_SYNC_FROM`, over SSH with `~/.ssh/rabbit_id_rsa`) into `FORGE_DATA_DIR` and removes merge inputs a sync caught mid-compaction. With `FORGE_SYNC_FROM` set, the CLI, the MCP server and the evals sync on their own before a query when the copy is older than 30 s; when the robot is off they query the last copy. Starting and stopping runs from the Mac goes to the robot's writer over NATS (`forge.run.start`, `forge.run.stop`).
- **Maintenance commands.** `pnpm forge compact` merges and applies retention once; `pnpm forge import <dir> --before '<UTC time>'` loads `<table>.parquet` exports (the migration from ClickHouse), replacing the store's rows before that time; `pnpm forge bench [<run id>]` times the heaviest tool queries and reports memory.

## Runs

A run is one recording session; every row carries its `run_id` (`20261001-100306-bench-idle`). `forge run start` and `forge run stop` append events to `run_events`; the `runs` view folds them into one row per run. The writer polls for the open manual run every two seconds and tags rows with it. When no manual run is recording, the writer opens an **auto** run so no data is untagged, and closes it after 60 s without messages or when a manual run starts. `run_id = 'latest'` resolves to the most recent manual run.

## Schema

`src/store/schema.sql`, one table per stream, `ORDER BY (run_id, ts)`, `ts` the robot wall clock as `DateTime64(9, 'UTC')`. Column comments carry units and caveats, and `describe_schema` serves them to agents. To add a column, add it to the schema and to `src/streams.ts`; files written before read it as its type's default.

| Table                         | Rate               | Contents                                                                                                                                                                                                                      |
| ----------------------------- | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `roboclaw`                    | 50 Hz              | per side (`left` = M1, `right` = M2) command, pwm, current, speed, encoder; 12 V `supply_voltage`, `duty_max` (voltage cap), temperature, status, errors, serial retries and reconnects                                       |
| `power`                       | 50 Hz              | INA4235: `battery_*` (99 Wh 4S Li-ion, 16.8 V full) voltage, current, power, `battery_charge_pct`, `battery_clipped`; `rail_6v_*` servo rail with `rail_6v_clipped`                                                           |
| `steering`                    | 20 Hz              | angle, pulse width, failed servo writes                                                                                                                                                                                       |
| `imu`                         | ~100 Hz            | acceleration, angular velocity, orientation, `g`                                                                                                                                                                              |
| `magnetometer`, `barometer`   | 50, 25 Hz          | field and heading; pressure                                                                                                                                                                                                   |
| `pose`                        | 30 Hz              | position, orientation, Euler angles, velocity, position std, confidence                                                                                                                                                       |
| `zed_health`                  | 1 Hz               | fps, dropped frames, tracking state and quality flags, relocalizing, map mode, map id and session, pose filter counters, nvblox timings, floor, tilt, temperatures; rabbit-loc shadow check (`loc_status`, `gen3_from_loc_*`) |
| `loc`                         | per keyframe, 1 Hz | rabbit-loc `map←odom` (RTAB-Map): status, mode, map id, odom session, translation and yaw, matches, corrections, grown nodes                                                                                                  |
| `jetson`, `jetson_containers` | 1 Hz               | per-core load, requested and actual clocks, clock floors, EMC clock, over-current counters, temperatures, rail power, fan; per-container CPU and memory                                                                       |
| `joy`                         | 30 Hz              | gamepad throttle and steer while connected (receive time)                                                                                                                                                                     |
| `operator_heartbeat`          | 2 Hz               | HUD heartbeats (HUD time) and their round trip through the robot back to Forge                                                                                                                                                |
| `wifi`                        | 1 Hz               | Wi-Fi signal, router ping, link rates, throughput, errors and drops                                                                                                                                                           |
| `map_chunks`                  | on change          | spatial-map mesh chunk vertex and triangle counts and centroid; the mesh is not stored                                                                                                                                        |
| `obstacle`                    | 10 Hz              | nearest obstacle and nearest obstacle in the driving corridor: distance, bearing, point; the governor's scan and blind flag                                                                                                   |
| `nav_state`                   | 10 Hz              | navigation mode, goal, mission step, distance to goal, heading error, speed, steer, free distance, safety fault, hold reason, mission id and source, trip id                                                                  |
| `drive`, `nav_events`         | 20 Hz, events      | drive commands; goals, missions and cancels; each with its `source` (nav, explore, forge, hud)                                                                                                                                |
| `command_events`              | events             | exploration starts and map saves with their sender and payload                                                                                                                                                                |
| `explore_state`               | 2 Hz               | exploration id, phase, limits, distance driven, frontiers, target, planning time                                                                                                                                              |
| `planner_state`               | 2 Hz               | route planner trips (go_to, explore): trip id, phase, target, goal viewpoint, route length and metres left, replans, recoveries, last replan reason, status message                                                           |
| `kv_changes`                  | on change          | changes of the robot key-value bucket: camera settings, intrinsics, operator and UI state (current values at writer start)                                                                                                    |
| `logs`                        | events             | log records of every node (see Logs)                                                                                                                                                                                          |
| `events`                      | events             | every decision and state change of the nodes with its reason, ids and measured values (see Events)                                                                                                                            |
| `node_starts`                 | per start          | code revision and source hash, package versions, environment and every constant in effect when a node started                                                                                                                 |
| `node_metrics`                | 0.1 Hz             | per node: CPU, RSS, threads, event-loop lag, NATS messages and bytes, dropped publishes, log and event drops, callback errors, loop timings                                                                                   |
| `nats_server`                 | 0.2 Hz             | robot NATS server: connections, subscriptions, slow consumers (message loss), messages and bytes, memory, CPU                                                                                                                 |
| `safety_state`                | 10 Hz              | Rabbit 2.0 body safety loop: mode, binding reason, requested vs allowed command, caps and clearances forward and in reverse, E-stop line, self-test, bumpers, input ages                                                      |
| `power_state`                 | 1 Hz, on change    | Rabbit 2.0 power supervisor: shutdown state machine state and reason, battery, Jetson current, brain and safety readiness                                                                                                     |
| `lidar_health`                | 1 Hz               | RPLIDAR C1: scan rate, points per rotation, rotation time, bad nodes, restarts, device health, nearest return per 30° sector                                                                                                  |
| `tof_health`                  | 1 Hz per sensor    | VL53L8CX ×4: state, frame rate, valid, floor and overhead zones, obstacle zones, nearest obstacle, errors, resets, power cycles                                                                                               |

The JPEG preview (`rabbit.zed.frame.preview`) and the map snapshot reply (`rabbit.map.snapshot`) are not stored; `zed_health` carries the preview counters and `map_chunks` the mesh summaries. The Rabbit 2.0 body streams are summarised too: full lidar scans (`rabbit.lidar.scan`, binary, 10 Hz, ~2 kB, ~70 MB/h raw, several times the whole store today), ToF frames (`rabbit.tof`, 4 × 15 Hz) and the 50 Hz `rabbit.safety.drive` are not stored; `lidar_health` keeps the nearest return per sector every second, `tof_health` the zone counts, `safety_state` the allowed command with its clearances at 10 Hz, and the decisions are `events` of the nodes `safety`, `power`, `lidar` and `tof`. Scans for localization benchmarks belong next to the SVO recording, not in Forge.

Commands carry the sender's clock: the robot's nodes stamp theirs (`ts`, `source` nav or explore), Forge stamps its own (`source` forge, Mac clock), and HUD commands without a `ts` get the writer's receive time (`source` hud). Both machines run NTP.

## Logs

Every robot node inherits `RabbitNode` (`rabbit/workspaces/rabbit/src/lib/node.py`), which adds `NatsLogHandler` (`lib/log.py`) to the root logger. Each record becomes a JSON message on `rabbit.log.<node>` with the robot wall clock, level, logger, message and template, exception type and traceback, `module:function:line`, the `extra` fields and the node's context (`mission_id` from nav, `map_session` from the camera and explore nodes, `exploration_id` from explore). Identical records (same logger, level, template with numbers ignored and exception) are suppressed for 10 s and the next record carries the suppressed count as `repeats`. The handler also logs uncaught exceptions in the main thread, other threads and the asyncio loop, and a `Node crashed` record before the process exits. The telemetry node logs Docker container events (`docker.events`: started, exited with its exit code, killed, out of memory, health changes), so a segmentation fault inside a native library still leaves a record.

On the robot the `LOGS` JetStream stream (created by `nats/init.sh`: file storage, s2 compression, 7 days, 2 GB) keeps the records while the Wi-Fi is down. The writer reads it with the durable pull consumer `forge-writer` and acknowledges a batch only after ClickHouse stored it. A record belongs to the run that contains its own timestamp, not the run open when it arrived, so a backlog replayed after an outage lands in the right run (`runAt` in `src/runs.ts`).

`logs` is keyed on `(run_id, ts, seq)`, deduplicated on that key when files merge, with a `fingerprint` that groups records of a kind. Word search is `hasAllTokens(lower(message), 'roboclaw error')`: without ClickHouse's text index the tokens are matched as written, so both sides are lower-cased. Retention: info and debug 30 days, warnings and worse 180 days.

- `search_logs` finds records by words (each must appear in the message or the traceback, case-insensitive, also as part of a longer word), node, level and run or time range, grouped by kind with counts, first and last time and the latest traceback.
- `logs_around` lists the records around a moment in time order with their offset in seconds.
- `timeline` returns everything around a moment or a range of at most 15 minutes on one clock: commands with their sender, state transitions (navigation mode, safety faults, missions, exploration phase, camera tracking, Wi-Fi), HUD heartbeat silences, configuration changes, log records (warnings and worse, plus info messages that occur at most three times), and every metric of the graph summarised as moved (min, max, mean, last, sparkline), steady or without data.
- `list_metrics` lists every graph metric with its table, expression and NATS subject, and every table with its subjects.

## Events

`RabbitNode.event(name, reason, severity=..., every_s=..., **fields)` (`lib/node.py`, helpers in `lib/observability.py`) records a decision or a state change. It publishes a JSON message on `rabbit.log.<node>.event`, which the `LOGS` stream keeps like the logs, and also logs a line with `fields['event']` set, so `docker logs` and log search still show it. The writer's log consumer routes `.event` subjects into `events`:

- `name` is `<area>.<what>` in snake_case (`nav.safety_stop`, `planner.plan`, `camera.restart`); `reason` says why in words; `severity` is info, warning, error or critical;
- the ids `mission_id`, `trip_id`, `exploration_id`, `odom_session`, `map_id`, `map_session` come from the node's log context or the call, plus `boot_id` (Linux boot) and `instance_id` (node process); a planner trip carries the exploration that asked for it and a nav mission the trip it belongs to, so one id follows a decision through every node;
- numbers go to `values` and text to `labels`, with the unit in the key (`free_distance_m`, `motor_current_a`, `plan_ms`);
- `suppressed` counts events of the same name and reason skipped by `every_s` since the previous one; a node-wide limit (20/s, burst 100) drops the rest and counts them in `node_metrics.events_dropped`.

Every node also sends `node.start` with a snapshot (code revision and hash, versions, environment, constants), stored in `node_starts`, and `node.stop` with the reason (signal, crash, or the camera's restart reason). `rabbit.metrics.<node>` carries the 10 s process metrics into `node_metrics`. Slabs: `decisions`, `nav_stops`, `camera_restarts`, `node_health`, `node_versions`; `timeline` lists events as decisions and leaves out their duplicate log lines.

Robot containers log through Docker's `json-file` driver with rotation (20 MB, 3 files) set once in `compose.yaml`.

## Slabs

A slab is one reviewed ClickHouse query in `slabs/<id>.yml`:

```yaml
title: Motor current and power by side
description: retrieval text, what the slab answers
tags: [motors, current, power, energy]
prompts: [Which motor drew more current?]
guidelines: how to read the result
dims: [side] # the grain: exactly the axis columns
sql: SELECT ... WHERE run_id = {run_id:String} ...
columns:
  side: { kind: category } # time | ordinal | category | entity | attribute
  avg_current_a: { measure: gauge, unit: A } # gauge | counter | event | ratio
  energy_wh: { measure: event, unit: Wh }
subs:
  min_command:
    { type: Float64, default: 0.1, description: Minimum drive command }
```

A column is a dimension (`kind`) or a metric (`measure`), never both. The measures say how a value may be combined further: a **gauge** is a sampled level (average, min or max; never summed over time), a **counter** is a device's running total (take the difference), an **event** is a count or total that sums, and a **ratio** is recomputed from its parts, never averaged. Time-series slabs take `bucket_s`, where 0 (the default) picks a bucket that keeps the result under about 180 rows. Well-known subs are injected when the SQL references them: `run_id` (default `latest`; `previous` also resolves), `other_run_id` (default `previous`) and the UTC time range `from`/`to` (default the whole run). The loader checks placeholders against `subs`, `dims` against the axis columns, and `forge slab check` asserts each slab's projected columns (via `DESCRIBE`) match its declared columns, then runs it.

| Slab                  | Answers                                                                                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_summary`         | one-row overview: duration, battery voltage, current, energy, charge, motor current and errors, Jetson peak temperature, path length, tracking drops       |
| `drive_tracking`      | motor command and nav speed command vs ZED ground speed and motor current over time (stalls)                                                               |
| `battery_sag`         | battery voltage, current and charge vs motor current over time                                                                                             |
| `battery_resistance`  | linear fit of battery voltage on current: internal resistance, worst unexplained sag                                                                       |
| `motor_power_by_side` | mean and peak current, power and energy per motor                                                                                                          |
| `turn_current`        | motor current by steering lock while driving (spikes in full-lock turns)                                                                                   |
| `power_rails`         | battery and 6 V rail power and energy                                                                                                                      |
| `jetson_throttling`   | junction temperature, clocks, load, power, share of time below peak clock                                                                                  |
| `power_throttling`    | over-current events (OC1/OC2/OC3) per second, share of time throttled, actual vs requested CPU clock, whether jetson_clocks floors were pinned             |
| `container_load`      | CPU and memory per Jetson container                                                                                                                        |
| `imu_shocks`          | peak deviation from 1 g, RMS vibration, shock count over a threshold                                                                                       |
| `trajectory`          | position, step, cumulative distance and speed from the ZED pose                                                                                            |
| `stream_rates`        | samples, rate and longest gap per stream (dropouts)                                                                                                        |
| `stall_events`        | seconds above a motor-current threshold, PWM at the peak, time over threshold, ground speed (stall vs inrush)                                              |
| `brownout_and_gaps`   | data gaps with reboot detection (Jetson uptime reset), battery and Wi-Fi state just before                                                                 |
| `tracking_quality`    | camera fps, dropped frames, pose lost share, tracking mode, quality warnings, confidence                                                                   |
| `steering_response`   | steering angle vs IMU yaw rate and ground speed, curvature per unit steer                                                                                  |
| `mission_timeline`    | second-by-second nav mode, step, distance and heading error, commands, ground speed, obstacle ahead                                                        |
| `power_budget`        | battery, motors, Jetson, servo rail and the rest: mean and peak W, Wh, share                                                                               |
| `thermal_timeline`    | Jetson, camera and motor controller temperatures, fan, slowest CPU clock                                                                                   |
| `obstacle_events`     | seconds with an obstacle closer than a clearance, nav mode and speed at that moment                                                                        |
| `run_compare`         | two runs side by side (`run_id`, `other_run_id` default latest and previous)                                                                               |
| `wifi_health`         | signal, router ping p50/p95/max, lost pings, throughput, drops                                                                                             |
| `obstacle_clearance`  | nearest obstacle overall and ahead, close calls under a clearance                                                                                          |
| `nav_missions`        | per mission or goal: plan, arrived, cancelled or replaced, time to arrive, share of time blocked                                                           |
| `planner_trips`       | route planner trips (go_to, HUD GO TO, exploration legs): target, start and end, final phase and message, replan reason, route length, replans, recoveries |
| `explorations`        | explorations: start and end, final phase and why they ended, distance driven, frontiers, limits                                                            |
| `nav_transitions`     | navigation mode, safety fault and mission changes with the speed command and free distance at that moment                                                  |
| `command_timeline`    | per bucket: gamepad, navigation drive commands, stops, goals, missions, cancels and other commands with their sender, HUD heartbeats                       |
| `operator_link`       | HUD heartbeats per second, round trip p50 and max, longest silence                                                                                         |
| `log_summary`         | log records per node and level: count with repeats, kinds, most frequent message, latest exception, first and last time                                    |
| `log_error_rate`      | warnings and errors per second per node over time, with the most frequent message                                                                          |
| `container_events`    | robot container starts, exits with exit code, kills, restarts, out-of-memory and health changes                                                            |
| `decisions`           | every recorded event in order with reason, ids and measured values; `id` follows one mission, trip or exploration through every node                       |
| `nav_stops`           | why the robot stopped or did not move: safety stops, holds, cancels and their sender, overrides, rejections, motor command timeouts, failed trips          |
| `body_safety`         | Rabbit 2.0 safety loop per second: worst mode, limiting reasons, requested vs allowed speed, clearances, E-stop line, bumpers, safety events               |
| `camera_restarts`     | per boot: camera restarts and their reasons, relocalizations and their time, failures, map archives, resets and saves, node crashes                        |
| `node_health`         | per node: CPU mean and peak, peak and last RSS, worst event-loop stall, NATS traffic, error and drop counters, restarts                                    |
| `node_versions`       | every node start with git revision, source hash, Python and environment, and the value of one constant (`key`)                                             |

`search_slabs` is deterministic BM25 (MiniSearch) over id, title, description, tags, prompts and column names.

## Metric graph

`graph/metrics.yml` is a typed graph of the robot's metrics: 56 nodes and 85 edges. A node is a measured series (`source: {table, expr, agg}` binned in ClickHouse, with unit, native rate `hz` and sensor resolution `floor`; `agg: rate` counts rows per second, with empty bins as zero, for logs and heartbeats) or an event list read from a slab (`events: {slab, time, end, where}`: reboots and data gaps from `brownout_and_gaps`, stalls from `stall_events`, navigation safety stops from `nav_transitions`, container crashes from `container_events`, missions from `nav_missions`); every node names the slabs that fetch it. Commands connect to what they move (gamepad throttle and the navigation speed command to the motor command, then PWM, current and ground speed; gamepad and navigation steering to the steering angle; missions to the navigation speed), safety stops to the signals behind each rule (motor current and ground speed for a stall, an IMU jolt for a collision, free distance for blocked, HUD heartbeats for operator link lost, the gamepad for a manual override) and to the navigation logs, and the log rates per node decompose the total. An edge is directed and typed, with a reason (`why`), an evidence class (`physics`, `design`, `observed`) and an optional `sign`:

| Relation          | Direction        | Example                                       |
| ----------------- | ---------------- | --------------------------------------------- |
| `decomposes_into` | total to part    | battery_power into motor, Jetson, servo power |
| `drives`          | cause to effect  | battery_current to battery_voltage (negative) |
| `causes`          | cause to effect  | junction_temp to cpu_freq (negative)          |
| `explains`        | load to level    | drive_command to motor_current                |
| `correlates_with` | none             | cpu_temp with junction_temp                   |
| `guards`          | safety to action | obstacle_clearance to nav_blocked             |
| `symptom_of`      | event to cause   | reboots to battery_voltage, imu_vibration     |

The loader validates the file like slabs: node ids, units and rates for series, known slabs, slab columns for event nodes, known edge ends, no self loops or repeated edges. `pnpm forge graph check` runs every series expression against the latest run.

- `metric_graph` (tool, `pnpm forge graph [<metric>]`) returns a node's neighbourhood (`hops`), the shortest path between two metrics (`node`, `to`) or the whole graph, optionally filtered by relation.
- `investigate` (tool, `pnpm forge investigate <metric>`) walks upstream from a symptom breadth-first (decompositions only as the first hop, at most 14 nodes, depth 2 by default), fetches every candidate on one grid (10 Hz up to 15 minutes, else 1 Hz) and compares each with its trailing 30 s median (robust z). For an event (`at` picks the nearest one, and the run containing it when `run_id` is omitted) the focus is the 15 s before it; for a metric it is the strongest deviation in the range (or the one nearest `at`). A link scores on how far the cause deviates in the focus window in the expected direction, its cross-correlation with the effect within 3 s of lag and whether it leads; a chain scores the blend of its geometric mean and its weakest link. It returns ranked hypotheses with evidence, a breakdown into parts, what it ruled out (link score below 0.15), the metrics without data, and `context`: the commands, state transitions and log records from 20 s before the focus to 5 s after it.

Both return `{kind: 'graph', id, title, nodes, edges, highlights}`; nodes carry role, status, value at the peak and a sparkline, edges their score and lag, `highlights` the top chain, and `investigate` adds a stacked chart of the chain. The HUD draws it as a node-link diagram.

On today's data: the 11:00:17 reboot ranks the uncommanded 0.429 A motor current and the 0.148 g IMU jolt 3 s before the gap first (0.85 each) and rules out Jetson power and heat; the 10:48 reboot finds no precursor (top chain 0.11, battery ruled out); the 11:04:12 stall is the 0.3 command step (12.6 A inrush); the 11:33:53 current rise is the navigation command with the corridor 0.16 m ahead; the Wi-Fi ping peak is 619 ms at 11:32:15.

## Anomaly detection

`detect_anomalies` (MCP tool, `ask` tool, `pnpm forge detect <signal>[,<signal>...]`) scores one to four graph metrics at once over a run against a forecast from `amazon/chronos-2` on tsfm.ai. The signals go in as one multivariate target (Chronos-2 takes `target` as `[time][channel]`, `null` for gaps), with past and future covariates picked from the graph: the metrics with an `explains` or `drives` edge into a target, by evidence class, at most four (`covariates` overrides them, `[]` forecasts from history alone). `NX-AI/TiRex-2` is the fallback, one channel per input, then the reference alone. Renamed signals: `camera_fps` is `zed_fps`, `jetson_cpu_temp` is `cpu_temp`, `jetson_cpu_freq` is `cpu_freq`.

ClickHouse resamples to bin means (10 Hz with context up to 512 and horizon 16 when the range is at most 15 minutes and every target is sampled at 10 Hz or faster; otherwise 1 Hz with 256 and 30). Windows need 64 points of history and at least half of it observed for some target, so a signal that starts late is still scored. Then, per signal:

- **Calibration.** Thresholds come from the signal's clean windows (all but the 5 % with the largest exceedance): a point is flagged above the 99.8th percentile of clean band exceedance (at least `threshold` band widths outside the 5-95 % band), a stretch when its 10-point mean deviation (each point clipped at 3) exceeds the clean 99.8th percentile.
- **Reference.** A run-wide reference (median and robust spread of the signal at the same levels of its two main covariates, per quarter of the range) flags regime shifts the forecast absorbs into its own context, such as a robot pushing a wall for 15 s: 10 points whose median deviation exceeds the clean 99.8th percentile (at least 6 sigma). Each event reports `reference_z` and `reference_agrees`.
- **Severity.** The event's peak over its threshold: alert from 4, warn from 2, info below. A short event that starts with a step in an explaining covariate (a command starting) is marked `at_covariate_step` and judged on an eight times wider margin, so start-up inrush stays visible only when it is extreme.
- **Joint events.** Events of different signals within 2 s (5 s at 1 Hz) form a joint event that names the signal that moved first.

The chart is stacked, one panel per signal with the observed line, the dashed expected median, the forecast band and the event ranges. Gaps are never scored; reboots and dropouts come from `investigate` or `brownout_and_gaps`.

`pnpm forge eval tools` checks `investigate` and `detect_anomalies` against labels verified in the raw data (`evals/tools.yml`): the 11:04:12 inrush, the 11:00:14 knock before the reboot (motor current and IMU), both wall pushes (11:33:53 and 11:34:46), the two Wi-Fi ping episodes (11:31:52 to 11:32:26 up to 619 ms, 11:33:51 to 11:34:03 up to 278 ms), the 11:37:08 uplink drop and the 0.43 V battery step at 10:05:27 with no current change. Counting warn and alert events, all 9 labelled events are found (recall 1.0) at a precision of 0.55 to 0.6 between runs; most remaining false alarms are real but unlabelled deviations (sub-amp current spikes while driving, single-sample uplink dips). The first multivariate version, forecast only, found 4 of 6 events at a precision of 0.4. All 11 cases pass.

## SQL gate

Every ad-hoc or generated query passes `src/sql/validate_sql.ts` (parsed with `@polyglot-sql/sdk`) and then `EXPLAIN PLAN` in a read-only reader session:

- exactly one `SELECT` / `WITH` / `UNION` statement;
- only Forge tables, CTEs of the query and subqueries; no other database, table function, `FINAL` or `SETTINGS` (table functions matter more now: the engine can read any file the process can, so the gate is what keeps the agent's SQL on the Forge views);
- no `FORMAT`, `INTO OUTFILE`, `GLOBAL IN` or references to `system` / `information_schema`;
- functions come from an allowlist (aggregates and their combinators, window, math, date and time, string, array, JSON and conditional functions), including those named in `* APPLY(fn)`, so anything reading server state or other data is rejected;
- every `JOIN` matches qualified `run_id` columns of its two sides with AND only (no `OR`), plus a time or sequence key from both sides (a shared bucket, or `ASOF ... a.ts >= b.ts`) unless one side is aggregated to one row per run; no comma joins. Two runs never pair up, and no join multiplies every row of a run with every other.

A test runs every slab through the gate, so a rule that is too strict fails CI rather than a slab.

A rejection returns a stable error plus a repair hint for the model (the columns of the tables it read, the GROUP BY rule, the aggregate-alias trap), as Nexus does with `NexusError.llm`.

## Agent

`ask` (CLI and MCP tool) starts with the recent runs and the five nearest slabs in context, and can call `list_runs`, `search_slabs`, `run_slab`, `write_query`, `detect_anomalies`, `metric_graph`, `investigate`, `timeline`, `search_logs` and `logs_around`. It runs a slab when one covers the question (fast path); otherwise it calls `write_query`, a sub-agent that sees the schema and the three nearest slabs' SQL and must commit through `finalize`, which runs the gate and EXPLAIN and returns repair hints until the SQL is valid (heavy path). The answer cites the run and the slab or SQL, and every number must come from a tool result. Data and tool parameters are UTC; the operator works in `config.operatorTimeZone` (Australia/Sydney), whose current time and offset the agent receives with every question, so it converts the operator's times for tools. Times in tool results reach the model twice: as UTC and as a `<field>_local` twin already in Sydney time with its abbreviation (`src/local_time.ts`, the IANA zone, so AEDT from 2026-10-04 02:00 is right), plus a `timezone` note; the prompt has it quote those and never do offset arithmetic, after the evals caught it adding 11 h in AEST. The result reports `path: fast | heavy` and a trace of tool calls.

## Chat API

The `forge-chat` service runs on the robot behind `rabbit-web` (nginx), which serves the HUD at `https://jetson.rabbit` and proxies `/api/` to the chat with `Host: localhost:18080`, passing the browser's `Origin` and filling it in for same-origin requests (browsers omit it on same-origin GETs). The HUD reads the base URL from `VITE_CHAT_URL` in `workspaces/web/src/chat/session.ts`: the robot build sets it empty (same origin), and the dev server on the Mac defaults to `https://jetson.rabbit`. `pnpm forge serve` runs the same server on a laptop at `http://127.0.0.1:18080` for development.

- `POST /api/chat` takes `{ messages: UIMessage[] }` (stateless, the client sends the history; only `user` and `assistant` messages) and streams the AI SDK UI message stream. A client that disconnects aborts the agent run. It requires an allowed `Origin` (`https://localhost:*`, `https://dev.rabbit:*`, `https://jetson.rabbit`) and `content-type: application/json`. There is no token: the chat is only reachable on the robot's local network, and the origin check keeps other websites from driving it.
- Only the `Host` values `127.0.0.1:18080` and `localhost:18080` are served (nginx sets the latter), which blocks DNS rebinding.
- `GET /api/health` returns `{ ok, model, clickhouse, latest_data_age_s, run }`; `clickhouse` says whether the embedded engine answers.

The chat agent is `ask` with more tools: the data tools, `write_query`, `chart` (plots a slab or SQL result; the server converts times to epoch ms and downsamples to 2000 rows), and the robot tools `robot_status`, `go_to`, `plan_route`, `find_object`, `list_places`, `save_place`, `run_mission`, `stop`, `save_map`, `start_run` and `stop_run`. `go_to` (approval) and `plan_route` (preview, no motion) resolve the destination in Forge and hand it to the robot's route planner (`rabbit.planner.goal`, request-reply): an object name (aliases such as fridge map to detector classes) is looked up in `objects` since the last map archive or reset (taken from rabbit-zed's logs), detections made while rabbit-zed is still relocalizing (INITIALIZING/SEARCHING, a temporary frame) are dropped, sightings are clustered within 0.8 m and the most-seen cluster wins, and the camera positions it was seen from (pose ASOF-joined to the detections) go along as `seen_from` so the planner prefers viewpoints with a proven line of sight; a room (kitchen, bedroom, ...) resolves to a saved place of that name or else to its typical objects; `x`/`z` is a point. The planner picks a viewpoint facing the object, plans on the map and drives the route through nav, replanning on its own; the tool waits up to 6 s for the plan and returns the route, or fails with the planner's reason. `save_place`/`list_places` keep named places on the robot (`rabbit.planner.places*`), per map. `run_mission` publishes `rabbit.nav.mission {id, steps}` (turn, move, goto, queued on the robot) and needs the operator's approval: tools declare `requiresApproval`, chat turns that into AI SDK tool approval signed per server process, and execution consumes a single-use approval that expires after 2 minutes (MCP never registers such tools). Before publishing, the server re-checks that the pose, camera tracking and obstacle readings are fresher than 3 s, tracking is OK and the first leg that moves is clear of the obstacle ahead (when it starts within 10 degrees of the current heading), and enforces at most 3 m per move, 5 m per goto, 10 steps and 10 m per mission, dead-reckoning the steps so each goto is measured from where the earlier steps leave the robot. The mission carries its own `id` (`forge-<uuid>`); the tool waits up to 3 s for `rabbit.nav.state` to report that `mission_id` (`accepted`), fails with nav's reason when nav sets a new `rejected: ...` fault, and otherwise returns `accepted: false`. `nav_state.mission_id` keeps the last mission after it ends, so whether a mission is running comes from `mode`. `stop` publishes `rabbit.nav.cancel` and a zero `rabbit.cmd.drive` independently, without approval, and reports each; the robot NATS connection reconnects indefinitely and every publish waits at most 3 s for the server. Chat never publishes a non-zero drive command. Tools return `{kind: 'table'}`, `{kind: 'chart'}` (optional `layout: 'stacked'`, `series.panel` and `dashed`, range markers with `x_end` and `series`, bands per series, and an `id`), `{kind: 'graph'}` or `{kind: 'status'}`; the model sees a summary of charts and graphs instead of their rows. The chat prompt asks for a TL;DR, key numbers, findings with status chips and evidence, and next steps, written with inline tokens the HUD renders: `ok:`, `info:`, `warn:`, `alert:` (status chips), `kpi:Label=value` (key numbers), `spark:v1,v2,...` (sparklines), `ref:kind:target?key=value` (evidence chips that re-run a slab, detection or investigation, or scroll to a chart or graph by id) and `next:question` (follow-ups).

## MCP

```sh
claude mcp add forge -- node /Users/sergey/projects/rabbit/workspaces/forge/src/cli.ts mcp
```

Tools: `list_runs`, `search_slabs`, `run_slab`, `query`, `describe_schema`, `detect_anomalies`, `metric_graph`, `investigate`, `timeline`, `search_logs`, `logs_around`, `list_metrics`, `ask` (no robot actions over MCP). All are read-only. To try it without Claude Code:

```sh
npx @modelcontextprotocol/inspector --cli node src/cli.ts mcp --method tools/list
```

## Development

```sh
pnpm check    # oxfmt --check, tsc, oxlint (type-aware), vitest
```

Tests cover the Parquet store (every view has exactly the schema's types; enums, maps, nullable arrays and computed columns survive a round trip; an uncommitted file is never read and is cleaned up; a retried write replaces its own file; merge inputs a crash left behind are removed; compaction, deduplication and log retention; every slab passes the gate and EXPLAIN on the views), the SQL gate, the writer's batching (bisection, retries, the buffer cap), mission planning and acceptance, approvals, slab search ranking for Russian and English questions, the metric graph loader and traversal, the graph statistics, grid filling (gaps and zero-filled rates), joint events, the anomaly reference, the run a record belongs to by its timestamp, and the mapping of robot log records to rows. The robot's log handler (repeat suppression, payload fields) is tested in `rabbit/workspaces/rabbit/tests/test_log.py`.

`pnpm forge eval [<case>]` runs the chat agent on `evals/chat.yml` (questions with the tool calls, approvals and facts each answer must contain) against the store in `FORGE_DATA_DIR` and the model, with robot actions as dry runs and a fixed `robot_status` (`heading_deg` and `obstacle_ahead_m` set its pose and obstacle). Cases do not name fixed runs or times: `anchor` is SQL run on the store first, and its first row fills `{column}` placeholders in the question, facts and approval input (the longest run, the biggest motor-current peak, the longest data gap, the latest camera restart, relocalization, operator stop, exploration and refrigerator trip, a rarely seen object, an object only in an earlier map); times in facts accept both UTC and Sydney time. A case whose anchor finds nothing is reported as skipped, not failed. `history` puts earlier messages before the question, which covers approval cards left unanswered and approvals that expired. 38 cases.
`pnpm forge eval tools` is the deterministic check for `investigate` and `detect_anomalies` (see Anomaly detection). Schema changes need no migration: edit `src/store/schema.sql` and restart.

## Data notes

- `roboclaw.supply_voltage` is the 12 V buck output feeding the motor controller, not the battery; battery voltage and power come from `power`.
- Motor current is measured at 12 V by the RoboClaw; battery current is measured at the pack and includes the Jetson, camera and servos.
- `rabbit.health.zed` occasionally publishes invalid JSON (NaN values); the writer counts and drops those messages.
- Wi-Fi telemetry starts at about 11:30 on 2026-10-01, so the earlier 1.5 s ping episode has no Wi-Fi rows.
- `battery_charge_pct` is a voltage-curve estimate and reads low under load. Rows recorded before the robot published it are NULL.
- Currents from `power` saturate at the INA's ±81.92 mV shunt range: 8.19 A on the 10 mOhm shunts. From 2026-10-03 `battery_clipped` and `rail_6v_clipped` are true from 90% of that range (7.37 A), so a peak such as the 7.64 A of 1 Oct is a lower bound, not the true peak; older rows are NULL. Each INA start records the shunt, current LSB and SHUNT_CAL of every channel in `events` (`power.calibrated`); before 2026-10-03 every channel was calibrated for 10 mOhm, so a channel with another shunt was scaled by R_true / 0.01.
- `roboclaw.duty_max` is the voltage cap rabbit-roboclaw applies (`pwm` = command × `duty_max` after the slew): 1 while the RoboClaw is on the 12 V buck, 12 / V on the 4S pack.
- `magnetometer.heading_deg` is meaningless while `heading_state` is `NOT_CALIBRATED`.
- Right after the ZED node restarted at 10:46, about 5 minutes of `pose` and `obstacle` rows carry camera timestamps up to 5.7 minutes behind the robot clock; later rows are aligned.
- The wheel encoders are not connected, so `roboclaw` speed and encoder columns are always 0; ground speed comes from `pose` velocity.
