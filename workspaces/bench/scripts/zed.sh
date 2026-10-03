#!/usr/bin/env bash
# Runs a command in a bench image on the robot, niced and memory-limited, with a guard that kills the
# container when the host's MemAvailable drops below BENCH_MIN_AVAIL_MB, and samples the container's
# GPU memory (nvmap, Jetson unified memory) once a second; the peak goes to stderr and BENCH_GPU_LOG.
# Usage on the robot: /root/bench/src/scripts/zed.sh python /bench/src/zed_dump/zed_dump.py ...
set -uo pipefail
IMAGE=${BENCH_IMAGE:-rabbit-bench}
MIN=${BENCH_MIN_AVAIL_MB:-350}
NAME=bench-$$
GPU_ARGS=()
[ "${BENCH_NO_GPU:-0}" = 1 ] || GPU_ARGS=(--runtime nvidia -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all)

guard() {
  local peak=0 low=999999
  sleep 1
  while docker inspect "$NAME" > /dev/null 2>&1; do
    local avail pids gpu
    avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
    [ "$avail" -lt "$low" ] && low=$avail
    if [ "$avail" -lt "$MIN" ]; then
      echo "memguard: MemAvailable ${avail} MB < ${MIN} MB, killing $NAME" >&2
      docker kill "$NAME" > /dev/null 2>&1
      break
    fi
    pids=$(docker top "$NAME" -eo pid 2> /dev/null | tail -n +2 | tr '\n' ' ')
    gpu=$(awk -v pids=" $pids " '$1=="user" && index(pids, " "$3" ") {gsub("K","",$4); s+=$4} END {print int(s/1024)}' \
      /sys/kernel/debug/nvmap/iovmm/clients 2> /dev/null)
    [ "${gpu:-0}" -gt "$peak" ] && peak=$gpu
    sleep 1
  done
  echo "gpu_peak_mb=$peak host_mem_available_min_mb=$low" >&2
  [ -n "${BENCH_GPU_LOG:-}" ] && echo "{\"gpu_peak_mb\": $peak, \"host_mem_available_min_mb\": $low}" > "$BENCH_GPU_LOG"
}

guard &
GUARD=$!
nice -n 19 ionice -c3 docker run --rm "${GPU_ARGS[@]}" --memory "${BENCH_MEMORY:-2g}" --name "$NAME" \
  -v /root/bench:/bench \
  -v /root/rabbit/workspaces/rabbit/data/svo:/svo:ro \
  -v /root/bench/zed/resources:/usr/local/zed/resources \
  -v /root/bench/zed/settings:/usr/local/zed/settings \
  -w /bench --entrypoint nice "$IMAGE" -n 19 "$@"
RC=$?
wait $GUARD
exit $RC
