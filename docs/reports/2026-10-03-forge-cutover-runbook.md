# Forge cutover runbook (working note, not committed)

T0 = 2026-10-03 01:43:53.505 UTC (first run start of forge-shadow).

0. Robot back: check forge-shadow recovered from the power cut
   - `docker logs forge-shadow | grep -i "unfinished\|Removed"`, no `*.tmp` in the volume
   - last row before power-off: store vs ClickHouse per table (`max(ts)` where ts < boot time)
1. Before-eval (old code + ClickHouse, on the robot, no secret copying):
   `docker cp workspaces/forge/evals forge-chat:/app/evals` (from robot path) then
   `docker exec forge-chat node src/cli.ts eval > /root/rabbit/data/eval-before.json`
2. Export ClickHouse rows before T0 on the robot host:
   copy `data/clickhouse-export/export.sh` to /root/rabbit/data/, run with
   `CH=http://127.0.0.1:18123 nice -n 19 ./export.sh /root/rabbit/data/clickhouse-export-T0 '2026-10-03 01:43:53.505'`
3. `docker tag forge:latest forge:alpine-clickhouse && docker tag forge:chdb forge:latest`
4. `docker stop -t 45 forge-shadow && docker rm forge-shadow`
5. Apply `compose.yaml.next` (compose.patch), deploy.sh pattern `^(rabbit-|forge$)`, web/nginx.conf `forge:18080`;
   `scripts/deploy.sh forge` (removes forge-writer, forge-chat as orphans; forge-clickhouse untouched)
6. Import (one-off, nice):
   `docker run --rm --network none --memory 768m --cpus 1 -e FORGE_DATA_DIR=/app/data -v workspaces_forge-data:/app/data -v /root/rabbit/workspaces/forge/src:/app/src:ro -v /root/rabbit/workspaces/forge/slabs:/app/slabs:ro -v /root/rabbit/workspaces/forge/graph:/app/graph:ro -v /root/rabbit/data/clickhouse-export-T0:/export:ro --entrypoint nice forge -n 19 node --liftoff-only src/cli.ts import /export --before '2026-10-03 01:43:53.505'`
7. `docker run --rm --network workspaces_default bitnami/natscli consumer rm LOGS forge-writer -f --server nats://nats:4222`
8. After-eval: `docker cp .../evals forge:/app/evals; docker exec forge node --liftoff-only src/cli.ts eval`
9. Robot parity + latency: `docker exec forge node --liftoff-only src/cli.ts parity http://forge-clickhouse:8123 --before '2026-10-03 01:43:53.505' --limit 14`
10. CPU/memory 180 s (cgroup cpu.stat, memory.stat), `docker exec forge node --liftoff-only src/cli.ts bench`
11. Mac: append `FORGE_SYNC_FROM=root@192.168.1.53:/var/lib/docker/volumes/workspaces_forge-data/_data` to workspaces/forge/.env, remove FORGE_CLICKHOUSE_URL line; `pnpm forge sync`
12. Step 4 (lead OK first): final export of all ClickHouse rows as backup (robot + Mac data/), remove forge-clickhouse service, volume `workspaces_forge-clickhouse`, `workspaces/forge/clickhouse/`, the `parity` command; remove the `forge-chat` alias once rabbit-web runs the new nginx.conf.
