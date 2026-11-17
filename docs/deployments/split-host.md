# Split-host Simulation

!!! warning "Experimental"
    Split-host roles may change in a minor release. See
    [Compatibility](../releases/compatibility.md#experimental).

Run the Autoware stack on one lab machine and the simulator on another, bridged
over Zenoh. A deployment keeps its name and declares its **roles** in
`deployment.json`; each machine starts one role with `--role`:

- `scenario-simulation`: `--role autoware` on one host, `--role scenario` on
  the other.
- `carla-simulation`: `--role autoware` on one host, `--role carla` on the
  other; both need an NVIDIA GPU.

Without `--role`, the deployment runs on one host as usual.

## How It Works

Each role lists the Compose files it starts in the deployment's
`deployment.json`: its own services and `compose.zenoh.yaml`, the Zenoh bridge
that carries the deployment's [allowlist](#allowlist). `--role` starts exactly
those files.

Each role is isolated: its own Compose project
(`openadkit-<deployment>_<role>`), container names and ROS domain. The roles
see each other only through the Zenoh bridge, so both can also run on **one
machine** for testing, as long as each listens on its own port (see
[below](#configure-the-bridge-endpoints)).

DDS stays on loopback (`CYCLONEDDS_NETWORK_INTERFACE=lo`) in the role's
containers and in the bridge; a role ignores another interface in the host
settings file. Only the ROS traffic on the deployment's
[allowlist](#allowlist) crosses Zenoh: simulation time, vehicle status and
commands, transforms, AD API calls, the enabled sensors and what the visualizer
shows. Map blobs and camera images are not routed.

!!! warning "Evidence scope"
    CI runs Scenario Simulation's two roles on one hosted runner; two-host runs
    and CARLA are checked by hand on a lab pair. See the
    [Evidence Policy](../releases/evidence.md).

## Prerequisites

On both hosts:

- Host setup as in the [Quickstart](../getting-started/index.md).
- The same Open AD Kit release and ROS distro.
- Layer-2/3 connectivity between the hosts and `7447/tcp` open **only**
  between them. An allowlist is not authentication; do not expose the port to
  a WAN.

Fetch data on the hosts that mount it:

```bash
openadkit fetch scenario-simulation   # both hosts (the runner bind-mounts MAP_PATH)
openadkit fetch carla-simulation      # Autoware host only
```

## Configure the Bridge Endpoints

Create or edit the host settings file,
`~/.config/openadkit/<deployment>.env`, on each host. Use the
host's LAN IP, not `0.0.0.0`:

| Host | Variables |
| --- | --- |
| Autoware (`--role autoware`) | `ZENOH_LISTEN=tcp/<autoware-host-ip>:7447` |
| Simulator (`--role scenario` or `--role carla`) | `ZENOH_LISTEN=tcp/<sim-host-ip>:7447` and `ZENOH_PEER=tcp/<autoware-host-ip>:7447` |

The Autoware role only listens and starts first. `validate` and `run` on the
connecting role fail fast when `ZENOH_PEER` is unset; `stop`, `status` and
`logs` never need either variable.

To run both roles on one machine, pass the endpoints per command instead, with
a separate port for each role. Leave them out of the host settings file then:
a value there wins over the command line.

```bash
ZENOH_LISTEN=tcp/127.0.0.1:7447 openadkit run scenario-simulation --role autoware
ZENOH_LISTEN=tcp/127.0.0.1:7448 ZENOH_PEER=tcp/127.0.0.1:7447 \
  openadkit run scenario-simulation --role scenario
```

## Scenario Simulation

Start Autoware first, then the scenario host:

```bash
openadkit run scenario-simulation --role autoware   # Autoware host
openadkit run scenario-simulation --role scenario   # scenario host
```

The runner waits up to `SCENARIO_READY_TIMEOUT` for Autoware over Zenoh before
it launches the scenario. Results are written on the **scenario** host under
`~/openadkit-output/scenario-simulation/results`. The visualizer runs there
too, so RViz takes no CPU or GPU from Autoware on the Autoware host.

## CARLA

Both hosts need an NVIDIA GPU. Start Autoware first, then the CARLA host:

```bash
openadkit run carla-simulation --role autoware   # Autoware host
openadkit run carla-simulation --role carla      # CARLA host
```

CARLA RPC (`127.0.0.1:2000`) and map loading stay local to the CARLA host.
The interface publishes simulation time, the enabled LiDAR, IMU and GNSS
sensors, vehicle status and transforms; Autoware publishes control commands.
Cameras are disabled in `sensor_mapping.yaml`; enabling them requires an
allowlist and throughput update. The visualizer runs on the CARLA host, where
the raw LiDAR already originates.

## Allowlist

Each deployment ships its Zenoh allowlist in
`deployments/<deployment>/config/zenoh.json5`, mounted into the bridge of
every role. Entries are full-name regular expressions, not globs. Both hosts
use the same file, since either role can own an endpoint. Review the list
before routing anything new.

- **The visualizer's topics** are on both allowlists: planning and control
  output, objects, the vector map marker, `/robot_description` and the AD API
  (`/api/.*`) its panels use. Zenoh sends a topic across only when the other
  host subscribes to it, so without a visualizer these stay on the Autoware host.
- **CARLA's processed point clouds** cross at 2 Hz (`pub_max_frequencies`);
  the point cloud map is not bridged.
- **`/sensing/imu/imu_data`** of the simple sensor simulator is on the
  scenario allowlist because autonomous emergency braking and autonomous-mode
  availability on the Autoware host depend on it. Without it the vehicle stays
  in `PLANNING` and the scenario times out.

## Latency and Timing

Cross-host simulation is timing sensitive. With a large round-trip time the
TF stream jitters and control nodes log transform or collision-detector
warnings even when scenarios still pass. Keep both hosts on the same lab LAN;
WAN and VPN links are best-effort and are not the supported setup.

## Lifecycle Notes

- `status`, `logs`, `restart`, `shell`, `record` and `stop` find the running
  role from its Compose project, so you normally omit `--role`. When several
  roles of one deployment run on the same machine, `status` and `stop` act on
  all of them; pass `--role` to choose one for the other commands.
- Running a role that is already up updates it in place. Starting the
  single-host deployment while a role is running, or a role while the
  single-host deployment is running, is refused: stop it first.

## Troubleshooting

If RViz shows no **Auto** button and
`/api/operation_mode/change_to_autonomous` answers "The target mode is not
available", a bridged vehicle-status topic has stopped flowing:

- **Diagnosis** on the Autoware host: a state monitor logs a bridge topic
  timeout (for example `/vehicle/status/steering_status topic is timeout`),
  and `/system/command_mode/availability` reports autonomous mode unavailable.
- **Cause:** restarting a single bridge or interface container in a running
  split can leave Zenoh routes half-created (a route is removed and not
  recreated), so the topic no longer crosses.
- **Remedy:** stop the deployment on both hosts and start the roles again
  (`openadkit stop`, then `openadkit run <deployment> --role ...`). A clean
  restart restores the routes.
