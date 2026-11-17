# Glossary

The terms these docs use, one per concept. Each links to the page that covers
it.

## Images

| Term | Meaning |
|------|---------|
| [**Component image**](deployments/components.md) | A published container image holding one or more Autoware functions, for example `planning`. |
| [**Latest alias**](releases/container-images.md#tag-reference) | An image tag such as `planning-humble` that follows the newest stable release. Release tags (`-vX.Y.Z`) and digests never move. |
| [**Digest pin**](releases/container-images.md#choosing-a-tag) | An image reference by content hash (`@sha256:…`) instead of a tag, so the same image bits are always used. |

## Deployments

| Term | Meaning |
|------|---------|
| [**Release**](releases/index.md) | One version of Open AD Kit, such as `v2.0.0`: the CLI, the pinned component images and the catalog. |
| [**Catalog**](deployments/index.md) | The deployments a release ships. `openadkit list` prints it. |
| [**Deployment**](deployments/index.md) | A named, ready-to-run stack for one task, such as Planning Simulation: a deployment manifest, settings and Compose files. A *catalog deployment* is one of the release's; a *kit deployment* is one of a kit's. |
| **Deployment manifest** | `deployment.json`: what the CLI needs to run a deployment and its Compose files do not say: requirements, data downloads, roles and the verify step. |
| [**Verify step**](getting-started/cli.md#run-a-deployment) | The check `openadkit run --verify` runs once a deployment is ready: a command in one of its services, or that service's own exit. |
| [**Launcher**](getting-started/cli.md) | The `openadkit` command: it finds the release or kit to run and hands the command to its CLI. |
| **Release manifest** | `openadkit.json` of a release or a source checkout: its deployments and the images it pins. |
| [**Settings**](getting-started/cli.md#settings) | `KEY=value` variables a deployment runs with, mostly Autoware launch arguments and host paths such as `MAP_PATH`: `settings.env`, then `settings.gpu.env` with `--gpu`, then the host settings. `run` and `restart` apply them. |
| [**Host settings**](getting-started/cli.md#settings) | The settings of one host, in `~/.config/openadkit/<deployment>.env`. They are loaded last and survive upgrades. |
| **One-shot service** | A service that does its work and exits, such as the scenario runner. Its Compose service has `restart: "no"`; it may finish but not fail. |
| [**Role**](deployments/split-host.md) | What one host does in a split-host deployment, such as `autoware` or `scenario`, with its own services, Compose project, ROS domain and Zenoh endpoint. |

## Kits

| Term | Meaning |
|------|---------|
| [**Kit**](kits/create-a-kit.md) | Your packages, parameters and services on top of a pinned release. `openadkit new` makes one. Open AD Kit itself is not a kit. |
| [**Kit manifest**](kits/kit-guide.md#pin-the-release) | `openadkit.json` of a kit: the release it extends, its deployments (each named by its key) and the images it pins. |
| [**`extends`**](kits/kit-guide.md#pin-the-release) | The release a kit pins. |
| [**`base`**](kits/kit-guide.md#choose-a-base-deployment) | The catalog deployment a kit deployment builds on. Only a kit deployment has one. |
| [**Extension point**](kits/kit-guide.md#extension-points) | One of the five ways a kit changes its base: settings, config overrides, the overlay workspace, extra services and image replacement. |
| [**Config override**](kits/kit-guide.md#2-config-overrides) | Parameter and file differences under `config/autoware/`, merged over a package's configuration on every start; not a copy of the full file. `restart` applies them. |
| [**Overlay workspace**](kits/kit-guide.md#3-overlay-workspace) | Your ROS packages in `overlay_ws/`, built in the release's devel image and sourced on top of Autoware. |
| **Integrator** | The person or organization that builds a kit. |
| [**Reference Design**](kits/kit-guide.md#reference-designs) | An Autoware Reference Design: a Deployment Profile and a Reference Software Stack that others can reproduce. A kit holds its software stack. |

## Evidence

| Term | Meaning |
|------|---------|
| [**Evidence cell**](releases/evidence.md#cells-and-levels) | One runtime test of a deployment on one ROS distro and topology, such as `planning-simulation-humble-linux-amd64`. |
| [**Evidence**](releases/evidence.md) | The evidence cells run against one build. A release needs a run in which every cell passed. |
| [**CI exemption**](releases/evidence.md#ci-exemptions) | A reasoned manifest entry for a deployment without a hosted evidence cell. It is not a passing test. |
| [**BOM**](releases/index.md) | A release's bill of materials: the pinned Autoware release, component images and external images. |

## Platforms

| Term | Meaning |
|------|---------|
| [**Mixed criticality**](platforms/autosd.md) | Running safety-critical and non-critical workloads on separately qualified execution environments. Here, the Safety Island's real-time hardware beside the containerized stack; the containers on one host share its network and are not isolated by criticality. |
