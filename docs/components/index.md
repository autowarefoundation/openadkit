# Components

Open AD Kit is a component-based project designed to run on a variety of platforms with containerized services. Each **Autoware function** remains independently deployable, while the published images group closely related functions together where that keeps the runtime layout simpler.

![Granular Components](../assets/images/granular-components.png)

## Autoware Components

### Sensing

The sensing component is responsible for collecting data from the vehicle's sensors. Sensing component can be configured to collect data from a variety of sensors, including **cameras, lidars, and radars**. For more details on the [Autoware sensing design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/sensing/).

### Perception

The perception component is responsible for processing the data from the vehicle's sensors and creating a map of the environment. Perception component can be configured to use a variety of perception algorithms, including **object detection, tracking, and mapping**. For more details, see the [Autoware perception design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/perception/).

### Mapping

The mapping component is responsible for creating a map of the environment. Mapping component can be configured to use a variety of mapping algorithms, including **occupancy grid mapping and point cloud mapping**. For more details, see the [Autoware mapping design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/map/).

### Localization

The localization component is responsible for determining the vehicle's position in the map. Localization component can be configured to use a variety of localization algorithms, including **GPS, IMU, and visual odometry**. For more details, see the [Autoware localization design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/localization/).

### Planning

The planning component is responsible for planning the vehicle's path. Planning component can be configured to use a variety of planning algorithms, including **Route Planning, Goal Planning, and Behavior Planning**. For more details, see the [Autoware planning design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/planning/).

### Control

The control component is responsible for controlling the vehicle's actuators. Control component can be configured to use a variety of control algorithms, including **PID and MPC**. For more details, see the [Autoware control design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/control/).

### Vehicle and System

The `vehicle-system` image packages both the vehicle interface and system-level services used by the Open AD Kit deployments. On the functional side, the vehicle component manages vehicle-specific interfaces and state, while the system component provides health monitoring and related system services. For more details, see the [Autoware vehicle design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/vehicle/).

### API

The API component is responsible for providing [AD API](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-interfaces/ad-api/) interface for the vehicle's state. API component can be configured to enable or disable various interfaces. For more details, see the [Autoware Interface design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/interfaces/).

## Building from source

Open AD Kit images are built with `docker buildx bake` using
[`components/docker-bake.hcl`](https://github.com/autowarefoundation/openadkit/blob/main/components/docker-bake.hcl).
The build graph is:

```
upstream autoware:core-devel / core / base-cuda-{devel,runtime}
        │
        ▼
universe-common  (openadkit-owned thin intermediate)
        │
        ▼
seven non-CUDA component images (sensing-perception,
localization-mapping, planning-control, vehicle-system,
api, visualizer, simulator)
```

`sensing-perception-cuda` is a parallel CUDA branch: it inherits from
upstream `base-cuda-{devel,runtime}` and additionally grafts in the
`universe-common` install tree (so it has both CUDA toolkit access and the
universe-common compiled packages).

The `universe-common` layer compiles only the universe-common slice of
Autoware on top of upstream `core-devel`/`core`; everything below
`universe-common` (base OS, ROS, core) is owned and built by upstream.

### Bake groups

| Group | Targets |
|-------|---------|
| `default` | everything: `universe-common` + `component` |
| `universe-common` | `universe-common-devel`, `universe-common` |
| `component` | the seven non-CUDA component images plus `sensing-perception-cuda` |

### Upstream pin

The `UPSTREAM_TAG` bake variable pins the upstream Autoware release the
images are built against. CI sets it from a repository Variable; leaving it
empty uses upstream's plain `<name>-<distro>` multi-arch tag.

## CI pipeline

`build-all-images.yaml` builds the universe-common graph on pushes,
schedules, and manual dispatch. It walks the `{humble, jazzy} × {amd64,
arm64}` matrix through staged jobs — `prepare`, then `build-common` and
`build-components` — so each layer is pushed before the
layer that depends on it. A final `create-manifests` job stitches the
per-arch tags into multi-arch manifests via the `combine-multi-arch-images`
composite action. `release-all-images.yaml` runs on a schedule to track
Autoware release tags and build the matching single-arch release images.
