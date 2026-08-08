# Localization & Mapping

The `localization-mapping` image serves HD maps and estimates the vehicle pose
within them.

## Localization

- GNSS/RTK positioning and IMU dead reckoning
- Visual odometry and LiDAR map matching
- Automatic pose initialization
- EKF state estimation
- Launch file: `tier4_localization_component.launch.xml`

## Mapping

- Lanelet2 vector map and point cloud map serving
- Occupancy grid and point cloud map construction
- Map coordinate transform management
- Launch file: `tier4_map_component.launch.xml`

Planning and Scenario Simulation use this image only for the `map` service; the
simulator supplies map-to-odometry transforms. Logging and CARLA Simulation also
run the localization component.
