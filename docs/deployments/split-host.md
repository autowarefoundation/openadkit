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

DDS stays local (`CYCLONEDDS_NETWORK_INTERFACE=lo`, applied by both the
workload containers and the bridge). Only ROS traffic selected by the
workload allowlist crosses Zenoh: simulation time, vehicle status and
commands, transforms, ADAPI calls, and the enabled sensors. Map blobs, camera
images, and the visualization/teleop traffic are not routed.

!!! warning "Verification status"
    Both role views are rendered and validated in CI (`docker compose config`).
    The scenario-simulation and CARLA closed loops have been exercised end to
    end on a lab pair: sample scenarios pass, and a CARLA goal reaches
    `ArrivedGoal` over the bridge. DDS isolation, bridge restart resilience,
    and recorded CARLA throughput/latency evidence are still open. Treat
    split-host roles as unreleased until the remaining gates land with the
    release notes.

## Prerequisites

On both hosts:

- Host setup via [Getting Started](../getting-started/index.md).
- The same Open AD Kit release and ROS distro on both machines.
- Layer-2/3 connectivity between the hosts and `7447/tcp` open **only**
  between them. Topic allowlists are not authentication; do not expose the
  port to a WAN.

Fetch data on the hosts that mount it:

```bash
openadkit fetch scenario-simulation   # both hosts (the runner bind-mounts MAP_PATH)
openadkit fetch carla-simulation      # Autoware host only (the map is autoware-scoped)
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
openadkit run scenario-simulation --role autoware
```

Then the scenario host:

```bash
openadkit run scenario-simulation --role scenario
```

The runner waits up to `SCENARIO_READY_TIMEOUT` for Autoware readiness over
Zenoh before launching the scenario. Results are written on the **scenario**
host under `OUTPUT_HOST_PATH` (`./output`). The visualizer stays on the
Autoware host; noVNC is loopback-only (`WEBSOCKIFY_BIND`), so remote desks use
an SSH tunnel.

Stop each host with its role restored from the live Compose project:

```bash
openadkit stop scenario-simulation
```

## CARLA

Both hosts need an NVIDIA GPU. Start Autoware first:

```bash
# Autoware host
openadkit run carla-simulation --role autoware --gpu
```

Then the CARLA host:

```bash
openadkit run carla-simulation --role carla --gpu
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
before routing anything new, and keep the host boundary on the lab LAN:
the allowlist is not authentication.

The scenario allowlist carries the simple sensor simulator's
`/sensing/imu/imu_data` because autonomous emergency braking and
autonomous-mode availability on the Autoware host depend on it; without
it the vehicle stays in `PLANNING` and the scenario times out.

## Latency and timing

Cross-host simulation is timing sensitive. With a large round-trip time the
TF stream jitters and control nodes log transform or collision-detector
warnings even when scenarios still pass. Keep both hosts on the same lab
LAN; WAN and VPN links are best-effort and are not the supported setup.

## Lifecycle notes

- `--role` is only on `validate` and `run`. The live Compose project records
  the role as an `openadkit.role` label on the Zenoh bridge container.
  `stop`, `status`, and `logs` restore it; you never pass `--role` to them.
- Re-running the same role against a live project keeps the current behavior
  (`up` again). Switching roles or omitting `--role` while a role stack is
  live is refused: stop the project first.
- A running project with no role label uses the single-host compose graph.
- Do not restart a single bridge or interface container while the split is
  live: route churn can leave a bridged topic half-connected until both hosts
  restart. Stop and start the role instead (see Troubleshooting).

## Troubleshooting

If RViz shows no **Auto** button and
`/api/operation_mode/change_to_autonomous` answers "The target mode is not
available", a bridged vehicle-status topic has stopped flowing:

- Diagnosis on the Autoware host: a state monitor logs a bridge topic timeout
  (for example `/vehicle/status/steering_status topic is timeout`), and
  `/system/command_mode/availability` reports autonomous mode unavailable.
- Cause: restarting a single bridge or interface container in a live split
  can leave Zenoh routes half-created (a route is removed and not recreated),
  so the topic no longer crosses.
- Remedy: stop the workload on both hosts and start the roles again
  (`openadkit stop <name>`, then `openadkit run <name> --role ...`). A
  clean restart restores the routes.
