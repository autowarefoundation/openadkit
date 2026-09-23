# Custom Deployment

Start from an existing deployment in a source checkout and adapt it to your task.
Each deployment selects shared services using native Docker Compose `include`;
its Compose file defines the dependencies and deployment-specific overrides.

## Start from Planning Simulation

From the repository root:

```bash
cp -r deployments/planning-simulation deployments/my-simulation
```

In the copied `deployment.json`, set `name` to `my-simulation` and update
`description`. Keep the other settings for this planning-based example, including
`"shared": ["shared"]`, the map download, and `resetServices`.

Add this entry to the `deployments` object in the root `openadkit.json`:

```json
"my-simulation": {
  "path": "deployments/my-simulation"
}
```

The inventory entry makes the deployment available to the CLI.

## Customize the Stack

| File | What to change |
|------|----------------|
| `docker-compose.yaml` | Select services with `include`, define `depends_on`, and add deployment-specific settings or services. |
| `config.env` | Supply the parameters needed by the selected services, such as map paths and simulator settings. Use ignored `config.local.env` for personal overrides. |
| `config.gpu.env` | Required when `deployment.json` lists `gpuFiles`. Loaded after `config.env` for `openadkit validate <deployment> --gpu` and `openadkit run <deployment> --gpu`; override interpolations here instead of restating a shared service command. |
| `deployment.json` | Declare supported architectures, ROS distros, GPU requirements, downloads, and one-shot services to reset on each run. |

Shared service definitions live in
[`deployments/shared/services/`](https://github.com/autowarefoundation/openadkit/tree/main/deployments/shared/services).
For example, these excerpts from the copied Compose file select the visualizer
and define its dependency:

```yaml
include:
  # Other selected services...
  - ../shared/services/visualizer.yaml

services:
  visualizer:
    depends_on:
      - map
```

The `visualizer` block customizes the included service; it does not create a
second container. Add only the settings that differ. Deployment-only services
can be defined directly in the same file.

Compose is the source of truth for the service set; there is no service list in
`deployment.json`. When removing a service, check references from `depends_on`,
`pid`, and `resetServices`. Most shared services use `pid: service:map` and need
the `map` service in the project.

Shared ROS/DDS settings live in `shared/runtime.env`, loaded inside containers
via `env_file`. Keep communicating services on the same ROS domain and middleware.
Keep the visualizer's entrypoint and command intact so noVNC and RViz start
together; use `config.local.env` to set `REMOTE_PASSWORD`.

## Validate and Run

```bash
./openadkit validate my-simulation
./openadkit run my-simulation
./openadkit logs my-simulation --follow
./openadkit stop my-simulation
```

Validate each distro and GPU mode you declare. See
[Logging Simulation](logging-simulation/index.md) for a GPU overlay
(`config.gpu.env` plus image/runtime overrides) and
[CARLA Simulation](carla-simulation/index.md) for deployment-specific services.
