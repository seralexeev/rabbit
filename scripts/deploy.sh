#!/usr/bin/env bash
set -euo pipefail

HOST="${RABBIT_HOST:-root@192.168.1.53}"
REMOTE="${RABBIT_REMOTE:-/root/rabbit/workspaces}"
KEY="${RABBIT_SSH_KEY:-$HOME/.ssh/rabbit_id_rsa}"
SSH=(ssh)
if [[ -f "$KEY" ]]; then
    SSH+=(-i "$KEY")
fi

BUILD=""
if [[ "${1:-}" == "--build" ]]; then
    BUILD="--build"
    shift
fi

ROOT="$(cd "$(dirname "$0")/../workspaces" && pwd)"

if [[ $# -eq 0 || " $* " == *" rabbit-web "* ]]; then
    (cd "$ROOT/web" && VITE_CHAT_URL= VITE_NATS_URL= node ../../.yarn/releases/yarn-4.9.3.cjs vite build --logLevel warn)
fi

git -C "$ROOT/.." describe --always --dirty > "$ROOT/rabbit/REVISION"
rsync -az -e "${SSH[*]}" \
    --exclude '__pycache__' --exclude '.venv' --exclude 'data/' --exclude '.pytest_cache' --exclude '.ruff_cache' \
    --exclude 'node_modules' --exclude '.env' --exclude 'dead_letters' --exclude 'alloy-presentation-*' \
    "$ROOT/compose.yaml" "$ROOT/nats" "$ROOT/rabbit" "$ROOT/forge" "$HOST:$REMOTE/"
"${SSH[@]}" "$HOST" "mkdir -p $REMOTE/web/dist $REMOTE/links && touch $REMOTE/links/links.map"
rsync -az -e "${SSH[*]}" "$ROOT/web/nginx.conf" "$HOST:$REMOTE/web/"
rsync -az --delete -e "${SSH[*]}" "$ROOT/web/dist/" "$HOST:$REMOTE/web/dist/"

SERVICES="${*:-\$(docker compose config --services | grep -E '^(rabbit-|forge-writer|forge-chat)')}"
"${SSH[@]}" "$HOST" "cd $REMOTE && docker compose up -d $BUILD --remove-orphans && docker compose up -d --no-deps --force-recreate $SERVICES"
"${SSH[@]}" "$HOST" "docker image prune -f | tail -1"
