#!/usr/bin/env bash
# Runs a command in the rabbit-rtabmap image on the robot (see zed.sh for limits and the memory guard).
# Usage on the robot: /root/bench/src/scripts/rtab.sh rtab_run --dump /bench/data/loop1 ...
BENCH_IMAGE=rabbit-rtabmap BENCH_NO_GPU=1 exec "$(dirname "$0")/zed.sh" "$@"
