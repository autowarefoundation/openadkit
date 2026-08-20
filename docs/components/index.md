# Components

Open AD Kit is a component-based project designed to run on a variety of platforms with containerized services. Each **Autoware function** remains independently deployable, while the published images group closely related functions together to keep the runtime layout simpler.

## Architecture Overview

Autoware uses a **Core / Universe** architecture. **Core** contains rigorously reviewed base functionality required for safe autonomous driving. **Universe** contains community extensions and research features that build on the Core foundation. Open AD Kit packages Universe components into focused container images that can be composed into complete AD systems.

## Build Pipeline

--8<-- "includes/build-pipeline.md"

`universe-common` is an Open AD Kit-owned thin intermediate built on top of the
upstream `autoware:core-devel`/`base` images. The bake groups and build commands
are documented in [Build from Source](../development/build-from-source.md).

## Interface Layers

Autoware defines three formal interface categories that govern how components communicate:

<div class="oak-component-grid">

<div class="oak-component-item">
<strong>AD API</strong>
<span>External interface for fleet management and HMI. Exposed as ROS 2 services and topics for vehicle state queries and commands; external gateways (e.g. HTTP/MQTT) can be layered on top.</span>
</div>

<div class="oak-component-item">
<strong>Component Interface</strong>
<span>Internal inter-module communication via ROS 2 topics and services. Standardized message types ensure compatibility across components.</span>
</div>

<div class="oak-component-item">
<strong>Local Interface</strong>
<span>Intra-component communication within a single image. Implementation details that do not cross component boundaries.</span>
</div>

</div>

```mermaid
flowchart LR
    subgraph AD_API["AD API (External)"]
        A1[ROS 2 Services / Topics]
    end

    subgraph Component_Interface["Component Interface"]
        C1[ROS 2 Topics]
        C2[ROS 2 Services]
    end

    subgraph Local_Interface["Local Interface"]
        L1[Intra-component Communication]
    end

    AD_API --> Component_Interface
    Component_Interface --> Local_Interface
```

## Autoware Components

Each Autoware function is packaged into a focused container image. Select a component from the sidebar or explore the pages below.

<div class="oak-component-grid">

<div class="oak-component-item">
<strong><a href="sensing-perception/">Sensing &amp; Perception</a></strong>
<span>Sensor preprocessing plus object detection, tracking, and multi-sensor fusion.</span>
</div>

<div class="oak-component-item">
<strong><a href="localization-mapping/">Localization &amp; Mapping</a></strong>
<span>HD map serving plus GNSS, IMU, visual odometry, and LiDAR map matching.</span>
</div>

<div class="oak-component-item">
<strong><a href="planning-control/">Planning &amp; Control</a></strong>
<span>Route, behavior, motion, and goal planning with PID/MPC trajectory tracking.</span>
</div>

<div class="oak-component-item">
<strong><a href="vehicle-system/">Vehicle and System</a></strong>
<span>Vehicle interface and system-level orchestration services.</span>
</div>

<div class="oak-component-item">
<strong><a href="api/">API</a></strong>
<span>AD API for external fleet management and HMI integration.</span>
</div>

<div class="oak-component-item">
<strong><a href="simulator/">Simulator</a></strong>
<span>Closed-loop simulation for validation and local development.</span>
</div>

<div class="oak-component-item">
<strong><a href="visualizer/">Visualizer</a></strong>
<span>Browser-accessible RViz2 via noVNC for remote monitoring.</span>
</div>

<div class="oak-component-item">
<strong><a href="carla-interface/">CARLA Interface</a></strong>
<span>Bridge for closed-loop simulation with the CARLA simulator.</span>
</div>

</div>

## Image Reference

The published component images and their platforms. This table is generated from
the image catalog (`.github/image-inventory.json`), so it always matches what CI
builds. See [Container Images & Versioning](../getting-started/container-images.md) for the tag
naming scheme.

{{ component_table() }}

## Related

- [Deployments](../deployment/index.md) — How to compose components into running systems
- [Build from Source](../development/build-from-source.md) — Bake groups, CI pipeline, and upstream pin
- [Roadmap](../roadmap.md) — Release ladder and focus areas
- [Supported Platforms](../platforms/index.md) — Where to deploy
