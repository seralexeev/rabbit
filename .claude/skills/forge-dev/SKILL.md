---
name: forge-dev
description: Develop and run Forge (workspaces/forge) - the Docker services, ClickHouse access, adding a NATS subject to the writer, schema changes, slabs, the metric graph, the chat/MCP agent and its evals - and investigate robot incidents with SQL over the recorded telemetry. Use before changing Forge or when asked why the robot did something.
---

# Developing Forge

`README.md` is the full reference: architecture, slabs, the SQL gate, the agent, the chat API, MCP and data notes. This skill is the short path through it.

## Services

On the robot, from `workspaces/compose.yaml`:
- `forge-clickhouse`: memory capped at 768 MiB inside and 900 MB by cgroup;
- `forge-writer`: reads NATS at `nats://nats:4222` locally, so recording doesn't depend on Wi-Fi or on the Mac being on;
- `forge-chat`.

The HUD is served by `rabbit-web` (nginx) at https://jetson.rabbit, which proxies `/api` to the chat. Data starts fresh on the robot; the old Mac ClickHouse volume (`forge_clickhouse-data`) is stopped.

- **Health:** `curl -sk https://jetson.rabbit/api/health` reports `latest_data_age_s`. `ssh ... 'docker logs --since 10m forge-writer'` prints rows/s every 10 s.
- **Deploying:** `scripts/deploy.sh forge-writer forge-chat` rebuilds the `forge` image on the Jetson (about a minute) and restarts both.
- **ClickHouse on the robot:** `ssh -i ~/.ssh/rabbit_id_rsa root@192.168.1.53 'docker exec forge-clickhouse clickhouse-client -d forge -q "SELECT ..."'`.
- **Local development on the Mac:** `workspaces/forge/docker-compose.yml` still runs a Mac-side stack (`docker compose up -d --wait` after `colima start`), and `pnpm forge ...` reads `workspaces/forge/.env`. `FORGE_NATS_URL` and `FORGE_CLICKHOUSE_URL` choose the robot or the local services.
- **Running on the host for debugging:** stop the matching container first, otherwise every message is recorded twice or port 18080 clashes.

## Checks

```sh
pnpm check            # oxfmt --check, tsc, oxlint (type-aware), vitest
pnpm format           # fixes formatting first
pnpm forge eval tools # deterministic check of investigate / detect_anomalies
pnpm forge eval       # chat agent on evals/chat.yml against live ClickHouse and the model (costs tokens)
```

## ClickHouse

```sh
ssh -i ~/.ssh/rabbit_id_rsa root@192.168.1.53 'docker exec forge-clickhouse clickhouse-client -d forge -q "SELECT ... FORMAT TSV"'
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
