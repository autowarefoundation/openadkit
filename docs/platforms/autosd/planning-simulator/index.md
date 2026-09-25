# AutoSD Planning Simulator

Run Autoware planning and TIER IV Scenario Simulator inside AutoSD as
systemd-managed Podman containers (Quadlet). For the modular Docker Compose
stack with browser RViz2, use
[Planning Simulation](../../../deployments/planning-simulation/index.md)
instead.

## Files

Assets live under
[`platforms/autosd/planning-simulator/`](https://github.com/autowarefoundation/openadkit/tree/main/platforms/autosd/planning-simulator).

| Folder | Contents |
|--------|----------|
| `aib/` | Automotive Image Builder manifest (`image.aib.yml`) and variables (`vars.yml`) |
| `components/container-files/` | Quadlet units for the containers and pod, plus the shared `awf-oak.env` |
| `components/systemd/` | Oneshot service that extracts the map |
| `components/scripts/` | Helper scripts installed into the image |

The image pulls two pinned upstream images, not the Open AD Kit component
images:

- `ghcr.io/autowarefoundation/autoware:universe-0.45.1-amd64`
- `ghcr.io/tier4/scenario_simulator_v2:humble-25.0.20-runtime`

## Services

| Unit | Type | What it does |
|------|------|--------------|
| `awf-oak-map.service` | Oneshot | Extracts the bundled Kashiwanoha map to `/opt/tier4/kashiwanoha_map` |
| `awf-oak-planning.container` | Container | Runs `planning_simulator.launch.xml` with the map at `/etc/awf/map` and RViz disabled |
| `awf-oak-simulator.container` | Container (oneshot) | Runs the bundled `sample.yaml` scenario once, then exits |
| `awf-oak.pod` | Pod | Shared pod for the planning and simulator containers |

Quadlet registers `.container` files as `.service` units, so use
`awf-oak-planning.service` with `systemctl`. Both containers use
`ROS_DOMAIN_ID=26` and `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` from
`awf-oak.env`; use the same values for extra ROS 2 nodes.

## Run

1. [Build an AutoSD image](../index.md#building-an-autosd-image) from this
   directory.
2. Boot it in QEMU or on target hardware.
3. Check the services and follow their logs:

   ```bash
   systemctl status awf-oak-map.service awf-oak-planning.service awf-oak-simulator.service
   journalctl -u awf-oak-planning.service -f
   journalctl -u awf-oak-simulator.service -f
   ```

The scenario runs for a few minutes (90 s initialization plus up to 180 s).
Afterwards `awf-oak-simulator.service` shows `inactive (dead)`; that is expected
for a oneshot. The planning container keeps running.
