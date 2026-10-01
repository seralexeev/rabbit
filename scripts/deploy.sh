#!/usr/bin/env bash
set -euo pipefail

HOST="${RABBIT_HOST:-root@192.168.1.53}"
REMOTE="${RABBIT_REMOTE:-/root/rabbit/workspaces}"
KEY="${RABBIT_SSH_KEY:-$HOME/.ssh/rabbit_id_rsa}"
SSH=(ssh)
if [[ -f "$KEY" ]]; then
    SSH+=(-i "$KEY")
fi

ROOT="$(cd "$(dirname "$0")/../workspaces" && pwd)"

rsync -az -e "${SSH[*]}" \
    --exclude '__pycache__' --exclude '.venv' --exclude 'data/' --exclude '.pytest_cache' --exclude '.ruff_cache' \
    "$ROOT/compose.yaml" "$ROOT/nats" "$ROOT/rabbit" "$HOST:$REMOTE/"

SERVICES="${*:-\$(docker compose config --services | grep '^rabbit-')}"
"${SSH[@]}" "$HOST" "cd $REMOTE && docker compose up -d --build --remove-orphans && docker compose restart $SERVICES"
