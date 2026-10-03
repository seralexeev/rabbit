#!/usr/bin/env bash
set -euo pipefail

HOST="${RABBIT_HOST:-root@192.168.1.53}"
REMOTE="${RABBIT_REMOTE:-/root/rabbit/workspaces}"
KEY="${RABBIT_SSH_KEY:-$HOME/.ssh/rabbit_id_rsa}"
PUBLIC_URL="${RABBIT_PUBLIC_URL:-https://live.rabbit0.dev}"
SSH=(ssh)
if [[ -f "$KEY" ]]; then
    SSH+=(-i "$KEY")
fi

MAP="$REMOTE/links/links.map"
RELOAD="docker exec rabbit-web nginx -s reload 2>&1 | grep -v 'signal process started' || true"

usage() {
    echo "usage: $0 [list] | add <name> | rm <name>" >&2
    exit 1
}

check_name() {
    [[ "${1:-}" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "name must match [A-Za-z0-9_-]+" >&2; exit 1; }
}

case "${1:-list}" in
list)
    "${SSH[@]}" "$HOST" "cat $MAP 2>/dev/null" | awk -v url="$PUBLIC_URL" \
        '{ sub(";", "", $2); printf "%-20s %-12s %s/k/%s\n", $2, $4, url, $1 }'
    ;;
add)
    check_name "${2:-}"
    TOKEN="$(openssl rand -hex 16)"
    "${SSH[@]}" "$HOST" "mkdir -p $REMOTE/links && touch $MAP \
        && if grep -q ' $2;' $MAP; then echo 'link $2 already exists' >&2; exit 1; fi \
        && echo '$TOKEN $2; # $(date +%F)' >> $MAP && $RELOAD"
    echo "$PUBLIC_URL/k/$TOKEN"
    ;;
rm)
    check_name "${2:-}"
    "${SSH[@]}" "$HOST" "grep -q ' $2;' $MAP || { echo 'no link $2' >&2; exit 1; } \
        && sed -i '/ $2;/d' $MAP && $RELOAD"
    echo "removed $2"
    ;;
*)
    usage
    ;;
esac
