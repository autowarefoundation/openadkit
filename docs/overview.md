# Overview

<p class="oak-hero-lead">
  What Open AD Kit is, why it exists, and how it relates to the Autoware ecosystem: the software it packages for cloud-native deployment.
</p>

## What is Open AD Kit

Open AD Kit packages the [Autoware](https://github.com/autowarefoundation/autoware) autonomous driving stack as focused, independently deployable container images. Instead of one monolithic image, it splits the stack along the AD pipeline — sensing, perception, localization, mapping, planning, control, vehicle system, API, simulation, visualization, and the CARLA bridge — so you run only what a workload needs.

Autoware provides the autonomy stack; Open AD Kit makes it deployable. It packages upstream software into composable images, defines deployment configurations, integrates target platforms and vehicle systems, and maintains the build, test, and release tooling that keeps simulation and in-vehicle deployments consistent.

It also integrates [Autoware Safety Island](https://autowarefoundation.github.io/autoware-safety-island/), which runs on real-time operating systems and automotive hardware rather than in a container. Open AD Kit is the first [SOAFEE](https://www.soafee.io/) blueprint for the software-defined vehicle; [Supported Platforms](platforms/index.md) covers the derived blueprints and the platform tiers.

## Why Open AD Kit

<div class="oak-card-grid oak-card-grid--four" markdown="1">

<div class="oak-card" markdown="1">

:material-view-module-outline:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">Modular Components</p>
<p>Independent images for each stage of the AD pipeline. Deploy only what you need.</p>
</div>

<div class="oak-card" markdown="1">

:material-shield-half-full:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">Mixed Criticality</p>
<p>Separate workloads by criticality assumption across safety-qualified and standard hardware.</p>
</div>

<div class="oak-card" markdown="1">

:material-cloud-sync-outline:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">Cloud Native</p>
<p>Scale from simulation to the edge with containerized deployments, reproducible image builds, and platform integrations.</p>
</div>

<div class="oak-card" markdown="1">

:material-infinity:{ .oak-card-icon }

<p class="oak-card-title" role="heading" aria-level="3">Connected and Continuous</p>
<p>CI/CD with GitHub Actions, optimized build caching, and containerized testing.</p>
</div>

</div>

## How It Works

Open AD Kit runs Autoware as a pipeline of containerized components. Each container handles one stage of autonomous driving, and the stages communicate over ROS 2 DDS on the host network.

Single-host deployments bind CycloneDDS to loopback by default. Set `CYCLONEDDS_NETWORK_INTERFACE` to an exact LAN or VPN interface name only when cross-host DDS is required. `ROS_DOMAIN_ID` separates domains but does not provide authentication or encryption.

1. [**Sensing**](components/index.md#sensing-perception) captures and preprocesses raw sensor data (LiDAR, camera, IMU).
2. [**Perception**](components/index.md#sensing-perception) detects and tracks objects, traffic lights, and drivable space.
3. [**Mapping**](components/index.md#localization-mapping) serves high-definition map data that the rest of the stack consumes.
4. [**Localization**](components/index.md#localization-mapping) determines the vehicle's exact position on the map.
5. [**Planning**](components/index.md#planning-control) computes a safe, feasible trajectory to the goal.
6. [**Control**](components/index.md#planning-control) converts that trajectory into throttle, brake, and steering commands.
7. [**Vehicle System**](components/index.md#vehicle-and-system) bridges those commands to the actual vehicle or simulator.

A **deployment** combines the shared base services with task-specific overlays. Planning and Scenario Simulation add a dummy simulator on top of the base; Logging Simulation adds sensing, perception, and localization for recorded sensor data. Autoware Safety Island integrates with the same pipeline over DDS, adding a safety-critical actuation path alongside the containerized services. See [Components](components/index.md) and [Deployments](deployments/index.md).

## Key Terms

| Term | Meaning |
|------|---------|
| **Component image** | A published container image holding one or more Autoware functions, for example `planning-control`. |
| **Deployment** | A named, ready-to-run stack: a manifest, environment files, and Compose configuration for a task such as planning simulation. |
| **Manifest** | The `deployment.json` file that tells the CLI how to run a deployment: services, requirements, and data. |
| **Overlay** | A deployment-specific Compose file layered on the shared `deployments/base/docker-compose.yaml`. |
| **Tag alias** | A moving image tag such as `planning-control-humble` that follows the newest stable release. Release tags (`-vX.Y.Z`) and digests stay immutable. |
| **Digest pin** | An image reference by content hash (`@sha256:…`) instead of a tag, so the same image bits are always used. |
| **Mixed criticality** | Running safety-critical and non-critical workloads in separate containers or partitions on the same hardware. |
