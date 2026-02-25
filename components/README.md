# Open AD Kit Components

[Open AD Kit](https://autoware.org/open-ad-kit/) offers containers for Autoware Components to simplify the deployment of Autoware and its dependencies. This directory contains scripts to build Component containers.

Detailed instructions on how to deploy the components can be found in the [Open AD Kit Deployments](https://autowarefoundation.github.io/openadkit/deployments/).

## Build Pipeline

```mermaid
block-beta
    columns 7

    space:2 ROS["ros:humble-ros-base-jammy"]:3 space:2

    space:7

    space:2 CB["common-base"]:3 space:2

    space:7

    space:2 CD["common-devel"]:3 space:2

    space:7

    SP["sensing-perception"] LM["localization-mapping"] PC["planning-control"] VS["vehicle-system"] API["api"] VIZ["visualizer"] SIM["simulator"]

    space:7

    space:2 UNI["universe"]:3 space:2

    ROS --> CB
    CB --> CD
    CD --> SP
    CD --> LM
    CD --> PC
    CD --> VS
    CD --> API
    CD --> VIZ
    CD --> SIM
    SP --> UNI
    LM --> UNI
    PC --> UNI
    VS --> UNI
    API --> UNI
    VIZ --> UNI
    SIM --> UNI

    style ROS fill:#334155,stroke:#64748b,color:#e2e8f0
    style CB fill:#1e3a5f,stroke:#3b82f6,color:#bfdbfe
    style CD fill:#1e3a5f,stroke:#3b82f6,color:#bfdbfe
    style SP fill:#14532d,stroke:#22c55e,color:#bbf7d0
    style LM fill:#14532d,stroke:#22c55e,color:#bbf7d0
    style PC fill:#14532d,stroke:#22c55e,color:#bbf7d0
    style VS fill:#14532d,stroke:#22c55e,color:#bbf7d0
    style API fill:#14532d,stroke:#22c55e,color:#bbf7d0
    style VIZ fill:#14532d,stroke:#22c55e,color:#bbf7d0
    style SIM fill:#14532d,stroke:#22c55e,color:#bbf7d0
    style UNI fill:#4c1d95,stroke:#a855f7,color:#e9d5ff
```

### Build Groups

| Group | Description | Targets |
|-------|-------------|---------|
| `common` | Common images | base, devel |
| `component` | Component images | sensing-perception, sensing-perception-cuda, localization-mapping, planning-control, vehicle-system, api, visualizer, simulator |
| `universe` | Universe images | universe, universe-cuda |
