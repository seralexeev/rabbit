#!/usr/bin/env bash
# "Switched on anywhere" simulation: RTAB-Map localization of QUERY in MAP's database started every STEP seconds
# into QUERY, each run limited to WINDOW seconds. Results: results_wake/<query>_in_<map>_<odom>_<offset>*.
# Usage: RUN="docker run --rm -v $HOME/projects/rabbit/data/offline/bench:/bench rabbit-rtabmap" scripts/rtab_wake.sh QUERY MAP [ODOM]
set -euo pipefail
Q=$1 M=$2 O=${3:-vio}
RUN=${RUN:?set RUN to the container prefix}
ROOT=${BENCH_ROOT:-$HOME/projects/rabbit/data/offline/bench}
STEP=${STEP:-5} WINDOW=${WINDOW:-15} RATE=${RATE:-2}
ODOM=$([ "$O" = vio ] && echo "/bench/data/$Q/zed_vio.txt" || echo "/bench/results/$Q/${O}_odom.txt")
mkdir -p "$ROOT/results_wake"
t0=$(sed -n 2p "$ROOT/data/$Q/frames.csv" | cut -d, -f1)
tl=$(tail -1 "$ROOT/data/$Q/frames.csv" | cut -d, -f1)
for ((off = 0; t0 + (off + 5) * 1000000000 < tl; off += STEP)); do
  st=$((t0 + off * 1000000000))
  $RUN rtab_run --dump /bench/data/$Q --odom "$ODOM" --db /bench/maps/${M}_$O.db \
    --out /bench/results_wake/${Q}_in_${M}_${O}_$off --mode localization --rate "$RATE" \
    --start-ns $st --end-ns $((st + WINDOW * 1000000000)) ${RTAB_PARAMS:-} > /dev/null 2>&1
done
