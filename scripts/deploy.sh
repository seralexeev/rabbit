#!/usr/bin/env bash
set -euo pipefail

HOST="${RABBIT_HOST:-root@192.168.1.53}"
REMOTE="${RABBIT_REMOTE:-/root/rabbit/workspaces}"
KEY="${RABBIT_SSH_KEY:-$HOME/.ssh/rabbit_id_rsa}"
SSH=(ssh)
if [[ -f "$KEY" ]]; then
    SSH+=(-i "$KEY")
fi

if [[ "${1:-}" == "--body" ]]; then
    shift
    BODY_HOST="${RABBIT_BODY_HOST:-root@rabbit-body.local}"
    ROOT="$(cd "$(dirname "$0")/../workspaces" && pwd)"
    if [[ "${1:-}" == "--build" ]]; then
        shift
        docker build --platform linux/arm64 -f "$ROOT/rabbit/docker/Dockerfile.body" -t rabbit-body "$ROOT/rabbit"
        docker save rabbit-body | zstd -T0 | "${SSH[@]}" "$BODY_HOST" 'zstd -d | docker load'
    fi
    git -C "$ROOT/.." describe --always --dirty > "$ROOT/rabbit/REVISION"
    rsync -az -e "${SSH[*]}" \
        --exclude '__pycache__' --exclude '.venv' --exclude 'data/' --exclude '.pytest_cache' --exclude '.ruff_cache' --exclude 'nats-data' \
        "$ROOT/body" "$ROOT/nats" "$ROOT/rabbit" "$BODY_HOST:$REMOTE/"
    CONTAINERS=""
    for service in "$@"; do
        [[ "$service" == rabbit-power ]] || CONTAINERS="$CONTAINERS $service"
    done
    if [[ $# -eq 0 || -n "$CONTAINERS" ]]; then
        TARGETS="${CONTAINERS:-\$(docker compose -f body/compose.yaml config --services | grep -E '^rabbit-')}"
        "${SSH[@]}" "$BODY_HOST" "cd $REMOTE && docker compose -f body/compose.yaml up -d nats nats-init && docker compose -f body/compose.yaml up -d --no-deps --force-recreate $TARGETS"
    fi
    if [[ $# -eq 0 || " $* " == *" rabbit-power "* ]]; then
        "${SSH[@]}" "$BODY_HOST" "install -m 644 $REMOTE/body/rabbit-power.service /etc/systemd/system/ && systemctl daemon-reload && systemctl restart rabbit-power"
    fi
    exit 0
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
