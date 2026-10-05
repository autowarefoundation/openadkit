# Custom Deployment

Build your own stack in an integrator repository. Include a pinned Open AD Kit
deployment and keep only your differences; do not copy its Compose files or
modify an installed release.

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

## Include Planning Simulation

Create an `openadkit.json` at the root of your repository:

```json
{
  "schemaVersion": 2,
  "kind": "kit",
  "extends": "v2.0.0",
  "deployments": {
    "my-simulation": {"path": "deployments/my-simulation"}
  }
}
```

Use a published schema-v2 release tag for `extends`; the version above is an
example, not a claim that it has been released. During development, `extends`
can instead point to a source checkout. The CLI uses the pinned base's own CLI
and asks you to install it when it is missing.

Create `deployments/my-simulation/deployment.json`:

```json
{
  "schemaVersion": 2,
  "name": "my-simulation",
  "description": "My Planning Simulation stack",
  "base": "planning-simulation",
  "compose": {"files": ["docker-compose.yaml"]}
}
```

The base's architecture, ROS distro and GPU requirements are inherited exactly;
do not redeclare them. Its data downloads are inherited too.

## Customize the Stack

Create `deployments/my-simulation/docker-compose.yaml`:

```yaml
include:
  - ${KIT_openadkit}/deployments/planning-simulation/docker-compose.yaml
```

The CLI sets `KIT_openadkit` to the resolved base. Add only settings that differ
in `config.env`, for example `VEHICLE_ID=my-vehicle`. Add your own services under
`services:` in the same Compose file. A block for an included service overrides
that service rather than creating another container.

Use parameter-level config differences and an overlay workspace instead of
mounting files over `/opt/autoware` or replacing a base command. See the
[Integrator Guide](integrator-guide.md) for all extension points, image
replacement, configuration order and contract warnings.

## Validate and Run

```bash
openadkit validate my-simulation
openadkit run my-simulation
openadkit stop my-simulation
```

Run these commands from your kit repository (or set `OPENADKIT_KIT` to its
root). Validate every distro and GPU mode supported by the base. The
[custom-kit example](https://github.com/autowarefoundation/openadkit/tree/main/examples/custom-kit)
is a complete, minimal Planning Simulation integration exercised by CI.
