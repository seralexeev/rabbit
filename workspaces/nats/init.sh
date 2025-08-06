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