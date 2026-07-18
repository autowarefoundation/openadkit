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

### 1. Set up the environment (one-time)

```bash
{{ install_command }}
```

--8<-- "includes/docker-group-activation.md"

### 2. Choose a deployment layout

#### Source checkout setup

```bash
git clone https://github.com/autowarefoundation/openadkit.git
cd openadkit/deployments/planning-simulation
../../install.sh sample-data planning-simulation
```

#### Release bundle setup

```bash
curl -fL https://github.com/autowarefoundation/openadkit/releases/latest/download/planning-simulation.tar.gz | tar xz
cd planning-simulation
./install.sh sample-data planning-simulation
```

!!! info "About this map"
    This demo map (Copyright 2020 TIER IV, Inc.) is provided for demonstration purposes only. For production use, follow the [Autoware map creation guide](https://autowarefoundation.github.io/autoware-documentation/main/how-to-guides/integrating-autoware/creating-maps/).

## Start the Deployment

From the `planning-simulation` directory, use the command for your layout.

### Start from a source checkout

```bash
docker compose --env-file ../base/base.env --env-file planning-simulation.env up -d
```

### Start from a release bundle

```bash
docker compose --env-file planning-simulation.env up -d
```

Wait approximately 10 seconds for the containers to initialize.

--8<-- "includes/visualizer-remote-access.md"

The RViz2 interface may take a few additional seconds to fully load.

## View Logs

### View source checkout logs

```bash
docker compose --env-file ../base/base.env --env-file planning-simulation.env logs -f
```

### View release bundle logs

```bash
docker compose --env-file planning-simulation.env logs -f
```

## Run the Simulation

Once the visualizer is open, follow the [Autoware planning simulation instructions](https://autowarefoundation.github.io/autoware-documentation/main/demos/planning-sim/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle) to:

1. Set an **initial pose** for the ego vehicle
2. Set a **goal pose** on the map
3. Observe the vehicle autonomously plan and execute the route

## Stop the Deployment

### Stop a source checkout

```bash
docker compose --env-file ../base/base.env --env-file planning-simulation.env down
```

### Stop a release bundle

```bash
docker compose --env-file planning-simulation.env down
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Vehicle does not move after setting goal | Check that the initial pose is set correctly and the map is loaded in RViz2 |

To re-download the map:

```bash
# Source checkout
../../install.sh sample-data planning-simulation --force

# Release bundle
./install.sh sample-data planning-simulation --force
```

For Docker, GPU, and visualizer issues common to all deployments, see [Troubleshooting](../../getting-started/troubleshooting.md).

## Architecture

```mermaid
flowchart LR
    subgraph Host["Single Host"]
        M[map]
        P[planning]
        C[control]
        V[vehicle]
        S[system]
        SIM[simulator]
        API[API]
        VIZ[visualizer]
    end

    Map[~/autoware_map] --> M
    M --> P
    P --> C
    C --> V
    SIM <-->|ROS 2 DDS| V
    S <-->|ROS 2 DDS| API
    P <-->|ROS 2 DDS| VIZ
```

## Related

- [Scenario Simulation](../scenario-simulation/index.md) — Test with predefined traffic scenarios
- [Logging Simulation](../logging-simulation/index.md) — Replay recorded sensor data
- [Components Overview](../../components/index.md) — Learn about the planning and control stack
