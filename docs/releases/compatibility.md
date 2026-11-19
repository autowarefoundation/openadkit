# Compatibility

Open AD Kit follows [Semantic Versioning](https://semver.org/) from v2.0.0.
This page lists what that promise covers. Within one major version:

- **A patch release** (`v2.0.1`) fixes bugs and keeps every item below working.
- **A minor release** (`v2.1.0`) adds features and may move to a newer Autoware
  release. It keeps every item below working. JSON output and manifests can
  gain new fields. A reader of the JSON output ignores a field it does not
  know; the CLI rejects an unknown manifest field, which is why a kit's pinned
  release runs the kit's commands, whichever `openadkit` you called.
- **A major release** (`v3.0.0`) is the only one that removes or changes an item
  below. Its release notes list each change under **Breaking changes**. v2.0.0
  is the [first release](before-v2.md), so its notes have no such list.

[Experimental](#experimental) features and what is
[not covered](#not-covered) can change in any release.

## Covered

### CLI

- The commands and options in `openadkit --help` and `openadkit <command> --help`.
- Exit status:

    | Status | Meaning |
    |--------|---------|
    | `0` | Success |
    | `1` | Failure, with an `error:` line on stderr |
    | `2` | Usage error, such as a missing deployment name |
    | `130` | Interrupted |

    `run --verify` exits with the verify step's own status, and `shell` with
    the status of the shell or command it runs.

- Machine-readable output: `list --json`, `version --json`, `validate --json`
  and each run's `results/run.json`, with the fields in the
  [reference](../kits/reference.md#json-output). Each carries `schemaVersion`.

### Kits

What a kit made with `openadkit new` builds on:

- The kit's manifest, `openadkit.json` at `schemaVersion: 2`: its fields and
  what they mean, as the [reference](../kits/reference.md) lists them.
- The kit's layout: `settings.env`, `config/autoware/` and `overlay_ws/` at its
  root for every deployment, and `deployments/<name>/` for the `settings.env`,
  `config/autoware/` and `compose.yaml` of one. They apply in the order base,
  kit, deployment, host settings file.
- `deployments/shared/services/autoware.yaml`, the service a kit's own services
  extend: the host network, the DDS settings, the config overrides, the overlay
  workspace and the healthcheck that fails when a process of the service's
  `ros2 launch` dies, with its record in `/tmp/openadkit/died`. A service with
  `restart: "no"` is a one-shot service.
- The variables the CLI sets for a kit's Compose files and settings:
  `OPENADKIT_ROOT` (the release), `OPENADKIT_BASE_DEPLOYMENT` (the base's
  directory), `OPENADKIT_KIT` (the kit's root), `OPENADKIT_OVERLAY_WS`,
  `OPENADKIT_DATA_DIR` (the data directory), `ROS_DISTRO` and the
  [component image variables](../kits/reference.md#release-manifest).
- Of each base deployment: its name, the names of its Autoware services (such
  as `planning`, `control` and `map`), its data destination variables (such as
  `MAP_PATH`), its `compose.yaml` as the file a kit includes, and its verify
  step.

See [Create a Kit](../kits/create-a-kit.md) and the
[Kit Guide](../kits/kit-guide.md).

### Settings and Paths

- `OPENADKIT_HOME` and the directories under it.
- The host settings file `~/.config/openadkit/<deployment>.env`, and the
  `results` and `recordings` directories under the output directory.
- These settings of a deployment's `settings.env` and of the host settings
  file: the data destination variables, `VEHICLE_MODEL`, `SENSOR_MODEL`,
  `VEHICLE_ID`, `CYCLONEDDS_NETWORK_INTERFACE`, and the visualizer's
  `REMOTE_DISPLAY`, `REMOTE_PASSWORD`, `RVIZ_CONFIG`, `RVIZ_GPU`,
  `WEBSOCKIFY_BIND`, `NOVNC_CERT` and `NOVNC_KEY`.
- The state on the host: a release reads the run records, data markers and
  overlay workspace builds that any release of the same major version wrote,
  so a kit that pins an older release shares the host with a newer one.

See [CLI & Maintenance](../getting-started/cli.md).

### Images

- Component image names and the tag scheme: release tags, latest aliases and
  the devel image a kit builds its overlay workspace in. See
  [Container Images](container-images.md).
- The images' entrypoint, `/opt/openadkit/entrypoint.sh`: it runs the command
  as the host user (`HOST_UID`, `HOST_GID`), with ROS, Autoware and the overlay
  workspace sourced and the config overrides applied.
- The Autoware packages that the catalog deployments run, in the image that
  [Components](../deployments/components.md) names. They change only with the
  pinned Autoware release; the minor release that moves to it says which
  packages Autoware removed.

### Releases

- The versionless installer and its `install`, `upgrade`, `uninstall` and
  `setup` commands.
- The `openadkit-vX.Y.Z.tar.gz` bundle.
- These fields of `release-metadata.json`, which the installer and
  [Verify a Release](verification.md) read: `version`, `bundles`, `evidence`
  and `bom`.

## Experimental

These work and are tested where the docs say so, but may change in a minor
release:

- **Split-host roles:** `--role`, `roles` in `deployment.json`, the Compose
  files a role lists and the Zenoh bridge. See
  [Split-host Simulation](../deployments/split-host.md).
- **AutoSD with Podman and Quadlet:** `platforms/autosd/` and the units it
  generates. See [AutoSD](../platforms/autosd.md).
- **The Diffusion Planner:** `planning-simulation --gpu`. See
  [Planning Simulation](../deployments/planning-simulation.md#gpu-mode).

## Not Covered

- Human-readable output: messages, tables and their wording.
- The output of `openadkit config`, which is Docker Compose's resolved model.
- A release's own manifests, `openadkit.json` and `deployment.json`, which its
  packaging writes and its own CLI reads.
- Services that are not Autoware's, such as a simulator's, and Autoware
  packages that no catalog deployment runs.
- The other settings in `settings.env`. Most are arguments of Autoware's launch
  files and follow the pinned Autoware release.
- The other fields of `release-metadata.json`, and image labels.
- The CI workflows, everything under `.github/`, and what a developer or CI
  uses to run a source checkout, such as `OPENADKIT_BUILD`.
- Environment variables, files and image internals that this page does not
  list.
