# Introduction

Open AD Kit adopts a modular, component-based architecture designed for flexibility, scalability, and platform independence. It leverages cloud-native principles and containerization to decompose the [Autoware Universe](https://github.com/autowarefoundation/autoware) into a collection of interoperable components. This approach allows developers to create customized autonomous driving (AD) systems by combining components to meet their specific needs.

## Architecture

The Autoware Foundation is a voting member of the [SOAFEE (Scalable Open Architecture For the Embedded Edge)](https://soafee.io/) initiative, as the Autoware Open AD Kit is the first SOAFEE blueprint for the software defined vehicle ecosystem.

![Soafee Architecture](assets/images/soafee_architecture.drawio.png)

At the heart of the Open AD Kit are two main types of components: **Autoware Components** and **Tools**.

## Components

The core functional components of the Open AD Kit are derived from the main **[Autoware Universe](https://github.com/autowarefoundation/autoware_universe)** project. Each component is packaged as an independent containerized component, responsible for a specific aspect of the autonomous driving pipeline. This modular approach provides flexibility in composing different AD systems by combining different components.

The primary components include:

- **Sensing**: Collects data from various sensors (Cameras, Lidars, Radars).
- **Perception**: Processes sensor data to detect and track objects in the environment.
- **Mapping**: Creates and maintains maps of the environment.
- **Localization**: Determines the vehicle's position within the map.
- **Planning**: Plans the vehicle's trajectory from its current location to a destination.
- **Control**: Sends commands to the vehicle's actuators to follow the planned trajectory.
- **Vehicle**: Manages the vehicle's internal state and interface.
- **System**: Provides system-level functionalities like health monitoring.
- **API**: Offers an interface for external systems to interact with the vehicle.
- **Simulator**: Allows for testing the AD stack in a virtual environment with ad-hoc simulations.

These components communicate with each other over a service mesh, allowing for flexible deployment and scaling. For more details, see the [Autoware components](./components/).

## Tools

In addition to the **Autoware components**, Open AD Kit provides essential tools for development, simulation, and visualization. These tools are also containerized and can be integrated into deployments as needed.

- **Scenario Simulator-TBD**: Allows for testing the AD stack in a virtual environment. It supports complex scenario-based simulations for validation and CI/CD.

For more details, see the [Tools](./tools/).

## Deployments

A **deployment** is a running instance of Open AD Kit, a specific combination of **Autoware components** configured to achieve a particular task, such as a simulation or a full autonomous driving stack.

Deployments are defined using container orchestration files (e.g., `docker-compose.yaml`). This makes them portable and easy to reproduce across different environments, from a developer's laptop to edge devices in a vehicle. This container-based approach is a cornerstone of the Open AD Kit's cloud-native and platform-agnostic philosophy, aligning with standards like SOAFEE.

This modular structure allows users to start with a minimal deployment and incrementally add components and tools as their system evolves.

For more details, see the [Deployments](./deployments/).

## Supported Platforms

Open AD Kit supports a variety of platforms as **development** and **SOAFEE production** platforms.

### Development platforms

- Ubuntu 22.04, 24.04

### SOAFEE Production platforms

- [EWAOL](https://ewaol.docs.arm.com/en/kirkstone-dev/)
- [AutoSD](https://docs.centos.org/automotive-sig-documentation/features-and-concepts/)

For more details, see the [Supported SOAFEE Platforms](./platforms/).

## Supported Hardware

For detailed information on system requirements, tested hardware, and cloud instances, please refer to the [Hardware](./hardware/) section.
