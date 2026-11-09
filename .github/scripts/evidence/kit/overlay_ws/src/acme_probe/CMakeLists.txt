cmake_minimum_required(VERSION 3.8)
project(acme_probe)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(diagnostic_updater REQUIRED)

add_executable(probe src/probe.cpp)
ament_target_dependencies(probe rclcpp std_msgs diagnostic_updater)
install(TARGETS probe DESTINATION lib/${PROJECT_NAME})

ament_package()
