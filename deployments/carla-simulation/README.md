# Open AD Kit CARLA Simulation

This deployment runs closed-loop CARLA 0.9.16 end-to-end simulation with modular Open AD Kit containers and Autoware's `autoware_carla_interface`.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — CARLA Simulation](https://autowarefoundation.github.io/openadkit/deployment/carla-simulation/)**

## Requirements

- Docker with NVIDIA Container Toolkit (`nvidia` runtime configured)
- Access to `carlasim/carla:0.9.16`
- Host X display and container access (`xhost +SI:localuser:root`) only when disabling the default offscreen rendering mode
- Host NVIDIA Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`
- Large kernel UDP buffers:

```bash
sudo sysctl -w net.core.rmem_max=2147483647 net.core.wmem_max=2147483647 \
  net.core.rmem_default=134217728 net.core.wmem_default=134217728
```

## Usage

```bash
./start-carla-e2e-demo.sh
```

The helper validates host prerequisites, downloads checksum-pinned map assets atomically, and then starts CARLA, Autoware modules, and the RViz visualizer. Failed startup or verification removes only services started by that invocation. Use `--drive` to auto-engage and verify movement. In a source checkout, use `--build` to rebuild the CARLA interface image locally; release bundles use the published image and reject this option.

| Flag | Behavior |
|------|----------|
| *(none)* | Start stack, no drive |
| `--drive` | Start + auto-engage + verify movement |
| `--build` | Rebuild CARLA interface image before starting (source checkout only) |
| `--no-drive` | Explicit no-drive (default) |
| `--skip-build` | Skip CARLA interface image rebuild (default) |
| `--skip-verify` | Skip the post-start verification checks |
| `--no-visualizer` | Start without the noVNC visualizer |
| `--dry-run` | Print what would happen without executing |

## Stop

From a source checkout:

```bash
docker compose --env-file ../base/base.env --env-file carla-simulation.env down
```

From a release bundle:

```bash
docker compose --env-file carla-simulation.env down
```
