# Scenario Simulation

Run predefined traffic scenarios with
[TIER IV Scenario Simulator](https://github.com/tier4/scenario_simulator_v2).
The deployment executes scenarios automatically and writes their results to the
host.

!!! warning "Use the Kashiwanoha map"
    `sample-map-planning` is incompatible and causes invalid-map and MRM errors.

## Setup

--8<-- "includes/cli-command-context.md"

```bash
openadkit setup --verify
```

--8<-- "includes/docker-group-activation.md"

The entry point downloads the Kashiwanoha map automatically.

## Configuration

Put overrides in `deployments/scenario-simulation/config.local.env`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCENARIO` | Scenario path inside the container | Bundled example |
| `SCENARIO_HOST_DIR` | Host scenario directory | `deployments/scenario-simulation/scenarios` |
| `OUTPUT_HOST_PATH` | Host results directory | `deployments/scenario-simulation/output` |
| `SCENARIO_READY_TIMEOUT` | Autoware readiness timeout in seconds | `300` |
| `MAP_PATH` | Host map directory | `~/autoware_map/kashiwanoha_map` |

`config.env` stores those host paths as `./scenarios` and `./output`. Compose
resolves them from `deployments/scenario-simulation/`, not the repository root.

For a custom scenario, place its YAML in
`deployments/scenario-simulation/scenarios` (or another `SCENARIO_HOST_DIR`)
and set, for example, `SCENARIO=/scenarios/my-scenario.yaml`. A custom map must
provide matching `MAP_PATH`, `LANELET2_MAP_FILE`, and `POINTCLOUD_MAP_FILE`
values.

## Run

```bash
openadkit run scenario-simulation
openadkit logs scenario-simulation --follow
```

--8<-- "includes/ros-distro.md"

Initialization takes about 90 seconds. The runner waits up to
`SCENARIO_READY_TIMEOUT`, executes the scenario, and writes results to
`deployments/scenario-simulation/output` unless `OUTPUT_HOST_PATH` is
overridden.

--8<-- "includes/visualizer-remote-access.md"

## Stop and Recover

```bash
openadkit stop scenario-simulation
```

Parameter overrides live in `config/mrm_handler.param.yaml` and
`config/default_adapi.param.yaml`. To replace missing map data, run
`openadkit fetch scenario-simulation --force`. For common issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
