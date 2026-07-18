# Planning & Control

The `planning-control` image packages trajectory generation and vehicle control.
Deployments run them as separate containers from the same image.

## Planning

- Route planning on Lanelet2 road networks
- Behavior planning for lanes, intersections, and obstacles
- Kinematically feasible motion planning
- Goal and parking maneuvers
- Emergency fallback trajectories
- Launch file: `tier4_planning_component.launch.xml`

## Control

- Lateral steering and longitudinal velocity control
- PID and Model Predictive Control modes
- Vehicle-specific command conversion
- Emergency stop and heartbeat monitoring
- Launch file: `tier4_control_component.launch.xml`
