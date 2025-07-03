FROM ros:jazzy-ros-base

SHELL ["/bin/bash", "-c"]

WORKDIR /ros2_ws
COPY rabbit_interfaces ./rabbit_interfaces
COPY rabbit ./rabbit
COPY run.sh ./run.sh

RUN <<EOF
    source /opt/ros/jazzy/setup.bash
    colcon build
EOF
