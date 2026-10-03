cmake_minimum_required(VERSION 3.22)
project(rabbit_rtabmap LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(Python 3.12 EXACT COMPONENTS Interpreter Development.Module REQUIRED)
find_package(nanobind CONFIG REQUIRED)
find_package(RTABMap REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgcodecs)

nanobind_add_module(rabbit_rtabmap NB_STATIC module.cpp)
target_link_libraries(rabbit_rtabmap PRIVATE rtabmap::core ${OpenCV_LIBS})
set_target_properties(rabbit_rtabmap PROPERTIES INSTALL_RPATH "$ORIGIN/lib" BUILD_WITH_INSTALL_RPATH ON)
install(TARGETS rabbit_rtabmap LIBRARY DESTINATION .)
