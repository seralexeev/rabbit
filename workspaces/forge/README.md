# Forge

Forge turns the telemetry of Rabbit, a small rover (this monorepo), into answers an agent can trust. It records every NATS stream, every command with its sender, the robot's configuration changes and the logs of all its nodes into ClickHouse on one clock, tagged by run, keeps a library of reviewed queries called **slabs**, guards every ad-hoc query with a static SQL gate and a ClickHouse EXPLAIN, and serves all of it to coding agents over MCP, plus an `ask` agent that answers questions in plain language.

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
writer (docker)          ── one INSERT per table every 10 s, deduplicated ──► ClickHouse (docker, forge db)
       logs: durable pull consumer, acked after the insert
                                                                          ▲ forge_reader (read-only)
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

Compose runs three services with `restart: unless-stopped`, so recording survives closed terminals, crashes and Docker restarts: `clickhouse`, `writer` (`forge-writer`) and `chat` (`forge-chat`, the chat API). The writer and chat share one image (`Dockerfile`: Node from `.nvmrc`, pnpm, production dependencies installed from the lockfile, no secrets) and start once ClickHouse is healthy. They read `.env` through `env_file` and reach ClickHouse at `http://clickhouse:8123`; the robot's NATS is reached over the LAN from inside Docker.

## Run it

In normal use Forge runs on the robot itself: `forge-clickhouse`, `forge-writer` and `forge-chat` are services in the monorepo's `workspaces/compose.yaml`, deployed with `scripts/deploy.sh`, and the HUD reaches the chat through `https://jetson.rabbit/api`. The commands below run the same stack on a laptop for development.

Requires Node 26 (`.nvmrc`), pnpm and Docker.

```sh
pnpm install
docker compose up -d --build --wait  # ClickHouse (127.0.0.1:18123 HTTP, :19000 native), writer, chat on 127.0.0.1:18080
docker compose ps                    # all three healthy
docker compose logs -f writer        # rows/s every 10 s, with the NATS state (connecting, connected, disconnected)
docker compose stop writer chat      # stop recording and chat; `docker compose start writer chat` resumes
docker compose up -d --build writer chat   # deploy code changes
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

The writer starts without the robot: it applies `clickhouse/schema.sql`, then keeps reconnecting to NATS every 2 s until the robot is up, and reconnects indefinitely after a drop. Its healthcheck is a heartbeat file the writer touches every 10 s; the chat healthcheck asks `/api/health` for a working ClickHouse connection. Rows that cannot be stored land in `dead_letters/`, bind-mounted from the repo.

For local development run `pnpm forge writer` or `pnpm forge serve` on the host after stopping the matching container (`docker compose stop writer` or `docker compose stop chat`): two writers would record every message twice, and two chat servers cannot share port 18080. `docker compose start writer chat` brings the services back.

`ask`, `write-query` and `serve` need `OPEN_AI_KEY` in `.env`, and `detect` needs `TSFM_KEY` (see `.env.example`). When `.env` exists Forge reads every setting from that file only, never from the shell environment; without it (the containers, which receive `.env` through `env_file`) it reads the process environment. Two settings exist for the containers: `FORGE_CLICKHOUSE_URL` (default `http://127.0.0.1:18123`) and `FORGE_CHAT_LISTEN_HOST` (default `127.0.0.1`; the chat container listens on `0.0.0.0` and Compose publishes it on `127.0.0.1:18080` only). The agent uses OpenAI `gpt-6-luna` with low reasoning effort through the Vercel AI SDK.

ClickHouse users: `forge_writer` owns the `forge` database; `forge_reader` is read-only (`readonly=1`; 30 s, 300 MB, 16 concurrent queries, 200 M rows or 4 GB read and 10k result rows per query) and is the only user that runs slabs, ad-hoc queries and agent SQL. `clickhouse/config.xml` sizes the server for a laptop: system log tables off except a one-day `query_log`, two merge threads, a 1.5 GB memory cap.

