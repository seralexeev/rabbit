#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ssh rabbit mkdir -p /root/bench/src
rsync -az --delete --exclude data --exclude __pycache__ --exclude build ./ rabbit:/root/bench/src/
ssh rabbit 'mkdir -p /root/bench/data /root/bench/zed && [ -d /root/bench/zed/resources ] || cp -a /root/zed/resources /root/zed/settings /root/bench/zed/'
