# Planning Simulation

Run the Autoware planning and control stack against a demo point cloud map,
then set an initial pose and goal in browser-based RViz2. A GPU is optional.

## Setup

Install Docker once:

```bash
{{ install_command }}
```

--8<-- "includes/docker-group-activation.md"

Choose one layout and download the map:

=== "Source checkout"

    ```bash
    git clone https://github.com/autowarefoundation/openadkit.git
    cd openadkit/deployments/planning-simulation
    ../../install.sh sample-data planning-simulation
    ```

=== "Release bundle"

    ```bash
    curl -fL https://github.com/autowarefoundation/openadkit/releases/latest/download/planning-simulation.tar.gz | tar xz
    cd planning-simulation
    ./install.sh sample-data planning-simulation
    ```

The demo map is Copyright 2020 TIER IV, Inc. and is provided for demonstration
only.

## Run

=== "Source checkout"

    ```bash
    docker compose --env-file ../base/base.env --env-file planning-simulation.env up -d
    ```

=== "Release bundle"

    ```bash
    docker compose --env-file planning-simulation.env up -d
    ```

--8<-- "includes/visualizer-remote-access.md"

In RViz2, set the initial pose, set a goal pose, and observe the planned route.
See the [Autoware planning simulation guide](https://autowarefoundation.github.io/autoware-documentation/main/demos/planning-sim/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle)
for the RViz workflow.

## Stop and Recover

=== "Source checkout"

    ```bash
    docker compose --env-file ../base/base.env --env-file planning-simulation.env down
    ```

=== "Release bundle"

    ```bash
    docker compose --env-file planning-simulation.env down
    ```

To replace missing or incomplete map data, run
`../../install.sh sample-data planning-simulation --force` from a source
checkout or `./install.sh sample-data planning-simulation --force` from a
release bundle. For common Docker and visualizer issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
