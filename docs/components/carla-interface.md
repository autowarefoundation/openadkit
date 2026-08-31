# CARLA Interface

The `carla-interface` image packages `autoware_carla_interface`, translating
Autoware control commands to CARLA and CARLA sensor data to ROS 2 messages.

!!! note "Platform support"
    The image is published for amd64 + Humble only. The bridge itself does not
    require a GPU, but the complete CARLA deployment needs an NVIDIA GPU for the
    CARLA server **and** defaults to the amd64 `sensing-perception-cuda`
    Autoware image for perception.

It provides:

- CARLA world initialization and synchronous simulation
- Ego vehicle spawning and sensor-kit configuration
- Camera, LiDAR, IMU, and GNSS message translation
- Vehicle command calibration
- Traffic light state publication
- Lightweight sensor mappings for constrained hosts
- Launch file: `autoware_carla_interface.launch.xml`

See the [CARLA Simulation deployment](../deployment/carla-simulation/index.md)
for `./openadkit run carla-simulation --gpu`.