Ingest: the writer subscribes once per subject and parses each message once. Every batch carries an `insert_deduplication_token` (tables, `logs` included, keep a 1000-insert deduplication window), so retries never duplicate rows. Transient ClickHouse or network errors, and a missing table or database, retry the same batch with exponential backoff up to 30 s; the first failure of a batch is logged. A batch ClickHouse rejects is split in half until the bad rows are isolated. Those rows, anything unsent 10 s into shutdown, and buffer overflow go to `dead_letters/<table>.jsonl`: at most 1 M rows (about 330 MB, roughly 35 minutes of telemetry) wait in memory across all tables, and beyond that the oldest tenth of the cap is taken from the largest table at once.

## Runs

A run is one recording session; every row carries its `run_id` (`20261001-100306-bench-idle`). `forge run start` and `forge run stop` append events to `run_events`; the `runs` view folds them into one row per run. The writer polls for the open manual run every two seconds and tags rows with it. When no manual run is recording, the writer opens an **auto** run so no data is untagged, and closes it after 60 s without messages or when a manual run starts. `run_id = 'latest'` resolves to the most recent manual run.

## Schema

`clickhouse/schema.sql`, applied idempotently by `forge migrate` and on writer start. One MergeTree table per stream, `ORDER BY (run_id, ts)`, `ts` the robot wall clock as `DateTime64(9, 'UTC')` with DoubleDelta, floats with Gorilla, all ZSTD. Column comments carry units and caveats, and `describe_schema` serves them to agents.

| Table                         | Rate          | Contents                                                                                                                                                      |
| ----------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `roboclaw`                    | 50 Hz         | per side (`left` = M1, `right` = M2) command, pwm, current, speed, encoder; 12 V `supply_voltage`, temperature, status, errors, serial retries and reconnects |
| `power`                       | 50 Hz         | INA4235: `battery_*` (99 Wh 4S Li-ion, 16.8 V full) voltage, current, power, `battery_charge_pct`; `rail_6v_*` servo rail                                     |
| `steering`                    | 20 Hz         | angle, pulse width, failed servo writes                                                                                                                       |
| `imu`                         | ~100 Hz       | acceleration, angular velocity, orientation, `g`                                                                                                              |
| `magnetometer`, `barometer`   | 50, 25 Hz     | field and heading; pressure                                                                                                                                   |
| `pose`                        | 30 Hz         | position, orientation, Euler angles, velocity, position std, confidence                                                                                       |
| `zed_health`                  | 1 Hz          | fps, dropped frames, tracking state and quality flags, mapping, temperatures                                                                                  |
| `jetson`, `jetson_containers` | 1 Hz          | per-core load and clocks, temperatures, rail power, fan; per-container CPU and memory                                                                         |
| `joy`                         | 30 Hz         | gamepad throttle and steer while connected (receive time)                                                                                                     |
| `operator_heartbeat`          | 2 Hz          | HUD heartbeats (HUD time) and their round trip through the robot back to Forge                                                                                |
| `wifi`                        | 1 Hz          | Wi-Fi signal, router ping, link rates, throughput, errors and drops                                                                                           |
| `map_chunks`                  | on change     | spatial-map mesh chunk vertex and triangle counts and centroid; the mesh is not stored                                                                        |
| `obstacle`                    | 10 Hz         | nearest obstacle and nearest obstacle in the driving corridor: distance, bearing, point; the governor's scan and blind flag                                   |
| `nav_state`                   | 10 Hz         | navigation mode, goal, mission step, distance to goal, heading error, speed, steer, free distance, safety fault, mission id                                   |
| `drive`, `nav_events`         | 20 Hz, events | drive commands; goals, missions and cancels; each with its `source` (nav, explore, forge, hud)                                                                |
| `command_events`              | events        | exploration starts and map saves with their sender and payload                                                                                                |
| `explore_state`               | 2 Hz          | exploration id, phase, limits, distance driven, frontiers, target, planning time                                                                              |
| `kv_changes`                  | on change     | changes of the robot key-value bucket: camera settings, intrinsics, operator and UI state (current values at writer start)                                    |
| `logs`                        | events        | log records of every node (see Logs)                                                                                                                          |

