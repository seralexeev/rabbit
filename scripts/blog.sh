#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

BLOG=workspaces/blog

count() { grep -c '^id:' "$1" || true; }

case "${1:-}" in
  build)
    [ -d "$BLOG/node_modules" ] || (cd "$BLOG" && npm ci --registry=https://registry.npmjs.org/)
    for f in README.ru.md README.md; do
      before=$(git show "HEAD:$BLOG/$f" 2>/dev/null | grep -c '^id:' || true)
      now=$(count "$BLOG/$f")
      if [ "$now" -lt "$before" ]; then
        echo "$f has $now posts, HEAD has $before: refusing to build" >&2
        exit 1
      fi
    done
    (cd "$BLOG" && OPENAI_API_KEY=unused node src/index.ts | grep -v 'already exists' || true)
    echo "posts: ru $(count "$BLOG/README.ru.md"), en $(count "$BLOG/README.md")"
    ;;
  *)
    echo "usage: scripts/blog.sh build" >&2
    exit 1
    ;;
esac
