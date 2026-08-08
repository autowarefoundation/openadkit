# Simulator

The `simulator` image provides closed-loop vehicle and environment simulation
without real sensors or vehicle hardware. It includes:

- Configurable kinematic and dynamic vehicle models
- Dummy perception and vehicle interfaces
- Dummy doors and traffic infrastructure
- Scenario Simulator v2 adapter
- Localization simulation mode
- Simulated point cloud preprocessing
- Object tracking, shape estimation, and map-based prediction
- Occupancy and elevation map handling
- Vehicle command conversion
- Launch file: `tier4_simulator_component.launch.xml`

`carla-interface` builds on this image for CARLA-specific sensor and control
translation.
