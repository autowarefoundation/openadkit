# Overview

<p class="oak-hero-lead">
  What Open AD Kit is, why it exists, and how it relates to Autoware — the autonomous driving stack it packages for cloud-native deployment.
</p>

## What is Open AD Kit

Open AD Kit packages the [Autoware](https://github.com/autowarefoundation/autoware) autonomous driving stack as a set of focused, independently deployable container images. Rather than shipping one monolithic image, it splits the stack along the AD pipeline — sensing, perception, localization, mapping, planning, control, and supporting services — so you can run only what a given workload needs.

Autoware provides the autonomy stack; Open AD Kit makes it deployable. It packages upstream software into composable container images, defines deployment configurations, integrates with target platforms and vehicle systems, and maintains the build, test, and release tooling needed to run consistently from simulation through in-vehicle deployment.

!!! abstract "SOAFEE Blueprint"
    The first [SOAFEE](https://www.soafee.io/) blueprint for the software-defined vehicle, co-developed with the [eSync Alliance](https://esyncalliance.org/). Learn more on the [Platforms](platforms/index.md) page.

## Why Open AD Kit

<div class="oak-card-grid" markdown="1">

<div class="oak-card" markdown="1">

:material-view-module-outline:{ .oak-card-icon }

<h3>Modular Components</h3>
<p>Independent images for each stage of the AD pipeline. Deploy only what you need.</p>
</div>

<div class="oak-card" markdown="1">

:material-shield-half-full:{ .oak-card-icon }

<h3>Mixed Criticality</h3>
<p>Separate workloads by criticality assumption across safety-qualified and standard hardware.</p>
</div>

<div class="oak-card" markdown="1">

:material-cloud-sync-outline:{ .oak-card-icon }

<h3>Cloud Native</h3>
<p>Scale from simulation to the edge with Docker Compose, Docker Bake, and platform integrations.</p>
</div>

<div class="oak-card" markdown="1">

:material-infinity:{ .oak-card-icon }

<h3>Connected and Continuous</h3>
<p>CI/CD with GitHub Actions, optimized build caching, and containerized testing.</p>
</div>

</div>

## How it works

Open AD Kit runs Autoware as a pipeline of containerized components. Each container handles one stage of autonomous driving, and the stages communicate over ROS 2 DDS on the host network:

1. **Sensing** captures and preprocesses raw sensor data (LiDAR, camera, IMU).
2. **Perception** detects and tracks objects, traffic lights, and drivable space.
3. **Mapping** serves high-definition map data that the rest of the stack consumes.
4. **Localization** determines the vehicle's exact position on the map.
5. **Planning** computes a safe, feasible trajectory to the goal.
6. **Control** converts that trajectory into throttle, brake, and steering commands.
7. **Vehicle System** bridges those commands to the actual vehicle or simulator.

A **deployment** is a Docker Compose file that starts the subset of these containers needed for a specific task — for example, planning simulation starts only planning, control, and visualization, while logging simulation adds sensing and perception to replay real sensor data. For the full picture, see [Components](components/index.md) and [Deployment](deployment/index.md).

## Related

- [Getting Started](getting-started/index.md) — Set up your environment
- [Deployment](deployment/index.md) — Run your first deployment
- [Platforms](platforms/index.md) — Choose a deployment target