The JPEG preview (`rabbit.zed.frame.preview`) and the map snapshot reply (`rabbit.map.snapshot`) are not stored; `zed_health` carries the preview counters and `map_chunks` the mesh summaries.

Commands carry the sender's clock: the robot's nodes stamp theirs (`ts`, `source` nav or explore), Forge stamps its own (`source` forge, Mac clock), and HUD commands without a `ts` get the writer's receive time (`source` hud). Both machines run NTP.

## Logs

Every robot node inherits `RabbitNode` (`rabbit/workspaces/rabbit/src/lib/node.py`), which adds `NatsLogHandler` (`lib/log.py`) to the root logger. Each record becomes a JSON message on `rabbit.log.<node>` with the robot wall clock, level, logger, message and template, exception type and traceback, `module:function:line`, the `extra` fields and the node's context (`mission_id` from nav, `map_session` from the camera and explore nodes, `exploration_id` from explore). Identical records (same logger, level, template with numbers ignored and exception) are suppressed for 10 s and the next record carries the suppressed count as `repeats`. The handler also logs uncaught exceptions in the main thread, other threads and the asyncio loop, and a `Node crashed` record before the process exits. The telemetry node logs Docker container events (`docker.events`: started, exited with its exit code, killed, out of memory, health changes), so a segmentation fault inside a native library still leaves a record.

On the robot the `LOGS` JetStream stream (created by `nats/init.sh`: file storage, s2 compression, 7 days, 2 GB) keeps the records while the Wi-Fi is down. The writer reads it with the durable pull consumer `forge-writer` and acknowledges a batch only after ClickHouse stored it. A record belongs to the run that contains its own timestamp, not the run open when it arrived, so a backlog replayed after an outage lands in the right run (`runAt` in `src/runs.ts`).

`logs` is a ReplacingMergeTree keyed on `(run_id, ts, seq)` with a `fingerprint` that groups records of a kind, a `text` index on `message` and `exception` (lowercase, split on non-letters; `hasAllTokens(message, 'roboclaw error')`), and TTL: info and debug 30 days, warnings and worse 180 days. The text index needs `enable_full_text_index`, set for both Forge users in `clickhouse/users.xml`.

- `search_logs` finds records by words, node, level and run or time range, grouped by kind with counts, first and last time and the latest traceback.
- `logs_around` lists the records around a moment in time order with their offset in seconds.
- `timeline` returns everything around a moment or a range of at most 15 minutes on one clock: commands with their sender, state transitions (navigation mode, safety faults, missions, exploration phase, camera tracking, Wi-Fi), HUD heartbeat silences, configuration changes, log records (warnings and worse, plus info messages that occur at most three times), and every metric of the graph summarised as moved (min, max, mean, last, sparkline), steady or without data.
- `list_metrics` lists every graph metric with its table, expression and NATS subject, and every table with its subjects.

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

