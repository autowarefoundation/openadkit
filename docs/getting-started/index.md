# Quickstart

From zero to a running Autoware planning simulation in about 10 minutes. No GPU required.

```mermaid
flowchart LR
    A[Install] --> B[Download] --> C[Start] --> D[Drive]
```

## Prerequisites

- **Ubuntu 22.04 (Jammy) or 24.04 (Noble)** with `sudo` access
- A web browser — the visualizer runs in it, no display server needed

A GPU is **not** needed for this quickstart. For GPU-accelerated deployments and tested machines, see the full [hardware requirements](../platforms/hardware/index.md).

## 1. Install Dependencies

The included `install.sh` sets up Docker Engine and the NVIDIA Container Toolkit in one step:

```bash
{{ install_command }}
```

!!! tip "Skip NVIDIA Toolkit"
    Append `--no-nvidia` to the final command (`install_openadkit --no-nvidia`) if you do not have an NVIDIA GPU. The toolkit is only needed for GPU-accelerated deployments.

--8<-- "includes/docker-group-activation.md"

Confirm the environment is ready:

```bash
docker compose version
```

## 2. Get the Deployment Files

### Source checkout files

```bash
git clone https://github.com/autowarefoundation/openadkit.git
cd openadkit/deployments/planning-simulation
../../install.sh sample-data planning-simulation
```

### Release bundle files

```bash
curl -fL https://github.com/autowarefoundation/openadkit/releases/latest/download/planning-simulation.tar.gz | tar xz
cd planning-simulation
./install.sh sample-data planning-simulation
```

## 3. Start It

### Start the source checkout

```bash
docker compose --env-file ../base/base.env --env-file planning-simulation.env up -d
```

### Start the release bundle

```bash
docker compose --env-file planning-simulation.env up -d
```

Wait about 10 seconds for the containers to initialize.

--8<-- "includes/visualizer-remote-access.md"

## 4. Drive

In RViz2, follow the [Autoware planning simulation instructions](https://autowarefoundation.github.io/autoware-documentation/main/demos/planning-sim/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle) to:

1. Set an **initial pose** for the ego vehicle
2. Set a **goal pose** on the map
3. Watch the vehicle plan and drive the route

That's it — you are running Autoware. The full guide with configuration, architecture, and cloned-repo usage is at [Planning Simulation](../deployment/planning-simulation/index.md).

If something goes wrong, see [Troubleshooting](troubleshooting.md).

## Next Steps

**[Explore the other deployments](../deployment/index.md)** — scenario testing, rosbag replay, closed-loop CARLA, and distributed cloud-edge operation with Zenoh.

- [Components](../components/index.md) — The architecture behind what you just ran
- [Container Images & Versioning](container-images.md) — Tag schema and pinning guidance
- [Custom Deployment](../deployment/custom-deployment.md) — Compose your own stack
