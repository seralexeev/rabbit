#!/usr/bin/env bash
# RTAB-Map suite over two sessions A and B: map each, localize each in the other's map, merge B into A.
# Odometry: ZED VIO (zed_vio.txt from the dump) and cuVSLAM (results/<s>/cuvslam_<ODOM>_odom.txt).
# Usage: rtab_suite.sh A B [RATE]
#   On the Mac:  RUN="docker run --rm -v $HOME/projects/rabbit/data/offline/bench:/bench rabbit-rtabmap" scripts/rtab_suite.sh loop1 loop2
#   On the robot: RUN=/root/bench/src/scripts/rtab.sh /root/bench/src/scripts/rtab_suite.sh loop1 loop2
set -euo pipefail
A=$1 B=$2 RATE=${3:-2}
RUN=${RUN:?set RUN to the container prefix}
ODOMS=${ODOMS:-"vio cuvslam_stereo"}
EXTRA=${RTAB_PARAMS:-}

odom_file() { [ "$2" = vio ] && echo "/bench/data/$1/zed_vio.txt" || echo "/bench/results/$1/$2_odom.txt"; }

for o in $ODOMS; do
  for s in "$A" "$B"; do
    $RUN rtab_run --dump /bench/data/$s --odom "$(odom_file $s $o)" --db /bench/maps/${s}_$o.db --fresh \
      --out /bench/results/$s/rtab_map_$o --mode mapping --rate "$RATE" $EXTRA > /dev/null
  done
  for pair in "$A $B" "$B $A"; do
    set -- $pair
    $RUN rtab_run --dump /bench/data/$1 --odom "$(odom_file $1 $o)" --db /bench/maps/${2}_$o.db \
      --out /bench/results/$1/rtab_loc_in_${2}_$o --mode localization --rate "$RATE" $EXTRA > /dev/null
  done
  $RUN cp /bench/maps/${A}_$o.db /bench/maps/${A}+${B}_$o.db
  $RUN rtab_run --dump /bench/data/$B --odom "$(odom_file $B $o)" --db /bench/maps/${A}+${B}_$o.db \
    --out /bench/results/$B/rtab_merge_into_${A}_$o --mode mapping --rate "$RATE" $EXTRA > /dev/null
done
