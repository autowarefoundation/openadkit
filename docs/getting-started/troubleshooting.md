# Troubleshooting

--8<-- "includes/cli-command-context.md"

## A Deployment Fails to Start

1. Check that Docker is running: `docker info`.
2. Check the configuration and the data: `openadkit validate <deployment> --data`.
3. See which services are up: `openadkit status`.
4. Read the logs: `openadkit logs --follow`.

If `run` fails after the containers are created, they stay so you can read
their logs, running or not; `openadkit status` lists them. Remove them with
`openadkit stop`, which another deployment needs before it can start.

## A Service Is Unhealthy

`openadkit status` lists a service as `unhealthy` and names the process that
died, for example `multi_object_tracker_node-4 died with exit code -9`.

`ros2 launch` keeps running when one of its nodes dies, so the container stays
up and the service's other nodes keep working. Nothing restarts the service: on
a vehicle, one failed node must not take its whole service down mid-drive.

1. Read why the node died: `openadkit logs <service>`.
2. Start the service again: `openadkit restart <service>`.

- When the process is a component container, such as
  `component_container_mt-1`, one of the nodes it hosts crashed it. The logs
  name that node.
- A service whose launch file starts one process ends with it: `status` then
  shows the service as exited, and `openadkit restart <service>` starts it
  again.
- `run` and `restart` fail when a node dies while the deployment starts, and
  name the service. A map loader that dies there usually
  cannot find a file: check `MAP_PATH` and the file names in
  `LANELET2_MAP_FILE` and `POINTCLOUD_MAP_FILE`.
- The `api` service reports a dead node within three minutes, the others within
  ten seconds: its check also covers Autoware's readiness and runs less often.
- A component that fails to load into a running container is not a process that
  died, and does not show here. It shows in the logs.

## Docker

### Permission denied

Your user must be in the `docker` group. Log out and back in after
`openadkit setup`, or run `newgrp docker`. Do not run `openadkit` with `sudo`.

### Docker Compose is too old

`openadkit setup` stops when Docker is installed but Docker Compose 5.0 or
newer is missing. Install Docker's `docker-compose-plugin`
([instructions](https://docs.docker.com/compose/install/linux/)) and rerun
setup. Ubuntu's own `docker-compose-v2` package is too old.

## Data

### Missing or incomplete maps, rosbags, or models

```bash
openadkit validate <deployment> --data
openadkit fetch <deployment>            # missing or outdated data
openadkit fetch <deployment> --force    # incomplete data
```

`validate --data` reports each resource as `ok`, `missing`, `incomplete` or
`outdated`, and a directory of your own as `own`; add `--gpu` to include the
data of a GPU mode, such as Logging Simulation's CenterPoint models. `fetch`
always includes it. `--force` only replaces data the CLI installed, and leaves
a directory of your own alone. See
[Downloaded Data](cli.md#downloaded-data).

## GPU

### NVIDIA Container Toolkit not detected

- Install it with `openadkit setup --gpu`.
- Check the GPU: `nvidia-smi` and `nvidia-ctk --version`.
- Restart Docker: `sudo systemctl restart docker`.

### Perception is slow

The default perception image runs on CPU. For CUDA perception, run Logging
Simulation with `--gpu` on an amd64 host with an NVIDIA GPU. The CUDA image does
not fall back to CPU.

## Visualizer and Network

### Blank visualizer

Wait 10 to 30 seconds after `run`, then reload the page. If it stays blank,
check `openadkit logs --follow`.

### noVNC says "failed to connect"

Open the page over `http://`. The visualizer serves plain HTTP unless you give
it a certificate (`NOVNC_CERT`, `NOVNC_KEY`); with one, open it over
`https://`.

### Port 6080 already in use

Port 6080 serves the visualizer. Stop the service that holds the port. The
deployments use host networking, so a `ports:` mapping in `compose.yaml`
has no effect.

### Point clouds arrive at a lower rate than they are published

Large messages need large UDP buffers between the containers.
`deployments/shared/cyclonedds.xml` requests them, and `openadkit setup` raises
the kernel limits that cap them (`/etc/sysctl.d/99-openadkit-dds.conf`). Check
the limit and whether the kernel drops packets:

```bash
sysctl net.core.rmem_max      # 2147483647 after setup
nstat -az UdpRcvbufErrors     # a growing count means drops
```

### ROS 2 nodes on another machine cannot see the stack

DDS stays on loopback by default. To reach other hosts, set
`CYCLONEDDS_NETWORK_INTERFACE` to the exact LAN or VPN interface name in your
[host settings file](cli.md#settings)
(`~/.config/openadkit/<deployment>.env`):

```bash
CYCLONEDDS_NETWORK_INTERFACE=eth0
```

The other host's nodes also need the stack's ROS domain, `ROS_DOMAIN_ID=1`,
and Cyclone DDS (`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`). This applies to single-host runs; a
split-host role always keeps DDS on loopback and reaches the other host through
its Zenoh bridge. `ROS_DOMAIN_ID` separates traffic but provides no
authentication or encryption.

## Getting Help

- [GitHub Issues](https://github.com/autowarefoundation/openadkit/issues)
- [Autoware Foundation Discord](https://discord.gg/Q94UsPvReQ)
