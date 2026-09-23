# Deployments

A deployment combines Open AD Kit images, environment files, and Docker Compose
configuration for a specific task.

| Deployment | Purpose | Topology | GPU |
|------------|---------|----------|-----|
| [Planning Simulation](planning-simulation/index.md) | Plan and follow a route on a demo map | Single host | No |
| [Scenario Simulation](scenario-simulation/index.md) | Execute predefined traffic scenarios | Single host | No |
| [Logging Simulation](logging-simulation/index.md) | Replay sensor data through sensing, perception, and localization | Single host | Recommended |
| [CARLA Simulation](carla-simulation/index.md) | Drive a CARLA ego vehicle in closed loop | Single host | Required |
| [Zenoh Bridge](zenoh-bridge/index.md) | Separate edge compute from visualization and control | Single Compose project | Varies |

New users should start with Planning Simulation. The CLI and release bundle
support Planning, Scenario, Logging, and CARLA Simulation. Zenoh remains a
standalone source-checkout deployment.

## Shared Services

Planning, Scenario, Logging, and CARLA Simulation select the services they need
from `deployments/shared/services/` using Docker Compose `include`. Each shared
file defines one service. The deployment's Compose file defines dependencies,
overrides, and deployment-only services; it is the source of truth for the
service set.

Each curated deployment carries a `deployment.json` manifest and one complete
`config.env` for Compose interpolation. Optional GPU mode also loads
`config.gpu.env` so model flags can change without copying a shared service
command.

--8<-- "includes/cli-command-context.md"

```bash
openadkit list
openadkit validate planning-simulation
openadkit run planning-simulation
openadkit status planning-simulation
openadkit logs planning-simulation --follow
openadkit stop planning-simulation
```

Add `--ros-distro jazzy` to `validate`, `fetch`, or `run` to select Jazzy;
Humble is the default. CARLA is Humble-only and requires `--gpu`. `status`,
`logs`, and `stop` take neither flag — they read the running deployment.

The release bundle vendors the curated deployments and shared assets. Local
settings belong in ignored `config.local.env`; release component images remain
pinned. `shared/runtime.env` is loaded inside containers via `env_file:`.

Zenoh does not have a runtime manifest. Use its source-checkout launcher
scripts documented on its deployment page.

See [Custom Deployment](custom-deployment.md) to compose a different stack and
[Container Images & Versioning](../getting-started/container-images.md) for tag
selection.
