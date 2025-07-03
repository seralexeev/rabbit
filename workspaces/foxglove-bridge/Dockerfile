FROM ros:jazzy-ros-base

SHELL ["/bin/bash", "-c"]

RUN apt-get update
RUN apt-get install -y \
    ros-$ROS_DISTRO-foxglove-bridge
RUN rm -rf /var/lib/apt/lists/*

WORKDIR /ros2_ws
COPY ./ros2_ws/src /ros2_ws/src
COPY ./foxglove-bridge/entrypoint.sh /ros2_ws/entrypoint.sh

RUN <<EOF
    source /opt/ros/jazzy/setup.bash
    colcon build
EOF

CMD ["bash", "/ros2_ws/entrypoint.sh"]
