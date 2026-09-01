# Troubleshooting

This page covers common issues and solutions when working with Open AD Kit.

## Docker Issues

### Container fails to start

- Verify Docker Engine is running: `docker info`
- Check that required ports are not already in use
- Ensure the deployment has its `config.env` and `openadkit.json`. Put local
  overrides in `config.local.env`, then run `./openadkit validate <deployment>`.

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

- The default sensing and perception image runs on CPU except where a deployment
  selects `sensing-perception-cuda` (Logging Simulation GPU overlay;
  CARLA Simulation by default). Install the NVIDIA Container Toolkit
  (`./openadkit setup --gpu` does this explicitly). The CUDA image requires a working NVIDIA
  runtime and does not automatically fall back to CPU.

## Deployment Issues

### Visualizer shows blank screen

- Wait 10–30 seconds for containers to fully initialize
- Check container logs with `./openadkit logs <deployment> --follow`.
- Verify all required map files are present

### Port 6080 or 6081 already in use

- Stop the conflicting service. Most deployments run the visualizer under `network_mode: host`, which binds the port directly — `ports:` mappings in `docker-compose.yaml` are ignored in that mode.

### Sample data or artifacts `file not found`

Recovery depends on the deployment:

| Deployment | Recover |
|------------|---------|
| `planning-simulation`, `scenario-simulation` | Run `./openadkit fetch <deployment> --force`. Maps land under `~/autoware_map`. |
| `logging-simulation` | Run `./openadkit fetch logging-simulation --force` for the map and rosbag. GPU perception models remain under `~/autoware_data`. |
| `zenoh-bridge` | From the source root, run `./openadkit fetch scenario-simulation --force` to refresh its Kashiwanoha map. |
| `carla-simulation` | Run `./openadkit fetch carla-simulation --force` for the Town01 map. |

## Getting Help

- [GitHub Issues](https://github.com/autowarefoundation/openadkit/issues)
- [Autoware Foundation Discord](https://discord.gg/Q94UsPvReQ)

## Related

- [Getting Started](index.md) — Quick start guide
- [Container Images & Versioning](container-images.md) — Tag schema and version policy
- [Deployments](../deployment/index.md) — Self-contained deployments
