# Deployment

A deployment combines Open AD Kit images, environment files, and Docker Compose
configuration for a specific task.

| Deployment | Purpose | Topology | GPU |
|------------|---------|----------|-----|
| [Planning Simulation](planning-simulation/index.md) | Plan and follow a route on a demo map | Single host | No |
| [Scenario Simulation](scenario-simulation/index.md) | Execute predefined traffic scenarios | Single host | No |
| [Logging Simulation](logging-simulation/index.md) | Replay recorded sensor data through the full stack | Single host | Recommended |
| [CARLA Simulation](carla-simulation/index.md) | Drive a CARLA ego vehicle in closed loop | Single host | Required |
| [Zenoh Bridge](zenoh-bridge/index.md) | Separate edge compute from visualization and control | Single Compose project | Varies |

New users should start with Planning Simulation. The manifest-driven CLI and
release bundle support Planning, Scenario, and Logging Simulation. CARLA and
Zenoh are standalone source-checkout deployments.

## Base and Overlay Model

Planning, Scenario, Logging, and CARLA Simulation include the shared
`deployments/base/docker-compose.yaml`. The base defines map, planning, vehicle,
system, control, simulator, API, and visualizer services; each deployment adds
only its delta.

Each curated deployment carries an `openadkit.json` runtime manifest and one
complete `config.env` for Compose interpolation. Operate it from the source
checkout or release bundle root:

```bash
./openadkit list
./openadkit validate planning-simulation
./openadkit run planning-simulation
./openadkit status planning-simulation
./openadkit logs planning-simulation --follow
./openadkit down planning-simulation
```

Add `--ros-distro jazzy` to select Jazzy; Humble is the default. The single
release bundle vendors the three curated deployments and shared base. Its
runtime context selects digest-pinned image references for both distros. Local
settings belong in ignored `config.local.env`; release component images remain
pinned. The base's `runtime.env` is loaded inside containers via `env_file:`.

CARLA and Zenoh do not have runtime manifests. Use their source-checkout
launcher scripts documented on their deployment pages.

See [Custom Deployment](custom-deployment.md) to compose a different stack and
[Container Images & Versioning](../getting-started/container-images.md) for tag
selection.
