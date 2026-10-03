#!/usr/bin/env bash
# Maps session MAP with RTAB-Map (if its database is missing), then localizes each QUERY session in it and
# merges each QUERY into a copy of it (multi-session). Same RUN/ODOMS/RTAB_PARAMS as rtab_suite.sh.
# Usage: RUN="docker run --rm -v $HOME/projects/rabbit/data/offline/bench:/bench rabbit-rtabmap" scripts/rtab_against.sh MAP QUERY...
set -euo pipefail
MAP=$1
shift
RUN=${RUN:?set RUN to the container prefix}
ODOMS=${ODOMS:-"vio cuvslam_stereo"}
RATE=${RATE:-2}
EXTRA=${RTAB_PARAMS:-}
ROOT=${BENCH_ROOT:-$HOME/projects/rabbit/data/offline/bench}

odom_file() { [ "$2" = vio ] && echo "/bench/data/$1/zed_vio.txt" || echo "/bench/results/$1/$2_odom.txt"; }

for o in $ODOMS; do
  if [ ! -f "$ROOT/maps/${MAP}_$o.db" ]; then
    $RUN rtab_run --dump /bench/data/$MAP --odom "$(odom_file $MAP $o)" --db /bench/maps/${MAP}_$o.db --fresh \
      --out /bench/results/$MAP/rtab_map_$o --mode mapping --rate "$RATE" $EXTRA > /dev/null
  fi
  for q in "$@"; do
    $RUN rtab_run --dump /bench/data/$q --odom "$(odom_file $q $o)" --db /bench/maps/${MAP}_$o.db \
      --out /bench/results/$q/rtab_loc_in_${MAP}_$o --mode localization --rate "$RATE" $EXTRA > /dev/null
    $RUN cp /bench/maps/${MAP}_$o.db /bench/maps/${MAP}+${q}_$o.db
    $RUN rtab_run --dump /bench/data/$q --odom "$(odom_file $q $o)" --db /bench/maps/${MAP}+${q}_$o.db \
      --out /bench/results/$q/rtab_merge_into_${MAP}_$o --mode mapping --rate "$RATE" $EXTRA > /dev/null
  done
done
