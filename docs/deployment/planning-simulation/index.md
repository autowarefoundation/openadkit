# Planning Simulation

!!! abstract ""
    The Planning Simulation deployment demonstrates the Open AD Kit planning simulation workflow. It runs the Autoware planning and control stack against a pre-recorded point cloud map, allowing you to set a goal pose and observe the vehicle plan and follow a trajectory in a virtual environment.

## What You Will See

After starting the deployment, you will access a noVNC-based RViz2 visualizer in your browser. From there you can:

- Set an initial pose for the ego vehicle
- Set a goal pose on the map
- Observe the planned trajectory, behavior planning, and control outputs in real time
- Monitor the vehicle as it follows the planned path

## Prerequisites

- Docker Engine (set up via `install.sh`, below)
- Planning simulation map (downloaded below)

!!! tip "GPU"
    A GPU is optional for this deployment. The planning and control components run efficiently on CPU.

## Before You Start

No `git clone` required — set up Docker, then download the self-contained deployment bundle and its demo map.

### 1. Set up the environment (one-time)

```bash
{{ install_command }}
```

### 2. Download the deployment bundle

```bash
curl -fL https://github.com/autowarefoundation/openadkit/releases/latest/download/planning-simulation.tar.gz | tar xz
cd planning-simulation
```

--8<-- "includes/first-release-note.md"

### 3. Download the demo map

```bash
./install.sh sample-data planning-simulation
```

!!! info "About this map"
    This demo map (Copyright 2020 TIER IV, Inc.) is provided for demonstration purposes only. For production use, follow the [Autoware map creation guide](https://autowarefoundation.github.io/autoware-documentation/main/how-to-guides/integrating-autoware/creating-maps/).

## Start the Deployment

From the `planning-simulation` directory, start the containers:

```bash
docker compose --env-file planning-simulation.env up -d
```

--8<-- "includes/cloned-repo-env-note.md"

Wait approximately 10 seconds for the containers to initialize.

--8<-- "includes/visualizer-remote-access.md"

The RViz2 interface may take a few additional seconds to fully load.

## Run the Simulation

Once the visualizer is open, follow the [Autoware planning simulation instructions](https://autowarefoundation.github.io/autoware-documentation/main/demos/planning-sim/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle) to:

1. Set an **initial pose** for the ego vehicle
2. Set a **goal pose** on the map
3. Observe the vehicle autonomously plan and execute the route

## Stop the Deployment

```bash
docker compose --env-file planning-simulation.env down
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Vehicle does not move after setting goal | Check that the initial pose is set correctly and the map is loaded in RViz2 |

For Docker, GPU, and visualizer issues common to all deployments, see [Troubleshooting](../../getting-started/troubleshooting.md).

## Architecture

```mermaid
flowchart LR
    subgraph Host["Single Host"]
        P[planning]
        C[control]
        VIZ[visualizer]
    end

    Map[~/autoware_map] --> P
    P --> C
    P <-->|ROS 2 DDS| VIZ
```

## Related

- [Scenario Simulation](../scenario-simulation/index.md) — Test with predefined traffic scenarios
- [Logging Simulation](../logging-simulation/index.md) — Replay recorded sensor data
- [Components Overview](../../components/index.md) — Learn about the planning and control stack
