#!/bin/bash

set -e

SERVER_URL="nats://nats:4222"
BUCKET="rabbit"
STREAM_NAME="KV_$BUCKET"

sleep 3

if nats stream info "$STREAM_NAME" --server="$SERVER_URL" > /dev/null 2>&1; then
  echo "KV bucket '$BUCKET' already exists"
else
  echo "🆕 Creating KV bucket '$BUCKET'..."
  nats kv add "$BUCKET" --server="$SERVER_URL" --marker-ttl "1y"
fi
if nats stream info LOGS --server="$SERVER_URL" > /dev/null 2>&1; then
  echo "Stream 'LOGS' already exists"
else
  echo "Creating stream 'LOGS'..."
  nats stream add LOGS --server="$SERVER_URL" --subjects "rabbit.log.>" --storage file --compression s2 \
    --retention limits --discard old --max-age 7d --max-bytes 2GB --max-msg-size 1MB --dupe-window 2m \
    --replicas 1 --defaults
fi
