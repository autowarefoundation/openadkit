# Open AD Kit Components

[Open AD Kit](https://autoware.org/open-ad-kit/) offers containers for Autoware Components to simplify the deployment of Autoware and its dependencies. This directory contains scripts to build Component containers.

Detailed instructions on how to deploy the components can be found in the [Open AD Kit Deployments](https://autowarefoundation.github.io/openadkit/deployments/).

## Build Pipeline

```mermaid
flowchart TB
    ROS["ros:humble-ros-base-jammy<br/>ros:jazzy-ros-base-noble"] --> CB["common-base"]
    CB --> CD["common-devel"]

    CD --> SP["sensing-perception"]
    CD --> LM["localization-mapping"]
    CD --> PC["planning-control"]
    CD --> VS["vehicle-system"]
    CD --> API["api"]
    CD --> VIZ["visualizer"]
    CD --> SIM["simulator"]
    CD --> CARLA["carla-interface"]

    classDef ros fill:#334155,stroke:#64748b,color:#fff
    classDef common fill:#1e3a5f,stroke:#3b82f6,color:#fff
    classDef component fill:#14532d,stroke:#22c55e,color:#fff

    class ROS ros
    class CB,CD common
    class SP,LM,PC,VS,API,VIZ,SIM,CARLA component

```

### Build Groups

| Group | Description | Targets |
|-------|-------------|---------|
| `common` | Common images | base, devel |
| `component` | Component images | sensing-perception, sensing-perception-cuda, localization-mapping, planning-control, vehicle-system, api, visualizer, simulator, carla-interface |
