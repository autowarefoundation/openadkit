# Scenario Simulation

Run predefined traffic scenarios with
[TIER IV Scenario Simulator](https://github.com/tier4/scenario_simulator_v2).
The deployment executes scenarios automatically and writes their results to the
host.

!!! warning "Use the Kashiwanoha map"
    `sample-map-planning` is incompatible and causes invalid-map and MRM errors.

## Setup

```bash
{{ install_command }}
```

--8<-- "includes/docker-group-activation.md"

=== "Source checkout"

    ```bash
    git clone https://github.com/autowarefoundation/openadkit.git
    cd openadkit/deployments/scenario-simulation
    ../../install.sh sample-data scenario-simulation
    ```

=== "Release bundle"

    ```bash
    curl -fL https://github.com/autowarefoundation/openadkit/releases/latest/download/scenario-simulation.tar.gz | tar xz
    cd scenario-simulation
    ./install.sh sample-data scenario-simulation
    ```

## Configuration

Edit `scenario-simulation.env` as needed:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCENARIO` | Scenario path inside the container | Bundled example |
| `SCENARIO_HOST_DIR` | Host scenario directory | `./scenarios` |
| `OUTPUT_HOST_PATH` | Host results directory | `./output` |
| `SCENARIO_READY_TIMEOUT` | Autoware readiness timeout in seconds | `300` |
| `MAP_PATH` | Host map directory | `~/autoware_map/kashiwanoha_map` |

For a custom scenario, place its YAML under `SCENARIO_HOST_DIR` and set, for
example, `SCENARIO=/scenarios/my-scenario.yaml`. A custom map must provide
matching `MAP_PATH`, `LANELET2_MAP_FILE`, and `POINTCLOUD_MAP_FILE` values.

## Run

=== "Source checkout"

    ```bash
    docker compose --env-file ../base/base.env --env-file scenario-simulation.env up -d
    docker compose --env-file ../base/base.env --env-file scenario-simulation.env logs -f scenario_simulator
    ```

=== "Release bundle"

    ```bash
    docker compose --env-file scenario-simulation.env up -d
    docker compose --env-file scenario-simulation.env logs -f scenario_simulator
    ```

Initialization takes about 90 seconds. The runner waits up to
`SCENARIO_READY_TIMEOUT`, executes the scenario, and writes results to
`OUTPUT_HOST_PATH`.

--8<-- "includes/visualizer-remote-access.md"

## Stop and Recover

=== "Source checkout"

    ```bash
    docker compose --env-file ../base/base.env --env-file scenario-simulation.env down
    ```

=== "Release bundle"

    ```bash
    docker compose --env-file scenario-simulation.env down
    ```

Parameter overrides live in `config/mrm_handler.param.yaml` and
`config/default_adapi.param.yaml`. To replace missing map data, run
`../../install.sh sample-data scenario-simulation --force` from a source
checkout or `./install.sh sample-data scenario-simulation --force` from a
bundle. For common issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