| Slab                  | Answers                                                                                                                                              |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_summary`         | one-row overview: duration, battery voltage, current, energy, charge, motor current and errors, Jetson peak temperature, path length, tracking drops |
| `drive_tracking`      | motor command and nav speed command vs ZED ground speed and motor current over time (stalls)                                                         |
| `battery_sag`         | battery voltage, current and charge vs motor current over time                                                                                       |
| `battery_resistance`  | linear fit of battery voltage on current: internal resistance, worst unexplained sag                                                                 |
| `motor_power_by_side` | mean and peak current, power and energy per motor                                                                                                    |
| `turn_current`        | motor current by steering lock while driving (spikes in full-lock turns)                                                                             |
| `power_rails`         | battery and 6 V rail power and energy                                                                                                                |
| `jetson_throttling`   | junction temperature, clocks, load, power, share of time below peak clock                                                                            |
| `container_load`      | CPU and memory per Jetson container                                                                                                                  |
| `imu_shocks`          | peak deviation from 1 g, RMS vibration, shock count over a threshold                                                                                 |
| `trajectory`          | position, step, cumulative distance and speed from the ZED pose                                                                                      |
| `stream_rates`        | samples, rate and longest gap per stream (dropouts)                                                                                                  |
| `stall_events`        | seconds above a motor-current threshold, PWM at the peak, time over threshold, ground speed (stall vs inrush)                                        |
| `brownout_and_gaps`   | data gaps with reboot detection (Jetson uptime reset), battery and Wi-Fi state just before                                                           |
| `tracking_quality`    | camera fps, dropped frames, pose lost share, tracking mode, quality warnings, confidence                                                             |
| `steering_response`   | steering angle vs IMU yaw rate and ground speed, curvature per unit steer                                                                            |
| `mission_timeline`    | second-by-second nav mode, step, distance and heading error, commands, ground speed, obstacle ahead                                                  |
| `power_budget`        | battery, motors, Jetson, servo rail and the rest: mean and peak W, Wh, share                                                                         |
| `thermal_timeline`    | Jetson, camera and motor controller temperatures, fan, slowest CPU clock                                                                             |
| `obstacle_events`     | seconds with an obstacle closer than a clearance, nav mode and speed at that moment                                                                  |
| `run_compare`         | two runs side by side (`run_id`, `other_run_id` default latest and previous)                                                                         |
| `wifi_health`         | signal, router ping p50/p95/max, lost pings, throughput, drops                                                                                       |
| `obstacle_clearance`  | nearest obstacle overall and ahead, close calls under a clearance                                                                                    |
| `nav_missions`        | per mission or goal: plan, arrived, cancelled or replaced, time to arrive, share of time blocked                                                     |
| `nav_transitions`     | navigation mode, safety fault and mission changes with the speed command and free distance at that moment                                            |
| `command_timeline`    | per bucket: gamepad, navigation drive commands, stops, goals, missions, cancels and other commands with their sender, HUD heartbeats                 |
| `operator_link`       | HUD heartbeats per second, round trip p50 and max, longest silence                                                                                   |
| `log_summary`         | log records per node and level: count with repeats, kinds, most frequent message, latest exception, first and last time                              |
| `log_error_rate`      | warnings and errors per second per node over time, with the most frequent message                                                                    |
| `container_events`    | robot container starts, exits with exit code, kills, restarts, out-of-memory and health changes                                                      |

`search_slabs` is deterministic BM25 (MiniSearch) over id, title, description, tags, prompts and column names.

## Metric graph

`graph/metrics.yml` is a typed graph of the robot's metrics: 54 nodes and 82 edges. A node is a measured series (`source: {table, expr, agg}` binned in ClickHouse, with unit, native rate `hz` and sensor resolution `floor`; `agg: rate` counts rows per second, with empty bins as zero, for logs and heartbeats) or an event list read from a slab (`events: {slab, time, end, where}`: reboots and data gaps from `brownout_and_gaps`, stalls from `stall_events`, navigation safety stops from `nav_transitions`, container crashes from `container_events`, missions from `nav_missions`); every node names the slabs that fetch it. Commands connect to what they move (gamepad throttle and the navigation speed command to the motor command, then PWM, current and ground speed; gamepad and navigation steering to the steering angle; missions to the navigation speed), safety stops to the signals behind each rule (motor current and ground speed for a stall, an IMU jolt for a collision, free distance for blocked, HUD heartbeats for operator link lost, the gamepad for a manual override) and to the navigation logs, and the log rates per node decompose the total. An edge is directed and typed, with a reason (`why`), an evidence class (`physics`, `design`, `observed`) and an optional `sign`:

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

Every ad-hoc or generated query passes `src/sql/validate_sql.ts` (parsed with `@polyglot-sql/sdk`) and then `EXPLAIN PLAN` as `forge_reader`:

- exactly one `SELECT` / `WITH` / `UNION` statement;
- only Forge tables, CTEs of the query and subqueries; no other database, table function, `FINAL` or `SETTINGS`;
- no `FORMAT`, `INTO OUTFILE`, `GLOBAL IN` or references to `system` / `information_schema`;
- functions come from an allowlist (aggregates and their combinators, window, math, date and time, string, array, JSON and conditional functions), including those named in `* APPLY(fn)`, so anything reading server state or other data is rejected;
- every `JOIN` matches qualified `run_id` columns of its two sides with AND only (no `OR`), plus a time or sequence key from both sides (a shared bucket, or `ASOF ... a.ts >= b.ts`) unless one side is aggregated to one row per run; no comma joins. Two runs never pair up, and no join multiplies every row of a run with every other.

A test runs every slab through the gate, so a rule that is too strict fails CI rather than a slab.

A rejection returns a stable error plus a repair hint for the model (the columns of the tables it read, the GROUP BY rule, the aggregate-alias trap), as Nexus does with `NexusError.llm`.

## Agent

`ask` (CLI and MCP tool) starts with the recent runs and the five nearest slabs in context, and can call `list_runs`, `search_slabs`, `run_slab`, `write_query`, `detect_anomalies`, `metric_graph`, `investigate`, `timeline`, `search_logs` and `logs_around`. It runs a slab when one covers the question (fast path); otherwise it calls `write_query`, a sub-agent that sees the schema and the three nearest slabs' SQL and must commit through `finalize`, which runs the gate and EXPLAIN and returns repair hints until the SQL is valid (heavy path). The answer cites the run and the slab or SQL, and every number must come from a tool result. Data and tool parameters are UTC; the operator works in `config.operatorTimeZone` (Australia/Sydney), whose current time and offset the agent receives with every question, so it converts the operator's times for tools and answers in local time. The result reports `path: fast | heavy` and a trace of tool calls.

## Chat API

The `forge-chat` service runs on the robot behind `rabbit-web` (nginx), which serves the HUD at `https://jetson.rabbit` and proxies `/api/` to the chat with `Host: localhost:18080`, passing the browser's `Origin` and filling it in for same-origin requests (browsers omit it on same-origin GETs). The HUD reads the base URL from `VITE_CHAT_URL` in `workspaces/web/src/chat/session.ts`: the robot build sets it empty (same origin), and the dev server on the Mac defaults to `https://jetson.rabbit`. `pnpm forge serve` runs the same server on a laptop at `http://127.0.0.1:18080` for development.

