# Scenario Simulation

Runs Autoware components with the [TIER IV Scenario Simulator](https://github.com/tier4/scenario_simulator_v2).
Checkout assets live under `deployments/scenario-simulation/`.

## Prerequisites

- Host setup via [`install.sh`](../../../getting-started/index.md)
- Kashiwanoha map (do **not** use `sample-map-planning`):

```bash
./install.sh sample-data scenario-simulation
```

## Run

```bash
cd deployments/scenario-simulation
docker compose \
  --env-file config.env \
  up -d
```

Open `https://localhost:6080/vnc.html` (`REMOTE_PASSWORD` in `config.env`).
The scenario runner waits up to `SCENARIO_READY_TIMEOUT` for Autoware readiness
before launching the one-shot scenario.

## Configuration

Edit `config.env`:

| Variable | Description |
| --- | --- |
| `SCENARIO` | Scenario path inside the container (empty = bundled sample) |
| `SCENARIO_HOST_DIR` | Host dir mounted at `/scenarios` |
| `OUTPUT_HOST_PATH` | Host dir for results |
| `SCENARIO_SIMULATOR_IMAGE` | TIER IV scenario simulator image |
| `SCENARIO_READY_TIMEOUT` | Seconds to wait for Autoware readiness |
| `MAP_PATH` | Host map directory (must match the scenario map) |

Custom scenarios must use the Kashiwanoha map unless you also change `MAP_PATH`
and map filenames consistently.

## Stop

```bash
cd deployments/scenario-simulation
docker compose \
  --env-file config.env \
  down
```

See also [Scenario test simulation](https://autowarefoundation.github.io/autoware-documentation/main/demos/scenario-simulation/scenario-simulator/scenario-test-simulation/)
in the Autoware documentation.
