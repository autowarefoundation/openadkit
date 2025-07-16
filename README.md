# Open AD Kit: Containerized Autoware Workloads

<p align="center">
    <a href="https://opensource.org/licenses/Apache-2.0">
        <img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
    <a href="https://autowarefoundation.github.io/openadkit/">
        <img src="https://img.shields.io/badge/docs-available-brightgreen.svg" alt="Documentation"></a>
    <a href="https://discord.gg/Q94UsPvReQ">
        <img src="https://img.shields.io/discord/953808765935816715?logo=discord&logoColor=white&style=flat&label=Autoware"
            alt="Autoware Discord"></a>
    <a href="https://www.linkedin.com/company/the-autoware-foundation/">
        <img src="https://img.shields.io/badge/Linkedin-Autoware-0a66c2?logo=linkedin&logoColor=white&style=flat"
            alt="Autoware"></a>
    <a href="https://twitter.com/intent/follow?screen_name=Autoware">
        <img src="https://img.shields.io/twitter/follow/Autoware?logo=x&logoColor=white&style=flat"
            alt="Autoware Twitter / X"></a>
</p>

Open AD Kit is a collaborative project developed by the Autoware Foundation and its member companies and alliance partners. It aims to bring software-defined best practices to the Autoware project and to enhance the Autoware ecosystem and capabilities by partnering with other organizations that share the goal of creating software-defined vehicles.

Open AD Kit aims to democratize autonomous drive (AD) systems by bringing the cloud and edge closer together. In doing so, Open AD Kit will lower the threshold for developing and deploying the Autoware software stack by providing an efficient and modernized CI-CD approach.

#### The First SOAFEE Blueprint

The Autoware Foundation is a voting member of the [SOAFEE (Scalable Open Architecture For the Embedded Edge)](https://soafee.io/) initiative, as the Autoware Open AD Kit is the first SOAFEE blueprint for the software defined vehicle ecosystem. Open AD Kit's containerized workloads for the Autoware software stack can be deployed on a variety of platforms with microservices architecture.

## Key Features

### Granular Workloads

Open AD Kit is a granular containerized project, which means that it is designed to be deployed on a variety of platforms with microservices architecture. Each workload is designed to be independent and can be deployed on a variety of platforms.

- **Independent microservices** for sensing, perception, planning, control, and visualization
- **Multi-platform deployment** supporting both amd64 and arm64 architectures  
- **Service mesh integration** with configurable environment variables

![Granular Workloads](docs/assets/images/granular-workloads.png)

### Mixed Criticality

Open AD Kit is a mixed critical implementation project, which means that it is designed to be deployed on a variety of platforms with microservices architecture. Each workload is designed to be independent and can be deployed on a variety of platforms.

- **Flexible deployment** separating safety-critical and monitoring workloads
- **Configurable criticality** from development testing to production safety systems
- **Hardware abstraction** supporting safety island compute architectures

![Mixed Criticality](docs/assets/images/mixed-criticality.png)

### Cloud Native

Open AD Kit leverages modern cloud native technologies to deliver scalable, portable autonomous driving workloads.

- **Seamless scaling** from development laptops to production edge devices
- **Hybrid cloud support** bridging development and production environments
- **Container orchestration** ready for Kubernetes and similar platforms

![Cloud Native](docs/assets/images/cloud-native.png)

### Connected and Continuous

From data collection, calibration, and map annotation to machine learning operations, open-source simulation and system validation, the Open AD Kit initiative envisions an always connected, complete autonomous driving development and deployment platform.

- **Automated CI/CD** with GitHub Actions integration
- **Optimized build caching** for faster deployment cycles
- **Continuous testing** in containerized environments

![Connected and Continuous](docs/assets/images/connected-continuous.png)

## Getting Started

- **[Quick start](https://autowarefoundation.github.io/openadkit/Quickstart/)**
- **[Documentation](https://autowarefoundation.github.io/openadkit/)**
- **[Roadmap](https://autowarefoundation.github.io/openadkit/Roadmap/)**
- **[Contributing](https://autowarefoundation.github.io/openadkit/Contributing/)**