- `POST /api/chat` takes `{ messages: UIMessage[] }` (stateless, the client sends the history; only `user` and `assistant` messages) and streams the AI SDK UI message stream. A client that disconnects aborts the agent run. It requires an allowed `Origin` (`https://localhost:*`, `https://dev.rabbit:*`, `https://jetson.rabbit`) and `content-type: application/json`. There is no token: the chat is only reachable on the robot's local network, and the origin check keeps other websites from driving it.
- Only the `Host` values `127.0.0.1:18080` and `localhost:18080` are served (nginx sets the latter), which blocks DNS rebinding.
- `GET /api/health` returns `{ ok, model, clickhouse, latest_data_age_s, run }`.

The chat agent is `ask` with more tools: the data tools, `write_query`, `chart` (plots a slab or SQL result; the server converts times to epoch ms and downsamples to 2000 rows), and the robot tools `robot_status`, `run_mission`, `stop`, `save_map`, `start_run` and `stop_run`. `run_mission` publishes `rabbit.nav.mission {id, steps}` (turn, move, goto, queued on the robot) and needs the operator's approval: tools declare `requiresApproval`, chat turns that into AI SDK tool approval signed per server process, and execution consumes a single-use approval that expires after 60 s (MCP never registers such tools). Before publishing, the server re-checks that the pose, camera tracking and obstacle readings are fresher than 3 s, tracking is OK and the first leg that moves is clear of the obstacle ahead (when it starts within 10 degrees of the current heading), and enforces at most 3 m per move, 5 m per goto, 10 steps and 10 m per mission, dead-reckoning the steps so each goto is measured from where the earlier steps leave the robot. The mission carries its own `id` (`forge-<uuid>`); the tool waits up to 3 s for `rabbit.nav.state` to report that `mission_id` (`accepted`), fails with nav's reason when nav sets a new `rejected: ...` fault, and otherwise returns `accepted: false`. `nav_state.mission_id` keeps the last mission after it ends, so whether a mission is running comes from `mode`. `stop` publishes `rabbit.nav.cancel` and a zero `rabbit.cmd.drive` independently, without approval, and reports each; the robot NATS connection reconnects indefinitely and every publish waits at most 3 s for the server. Chat never publishes a non-zero drive command. Tools return `{kind: 'table'}`, `{kind: 'chart'}` (optional `layout: 'stacked'`, `series.panel` and `dashed`, range markers with `x_end` and `series`, bands per series, and an `id`), `{kind: 'graph'}` or `{kind: 'status'}`; the model sees a summary of charts and graphs instead of their rows. The chat prompt asks for a TL;DR, key numbers, findings with status chips and evidence, and next steps, written with inline tokens the HUD renders: `ok:`, `info:`, `warn:`, `alert:` (status chips), `kpi:Label=value` (key numbers), `spark:v1,v2,...` (sparklines), `ref:kind:target?key=value` (evidence chips that re-run a slab, detection or investigation, or scroll to a chart or graph by id) and `next:question` (follow-ups).

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

