# CARLA Simulation

Runs closed-loop CARLA 0.9.16 simulation with modular Open AD Kit containers.
See the [canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/carla-simulation/)
for configuration, launcher options, and troubleshooting.

## Requirements

- Docker with NVIDIA Container Toolkit
- Access to `carlasim/carla:0.9.16`
- Host NVIDIA Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`
- Large UDP buffers:

```bash
sudo sysctl -w net.core.rmem_max=2147483647 net.core.wmem_max=2147483647 \
  net.core.rmem_default=134217728 net.core.wmem_default=134217728
```

## Start

```bash
./start-carla-e2e-demo.sh
```

Use `--drive` to engage and verify movement. A source checkout also supports
`--build`; release bundles use the published image.

## Stop

```bash
# Source checkout
docker compose --env-file ../base/base.env --env-file carla-simulation.env down

# Release bundle
docker compose --env-file carla-simulation.env down
```
