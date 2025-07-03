FROM ros:jazzy-ros-base

SHELL ["/bin/bash", "-c"]

WORKDIR /ros2_ws
COPY ./src /ros2_ws/src

RUN <<EOF
    source /opt/ros/jazzy/setup.bash
    colcon build
EOF
