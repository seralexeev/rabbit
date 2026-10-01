---
name: forge-dev
description: Develop and run Forge (workspaces/forge) - the Docker services, ClickHouse access, adding a NATS subject to the writer, schema changes, slabs, the metric graph, the chat/MCP agent and its evals - and investigate robot incidents with SQL over the recorded telemetry. Use before changing Forge or when asked why the robot did something.
---

# Developing Forge

`README.md` is the full reference: architecture, slabs, the SQL gate, the agent, the chat API, MCP and data notes. This skill is the short path through it.

## Services

ClickHouse, the writer and the chat server run in Docker Compose inside the Colima VM.

- **Health check:** `docker compose ps` should show `forge-clickhouse`, `forge-writer` and `forge-chat` as healthy, and `curl -s http://127.0.0.1:18080/api/health` reports `latest_data_age_s`.
- **After a Mac reboot** Colima doesn't start by itself. Run `colima start`, then `docker compose up -d --wait` in `workspaces/forge`. Until then nothing is recorded and the HUD chat is down.
- **Deploying code changes:** `docker compose up -d --build --wait writer chat`.
- **Running on the host for debugging:** stop the matching container first (`docker compose stop writer`), otherwise every message is recorded twice or port 18080 clashes.
- **Writer state:** `docker compose logs --since 10m writer` prints rows/s every 10 s and the NATS state. NATS pings every 5 s, so a dead link is noticed in about 10 s.

## Checks

```sh
pnpm check            # oxfmt --check, tsc, oxlint (type-aware), vitest
pnpm format           # fixes formatting first
pnpm forge eval tools # deterministic check of investigate / detect_anomalies
pnpm forge eval       # chat agent on evals/chat.yml against live ClickHouse and the model (costs tokens)
```

## ClickHouse

```sh
docker compose exec -T clickhouse clickhouse-client -d forge -q "SELECT ... FORMAT TSV"
```

- **Timestamps.** Every table has `ts DateTime64(9, 'UTC')` on the robot's clock and a `run_id`. Write time literals as `toDateTime64('2026-10-01 21:10:00', 9, 'UTC')`. The robot's local time zone is AEST (UTC+10).
- **Main tables:**
  - motion and perception: `pose`, `imu`, `obstacle` (scan bins as an array);
  - drive: `roboclaw`, `steering`, `power`;
  - navigation: `nav_state`, `nav_events`, `explore_state`, `drive` and `joy` (commands with `source`);
  - system: `logs` (every node's log records, full-text index), `zed_health`, `jetson`, `jetson_containers`, `wifi`;
  - map and config: `map_chunks` (metadata only), `kv_changes`, `command_events`, `operator_heartbeat`;
  - runs: `runs`, `run_events`.
- **Known data bug.** In `pose`, `pitch_deg` actually holds yaw: ZED Euler angles are (x, y, z) in a Y-up frame and the writer mapped them as roll, pitch, yaw. Fix the mapping in `src/streams.ts` and treat older rows accordingly.
- **Data notes.** The README lists the rest, for example that encoders are always 0 and `roboclaw.supply_voltage` is the 12 V buck, not the battery.

## Changing the data path

- **New robot subject:**
  1. Add a stream entry to `src/streams.ts`: subject, table, zod schema and `toRows`.
  2. Add the table to `clickhouse/schema.sql`.
  3. Apply the matching `CREATE` or `ALTER` to the live database once by hand. The writer applies `schema.sql` at start, but `ALTER`s on existing tables are yours to run.
  4. Redeploy the writer.
- **Map chunk format.** It is shared with the robot and the HUD. Change all decoders together (see `rabbit-dev`).
- **Slabs.** Reviewed YAML queries in `slabs/` with grain and measure metadata. `pnpm forge slab check` validates them, `pnpm forge slab run <name> --param ...` runs one.
- **Metric graph.** `graph/metrics.yml`, 54 nodes and 82 edges. It links commands to motor current and motion, safety stops to their signals, and log error rates to nodes. `investigate` walks it.
- **Agent prompts** live in `src/agent/` and the MCP instructions in `src/mcp/`. Prompt changes alter agent behaviour, so run `pnpm forge eval` after them.

## Investigating an incident

This is how the map-loss and stutter incidents were solved: go from symptom to timestamps, then to every signal around them.

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
