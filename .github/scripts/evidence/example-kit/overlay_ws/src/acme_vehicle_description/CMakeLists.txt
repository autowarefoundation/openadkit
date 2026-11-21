cmake_minimum_required(VERSION 3.8)
project(acme_vehicle_description)

find_package(ament_cmake REQUIRED)

install(DIRECTORY config urdf DESTINATION share/${PROJECT_NAME})

ament_package()
