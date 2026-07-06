# Troubleshooting

This page covers common issues and solutions when working with Open AD Kit.

## Docker Issues

### Container fails to start

- Verify Docker Engine is running: `docker info`
- Check that required ports are not already in use
- Ensure the correct environment file exists and is correctly configured. Each [deployment](../deployment/index.md) ships with its own `.env` file (e.g. `planning-simulation.env`, `logging-simulation.env`) — confirm you are running `docker compose` from the deployment directory that contains it. If running from a cloned repository, also pass `--env-file ../base/base.env`.

### Permission denied

- Make sure your user is in the `docker` group, or use `sudo`
- Check file permissions on mounted volumes

## GPU Issues

### NVIDIA Container Toolkit not detected

- Verify installation: `nvidia-ctk --version`
- Restart Docker: `sudo systemctl restart docker`
- Check GPU availability: `nvidia-smi`

### Perception is very slow

- The sensing and perception pipeline is falling back to CPU. Install the NVIDIA Container Toolkit (`install.sh` does this by default) and, for Logging Simulation, start with the GPU overlay described on that page.

## Deployment Issues

### Visualizer shows blank screen

- Wait 10–30 seconds for containers to fully initialize
- Check container logs: `docker compose --env-file <deployment>.env logs -f` (replace `<deployment>` with the actual env file name, e.g. `planning-simulation.env`)
- Verify all required map files are present

### Port 6080 or 6081 already in use

- Stop the conflicting service. Most deployments run the visualizer under `network_mode: host`, which binds the port directly — `ports:` mappings in `docker-compose.yaml` are ignored in that mode.

### Sample data `file not found`

- Re-run the fetch with `--force` from the deployment directory: `./install.sh sample-data <deployment> --force` (e.g. `planning-simulation`). Data lands in `~/autoware_map`.

## Getting Help

- [GitHub Issues](https://github.com/autowarefoundation/openadkit/issues)
- [Autoware Foundation Discord](https://discord.gg/Q94UsPvReQ)

## Related

- [Getting Started](index.md) — Quick start guide
- [Container Images & Versioning](container-images.md) — Tag schema and version policy
- [Deployments](../deployment/index.md) — Self-contained deployments
