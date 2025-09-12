# Open AD Kit

<div align="center">

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen.svg)](https://autowarefoundation.github.io/openadkit/)
[![Autoware Discord](https://img.shields.io/discord/953808765935816715?logo=discord&logoColor=white&style=flat&label=Autoware)](https://discord.gg/Q94UsPvReQ)
[![Autoware](https://img.shields.io/badge/Linkedin-Autoware-0a66c2?logo=linkedin&logoColor=white&style=flat)](https://www.linkedin.com/company/the-autoware-foundation/)
[![Autoware Twitter / X](https://img.shields.io/twitter/follow/Autoware?logo=x&logoColor=white&style=flat)](https://twitter.com/intent/follow?screen_name=Autoware)

</div>

#### Service-Based Architecture for Autoware

Open AD Kit is a collaborative project developed by the Autoware Foundation and its member companies and alliance partners. It aims to bring software-defined best practices to the Autoware project and to enhance the Autoware ecosystem and capabilities by partnering with other organizations that share the goal of creating software-defined vehicles.

Open AD Kit aims to democratize autonomous drive (AD) systems by bringing the cloud and edge closer together. In doing so, Open AD Kit will lower the threshold for developing and deploying the Autoware software stack by providing an efficient and modernized CI-CD approach.

#### The First SOAFEE Blueprint

The Autoware Foundation is a voting member of the [SOAFEE (Scalable Open Architecture For the Embedded Edge)](https://soafee.io/) initiative, as the Autoware Open AD Kit is the first SOAFEE blueprint for the software defined vehicle ecosystem.

## Key Features

### Granular Services

Open AD Kit is a micro-service based project, which means that it is designed to be deployed on a variety of platforms with microservices architecture. Each service is designed to be independent and can be deployed on a variety of platforms.

- **Independent microservices** for sensing, perception, planning, control, and visualization
- **Multi-platform deployment** supporting both amd64 and arm64 architectures  
- **Service mesh integration** with configurable environment variables

![Granular Services](docs/assets/images/granular-services.png)

### Mixed Criticality

Open AD Kit supports mixed criticality deployment, enabling separation of safety-critical and non-critical services. This architecture allows flexible deployment strategies where critical autonomous driving functions can run on certified hardware while monitoring and development services operate on standard platforms.

- **Flexible deployment** separating safety-critical and monitoring services
- **Configurable criticality** from development testing to production safety systems
- **Hardware abstraction** supporting safety island compute architectures

![Mixed Criticality](docs/assets/images/mixed-criticality.png)

### Cloud Native

Open AD Kit leverages modern cloud native technologies to deliver scalable, portable AD stack.

- **Seamless scaling** from development laptops to production edge devices
- **Hybrid cloud support** bridging development and production environments
- **Container orchestration** ready for Kubernetes and similar platforms

![Cloud Native](docs/assets/images/cloud-native.png)

### Connected and Continuous

Open AD Kit envisions an always connected, complete autonomous driving development and deployment platform spanning data collection, calibration, and map annotation to machine learning operations, open-source simulation and system validation.

- **Automated CI/CD** with GitHub Actions integration
- **Optimized build caching** for faster deployment cycles
- **Continuous testing** in containerized environments

![Connected and Continuous](docs/assets/images/connected-continuous.png)

## Roadmap

```mermaid
graph LR
    A[STRUCTURE<br/>Define Open AD Kit services and tools]
    B[MODULARITY<br/>Enable modular Autoware services]
    C[CONFIGURABILITY<br/>Provide configurable services for use case]
    D[ORCHESTRATION<br/>Support service orchestration]

    A --> B --> C --> D;

    classDef p1 fill:#0d2c54,stroke:#333,stroke-width:2px,color:#fff,font-weight:bold;
    classDef p2 fill:#2d6a8b,stroke:#333,stroke-width:2px,color:#fff,font-weight:bold;
    classDef p3 fill:#3690c0,stroke:#333,stroke-width:2px,color:#fff,font-weight:bold;
    classDef p4 fill:#673ab7,stroke:#333,stroke-width:2px,color:#fff,font-weight:bold;

    class A p1;
    class B p2;
    class C p3;
    class D p4;
```

## Getting Started

- **[Getting Started](https://autowarefoundation.github.io/openadkit/GettingStarted/)**
- **[Documentation](https://autowarefoundation.github.io/openadkit/)**
- **[Contributing](https://autowarefoundation.github.io/openadkit/contributing/)**
