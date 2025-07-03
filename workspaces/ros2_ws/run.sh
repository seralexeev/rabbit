set -e

source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 interface show rabbit_interfaces/msg/SensorReading
find install/rabbit_interfaces/lib/ -name '*SensorReading*'

ros2 run rabbit power_sensor
