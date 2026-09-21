# Troubleshooting

This page covers common issues and solutions when working with Open AD Kit.

--8<-- "includes/cli-command-context.md"

## Docker Issues

### Container fails to start

- Verify Docker Engine is running: `docker info`
- Check that required ports are not already in use
- Ensure the deployment has its `config.env` and `deployment.json` (the bundle
  root has `openadkit.json`). Put local overrides in `config.local.env`, then run
  `openadkit validate <deployment>`.

### Permission denied

- Make sure your user is in the `docker` group; do not run runtime commands with
  `sudo`
- Check file permissions on mounted volumes

## GPU Issues

### NVIDIA Container Toolkit not detected

- Verify installation: `nvidia-ctk --version`
- Restart Docker: `sudo systemctl restart docker`
- Check GPU availability: `nvidia-smi`

### Perception is very slow or the GPU overlay does not start

- The default sensing and perception image runs on CPU.
- A deployment selects `sensing-perception-cuda` instead: Logging Simulation
  through its GPU overlay, CARLA Simulation by default.
- The CUDA image needs a working NVIDIA runtime and does not fall back to CPU.
  Install the NVIDIA Container Toolkit with `openadkit setup --gpu`.

## Deployment Issues

### Visualizer shows blank screen

- Wait 10–30 seconds for containers to fully initialize
- Check container logs with `openadkit logs <deployment> --follow`.
- Verify all required map files are present

### Port 6080 or 6081 already in use

- Stop the conflicting service. Most deployments run the visualizer under
  `network_mode: host`, which binds the port directly; `ports:` mappings in
  `docker-compose.yaml` are ignored in that mode.

### Sample data or artifacts `file not found`

Recovery depends on the deployment:

| Deployment | Recover |
|------------|---------|
| `planning-simulation`, `scenario-simulation` | Run `openadkit fetch <deployment> --force`. Maps land under `~/autoware_map`. |
| `logging-simulation` | Run `openadkit fetch logging-simulation --force` for the map and rosbag; the fetch also refreshes the CenterPoint models under `~/autoware_data/lidar_centerpoint`. |
| `zenoh-bridge` | From the source root, run `./openadkit fetch scenario-simulation --force` to refresh its Kashiwanoha map. |
| `carla-simulation` | Run `openadkit fetch carla-simulation --force` for the Town01 map. |

To see what is missing before downloading anything, run
`openadkit validate <deployment> --data`. It reports each selected data resource
as `ok`, `missing`, or `incomplete`, using the same GPU selection as `run`.
Add `--gpu` for CARLA and for Logging Simulation CenterPoint:
`openadkit validate carla-simulation --gpu --data` and
`openadkit validate logging-simulation --gpu --data`.

## Getting Help

- [GitHub Issues](https://github.com/autowarefoundation/openadkit/issues)
- [Autoware Foundation Discord](https://discord.gg/Q94UsPvReQ)
