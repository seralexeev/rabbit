# Forge on Parquet and chDB

Date: 2026-10-03 00:55 UTC – (in progress). Reference documentation: `workspaces/forge/README.md` (Storage) and the `forge-dev` skill. Earlier history: `2026-10-01-forge.md`.

## Context and goal

The Jetson Orin Nano shares 8 GB between CPU and GPU, and Forge was its largest memory user after the camera: on 2026-10-03 at 01:00 UTC `docker stats` showed `forge-clickhouse` 442–624 MiB (limit 900 MB), `forge-writer` 116 MiB and `forge-chat` 86–118 MiB. The owner decided to replace the ClickHouse server with Parquet files and chDB (ClickHouse as a library), keeping the ClickHouse SQL dialect so slabs, the metric graph, the tools and the agent's SQL keep working. Data at the start: 17.06 M rows in 25 tables, 221 MiB in ClickHouse, ingest about 300 rows/s (IMU 110–150 Hz, power and RoboClaw 50 Hz).

## Design

- **One process.** `forge` runs the writer, compaction and the chat API (`serve --writer`). Two processes would each load chDB, and compaction needs a lock shared with the queries (below), which is trivial in one process. A deploy restarted writer and chat together before as well.
- **chDB from Node.** The `chdb` npm package 3.4.0 (engine 26.7.2) has prebuilt `linux-arm64-gnu` and `darwin-arm64` libraries, so no sidecar was needed. They are glibc builds: the image moved from `node:26-alpine` to `node:26-slim` (Debian 13). The engine is a process singleton, but several `Session` objects on the same path run queries in parallel (a `SELECT 1` returned in 0 ms while another session ran a 1.2 s query; within one session it waited the full 1.1 s), so the store keeps one writer session and four reader sessions.
- **Layout.** `data/<table>/date=YYYY-MM-DD/hour=HH/<from>-<to>.parquet`, zstd, sorted by the table's `ORDER BY`, row groups of 65,536 rows. File names are the writer's flush ids (milliseconds, strictly increasing across restarts); a merged file is named after the range it covers.
- **Schema.** `src/store/schema.sql` (moved from `clickhouse/schema.sql`, codecs, settings, TTL and the text indexes removed) is created as empty tables in an in-memory `forge_schema` database. Each table becomes a view `forge.<table>` over `file('<table>/*/*/*.parquet', Parquet, '<columns with exact types>')`, so Enum, LowCardinality, Map, `Array(Nullable(Float32))` and Bool come back with the schema's types and `level >= 'warning'` still compares enum values (Parquet stores the enum as a string). Writes go through `ENGINE = Memory` staging tables built from the same schema, so `imu.g` and `logs.fingerprint` are computed as before.
- **Atomic flushes.** Every 10 s each table with rows writes one file per hour it touches: `INSERT INTO FUNCTION file('….parquet.tmp')`, fsync, rename, fsync of the directory. Readers glob `*.parquet`, so a torn file is never read; the next start deletes `.tmp` files. A hard power-off loses at most the 10 s in memory. A retried write reuses its file id, so a retry replaces its own file instead of duplicating rows (this replaces ClickHouse's `insert_deduplication_token`).
- **Freshness: flush every 10 s, no in-memory tail.** The suggested 30–60 s flush with a queryable in-memory tail was rejected: the tail must be unioned into every view and swapped atomically with the file that replaces it, and the robot is often hard-powered off, so the last seconds before a brownout are exactly the data `brownout_and_gaps` needs. 10 s flushes give the same freshness as the old 10 s inserts with a 10 s loss bound, and compaction absorbs the small files.
- **Compaction and crashes.** A closed hour (2 minutes past its end) is merged into one file; an open hour merges once 30 small files pile up (an imu hour is 3 writes per row: 10 s file, intermediate, hourly). The rename of the merged file and the deletion of its inputs run under a read-write lock that every query holds as a reader, so a query never sees both. A crash between the two leaves files whose id range lies inside another file's; startup (and every Mac sync) deletes them. `ReplacingMergeTree` tables (`logs`, `kv_changes`) drop duplicate sorting keys while merging, as ClickHouse merges did.
- **Retention** replaces the ClickHouse TTL: `logs` keep only warnings and worse after 30 days and are dropped after 180; above 50 GB (`FORGE_MAX_DATA_GB`) the oldest hours go first; `run_events` stays.
- **Limits.** Reader sessions: `readonly=2` (`readonly=1` also forbids `file()`, so views would fail), 30 s, 300 MB per query with sort and GROUP BY spilling above 100 MB, 200 M rows or 4 GB read, 10k result rows, 2 threads; 900 MB for the engine. The static SQL gate is unchanged and matters more: chDB can read any file the process can (`file('/etc/hosts')` works), and the gate already rejects table functions, other databases and `SETTINGS`.
- **The Mac.** The CLI, MCP and evals used the robot's ClickHouse over port 18123. Now `pnpm forge sync` rsyncs the robot's volume into `data/forge` (repository root), and with `FORGE_SYNC_FROM` in `.env` every query syncs first when the copy is older than 30 s; with the robot off they query the last copy. Runs started from the Mac go to the writer over NATS (`forge.run.start/stop`). A remote SQL endpoint was considered and dropped: it would expose the engine on the LAN and every internal query would need the gate.
- **Considered and dropped:** chDB with its own MergeTree storage (the owner chose Parquet); a pure-JS Parquet writer (`hyparquet-writer`, `parquet-wasm`): staging plus ClickHouse's own writer gives exact types and defaults for free; a separate process for the writer.

## Differences found

- `hasAllTokens(message, ...)` was case-insensitive only through the text index's `lower` preprocessor. Without an index it matches tokens as written, so `search_logs` and the table comment now use `hasAllTokens(lower(message), lower(...))`.
- `FINAL` does not apply to views: the timeline reads `kv_changes` with `LIMIT 1 BY ts, key, revision`.
- chDB returns 64-bit integers as JSON numbers, like the ClickHouse 26.1 server over HTTP; setting `output_format_json_quote_64bit_integers=1` broke 500 parity comparisons and was removed.
- The ClickHouse 26.1 server parsed about 12 % of decimal Float32 values one ULP off (`1.305` stored as 0x3FA70A3E instead of the correctly rounded 0x3FA70A3D); chDB 26.7 rounds them correctly. Migrated rows keep the old bits.
- Joins: without table statistics the planner may build the hash table from either side; the slabs still run within the limits.
- `raw insert` of chDB accepts only plain `db.table` names (a backquoted name fails); the store tests caught it before the first deploy.

## Also fixed in Forge

- **Pose Euler angles.** ZED `get_euler_angles()` returns the rotations about x, y and z; in the right-handed Y-up frame that is pitch, yaw, roll, and the writer stored them as roll, pitch, yaw. On the 6.8 h run `20261002-014624-auto`, `pitch_deg` equals minus the quaternion heading with a median error of 0.002°, spreads 80° while `roll_deg` and `yaw_deg` stay within 1–2.5°. The mapping is fixed (`zedEuler` in `src/streams.ts`, test in `src/streams.test.ts`), and `robot_status` took its live yaw from index 2 (roll) and now from index 1. Older rows are left as they are and documented in the column comments.
- **Unanswered approvals.** A motion approval card left unanswered (or whose approval never ran) left a function call without an output in the history, and OpenAI refused the next message ("No tool output found for function call"). `settlePendingTools` in `src/agent/chat.ts` turns every unsettled tool call in earlier messages into a denied or failed call ("Not run: the operator did not approve it ..."), keeping the last message untouched so a fresh approval still runs. The approval window is 2 minutes instead of 60 s.
- **Throttling telemetry** (recommendation 2 of `docs/reports/2026-10-03-power-throttling.md`). `rabbit-telemetry` adds `clocks` to `rabbit.telemetry` at 1 Hz: the clock each core actually runs at (`cpuinfo_cur_freq`; `scaling_cur_freq` through jtop never showed the OC3 cuts), the CPU floors (`scaling_min_freq`), GPU devfreq min and max, the EMC clock (jtop), `oc1/oc2/oc3_event_cnt` of the `soctherm_oc` hwmon, the BPMP throttle time (`soctherm/oc2/event_time`, debugfs mounted read-only into the container) and the nvpmodel mode (`lib/jetson_clocks.py`, tested on a fake sysfs). Forge stores them as new `jetson` columns (NULL or empty before 2026-10-03), the slab `power_throttling` gives OC events per second, the throttled share, actual against requested clock and whether the jetson_clocks floors held, and the graph has `cpu_actual_freq` and `cpu_clock_floor` (56 nodes, 85 edges). Not deployed yet: it needs `rabbit-telemetry` recreated and the Forge switch.

## Parity

- **Query parity (history).** The robot's ClickHouse was exported over HTTP (`SELECT * … FORMAT Parquet`, 36 s, 220 MB, rows before 2026-10-03 01:00 UTC) and imported into a store on the Mac (31 s for 17.06 M rows, 255 MB in 388 files). `pnpm forge parity` ran every tool on both: all 32 slabs, `timeline`, `search_logs` (with and without words), `logs_around`, `investigate` (events and a metric), the metric graph series and `find_object` over 14 closed runs, recorded each SQL statement with its parameters and replayed it on both engines. 1,904 distinct queries: 1,389 identical, 4 identical up to row order (ties), 6 approximate (`quantile` sampling and `topK` ties), 503 EXPLAIN/system/now()-dependent queries that ran on both, 2 different because ClickHouse already had a later map reset than the export, 0 errors.
- **Live shadow (robot).** A shadow writer (`forge-shadow`, image `forge:chdb`, code in `/root/rabbit/workspaces/forge-next`, volume `workspaces_forge-data`, log consumer `forge`) ran next to ClickHouse from 01:43:53 UTC. Per table and minute, 01:45–01:49: equal row counts in all 24 tables and equal per-column sums (floats within 1e-5, everything else by `cityHash64`), except `map_chunks`, `joy` and `operator_heartbeat`, whose `ts` is each writer's own receive time.

## Measurements

Robot (Jetson Orin Nano, 6 cores), CPU averaged over 180 s with the robot idle, from cgroup `cpu.stat`:

| | before | shadow writer |
|---|---|---|
| CPU | writer 7.2 % + ClickHouse 14.6 % + chat 1.6 % | 15.8 % (the first version, which issued 5 statements per flush, used 20 %) |
| memory (`docker stats`) | ClickHouse 356–624 MiB + writer 116 MiB + chat 114 MiB | 294 MiB, of which 253 MiB anonymous |

Linux arm64 container on the Mac (colima, 2 CPUs, 768 MB limit), the whole process (store, chat code, gate) on the 6.8 h run `20261002-014624-auto`:

| | latency | anonymous memory after |
|---|---|---|
| engine start (schema, 25 views, 5 sessions) | 142 ms | 209 MB |
| `robot_status`-style latest-row queries ×4 | 36 ms | 213 MB |
| all 32 slabs | 2.5 s (`stream_rates` 390 ms, `run_compare` 165 ms) | 259 MB |
| `timeline` over 15 min | 191 ms | 259 MB |
| `investigate motor_current` over 15 min | 270 ms | 260 MB |
| metric graph series over the whole run | 529 ms | 195 MB |
| 8 slabs in parallel | 581 ms | 196 MB |

The cgroup peak was 314 MB. chDB's own tracked memory (`MemoryTrackingUncorrected`) stays near 30 MB; its library maps about 190 MB of code, which is file-backed and shared.

**The SQL gate's parser was the largest item.** `@polyglot-sql/sdk` is a 25 MB WebAssembly module; after parsing the 32 slabs the process held 170–185 MB more, also in the old `forge-chat`, and neither a worker thread (terminated after idling: only 80 MB came back) nor allocator settings (`MALLOC_ARENA_MAX`, jemalloc preload, `MALLOC_CONF`) changed it. It is V8's optimized machine code for the module: with `node --liftoff-only` the growth is 28 MB and parsing costs 0.77 instead of 0.70 ms per query. The image's entrypoint and `pnpm forge` use the flag.

## Rollout

1. Prototype and benchmarks on the Mac and in colima (arm64 Linux): done.
2. Shadow mode on the robot: running from 01:43 UTC until the robot was switched off around 02:01 UTC. `forge-shadow` has `restart: unless-stopped`, so it comes back with the robot.
3. Switch (prepared, not deployed): `data/forge-cutover/compose.yaml.next` replaces `forge-writer` and `forge-chat` with `forge` (alias `forge-chat` for nginx until `rabbit-web` reloads `web/nginx.conf` pointing at `forge`); `scripts/deploy.sh` must then match `forge` instead of `forge-writer|forge-chat`. History before the shadow start comes from a ClickHouse export imported with `pnpm forge import <dir> --before '2026-10-03 01:43:53.505'`, which replaces the shadow's replayed logs and KV values before that moment and closes the ClickHouse runs still open at it.
4. Removing `forge-clickhouse`, its volume and `workspaces/forge/clickhouse/` after a final export kept as a backup: pending.

## Evals

The chat suite named runs and times from the 2026-10-01 laptop database (`bench-idle`, `autonomous-nav`, the 11:00 reboot), so 11 of its 29 cases could not pass on the robot's data. It now resolves its anchors from the store at eval time (`anchor` SQL in `evals/chat.yml`: the longest run, the biggest motor-current peak, the longest gap, the latest camera restart, relocalization, operator stop, exploration and refrigerator trip, a rarely seen object, an object only in an earlier map), accepts times in UTC and Sydney time, and adds cases for an approval card left unanswered, an expired approval, `power_throttling`, the robot's heading from `robot_status` and `find_object` on few detections; `find_object` now returns the frames and confidence of its match. 38 cases.

On the same data (the offline exports `data/offline/export` and `export-20261003`, 1–3 October, merged into one store, about 18.4 M rows): the old suite passed 18 of 29 cases (73 % of checks), the new one 32 of 38 (93 % of checks; 33 with the encoder fact accepting "no encoder distance"). The failures it found at that point, all genuine:

- `stall`, `motor_anomaly_window`, `last_relocalization`: the agent converts UTC to Sydney time with +11 h (daylight time starts on 4 October), although its context says AEST, UTC+10:00; tool results carry UTC only.
- `fridge_trip`: no slab covers `planner_state`, and the SQL sub-agent looked at `nav_missions`, which has no destinations.
- `object_from_old_map`: the agent answers "where is the nightstand" from `objects_seen` over the latest run, which includes detections from before the map reset, instead of `find_object`, which knows the current map.

Fixed after that, on the owner's go-ahead: tool results now carry every time a second time in Sydney time (`<field>_local`, computed with the IANA zone, so AEDT from 2026-10-04 is right) with a `timezone` note, and the prompt forbids offset arithmetic; new slabs `planner_trips` (per trip: source, target, start and end, final phase and message, replan reason, route length, replans, recoveries, `all_runs` to search every run) and `explorations` (per exploration: end phase and reason, distance, frontiers, limits); "where is X" and "where did you see X" go to `find_object` (the `objects_seen` description and the chat prompt now say it is run history, including objects from before a map reset); `search_logs` matches word parts ("relocali" finds "Relocalized"). With the eval checks tightened to require `find_object`, `planner_trips` and `explorations` and one more case (what was seen during a run), the suite passes 38 of 39 on the same data (99 % of checks); the remaining failure was a fact matched too literally ("distance limit reached" against "its 8 m distance limit"), fixed in the case and passing on its own.
