FROM ros:jazzy-ros-base

RUN apt-get update

RUN apt-get install -y \
    ros-jazzy-foxglove-bridge

RUN rm -rf /var/lib/apt/lists/*

CMD ["ros2", "launch", "foxglove_bridge", "foxglove_bridge_launch.xml"]
