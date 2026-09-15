# API

The `api` image packages the
[Autoware AD API](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-interfaces/ad-api/)
used by fleet managers, HMIs, and scenario runners. It provides ROS 2 services
and topics for:

- Vehicle position, velocity, engage status, and operation mode
- Autonomous, manual, stop, local, and remote mode transitions
- Route and goal setting
- Emergency stop and engage/disengage commands
- Scenario simulation auto-engage and route integration

The component starts with `tier4_autoware_api_component.launch.xml`. It is the
standard external entry point for the modular simulation deployments.
