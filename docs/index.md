# Introduction

Open AD Kit adopts a modular, component-based architecture designed for flexibility, scalability, and platform independence. It leverages cloud-native principles and containerization to decompose [Autoware](https://github.com/autowarefoundation/autoware) into a collection of interoperable components. This approach allows developers to create customized autonomous driving (AD) systems by combining components to meet their specific needs.

## Architecture

The Autoware Foundation is a voting member of the [SOAFEE (Scalable Open Architecture For the Embedded Edge)](https://soafee.io/) initiative, as the **Autoware Open AD Kit is the first SOAFEE blueprint for the software defined vehicle ecosystem**.

![Soafee Architecture](assets/images/openadkit.drawio.png)

## Deployments

A **deployment** is a running instance of Open AD Kit, a specific combination of **Autoware components** configured to achieve a particular task, such as a simulation or a full autonomous driving stack.

Deployments are defined using container orchestration files (e.g., `docker-compose.yaml`). This makes them portable and easy to reproduce across different environments, from a developer's laptop to edge devices in a vehicle. This container-based approach is a cornerstone of the Open AD Kit's cloud-native and platform-agnostic philosophy, aligning with standards like SOAFEE.

This modular structure allows users to start with a minimal deployment and incrementally add components and tools as their system evolves.

For more details, see the [Deployments](./deployments/index.md).

## Components

The core functional components of the Open AD Kit are derived from the main **[Autoware](https://github.com/autowarefoundation/autoware)** project. Each image packages a focused part of the autonomous driving pipeline, which makes it possible to compose different AD systems from a common container set.

The primary images include:

- **Sensing and Perception**: Collects and processes sensor data.
- **Localization and Mapping**: Manages maps and vehicle pose estimation.
- **Planning and Control**: Produces and follows the driving trajectory.
- **Vehicle and System**: Packages vehicle interfaces and system-level services in the `vehicle-system` image.
- **API**: Offers an interface for external systems to interact with the vehicle.
- **Simulator**: Allows testing the AD stack in a virtual environment.
- **Visualizer**: Provides a browser-accessible RViz environment for remote inspection.

These images communicate through ROS 2 middleware, and some deployments bridge isolated environments with Zenoh. For more details, see the [Autoware components](./components/index.md).

## Tools

In addition to the **Autoware components**, Open AD Kit provides essential tools for development, simulation, and visualization. These tools are also containerized and can be integrated into deployments as needed.

- **Scenario Simulator**: Runs scenario-based simulations for validation, CI, and local development.

For more details, see the [Tools](./tools/index.md).

## Supported Platforms

Open AD Kit currently documents Ubuntu as the primary development host and AutoSD as the platform-specific deployment path available in this repository. EWAOL is planned but does not yet ship runnable assets here.

### Development platforms

- Ubuntu 22.04, 24.04

### Platform-specific deployment paths

- [AutoSD](https://docs.centos.org/automotive-sig-documentation/features-and-concepts/)
- [EWAOL](https://ewaol.docs.arm.com/en/kirkstone-dev/) (planned)

For more details, see the [Supported SOAFEE Platforms](./platforms/index.md).

## Supported Hardware

For detailed information on system requirements, tested hardware, and cloud instances, please refer to the [Hardware](./hardware/index.md) section.
