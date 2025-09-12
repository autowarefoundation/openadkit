# Services

Open AD Kit is a micro-service based project, which means that it is designed to be deployed on a variety of platforms with microservices architecture. Each service is designed to be independent and can be deployed on a variety of platforms.

![Granular Services](../assets/images/granular-services.png)

## Autoware Services

### Sensing

The sensing service is responsible for collecting data from the vehicle's sensors. Sensing service can be configured to collect data from a variety of sensors, including **cameras, lidars, and radars**. For more details on the [Autoware sensing design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture/sensing/).

### Perception

The perception service is responsible for processing the data from the vehicle's sensors and creating a map of the environment. Perception service can be configured to use a variety of perception algorithms, including **object detection, tracking, and mapping**. For more details on the [Autoware perception design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture/perception/).

### Mapping

The mapping service is responsible for creating a map of the environment. Mapping service can be configured to use a variety of mapping algorithms, including **occupancy grid mapping and point cloud mapping**. For more details on the [Autoware mapping design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture/mapping/).

### Localization

The localization service is responsible for determining the vehicle's position in the map. Localization service can be configured to use a variety of localization algorithms, including **GPS, IMU, and visual odometry**. For more details on the [Autoware localization design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture/localization/).

### Planning

The planning service is responsible for planning the vehicle's path. Planning service can be configured to use a variety of planning algorithms, including **Route Planning, Goal Planning, and Behavior Planning**. For more details on the [Autoware planning design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture/planning/).

### Control

The control service is responsible for controlling the vehicle's actuators. Control service can be configured to use a variety of control algorithms, including **PID and MPC**. For more details on the [Autoware control design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture/control/).

### Vehicle

The vehicle service is responsible for managing the vehicle's state. Vehicle service can be configured to use a variety of vehicle algorithms, including **vehicle state estimation and vehicle control**. For more details on the [Autoware vehicle design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture/vehicle/).

### System

The system service is responsible for managing the vehicle's system. System service can be configured to use a variety of system algorithms, including **system health monitoring and system error handling**. For more details on the [Autoware system design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture/system/).

### API

The API service is responsible for providing [AD API](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-interfaces/ad-api/) interface for the vehicle's state. API service can be configured to enable/disable various interfaces. For more details on the [Autoware interfaces design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-interfaces/).
