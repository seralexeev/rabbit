cmake_minimum_required(VERSION 3.8)
project(rabbit)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

set(msg_files
  "msg/SensorReading.msg"
)

rosidl_generate_interfaces(${PROJECT_NAME}
  ${msg_files}
  DEPENDENCIES std_msgs
)

# Install Python scripts
install(PROGRAMS
  rabbit/power_sensor.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME power_sensor
)

ament_export_dependencies(rosidl_default_runtime)

ament_package()
