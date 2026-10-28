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

Run Autoware on one host and the TIER IV runner on another with `--node`; see
[Split-host simulation](../split-host.md).

--8<-- "includes/ros-distro.md"

`run` downloads the Kashiwanoha map. Autoware takes about 90 seconds to
initialize; the runner then executes the scenario and writes the results to
`~/.local/state/openadkit/scenario-simulation/output` (`run` prints the path).

--8<-- "includes/visualizer-remote-access.md"

## Configure

Put overrides in `~/.config/openadkit/scenario-simulation.env`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCENARIO` | Scenario path inside the container | Bundled example |
| `SCENARIO_HOST_DIR` | Host scenario directory, mounted at `/scenarios` | `./scenarios` |
| `OUTPUT_HOST_PATH` | Host results directory | `~/.local/state/openadkit/scenario-simulation/output` |
| `SCENARIO_READY_TIMEOUT` | Seconds to wait for Autoware before running | `600` |
| `GLOBAL_REAL_TIME_FACTOR` | Simulated seconds per wall-clock second; below `1` on a host that cannot run Autoware in real time | `1.0` |
| `GLOBAL_TIMEOUT` | Wall-clock seconds each scenario may take; scale it with the factor | `180` |
| `MAP_PATH` | Host map directory | `~/autoware_map/kashiwanoha_map` |

A relative `SCENARIO_HOST_DIR` resolves from `deployments/scenario-simulation/`. `MAP_PATH` must be absolute; use `$HOME`
rather than `~`.

To run your own scenario, keep it outside the release. Create a directory, put
the YAML there, and point the deployment at it in the host settings file:

```bash
SCENARIO_HOST_DIR=$HOME/openadkit-scenarios
SCENARIO=/scenarios/my-scenario.yaml
```

The default `./scenarios` lies inside the installed release: files placed there
mark the deployment as modified and are lost on `upgrade` or `uninstall`.

Scenarios must match the map, and the planning sample map does not work here.
To use your own map, point `MAP_PATH` at a directory that holds the same files
as the bundled map, which the CLI checks before starting: `lanelet2_map.osm`,
`pointcloud_map.pcd`, `global_map_center.pcd.yaml`,
`lanelet2_map_provider.osm.yaml` and `map.map_publisher.yaml`.

This deployment changes one Autoware parameter, in a file that holds only the
changed value. On every start, the images merge it into the upstream parameter
file: `config/autoware/autoware_default_adapi_universe/config/default_adapi.param.yaml`.

## Stop and Recover

```bash
openadkit stop scenario-simulation
```

To replace missing map data, run `openadkit fetch scenario-simulation --force`.
For other issues, see [Troubleshooting](../../getting-started/troubleshooting.md).
