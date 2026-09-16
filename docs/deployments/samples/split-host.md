# Split-host simulation (Zenoh)

Run the Autoware stack on one lab machine and the simulator on another.
Each workload keeps its catalog name; the split is selected per machine with
`--role`.

- `scenario-simulation`: `--role autoware` on one host, `--role scenario` on
  the other.
- `carla-simulation`: `--role autoware` on one GPU host, `--role carla` on
  the other.

Omitting `--role` keeps today's single-host graph. One role per machine; two
hosts (or two VMs) are required. On a single machine the two roles would share
local DDS and bypass the bridge, so that is not the supported path.

DDS stays local (`CYCLONEDDS_NETWORK_INTERFACE=lo` plus
`ROS_LOCALHOST_ONLY=1` on the bridge). Only ROS traffic selected by the
workload allowlist crosses Zenoh: simulation time, vehicle status and
commands, transforms, ADAPI calls, and the enabled sensors. Map blobs, camera
images, and the visualization/teleop traffic are not routed.

!!! warning "Verification status"
    Both role views are built and validated in CI (`docker compose config`).
    The two-host runtime acceptance gates — full scenario closed loop, DDS
    isolation, and CARLA throughput/latency — have not been recorded yet.
    Treat split-host roles as unreleased until that evidence lands with the
    release notes.

## Prerequisites

On both hosts:

- Host setup via [Getting Started](../../getting-started/index.md).
- The same Open AD Kit release and ROS distro on both machines.
- Layer-2/3 connectivity between the hosts and `7447/tcp` open **only**
  between them. Topic allowlists are not authentication; do not expose the
  port to a WAN.
- Fetch data on both hosts. The scenario host also needs the map because the
  runner bind-mounts `MAP_PATH`:

```bash
./openadkit fetch scenario-simulation   # both hosts
./openadkit fetch carla-simulation      # both hosts (CARLA)
```

## Configure the bridge endpoints

Create or edit `deployments/<workload>/config.local.env` on each host
(gitignored). Use the host's LAN IP, not `0.0.0.0`:

| Host | Variables |
| --- | --- |
| Autoware (`--role autoware`) | `ZENOH_LISTEN=tcp/<autoware-host-ip>:7447` |
| Simulator (`--role scenario` or `--role carla`) | `ZENOH_LISTEN=tcp/<sim-host-ip>:7447` and `ZENOH_PEER=tcp/<autoware-host-ip>:7447` |

The Autoware role is listen-only and starts first. `validate` and `run` on the
connecting role fail fast when `ZENOH_PEER` is unset; `stop`, `status`, and
`logs` never need either variable.

## Scenario simulation

Start Autoware first:

```bash
# Autoware host
./openadkit run scenario-simulation --role autoware
```

Then the scenario host:

```bash
./openadkit run scenario-simulation --role scenario
```

The runner waits up to `SCENARIO_READY_TIMEOUT` for Autoware readiness over
Zenoh before launching the scenario. Results are written on the **scenario**
host under `OUTPUT_HOST_PATH` (`./output`). The visualizer stays on the
Autoware host; noVNC is loopback-only (`WEBSOCKIFY_BIND`), so remote desks use
an SSH tunnel.

Stop each host with its role restored automatically:

```bash
./openadkit stop scenario-simulation
```

## CARLA

Both hosts need an NVIDIA GPU. Start Autoware first:

```bash
# Autoware host
./openadkit run carla-simulation --role autoware --gpu
```

Then the CARLA host:

```bash
./openadkit run carla-simulation --role carla --gpu
```

CARLA RPC (`127.0.0.1:2000`) and map loading stay local to the CARLA host.
The interface publishes simulation time, the enabled lidar/IMU/GNSS sensors,
vehicle status, and transforms; Autoware publishes control commands. Cameras
are disabled in `sensor_mapping.yaml`; enabling them requires an allowlist and
throughput update.

## Allowlist

Each workload ships its Zenoh allowlist in
`deployments/<workload>/config/zenoh.json5`, mounted into the bridge for
role views. Entries are full-name regular expressions, not globs. Both
hosts use the same file: either side can own an endpoint. Review the list
before routing anything new; the workload pages and the
[Zenoh bridge demo](../demos/zenoh-bridge/index.md) cover the standalone
edge/cloud demo, which is a different topology.

## Lifecycle notes

- The CLI records the active role in `deployments/<workload>/.cache/runtime.json`.
  `stop`, `status`, and `logs` restore it; you never pass `--role` to them.
- Re-running the same role against a live project keeps the current behavior
  (`up` again). Switching roles or omitting `--role` while a role stack is
  live is refused: stop the project first.
- If runtime state is missing or unreadable while the project is live, `run`
  refuses and `stop` still removes the project by name.
