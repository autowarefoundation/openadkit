# Quickstart

From zero to a running Autoware planning simulation in about 10 minutes. No GPU is required.

## Prerequisites

- **Ubuntu 22.04 (Jammy) or 24.04 (Noble)** with `sudo` access
- 8 CPU cores, 16 GB of RAM and 50 GB of storage or more; see
  [Host Requirements](../platforms/index.md#host-requirements)
- `curl` for the release installer; `python3` and `tar` are preinstalled on
  supported Ubuntu releases
- A web browser: the visualizer runs in it, so no display server is needed

## 1. Install {: #install }

```bash
curl -fsSL https://github.com/autowarefoundation/openadkit/releases/latest/download/openadkit \
  | bash -s -- install
```

The installer verifies the release bundle, installs it to
`~/.local/share/openadkit` and puts `openadkit` in `~/.local/bin`. If that
directory is not on your `PATH`, it prints the command to add it. The bundle
holds the CLI and the deployments; images and sample data are pulled on demand.

??? note "Pin a version, or check the files first"
    For a reproducible install, replace `latest` with a release version and
    pass the same version to `install`:

    ```bash
    curl -fsSL https://github.com/autowarefoundation/openadkit/releases/download/vX.Y.Z/openadkit \
      | bash -s -- install --version vX.Y.Z
    ```

    To check the files yourself before running them, see
    [Verify a Release](../releases/verification.md).

## 2. Set Up the Host {: #set-up-the-host }

```bash
openadkit setup
```

Run setup as your normal user; it asks for `sudo` only for host changes:

- missing packages such as `git` and `curl`
- Docker, when the host has none; it never replaces an existing engine
- your user's membership of the `docker` group
- the kernel's UDP buffer limits, which DDS needs for sensor data
  (`/etc/sysctl.d/99-openadkit-dds.conf`)

It then runs a test container to confirm that Docker works; `--no-check` skips
that on a host that cannot pull it. Add `--gpu` for NVIDIA deployments: it also
installs the NVIDIA Container Toolkit and the OpenGL/Vulkan libraries CARLA
needs, and tests the GPU in a container. It does not install the NVIDIA driver:
install one first, so that `nvidia-smi` works on the host.

--8<-- "includes/docker-group-activation.md"

## 3. Run Planning Simulation {: #run-planning-simulation }

```bash
openadkit run planning-simulation
```

`run` downloads and verifies the sample map, pulls missing images, starts the
services, and returns once Autoware is ready.

Add `--ros-distro jazzy` to select Jazzy; Humble is the default.

## 4. Open the Visualizer {: #open-the-visualizer }

--8<-- "includes/visualizer-remote-access.md"

To open RViz on your own desktop instead of the browser, see
[Visualizer](../deployments/components.md#visualizer).

## 5. Drive {: #drive }

In RViz, follow the [Autoware planning simulation instructions](https://docs.autoware.org/main/simulation/planning-simulation/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle) to:

1. Set an **initial pose** for the ego vehicle
2. Set a **goal pose** on the map; Autoware plans the route
3. Press **AUTO** in the **OperationMode** section of the AutowareStatePanel; the
   vehicle drives the route

## When You Are Done

```bash
openadkit stop
```

`stop` removes the containers. The images and the sample map stay on the host,
so the next `run` starts faster.

## Next Steps

- [Deployments](../deployments/index.md) — scenario testing, rosbag replay, CARLA and Safety Island
- [CLI & Maintenance](cli.md) — runtime controls, settings, upgrades and cleanup
- [Create a Kit](../kits/create-a-kit.md) — your packages, parameters and services on top of a deployment
- [Components](../deployments/components.md) — the images behind what you just ran
- [Troubleshooting](troubleshooting.md) — when something does not start
