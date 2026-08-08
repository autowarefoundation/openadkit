# Vehicle and System

The `vehicle-system` image supplies vehicle actuation and system diagnostics.
Deployments run these responsibilities as separate containers from the same
image.

## Vehicle Services

- Vehicle actuation and state reporting
- Steering, throttle, brake, gear, and turn-signal conversion
- Vehicle dimensions, limits, and kinematic parameters
- Launch file: `tier4_vehicle_launch/vehicle.launch.xml`

## System Services

- Health monitoring and heartbeat management
- Diagnostic aggregation
- Minimum Risk Maneuver emergency handling
- CPU, memory, and process monitoring
- Launch file: `tier4_system_component.launch.xml`

| | Vehicle | System |
|---|---|---|
| Purpose | Communicates with real or simulated vehicle hardware | Monitors the Autoware stack |
| Outputs | Actuation commands and vehicle state | Diagnostics, health, and emergency state |
| Typical configuration | Vehicle model and interface | Monitor enablement and run mode |
