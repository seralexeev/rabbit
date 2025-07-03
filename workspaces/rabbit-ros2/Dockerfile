FROM ros:jazzy-ros-base

WORKDIR /ros2_ws

COPY ./src src

RUN bash -c "source /opt/ros/jazzy/setup.bash && colcon build"
