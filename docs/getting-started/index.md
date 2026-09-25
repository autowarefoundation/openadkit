# Quickstart

From zero to a running Autoware planning simulation in about 10 minutes. No GPU is required.

<nav class="oak-quickstart" aria-label="Quickstart steps">
  <ol>
    <li>
      <a href="#get-open-ad-kit">
        <span class="oak-quickstart__number">1</span>
        <span><strong>Get the kit</strong><small>Download or clone</small></span>
      </a>
    </li>
    <li>
      <a href="#set-up-the-host">
        <span class="oak-quickstart__number">2</span>
        <span><strong>Set up the host</strong><small>Configure dependencies</small></span>
      </a>
    </li>
    <li>
      <a href="#run-planning-simulation">
        <span class="oak-quickstart__number">3</span>
        <span><strong>Run simulation</strong><small>Start planning</small></span>
      </a>
    </li>
    <li>
      <a href="#open-the-visualizer">
        <span class="oak-quickstart__number">4</span>
        <span><strong>Open visualizer</strong><small>Inspect the output</small></span>
      </a>
    </li>
    <li>
      <a href="#drive">
        <span class="oak-quickstart__number">5</span>
        <span><strong>Drive</strong><small>Set a route</small></span>
      </a>
    </li>
  </ol>
</nav>

## Prerequisites

- **Ubuntu 22.04 (Jammy) or 24.04 (Noble)** with `sudo` access
- `curl` for the release installer; `python3` and `tar` are preinstalled on supported Ubuntu releases
- A web browser - the visualizer runs in it, no display server needed

## 1. Get Open AD Kit {: #get-open-ad-kit }

--8<-- "includes/first-release-note.md"

=== "Source checkout"

    ```bash
    git clone https://github.com/autowarefoundation/openadkit.git
    cd openadkit
    ```

=== "Release bundle"

    Download the latest release. The command verifies the release bundle before
    installing it to `~/.local/share/openadkit` and makes `openadkit` available
    from `~/.local/bin`.

    ```bash
    curl -fsSL https://github.com/autowarefoundation/openadkit/releases/latest/download/openadkit \
      | bash -s -- install
    ```

    If `~/.local/bin` is not on your `PATH`, the installer prints the command to
    add it. For a reproducible install, replace `latest` with a release version
    and pass the same version to `install`:

    ```bash
    curl -fsSL https://github.com/autowarefoundation/openadkit/releases/download/vX.Y.Z/openadkit \
      | bash -s -- install --version vX.Y.Z
    ```

    To verify the bundle yourself before running it, see
    [Verify a Release Bundle Manually](cli.md#verify-a-release-bundle-manually).

The release bundle contains only the runtime and deployment assets. A source
checkout also contains the image sources, CI, and development tools.

## 2. Set Up the Host {: #set-up-the-host }

After a release install, these commands work from any directory. For a source
checkout, prefix them with `./` (for example `./openadkit`) and run them from
the repository root.

```bash
openadkit setup --verify
```

Run setup as your normal user. It requests `sudo` only for host changes. CPU is
the default; add `--gpu` for NVIDIA deployments. `--gpu` also installs NVIDIA
OpenGL/Vulkan libraries needed for CARLA.

--8<-- "includes/docker-group-activation.md"

## 3. Run Planning Simulation {: #run-planning-simulation }

```bash
openadkit run planning-simulation
```

Add `--ros-distro jazzy` to select Jazzy. Humble is the default in both source
checkouts and release bundles.

`run` downloads and verifies the sample map, pulls missing images, starts the
services, and waits until they are ready.

## 4. Open the Visualizer {: #open-the-visualizer }

Wait about 10 seconds for the containers to initialize, then open:

```text
https://localhost:6080/vnc.html
```

Use the default password **`openadkit`** and accept the self-signed certificate.

For a remote host, keep noVNC loopback-only and forward it over SSH:

```bash
ssh -L 8080:localhost:6080 <user>@<host>
```

Then open `https://localhost:8080/vnc.html` locally.

## 5. Drive {: #drive }

In RViz2, follow the [Autoware planning simulation instructions](https://autowarefoundation.github.io/autoware-documentation/main/demos/planning-sim/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle) to:

1. Set an **initial pose** for the ego vehicle
2. Set a **goal pose** on the map
3. Watch the vehicle plan and drive the route

## Next Steps

**[Explore the other deployments](../deployments/index.md)** - scenario testing,
rosbag replay, and CARLA. Split-host (`--role` over Zenoh) is documented but
unreleased until the remaining two-host gates land.

- [CLI & Maintenance](cli.md) - Runtime controls, validation, upgrades, and cleanup
- [Components](../components/index.md) - The architecture behind what you just ran
- [Container Images & Versioning](container-images.md) - Tag schema and pinning guidance
- [Custom Deployment](../deployments/custom-deployment.md) - Compose your own stack
