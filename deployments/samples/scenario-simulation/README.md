# Autoware Open AD Kit Scenario Simulation

This sample deployment runs Autoware Open AD Kit **scenario simulation** with the [TIER IV Scenario Simulator](https://github.com/tier4/scenario_simulator_v2/pkgs/container/scenario_simulator_v2) container.

Autoware runs as component containers. The scenario simulator connects to that stack over ROS 2 DDS on the host network.

## Requirements

The default `sample.yaml` scenario uses the **Kashiwanoha** map bundled in the TIER IV scenario simulator image. Autoware must load the same map.

On first startup, the `map-init` service extracts that map to `~/autoware_map/kashiwanoha_map` automatically. It re-extracts the map if required files are missing or the configured TIER IV image tag changes. No manual download is required.

> **Note**: Do not use `sample-map-planning` here. It is a different map and will cause `setMap() for invalid version map`, missing route/localization, and repeated MRM transitions.

## Run the Deployment

```bash
docker compose --env-file scenario-simulation.env up -d
```

Open the visualizer at `http://localhost:6080/vnc.html` (password: `openadkit`). If the deployment runs on a remote server, use `http://<server-ip>:6080/vnc.html` and ensure port `6080` is reachable.

Wait about 90 seconds for Autoware and the scenario simulator to initialize. Before launching the one-shot scenario, the runner waits up to `SCENARIO_READY_TIMEOUT` seconds for required Autoware map and API endpoints.

## Configuration

Edit `scenario-simulation.env` to customize the scenario simulator:

| Variable | Description |
| --- | --- |
| `SCENARIO` | Scenario file path inside the container. Leave empty to use the bundled sample scenario. |
| `SCENARIO_HOST_DIR` | Host directory mounted at `/scenarios` |
| `OUTPUT_HOST_PATH` | Host directory for simulation results |
| `OUTPUT_DIRECTORY` | Container path for simulation results |
| `SCENARIO_SIMULATOR_IMAGE` | TIER IV scenario simulator image tag |
| `SCENARIO_READY_TIMEOUT` | Maximum seconds to wait for Autoware readiness before launching the scenario |
| `AUTO_EXTRACT_MAP` | Extract Kashiwanoha from `SCENARIO_SIMULATOR_IMAGE` when `true`; validate the host map only when `false` |
| `MAP_PATH` | Host map directory mounted into Autoware and the scenario simulator at `/autoware_map` |

Example custom scenario:

```bash
SCENARIO=/scenarios/my-scenario.yaml
```

Place scenario files under the host path configured by `SCENARIO_HOST_DIR` (default: `./scenarios/`). Simulation results are saved to `OUTPUT_HOST_PATH` (default: `./output/`).

Custom scenarios must use the Kashiwanoha map unless you also provide a matching host map. For a different map, set `AUTO_EXTRACT_MAP=false`, update `MAP_PATH`, `LANELET2_MAP_FILE`, and `POINTCLOUD_MAP_FILE`, and ensure the files exist under `MAP_PATH` before starting the deployment. The same host map is mounted in the simulator container at `/autoware_map`.

## Stop the Deployment

```bash
docker compose --env-file scenario-simulation.env down
```

For the underlying scenario workflow, see [Scenario test simulation](https://autowarefoundation.github.io/autoware-documentation/main/demos/scenario-simulation/scenario-simulator/scenario-test-simulation/) in the Autoware documentation.
