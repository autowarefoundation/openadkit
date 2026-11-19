# Kit Guide

The reference for a kit: what it pins, each extension point, and how it is
validated and upgraded. A kit owns its differences; Open AD Kit owns the
CLI, the images and the catalog. Start one with `openadkit new`
([Create a Kit](create-a-kit.md)).

## Pin the Release

In the kit's `openadkit.json`, `kind` is `kit` and `extends` names a published
release tag or, for development, the path of a source checkout. The kit's
`openadkit.json` has `schemaVersion: 2`.

- **The pinned release runs the kit.** The CLI finds it under
  `~/.local/share/openadkit/openadkit-<tag>` (`releases/` under
  `OPENADKIT_HOME` when set) and hands the command to its launcher. A missing version is
  downloaded and verified on first use, as a build tool's wrapper does; your
  active `openadkit` stays as it is.
- **Only the commands that act on a kit download it:** `validate`, `config`,
  `fetch`, `run`, `build` and `clean`. `list`, `version` and Tab completion
  run with the pinned release when it is installed; while it is missing, they
  stop and name it. `--help` is always that of the CLI you called. A directory
  you only look at starts no download and no program that it names.
- **One level of `extends`:** a kit extends Open AD Kit, not another kit.

## Choose a Base Deployment

Each deployment of a kit names a `base` deployment of the pinned release in
its entry of the kit's `openadkit.json`:
`"deployments": { "<name>": { "base": "planning-simulation" } }`. The entry may
also hold `description`, `requirements`, `data`, `verify` and `waitTimeout`;
the [reference](reference.md#deployment-entry) lists their fields.

- **Requirements** (architectures, ROS distros, GPU) are inherited.
  `requirements` may narrow them: fewer architectures or ROS distros, or `gpu`
  set to `none` or `required` where the base leaves it optional. It never
  widens them, since the kit runs the base's services. Without a GPU mode, the
  base's GPU-only downloads are left out.
- **Downloads and one-shot services** are inherited. A kit can add downloads
  and one-shot services of its own. A download whose `destinationEnv` a base's
  download has, such as `ROSBAG_PATH`, replaces that one. Set that variable in
  the deployment's own `deployments/<name>/settings.env` too, so the download
  gets a directory of its own.
- **Split-host roles are not inherited:** a kit deployment runs on one host.

### What Applies Where

| Files | At the kit root | In `deployments/<name>/` |
| --- | --- | --- |
| `settings.env`, `settings.gpu.env` | Every deployment | That deployment, after the kit's |
| `config/autoware/` | Every deployment | That deployment, after the kit's |
| `overlay_ws/` | Every deployment | Not read |
| `compose.yaml` | Not read | That deployment's services |

The CLI warns about a `compose.yaml` at the kit root and about a directory
under `deployments/` that holds a deployment's files but matches no name in
`openadkit.json`.

The kit root is your vehicle's layer. A setting or a parameter that a
deployment does not use does no harm there. A Compose file is different: a
service depends on other services, and not every base has them, so each
deployment has its own. A deployment's name is also its Compose project, its
host settings file and its output directory, so keep it unique among the kits
on one host.

## Extension Points

### 1. Settings

Put only differences in the kit's `settings.env`, and what one deployment alone
needs in `deployments/<name>/settings.env`. Compose reads these files in order
(later files win); each `settings.gpu.env` follows its `settings.env` when GPU
mode is selected:

1. The base's `settings.env`
2. The kit's `settings.env`, if present
3. The deployment's `settings.env`, if present
4. The host settings file, `~/.config/openadkit/<deployment>.env`, if present

Shell exports do not override values set in these files. The CLI adds the ROS
distro, the host UID and GID, the config override and overlay workspace mounts,
`OPENADKIT_ROOT` (the release's root), `OPENADKIT_BASE_DEPLOYMENT` (the
directory of the `base` deployment) and `OPENADKIT_KIT` (the kit's root); a
release's component and external images stay pinned. Inside the containers, the
ROS and DDS defaults come from the base services' `runtime.env`.

A setting that names a file of the kit builds its path on `OPENADKIT_KIT`. A
relative path would resolve inside the release, next to the base's Compose
file:

```bash
SCENARIO_HOST_PATH=${OPENADKIT_KIT}/scenarios
```

### 2. Config Overrides

Store overrides under
`config/autoware/<package>/<path-relative-to-package-share>` at the kit root,
or in `deployments/<name>/` for one deployment. For example,
`config/autoware/autoware_control_config/config/lane_departure_checker/lane_departure_checker.param.yaml`:

```yaml
/**:
  ros__parameters:
    update_rate: 20.0
```

On each start the images' entrypoint merges the overrides over the package's
own files: the base deployment's layer, then the kit's, then the deployment's.
YAML mappings merge recursively; scalars and lists replace the old value, and a
non-YAML file replaces its counterpart. Nothing is written into the image:
remove an override and restart to return to the remaining layers.

An override without a counterpart is a warning, not a startup failure. Once the
services are up, `run` names each one: a package that no service has, or a
file or parameter its package does not have. That is intended for a new file
such as a diagnostics graph; after a release change it usually means a renamed
package, file or parameter.

### 3. Overlay Workspace

Put ROS packages in `overlay_ws/src` and build them in the
`universe-common-devel` image from the **same build** as your runtime images.
A release pins that image next to its runtime images, so the CLI builds with
the right one:

```bash
openadkit build [--ros-distro humble]   # in the kit: its overlay_ws
openadkit build PATH                    # any workspace, with the pins of the kit around it
openadkit build -- --packages-select my_pkg                # arguments after -- go to colcon build
openadkit build -- --cmake-args -DCMAKE_BUILD_TYPE=Debug   # Release unless you set another
```

#### Build

- Packages build incrementally: a second build compiles only what changed.
- The CLI records the image and distro in `install/.openadkit-overlay.json`.
  After a release upgrade or a distro change, `validate`, `run` and `restart`
  stop and name the rebuild; that rebuild starts from a clean `build/` and
  `install/`, since CMake caches record the paths they were configured with.
- Without `--ros-distro`, the build uses the release's default distro, or
  the first one that every kit deployment runs on.
- A `build/` or `install/` that `openadkit build` did not make, such as a colcon
  build on the host, stops the build; remove them first.
- `--install-base` and `--build-base` stay fixed: the services source
  `install/` where they mount the workspace.
- On a source checkout, the build uses the devel image of the build the
  runtime images come from: the
  [local build](../development/build-from-source.md#build-and-run-locally)'s,
  or the one of the CI build `OPENADKIT_BUILD` names.

#### Run

The workspace belongs to the kit: the one `overlay_ws` at the kit root serves
every deployment of the kit, since they all extend one release and its images.
Every Autoware service mounts it, and the image entrypoint sources
`overlay_ws/install/local_setup.bash` on top of Autoware, so its packages are
visible in every service. Whether your code runs depends on what starts it:

- A changed copy of an Autoware package shadows the image's own. It runs where
  Autoware already launches that package, with nothing more to configure;
  Autoware packages that link against its library keep the copy they were
  built with.
- A new node runs only where something starts it: an extra service (as the
  [example kit](https://github.com/autowarefoundation/openadkit/tree/main/.github/scripts/evidence/example-kit)'s `acme-probe`), a launch file you override under
  `config/autoware`, or by hand with
  `openadkit shell <service> ros2 run <package> <node>`.

#### Without a Kit

To try a workspace with a catalog deployment, without writing a kit, mount it
with `--ws`:

```bash
openadkit build ~/my_ws
openadkit run planning-simulation --ws ~/my_ws
```

`--ws` is for a deployment without packages of its own; on a kit whose
`overlay_ws/src` holds packages it is an error rather than a second layer.

#### ABI

The devel and runtime images install ROS packages from the same
[ROS snapshot](../releases/container-images.md#ros-package-snapshot), so
an overlay built in the devel image links the ROS versions the runtime image
ships. A dependency you add must also exist in the runtime image; the overlay
cannot install packages. The example kit's C++ node links `diagnostic_updater`
deliberately to test this devel/runtime boundary, then publishes `/acme/probe`.

### 4. Extra Services

A deployment without a `compose.yaml` runs its base's services. To add or
change services, write `deployments/<name>/compose.yaml`: include the base's
Compose file through `OPENADKIT_BASE_DEPLOYMENT`, then define your services
under `services:`.

```yaml
include:
  - ${OPENADKIT_BASE_DEPLOYMENT}/compose.yaml

services:
  ota-agent:
    image: ${OTA_AGENT_IMAGE:?pinned in openadkit.json externalImages}
    init: true
```

Keep communicating ROS services on the base ROS domain and middleware, and give
each one `init: true`
([Develop and Debug](develop-and-debug.md#the-development-loop)). A service
that is already in the base changes the same way: name it and set only what
differs.

- **A service that runs `ros2 launch`** also sets `pid: service:map`, as the
  base's Autoware services and the example kit's `acme-probe` do. `ros2 launch` names its own node after its PID,
  and in separate PID namespaces every launch gets the same one: Autoware then
  reports the repeated node name as an error, and autonomous mode becomes
  unavailable.
- **With `--gpu`**, the base's `compose.gpu.yaml` applies after your
  `compose.yaml`, so what it sets for a service, such as the CUDA image of
  `planning`, wins over yours. A kit deployment has no `compose.gpu.yaml` of
  its own; its `settings.gpu.env` is read.

A service that several deployments of the kit run goes in a file of its own,
such as `services/ota-agent.yaml` at the kit root, which each of their Compose
files includes next to the base. Compose resolves the relative paths of an
included file against that file's own directory.

An extra service on an Open AD Kit runtime image extends
`${OPENADKIT_ROOT}/deployments/shared/services/autoware.yaml`, as the example
kit's `acme-probe` does. That gives it what the base's Autoware services share:
the host network, the ROS domain and DDS settings, the config overrides and the
kit workspace at `/openadkit/overlay_ws`. It also turns unhealthy when a
process of its `ros2 launch` dies
([A Service Is Unhealthy](../getting-started/troubleshooting.md#a-service-is-unhealthy)).
A `healthcheck` of its own replaces that check. To keep it, start the command
with `! cat /tmp/openadkit/died 2>/dev/null &&`, as `acme-probe` does.

Such a service needs no image of its own: a runtime image and the workspace are
enough. Build your own image only for what the runtime images lack, such as a
system package or a non-ROS application, and declare it as an external image
([point 5](#5-image-replacement)).

To replace one role of a base that runs as split-host roles, include only the
other role's Compose file instead of the base's `compose.yaml`. For
example, a kit that brings its own simulator to `carla-simulation` includes
`${OPENADKIT_BASE_DEPLOYMENT}/compose.autoware.yaml`: no service in it depends
on a CARLA service. A kit that leaves out the service of its base's verify step
has none, until it names its own.

### 5. Image Replacement

Declare the images your kit uses but does not build in its `externalImages`,
each with either one digest-pinned `ref` or a `distros` map of digest-pinned
references. A name matching a component image variable replaces that
component; other names supply images for new services. Use `${NAME:?}` in
Compose to require the declared reference.

A replaced component image needs your own runtime evidence: pinning alone does not
prove that it honors the entrypoint, launch or parameter interfaces.

## Validation and Evidence

`openadkit validate` renders the deployment and checks its manifest (and, with
`--data`, its data). It does not pull images or prove that the runtime works;
`run` reports overrides without a counterpart (see
[Config Overrides](#2-config-overrides)).

Your kit's acceptance checks run where CI runs its own:

- **Readiness:** give a service of your own a Compose `healthcheck`. `run`
  waits until it passes. The example kit's `acme-probe` service runs
  `checks/example_kit.py`, which checks the fresh `/acme/probe` publication of
  its C++ package and its parameters.
- **End to end:** the base's `verify` step runs on top of your layer with
  `openadkit run --verify`. To check something else, name your own in the
  deployment's manifest entry: `{"verify": {"service": "<service>", "command": [...]}}`
  runs the command in that running service, and without `command` the step
  waits for the service to exit and takes its exit code.

Every release runs both checks on the
[example kit](../releases/evidence.md#cells-and-levels), which uses every
extension point. That shows the extension points work on the build; it does
not verify your kit.

A base deployment's CI exemption stays with the kit; an exemption is not
runtime evidence.

## Upgrade Without Losing Your Work

Update `extends` (the next command downloads that release), rebuild your
workspace against its devel digest, then validate and run your acceptance
checks. Your repository, host settings, downloaded data and output directories
are outside the release, and `openadkit upgrade` does not change a kit's
`extends`. See [Settings](../getting-started/cli.md#settings) and
[Downloaded Data](../getting-started/cli.md#downloaded-data).

## Reference Designs

An [Autoware Reference Design](https://docs.autoware.org/main/reference-design/)
combines a Deployment Profile (the vehicle, the operating conditions and the
use case) with a Reference Software Stack (the modules, the model versions and
the parameters), so that others can reproduce the system. A kit is the form in
which Open AD Kit holds such a software stack: it pins every part, and one
command runs it.

No Reference Design is published as a kit.

### What Goes Where

| Part of a Reference Design | In a kit |
| --- | --- |
| Autoware version | `extends`: one Open AD Kit release, which pins one Autoware release and its images |
| Modules | The base deployment's services, your packages in `overlay_ws/` and your extra services |
| Model versions | `data` in the deployment's manifest entry: each download with its URL and SHA-256 |
| Parameters | `config/autoware/` and `settings.env` |
| Vehicle and sensors | `VEHICLE_MODEL` and `SENSOR_MODEL`, with the vehicle's description and launch packages in `overlay_ws/` ([A New Vehicle](new-vehicle.md)) |
| Evaluation and testing | The `verify` step, which `openadkit run --verify` runs |

The Deployment Profile stays in the Reference Design's own documents: the
hardware, the operational design domain and the use case. The kit states only
what it needs from the host, in `requirements`: architectures, ROS distros and
GPU.

### Limits

- **Simulation only.** Every catalog deployment is a simulation, so a kit shows
  the stack in simulation, not on the vehicle.
- **A base is required.** A kit deployment builds on a base deployment. A stack
  that does not run the Autoware Universe pipeline, such as
  [Vision Pilot](https://github.com/autowarefoundation/vision_pilot), cannot be
  a kit.
