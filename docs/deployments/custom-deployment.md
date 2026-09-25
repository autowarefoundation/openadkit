# Custom Deployment

Build your own stack by copying an existing deployment in a source checkout.

## How Deployments Are Built

Each service is defined once in
[`deployments/shared/services/`](https://github.com/autowarefoundation/openadkit/tree/main/deployments/shared/services),
one file per service. A deployment directory contains:

| File | Purpose |
|------|---------|
| `docker-compose.yaml` | Selects services with `include`, sets `depends_on`, and adds deployment-specific settings or services. It is the source of truth for the service set. |
| `config.env` | Values the selected services need, such as map paths and simulator settings. |
| `config.gpu.env` | GPU settings loaded with `--gpu`. Required when `deployment.json` lists `gpuFiles`. |
| `deployment.json` | Supported architectures, ROS distros, GPU requirement, data downloads, and one-shot services to reset on each run. |

Container ROS and DDS settings shared by all deployments live in
`deployments/shared/runtime.env`.

## Start from Planning Simulation

From the repository root:

```bash
cp -r deployments/planning-simulation deployments/my-simulation
```

In the copied `deployment.json`, set `name` to `my-simulation` and update
`description`. Then register it in the `deployments` object of the root
`openadkit.json`:

```json
"my-simulation": {
  "path": "deployments/my-simulation"
}
```

## Customize the Stack

Add or remove services in `docker-compose.yaml`. A block under `services:`
customizes an included service; it does not create a second container:

```yaml
include:
  # Other selected services...
  - ../shared/services/visualizer.yaml

services:
  visualizer:
    depends_on:
      - map
```

Add only the settings that differ. Deployment-only services can be defined
directly in the same file. When removing a service, also check `depends_on`,
`pid`, and `resetServices`: most shared services use `pid: service:map` and need
the `map` service.

Keep communicating services on the same ROS domain and middleware. For the
order in which env files are loaded, see
[Configuration](../getting-started/cli.md#configuration).

## Validate and Run

```bash
./openadkit validate my-simulation
./openadkit run my-simulation
./openadkit stop my-simulation
```

Validate every distro and GPU mode you declare. Logging Simulation is an example
of a GPU overlay; CARLA Simulation is an example of deployment-only services.
