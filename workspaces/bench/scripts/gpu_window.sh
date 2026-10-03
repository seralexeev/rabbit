#!/usr/bin/env bash
# Everything that needs the Jetson's GPU or measures Jetson timing, for a scheduled window
# (ideally with rabbit-zed stopped). Runs on the robot:
#   nohup /root/bench/src/scripts/gpu_window.sh [cuvslam|loc|rtab|depth ...] > /root/bench/results/window.log 2>&1 &
# Prerequisites: scripts/sync.sh, maps/ and results/ synced from the Mac (see README), images rabbit-bench and
# rabbit-rtabmap on the robot.
set -u
Z=/root/bench/src/scripts/zed.sh
RT=/root/bench/src/scripts/rtab.sh
C=/bench/src/cuvslam/run_cuvslam.py
STEPS=${*:-cuvslam loc rtab depth}
step() { echo "== $(date -u +%T) $* (MemAvailable $(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo) MB)"; }
gpu() { echo "/root/bench/results/$1_gpu.json"; }

for s in $STEPS; do case $s in
session:*)
  # session:NAME[:QUERY1,QUERY2] — dump NAME.svo2, cuVSLAM odometry, a ZED GEN_3 area from it and ZED
  # relocalization of the QUERY sessions against that area.
  IFS=: read -r _ name queries <<< "$s"
  step dump $name
  $Z python /bench/src/zed_dump/zed_dump.py /svo/$name.svo2 /bench/data/$name --images --depth neural_light
  mkdir -p /root/bench/results/$name /root/bench/results/zed_areas
  cp /root/bench/data/$name/zed_vio.txt /root/bench/data/$name/meta.json /root/bench/results/$name/
  for m in stereo inertial; do
    step cuvslam $name $m
    BENCH_GPU_LOG=$(gpu $name/cuvslam_$m) $Z python $C /bench/data/$name /bench/results/$name/cuvslam_$m --mode $m
  done
  step zed area $name
  $Z python /bench/src/zed_dump/zed_dump.py /svo/$name.svo2 /bench/results/zed_areas/$name --tracking map \
    --area /bench/results/zed_areas/$name.area
  cp /root/bench/results/zed_areas/$name/zed_map.txt /root/bench/results/$name/zed_map.txt
  for q in ${queries//,/ }; do
    step zed reloc $q in $name
    $Z python /bench/src/zed_dump/zed_dump.py /svo/$q.svo2 /bench/results/zed_areas/${q}_in_$name --tracking reloc \
      --area /bench/results/zed_areas/$name.area
    cp /root/bench/results/zed_areas/${q}_in_$name/zed_reloc_status.csv /root/bench/results/$q/zed_reloc_in_${name}_status.csv
    cp /root/bench/results/zed_areas/${q}_in_$name/zed_reloc.txt /root/bench/results/$q/zed_reloc_in_${name}.txt
  done ;;
cuvslam)
  for x in loop1 loop2; do
    for m in stereo inertial; do
      step cuvslam $x $m
      BENCH_GPU_LOG=$(gpu $x/cuvslam_$m) $Z python $C /bench/data/$x /bench/results/$x/cuvslam_$m --mode $m
      step cuvslam $x $m async
      BENCH_GPU_LOG=$(gpu $x/cuvslam_${m}_async) $Z python $C /bench/data/$x /bench/results/$x/cuvslam_${m}_async \
        --mode $m --async-sba
    done
    step cuvslam $x slam
    BENCH_GPU_LOG=$(gpu $x/cuvslam_inertial_slam) $Z python $C /bench/data/$x /bench/results/$x/cuvslam_inertial_slam \
      --mode inertial --slam --save-map /bench/results/$x/cuvslam_map
  done ;;
loc)
  for pair in "loop2 loop1 1.0" "loop1 loop2 5.0"; do
    set -- $pair
    a=$1 b=$2 start=$3
    prior=/bench/results/$a/rtab_loc_in_${b}_cuvslam_inertial_poses.txt
    for v in "exact 0 0 1.0" "noisy 0.5 20 1.0" "noisier 1.0 45 1.5"; do
      set -- $v
      step cuvslam localize $a in $b prior $1
      $Z python $C /bench/data/$a /bench/results/$a/cuvslam_loc_in_${b}_$1 --mode inertial \
        --localize /bench/results/$b/cuvslam_map --guess "$prior" --guess-noise $2 $3 --loc-radius $4 \
        --loc-start $start --loc-retry 2
    done
    step cuvslam localize $a in $b blind
    $Z python $C /bench/data/$a /bench/results/$a/cuvslam_loc_in_${b}_blind --mode inertial \
      --localize /bench/results/$b/cuvslam_map --guess "0 0 0 0 0 0 1" --loc-radius 2.0 --loc-angle-deg 15 \
      --loc-start 0.5 --loc-retry 3
  done ;;
rtab)
  step rtab jetson localization loop2 in loop1
  $RT rtab_run --dump /bench/data/loop2 --odom /bench/data/loop2/zed_vio.txt --db /bench/maps/loop1_vio.db \
    --out /bench/results/loop2/rtab_jetson_loc_in_loop1_vio --mode localization --rate 2
  step rtab jetson mapping loop2
  $RT rtab_run --dump /bench/data/loop2 --odom /bench/data/loop2/zed_vio.txt --db /bench/maps/jetson_loop2_vio.db \
    --fresh --out /bench/results/loop2/rtab_jetson_map_vio --mode mapping --rate 2 ;;
depth)
  mkdir -p /root/bench/results/depth
  for cfg in "neural_light fp16" "neural fp16" "neural int8" "neural_plus fp16"; do
    set -- $cfg
    step depth $1 $2
    BENCH_MEMORY=3g BENCH_GPU_LOG=$(gpu depth/loop1_$1_$2) $Z python /bench/src/zed_dump/depth_bench.py \
      /svo/loop1.svo2 /bench/results/depth/loop1_$1_$2.json --mode $1 --precision $2 --static 0:50
  done ;;
esac; done
step done
