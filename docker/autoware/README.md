# Open AD Kit - Autoware

Runs Autoware in a container.

## Standalone Run

```bash
docker run --rm --name autoware ghcr.io/autowarefoundation/openadkit:autoware
```

## Settings

The following environment variables can be passed to the `autoware` container:

| Variable          | Default Value                  | Possible Values | Description                                                                                                                            |
| ----------------- | ------------------------------ | --------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `RUN_MODE`        | `planning-simulator`           | `planning-simulator`, `autoware` | The mode to run Autoware in.                                                                                                          |
| `SCENARIO_SIMULATION` | `false`                        | `true`, `false` | Set to `true` to launch Autoware for scenario simulation. Only effective when `RUN_MODE=planning-simulator`. |
| `MAP_PATH`        | `/root/autoware_map`           | Any valid path  | The path to the map file.                                                                                                            |
| `SENSOR_MODEL`    | `sample_sensor_kit`            | Any valid sensor model      | The sensor model to use                                                                                 |
| `VEHICLE_MODEL`   | `sample_vehicle`               | Any valid vehicle model     | The vehicle model to use                                                                                 |
| `USE_SIM_TIME`    | `false`                         | `true`, `false` | Set to `true` to use simulation time.                                                                                              |
