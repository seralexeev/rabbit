#!/usr/bin/env bash
# Full-stack simulator on the Mac: NATS + rabbit-sim (camera and motors) + the real nav, planner and explore nodes.
#   scripts/sim.sh start [--hud]    SIM_WORLD=apartment|corridor|open-plan|/path/to/map.npz, SIM_START=x,z,heading_deg, SIM_KNOWN_MAP=1
#   SIM_BODY=1 adds the Rabbit 2.0 body: simulated lidar, ToF and bumpers, and the real safety and power nodes on fake GPIO
#   scripts/sim.sh restart <node> | stop | status
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUN=${SIM_RUN_DIR:-/tmp/rabbit-sim}
PORT=${SIM_NATS_PORT:-14222}
WS_PORT=${SIM_WS_PORT:-19222}
NODES=(sim nav planner explore)
if [ "${SIM_BODY:-}" = "1" ]; then
  NODES+=(safety power)
fi
PYTHON=(uv run --no-project --python 3.10 --with numpy --with numba --with pydantic --with nats-py python)

nats_server() {
  if command -v nats-server > /dev/null; then
    command -v nats-server
    return
  fi
  local bin="$HOME/.cache/rabbit/nats-server"
  if [ ! -x "$bin" ]; then
    local version arch
    version=$(curl -fsSL https://api.github.com/repos/nats-io/nats-server/releases/latest | python3 -c "import json, sys; print(json.load(sys.stdin)['tag_name'])")
    arch=$(uname -m | sed 's/x86_64/amd64/')
    mkdir -p "$(dirname "$bin")"
    curl -fsSL "https://github.com/nats-io/nats-server/releases/download/$version/nats-server-$version-darwin-$arch.tar.gz" | tar xz -C "$(dirname "$bin")" --strip-components 1 "nats-server-$version-darwin-$arch/nats-server"
  fi
  echo "$bin"
}

launch() {
  (cd "$ROOT/workspaces/rabbit" && RABBIT_HW=fake RABBIT_BOOT_ID=$(cat "$RUN/boot_id" 2> /dev/null) NATS_URL="nats://127.0.0.1:$PORT" PYTHONPATH=src exec nohup "${PYTHON[@]}" "src/node/$1.py") > "$RUN/$1.log" 2>&1 < /dev/null &
  echo $! > "$RUN/$1.pid"
}

restart() {
  local pidfile="$RUN/$1.pid"
  if [ -e "$pidfile" ]; then
    pkill -P "$(cat "$pidfile")" 2> /dev/null || true
    kill "$(cat "$pidfile")" 2> /dev/null || true
  fi
  launch "$1"
}

start() {
  mkdir -p "$RUN"
  echo "sim-$(date -u +%Y%m%d-%H%M%S)" > "$RUN/boot_id"
  cat > "$RUN/nats.conf" <<EOF
port: $PORT
max_payload: 64MB
jetstream { store_dir: "$RUN/jetstream" }
websocket { port: $WS_PORT, no_tls: true, same_origin: false }
EOF
  nohup "$(nats_server)" -c "$RUN/nats.conf" > "$RUN/nats.log" 2>&1 < /dev/null &
  echo $! > "$RUN/nats.pid"
  export NATS_URL="nats://127.0.0.1:$PORT"
  (cd "$ROOT/workspaces/rabbit" && PYTHONPATH=src "${PYTHON[@]}" -c "
import asyncio, nats
from nats.js.api import StreamConfig
async def main():
    for _ in range(50):
        try:
            nc = await nats.connect('$NATS_URL')
            break
        except Exception:
            await asyncio.sleep(0.2)
    js = nc.jetstream()
    await js.create_key_value(bucket='rabbit')
    await js.add_stream(StreamConfig(name='LOGS', subjects=['rabbit.log.>'], max_age=3600))
    await nc.close()
asyncio.run(main())
")
  for node in "${NODES[@]}"; do
    launch "$node"
  done
  if [ "${1:-}" = "--hud" ]; then
    (cd "$ROOT/workspaces/web" && VITE_NATS_URL="ws://localhost:$WS_PORT" exec nohup node ../../.yarn/releases/yarn-4.9.3.cjs dev) > "$RUN/hud.log" 2>&1 < /dev/null &
    echo $! > "$RUN/hud.pid"
  fi
  echo "NATS on $NATS_URL (websocket ws://localhost:$WS_PORT), logs in $RUN"
}

stop() {
  local pids=()
  for pidfile in "$RUN"/*.pid; do
    [ -e "$pidfile" ] || continue
    [ "$(basename "$pidfile")" = nats.pid ] && continue
    pids+=("$(cat "$pidfile")" $(pgrep -P "$(cat "$pidfile")" || true))
    rm -f "$pidfile"
  done
  if [ ${#pids[@]} -gt 0 ]; then
    kill "${pids[@]}" 2> /dev/null || true
    for _ in $(seq 50); do
      local alive=0
      for pid in "${pids[@]}"; do
        kill -0 "$pid" 2> /dev/null && alive=1
      done
      [ "$alive" = 1 ] || break
      sleep 0.1
    done
    kill -9 "${pids[@]}" 2> /dev/null || true
  fi
  if [ -e "$RUN/nats.pid" ]; then
    kill "$(cat "$RUN/nats.pid")" 2> /dev/null || true
    rm -f "$RUN/nats.pid"
  fi
  rm -rf "$RUN/jetstream"
}

status() {
  for pidfile in "$RUN"/*.pid; do
    [ -e "$pidfile" ] || continue
    name=$(basename "$pidfile" .pid)
    if kill -0 "$(cat "$pidfile")" 2> /dev/null; then echo "$name running"; else echo "$name stopped"; fi
  done
}

case "${1:-}" in
  start) shift; start "$@" ;;
  restart) restart "${2:?node name, e.g. sim}" ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 start [--hud] | restart <node> | stop | status" >&2; exit 2 ;;
esac
