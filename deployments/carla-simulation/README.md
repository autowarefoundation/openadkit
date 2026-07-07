# Open AD Kit CARLA Simulation

This deployment runs closed-loop CARLA 0.9.16 end-to-end simulation with modular Open AD Kit containers and Autoware's `autoware_carla_interface`.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — CARLA Simulation](https://autowarefoundation.github.io/openadkit/deployment/carla-simulation/)**

## Requirements

- Docker with NVIDIA Container Toolkit (`nvidia` runtime configured)
- Access to `carlasim/carla:0.9.16`
- Host X display (`DISPLAY=:0`)
- Host X access for containers: `xhost +SI:localuser:root`
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

The helper downloads map assets, starts CARLA, Autoware modules, and the RViz visualizer. Use `--drive` to auto-engage and verify movement. Use `--build` to rebuild the CARLA interface image locally.

| Flag | Behavior |
|------|----------|
| *(none)* | Start stack, no drive |
| `--drive` | Start + auto-engage + verify movement |
| `--build` | Rebuild CARLA interface image before starting |
| `--no-drive` | Explicit no-drive (default) |
| `--skip-build` | Skip CARLA interface image rebuild (default) |
| `--skip-verify` | Skip the post-start verification checks |
| `--no-visualizer` | Start without the noVNC visualizer |
| `--dry-run` | Print what would happen without executing |

## Stop

```bash
docker compose --env-file ../base/base.env --env-file carla-simulation.env down
```
