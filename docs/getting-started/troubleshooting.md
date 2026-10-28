# Troubleshooting

--8<-- "includes/cli-command-context.md"

## Docker

### Permission denied

Your user must be in the `docker` group. Log out and back in after
`openadkit setup`, or run `newgrp docker`. Do not run `openadkit` with `sudo`.

### A deployment fails to start

1. Check that Docker is running: `docker info`.
2. Check the configuration: `openadkit validate <deployment> --data`.
3. Read the logs: `openadkit logs <deployment> --follow`.

If `run` fails after the containers are created, they keep running so you can
read their logs. Stop them with `openadkit stop <deployment>`.

## Data

### Missing or incomplete maps, rosbags, or models

```bash
openadkit validate <deployment> --data
openadkit fetch <deployment> --force
```

`validate --data` reports each resource as `ok`, `missing`, or `incomplete`;
add `--gpu` to it for Logging Simulation's CenterPoint models (CARLA always
runs in GPU mode).
`fetch` always includes GPU data. `--force` only replaces data the CLI
installed; remove data you placed yourself, then run `openadkit fetch <deployment>`.

## GPU

### NVIDIA Container Toolkit not detected

- Install it with `openadkit setup --gpu --verify`.
- Check the GPU: `nvidia-smi` and `nvidia-ctk --version`.
- Restart Docker: `sudo systemctl restart docker`.

### Perception is slow

The default perception image runs on CPU. For CUDA perception, run Logging
Simulation with `--gpu` on an amd64 host with an NVIDIA GPU. The CUDA image does
not fall back to CPU.

## Visualizer and Network

### Blank visualizer

Wait 10 to 30 seconds after `run`, then reload the page. If it stays blank,
check `openadkit logs <deployment> --follow`.

### noVNC says "failed to connect"

Open the page over `http://`. Releases up to v2.0.0-rc.7 served noVNC over
HTTPS with a certificate generated at each start: the browser loaded the page
from its cache, never asked about the new certificate, and the WebSocket to it
failed (the visualizer log shows `SSLV3_ALERT_CERTIFICATE_UNKNOWN`). The
visualizer now serves plain HTTP unless you give it a certificate
(`NOVNC_CERT`, `NOVNC_KEY`).

### Port 6080 already in use

Port 6080 serves the visualizer. Stop the service that holds the port. The CLI deployments use host
networking, so adding a `ports:` mapping to `docker-compose.yaml` has no effect.

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
[host settings file](cli.md) (`~/.config/openadkit/<deployment>.env`):

```bash
CYCLONEDDS_NETWORK_INTERFACE=eth0
```

This applies to single-host runs; a split-host node always keeps DDS on
loopback and reaches the other host through its Zenoh bridge.
`ROS_DOMAIN_ID` separates traffic but provides no authentication or encryption.

## Getting Help

- [GitHub Issues](https://github.com/autowarefoundation/openadkit/issues)
- [Autoware Foundation Discord](https://discord.gg/Q94UsPvReQ)
