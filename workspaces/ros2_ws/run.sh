set -e

source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 interface show rabbit/msg/SensorReading
find install/rabbit/lib/ -name '*SensorReading*'

ros2 run rabbit power_sensor
