# Scenario Simulation

Run predefined traffic scenarios with
[TIER IV Scenario Simulator](https://github.com/tier4/scenario_simulator_v2).
The deployment runs a scenario automatically and writes the results to the host.
No GPU is required.

![Scenario Simulation runs localization-mapping, planning, control, vehicle-system, simulator, Scenario Simulator and visualizer, which talk over ROS 2](../assets/images/deployment-scenario-simulation-light.svg#only-light)
![Scenario Simulation runs localization-mapping, planning, control, vehicle-system, simulator, Scenario Simulator and visualizer, which talk over ROS 2](../assets/images/deployment-scenario-simulation-dark.svg#only-dark)

## Run

```bash
openadkit run scenario-simulation --verify
```

To run Autoware on one host and the scenario runner on another, see
[Split-host Simulation](split-host.md).

`run` downloads the Kashiwanoha map. Autoware takes about two minutes to be
ready; the runner then executes the scenario, three runs of the bundled sample
in seven to eight minutes on a 4-vCPU host, and writes the results to
`~/openadkit-output/scenario-simulation/results` (`run` prints the path).

With `--verify`, `run` waits for the runner and ends with `verify: passed`, or
fails with the runner's exit code. The runner's log ends with
`scenario: N of M passed`: see `openadkit logs scenario-simulator`. Without
`--verify`, `openadkit status` shows the runner's exit code once it ends.

## Settings

Set these in the host settings file,
`~/.config/openadkit/scenario-simulation.env`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCENARIO` | Scenario path inside the container | Bundled example |
| `SCENARIO_HOST_PATH` | Host scenario directory, mounted at `/scenarios` | `./scenarios` |
| `OUTPUT_HOST_PATH` | Host results directory | `~/openadkit-output/scenario-simulation/results` |
| `SCENARIO_READY_TIMEOUT` | Seconds to wait for Autoware before running | `600` |
| `INITIALIZE_DURATION` | Seconds each scenario gives Autoware to reach driving | `300` |
| `GLOBAL_REAL_TIME_FACTOR` | Simulated seconds per wall-clock second; below `1` on a host that cannot run Autoware in real time | `1.0` |
| `GLOBAL_TIMEOUT` | Wall-clock seconds each scenario may take; scale it with the factor | `180` |
| `MAP_PATH` | Host map directory | `~/autoware_data/maps/kashiwanoha_map` |

A relative `SCENARIO_HOST_PATH` resolves from
`deployments/scenario-simulation/`. `MAP_PATH` must be absolute; use `$HOME`
rather than `~`.

To run your own scenario, keep it outside the release. Create a directory, put
the YAML there, and point the deployment at it in the host settings file:

```bash
SCENARIO_HOST_PATH=$HOME/openadkit-scenarios
SCENARIO=/scenarios/my-scenario.yaml
```

The default `./scenarios` lies inside the installed release: files placed there
mark the deployment as modified, stay behind in the old version on `upgrade`
and are deleted by `uninstall`.

Scenarios must match the map, and the planning sample map does not work here.
To use your own map, point `MAP_PATH` at a directory that holds the same files
as the bundled map: `lanelet2_map.osm`, `pointcloud_map.pcd`,
`global_map_center.pcd.yaml`, `lanelet2_map_provider.osm.yaml` and
`map.map_publisher.yaml`. The CLI uses your directory as it is and does not
check it.

This deployment changes one Autoware parameter with a
[config override](../kits/kit-guide.md#2-config-overrides): a file that holds
only the changed value, merged into the upstream parameter file on every start
(`config/autoware/autoware_default_adapi_universe/config/default_adapi.param.yaml`).
