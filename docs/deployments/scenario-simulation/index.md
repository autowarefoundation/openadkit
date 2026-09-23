# Scenario Simulation

Run predefined traffic scenarios with
[TIER IV Scenario Simulator](https://github.com/tier4/scenario_simulator_v2).
The deployment runs a scenario automatically and writes the results to the host.
No GPU is required.

Complete the [Quickstart](../../getting-started/index.md) setup first.

## Run

--8<-- "includes/cli-command-context.md"

```bash
openadkit run scenario-simulation
openadkit logs scenario-simulation --follow
```

Run Autoware on one host and the TIER IV runner on another with `--role`; see
[Split-host simulation](../split-host.md).

--8<-- "includes/ros-distro.md"

`run` downloads the Kashiwanoha map. Autoware takes about 90 seconds to
initialize; the runner then executes the scenario and writes the results to
`deployments/scenario-simulation/output`.

--8<-- "includes/visualizer-remote-access.md"

## Configure

Put overrides in `deployments/scenario-simulation/config.local.env`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCENARIO` | Scenario path inside the container | Bundled example |
| `SCENARIO_HOST_DIR` | Host scenario directory, mounted at `/scenarios` | `./scenarios` |
| `OUTPUT_HOST_PATH` | Host results directory | `./output` |
| `SCENARIO_READY_TIMEOUT` | Seconds to wait for Autoware before running | `300` |
| `MAP_PATH` | Host map directory | `~/autoware_map/kashiwanoha_map` |

Relative paths resolve from `deployments/scenario-simulation/`.

To run your own scenario, put its YAML in the scenarios directory and set, for
example, `SCENARIO=/scenarios/my-scenario.yaml`. Scenarios must match the map: a
custom map needs matching `MAP_PATH`, `LANELET2_MAP_FILE`, and
`POINTCLOUD_MAP_FILE` values, and the planning sample map does not work here.

Autoware parameter overrides for this deployment live in
`config/mrm_handler.param.yaml` and `config/default_adapi.param.yaml`.

## Stop and Recover

```bash
openadkit stop scenario-simulation
```

To replace missing map data, run `openadkit fetch scenario-simulation --force`.
For other issues, see [Troubleshooting](../../getting-started/troubleshooting.md).