Tests cover the SQL gate, the writer's batching (bisection, retries, the buffer cap), mission planning and acceptance, approvals, slab search ranking for Russian and English questions, the metric graph loader and traversal, the graph statistics, grid filling (gaps and zero-filled rates), joint events, the anomaly reference, the run a record belongs to by its timestamp, and the mapping of robot log records to rows. The robot's log handler (repeat suppression, payload fields) is tested in `rabbit/workspaces/rabbit/tests/test_log.py`.

`pnpm forge eval [<case>]` runs the chat agent on `evals/chat.yml` (questions with the tool calls, approvals and facts each answer must contain) against live ClickHouse and the model, with robot actions as dry runs and a fixed `robot_status`. It has 25 cases, including investigations (reboot at 11:00, battery sag, wall push), the metric graph (neighbourhood and path), multi-metric anomalies, a camera node crash read from the logs and container events, and who sent a stop command; with the final prompt it passes 25 of 25. `pnpm forge eval tools` is the deterministic check for `investigate` and `detect_anomalies` (see Anomaly detection). Schema changes during development: edit `schema.sql` and apply the matching `ALTER` once, or reset with `docker compose down -v`.

## Data notes

- `roboclaw.supply_voltage` is the 12 V buck output feeding the motor controller, not the battery; battery voltage and power come from `power`.
- Motor current is measured at 12 V by the RoboClaw; battery current is measured at the pack and includes the Jetson, camera and servos.
- `rabbit.health.zed` occasionally publishes invalid JSON (NaN values); the writer counts and drops those messages.
- Wi-Fi telemetry starts at about 11:30 on 2026-10-01, so the earlier 1.5 s ping episode has no Wi-Fi rows.
- `battery_charge_pct` is a voltage-curve estimate and reads low under load. Rows recorded before the robot published it are NULL.
- `magnetometer.heading_deg` is meaningless while `heading_state` is `NOT_CALIBRATED`.
- Right after the ZED node restarted at 10:46, about 5 minutes of `pose` and `obstacle` rows carry camera timestamps up to 5.7 minutes behind the robot clock; later rows are aligned.
- The wheel encoders are not connected, so `roboclaw` speed and encoder columns are always 0; ground speed comes from `pose` velocity.
