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
add `--gpu` to it for CARLA and for Logging Simulation's CenterPoint models.
`fetch` always includes GPU data.

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

### Port 6080 already in use

Port 6080 serves the visualizer. Stop the service that holds the port. The CLI deployments use host
networking, so adding a `ports:` mapping to `docker-compose.yaml` has no effect.

### ROS 2 nodes on another machine cannot see the stack

DDS stays on loopback by default. To reach other hosts, set
`CYCLONEDDS_NETWORK_INTERFACE` in `deployments/shared/runtime.env` to the exact
LAN or VPN interface name. `ROS_DOMAIN_ID` separates traffic but provides no
authentication or encryption.

## Getting Help

- [GitHub Issues](https://github.com/autowarefoundation/openadkit/issues)
- [Autoware Foundation Discord](https://discord.gg/Q94UsPvReQ)
