---
name: forge-dev
description: Develop and run Forge (workspaces/forge) - the Docker service, its Parquet store and chDB queries, adding a NATS subject to the writer, schema changes, slabs, the metric graph, the chat/MCP agent and its evals - and investigate robot incidents with SQL over the recorded telemetry. Use before changing Forge or when asked why the robot did something.
---

# Developing Forge

`README.md` is the full reference: architecture, storage, slabs, the SQL gate, the agent, the chat API, MCP and data notes. This skill is the short path through it.

## Service

On the robot, from `workspaces/compose.yaml`, one service `forge` (`node --liftoff-only src/cli.ts serve --writer`) does everything in one Node process:
- the writer reads NATS at `nats://nats:4222` locally (recording doesn't depend on Wi-Fi or the Mac) and writes Parquet files into the Docker volume `workspaces_forge-data` (`/var/lib/docker/volumes/workspaces_forge-data/_data` on the robot), one file per table and hour every 10 s;
- compaction merges them into hourly files and applies retention;
- the chat API queries the files with chDB, ClickHouse embedded in the process. There is no database server.

The HUD is served by `rabbit-web` (nginx) at https://jetson.rabbit, which proxies `/api` to the chat. Through the proxy the chat's origin check is effectively off: nginx always sends `Origin: https://jetson.rabbit`, so the shared tunnel link works too.

- **Health:** `curl -sk https://jetson.rabbit/api/health` reports `latest_data_age_s`. The writer opens a new `auto` run each time it restarts, and the agent looks at the latest run by default. `ssh ... 'docker logs --since 10m forge'` prints rows/s every 10 s and the compactions.
- **Deploying:** `scripts/deploy.sh forge` syncs the code and recreates the service in seconds; the last 10 s in memory are flushed on stop. The `forge` image holds only the dependencies (Debian slim, because chDB has only glibc builds); `src`, `slabs` and `graph` are mounted read-only. After changing `package.json`, `pnpm-lock.yaml` or the `Dockerfile`, build the image on the Mac (colima, arm64) and load it on the robot instead of building on the Jetson: `docker build -t forge workspaces/forge && docker save forge | zstd -T0 | ssh rabbit 'zstd -d | docker load'`, then deploy.
- **Queries on the robot:** `ssh rabbit 'docker exec forge node --liftoff-only src/cli.ts query "SELECT ..."'` (the gate applies). A second process opens its own engine (about 100 MB), so keep it to one-off checks.
- **From the Mac.** `pnpm forge ...` (CLI, `ask`, evals) and the MCP server query a mirror of the robot's files in `data/forge` at the repository root. `FORGE_SYNC_FROM` in `workspaces/forge/.env` points at the robot's volume; with it set they rsync before a query when the mirror is older than 30 s, and fall back to the last copy when the robot is off. `pnpm forge sync` syncs by hand. `run start/stop` goes to the robot's writer over NATS. When `.env` exists, Forge reads settings only from it, never from the shell.
- **Running on the host for debugging:** `pnpm forge serve` serves the chat over the mirror on 127.0.0.1:18080. Never start a second writer against the robot's NATS with the default log consumer (`forge`): it would split the robot's log stream. `workspaces/forge/docker-compose.yml` runs a full service on the Mac with its own volume and consumer.

## Checks

```sh
pnpm check            # oxfmt --check, tsc, oxlint (type-aware), vitest (the store tests open chDB)
pnpm format           # fixes formatting first
pnpm forge eval tools # deterministic check of investigate / detect_anomalies
pnpm forge eval       # chat agent on evals/chat.yml against the store and the model (costs tokens)
pnpm forge bench      # latency and memory of the heaviest tool queries
```

## Querying

The SQL is ClickHouse's: every table is a view `forge.<table>` over its Parquet files with the schema's exact types.

- **Timestamps.** Every table has `ts DateTime64(9, 'UTC')` on the robot's clock and a `run_id`. Write time literals as `toDateTime64('2026-10-01 21:10:00', 9, 'UTC')`. The robot's local time zone is AEST (UTC+10).
- **Main tables:**
  - motion and perception: `pose`, `imu`, `obstacle` (scan bins as an array), `objects`;
  - drive: `roboclaw`, `steering`, `power`;
  - navigation: `nav_state`, `nav_events`, `explore_state`, `planner_state`, `drive` and `joy` (commands with `source`);
  - localization: `loc` (rabbit-loc `map←odom`); the GEN_3-vs-rabbit-loc shadow check is `gen3_from_loc_x/z/yaw_deg` in `zed_health` (constant while both agree);
  - decisions: `events` (every node's decisions and state changes with `reason`, ids, `values` and `labels`; start here for "why"), `node_starts` (code revision, source hash, versions, environment and every constant at each node start);
  - system: `logs` (every node's log records), `node_metrics` (per node every 10 s: CPU, RSS, event-loop lag, NATS traffic, drops, error counters, loop timings in `values`), `nats_server` (slow consumers = message loss), `zed_health`, `jetson`, `jetson_containers`, `wifi`;
  - map and config: `map_chunks` (metadata only), `kv_changes`, `command_events`, `operator_heartbeat`;
  - runs: `runs`, `run_events`.
- **Words in logs:** `hasAllTokens(lower(message), 'roboclaw error')`; there is no text index, so the match is case-sensitive without `lower`.
- **Pose angles.** ZED `euler_deg` is the rotation about x, y and z in the Y-up frame, that is pitch, yaw, roll (`ZED_EULER` in `src/streams.ts`). Rows recorded before the writer fix of 2026-10-03 hold yaw in `pitch_deg`, roll in `yaw_deg` and pitch in `roll_deg`; for heading across all rows use the quaternion (`robot_status` heading formula in `src/robot.ts`).
- **Data notes.** The README lists the rest, for example that encoders are always 0 and `roboclaw.supply_voltage` is the 12 V buck, not the battery. Rows before 2026-10-03 01:43 UTC were migrated from ClickHouse; their Float32 values can differ from newer ones in the last bit (ClickHouse 26.1 rounded some decimals one ULP off).

## Changing the data path

- **New robot subject:**
  1. Add a stream entry to `src/streams.ts`: subject, table, zod schema and `toRows`.
  2. Add the table to `src/store/schema.sql` (`CREATE TABLE IF NOT EXISTS forge.<table>`, with `ORDER BY`; `ReplacingMergeTree` makes compaction drop duplicate keys).
  3. Redeploy. There are no migrations: a new column reads as its type's default in older files.
- **New robot event** (no Forge change needed): a node calls `self.event(...)` (see the rabbit-dev checklist); it arrives on `rabbit.log.<node>.event` through the `LOGS` stream and lands in `events`. Add it to the `name` comment in `src/store/schema.sql` and, when it answers a new kind of question, to a slab (`decisions` and `nav_stops` read `events`) and to `src/agent/ask.md`.
- **Checklist for a new subject or field:**
  1. zod schema and `toRows` in `src/streams.ts`; optional fields `.nullish()` so older senders and the simulator still parse (a schema mismatch drops the whole message and only shows in the writer's `malformed` counter);
  2. the column in `src/store/schema.sql` with a `COMMENT` that gives the unit, the frame and what a value means;
  3. the table row in `README.md` and, for a question the chat should answer, a slab and a case in `evals/chat.yml` (an anchor that finds nothing skips the case);
  4. `pnpm check`;
  5. record it from the simulator (rabbit-dev, "Checking observability in the simulator") and query it: the writer's `rows/s` line names the table and `malformed` must not grow.
- **Storage internals** live in `src/store/`: `engine.ts` (chDB sessions, views, limits), `write.ts` (staging table → Parquet, atomic commit), `compact.ts` (merges, retention), `layout.ts` (file layout, crash recovery), `sync.ts` (the Mac mirror), `import.ts` (loading `<table>.parquet` exports). The tests in `src/store/store.test.ts` pin the atomicity, the type mapping and the slabs on the views.
- **Map chunk format.** It is shared with the robot and the HUD. Change all decoders together (see `rabbit-dev`).
- **Slabs.** Reviewed YAML queries in `slabs/` with grain and measure metadata. `pnpm forge slab check` validates them, `pnpm forge slab run <name> --param ...` runs one.
- **Metric graph.** `graph/metrics.yml`, 56 nodes and 85 edges. It links commands to motor current and motion, safety stops to their signals, and log error rates to nodes. `investigate` walks it.
- **Agent prompts** live in `src/agent/` and the MCP instructions in `src/mcp/`. Prompt changes alter agent behaviour, so run `pnpm forge eval` after them.

## Investigating an incident

This is how the map-loss and stutter incidents were solved: go from symptom to timestamps, then to every signal around them. Run these with `pnpm forge query` (or over MCP).

```sql
-- data gaps per minute (writer blind vs robot silent)
SELECT toStartOfMinute(ts) m, count() FROM roboclaw WHERE ts > now() - INTERVAL 1 HOUR GROUP BY m ORDER BY m;
-- what a node logged around a moment, with tracebacks
SELECT ts, node, level, message, exception FROM logs WHERE ts BETWEEN ... ORDER BY ts;
-- tracking jumps / implausible poses
SELECT toStartOfMinute(ts) m, min(x), max(x), min(z), max(z), min(confidence) FROM pose WHERE ts > ... GROUP BY m ORDER BY m;
-- stops: blocked episodes with distance to goal and free distance
SELECT ts, mode, fault, free_distance, distance_to_goal, mission_id FROM nav_state WHERE ts BETWEEN ... AND mode != 'driving';
```

- **Cross-check against the robot itself.** Use `docker logs` there and the NATS server log (`docker logs nats`, for example "Slow Consumer" lines). Separate network effects from robot-side ones by comparing a subscriber on the robot with one on the Mac; the `rabbit-robot` skill has the access details.
- **The agent can investigate too.** `pnpm forge ask "..."` or the MCP tools `timeline`, `investigate`, `search_logs` and `logs_around` do the same over these tables.

### Investigation queries

Data from 3 Oct 2026 on carries `events`; older runs only have logs and state tables. Each query passed the SQL gate (`pnpm forge query "..."`). The slabs `decisions` (`--param id=<mission, trip or exploration id>`), `nav_stops`, `camera_restarts`, `node_health` and `node_versions` (`--param key=SAFETY_STOP`) wrap them.

```sql
-- the last mission (or exploration) with every decision and its reason, through planner and explore
WITH (SELECT argMax(mission_id, ts) FROM events WHERE name = 'nav.mission_started') AS last
SELECT ts, node, name, reason, values, labels FROM events
WHERE mission_id = last OR trip_id = (SELECT any(trip_id) FROM events WHERE mission_id = last)
ORDER BY ts;
-- for an exploration: exploration_id = <id> OR trip_id IN (SELECT trip_id FROM events WHERE exploration_id = <id> AND trip_id != '')

-- why nav stopped (or did not move): faults with their measurement, governor holds, cancels and who sent them
SELECT ts, name, reason, labels['source'] AS sent_by, values FROM events
WHERE name IN ('nav.safety_stop', 'nav.hold', 'nav.mission_cancelled', 'nav.manual_override', 'nav.odometry_reset',
               'motors.command_timeout', 'drive.owner_changed')
  AND ts > now() - INTERVAL 1 DAY
ORDER BY ts DESC;

-- camera restarts and relocalizations per boot
SELECT boot_id, min(ts) AS first_seen, countIf(name = 'camera.restart') AS restarts,
  groupArrayIf(reason, name = 'camera.restart') AS reasons, countIf(name = 'camera.relocalized') AS relocalized,
  avgIf(values['relocalization_s'], name = 'camera.relocalized') AS relocalization_s,
  countIf(name = 'camera.relocalization_failed') AS failed, countIf(name = 'map.archived') AS archived
FROM events GROUP BY boot_id ORDER BY first_seen;

-- reboots: a boot whose nodes never logged node.stop ended in a power loss or a hard reset
SELECT boot_id, min(ts) AS booted, max(ts) AS last_event, countIf(name = 'node.stop') AS clean_stops, countIf(name = 'node.start') AS starts
FROM events WHERE name IN ('node.start', 'node.stop') GROUP BY boot_id ORDER BY booted;

-- power and throttling per second around an event (here the last blocked stop)
WITH
  (SELECT max(ts) FROM events WHERE name = 'nav.safety_stop' AND reason = 'blocked') AS at,
  p AS (SELECT run_id, toStartOfSecond(ts) AS t, min(battery_voltage) AS battery_min_v, max(battery_current) AS battery_max_a
        FROM power WHERE ts BETWEEN at - INTERVAL 10 SECOND AND at + INTERVAL 5 SECOND GROUP BY run_id, t),
  j AS (SELECT run_id, toStartOfSecond(ts) AS t, max(power_mw) AS board_mw, min(arrayMin(cpu_freq_mhz)) AS cpu_min_mhz,
               max(temp_tj) AS tj_c, max(oc3_events) AS oc3_events
        FROM jetson WHERE ts BETWEEN at - INTERVAL 10 SECOND AND at + INTERVAL 5 SECOND GROUP BY run_id, t)
SELECT p.t, dateDiff('second', toStartOfSecond(at), p.t) AS offset_s, p.battery_min_v, p.battery_max_a, j.board_mw, j.cpu_min_mhz, j.tj_c, j.oc3_events
FROM p LEFT JOIN j ON j.run_id = p.run_id AND j.t = p.t ORDER BY p.t;

-- which code and which constant values were running
SELECT ts, node, git_rev, code_hash, config['nav.Node.SAFETY_STOP'] AS safety_stop_m FROM node_starts WHERE node = 'nav' ORDER BY ts DESC;

-- process health per node and minute (stalls, leaks, rabbit-zed grab times)
SELECT node, toStartOfMinute(ts) AS m, max(cpu_pct) AS cpu, max(rss_bytes) / 1048576 AS rss_mb, max(loop_lag_max_ms) AS lag_ms,
  max(values['grab_ms_max']) AS grab_ms
FROM node_metrics GROUP BY node, m ORDER BY m, node;
```

Without Forge, the same SQL runs over the files with `clickhouse local`, a table being `file('<data dir>/<table>/**/*.parquet', Parquet)`.
