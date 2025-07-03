#!/bin/bash

set -e

source /opt/ros/$ROS_DISTRO/setup.bash
source /ros2_ws/install/setup.bash

# Something wrong with install/setup this is a workaround
export AMENT_PREFIX_PATH="/ros2_ws/install/rabbit_interface:$AMENT_PREFIX_PATH"

ros2 launch foxglove_bridge foxglove_bridge_launch.xml
