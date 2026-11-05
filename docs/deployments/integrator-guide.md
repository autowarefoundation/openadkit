# Integrator Guide

An integrator kit owns its differences, while Open AD Kit owns the base CLI,
images and deployments. Start with [Custom Deployment](custom-deployment.md)
and the [custom-kit example](https://github.com/autowarefoundation/openadkit/tree/main/deployments/custom-kit).
This interface requires manifest schema version 2; older manifests are rejected.

## Pin the Base

Set `kind` to `kit` and `extends` to a published schema-v2 release tag in your
root `openadkit.json`. The CLI locates that version under
`~/.local/share/openadkit/openadkit-<tag>` and delegates to its launcher. Install
a missing version with `openadkit install --version <tag>`.
`OPENADKIT_INSTALL_DIR` overrides the install root for both.

A relative or absolute source path is also accepted for development. Only one
level of `extends` is supported: a kit extends Open AD Kit, not another kit.
Each kit deployment names a `base` deployment in the pinned release. Its
architecture, ROS distro and GPU requirements are inherited without narrowing
or widening. Base downloads and one-shot reset services are inherited; a kit
can add downloads with distinct destination variables and extra reset services.
Kit deployments currently use the single-host Compose view, not inherited
split-host nodes.

The example has just one deployment, also named `custom-kit`. Its
`openadkit.json`, `deployment.json`, Compose and differences live in one
directory; `deployments.custom-kit.path` is `"."`. No nested `deployments/`
directory is needed. Run commands from that directory, not the base repository.

## Extension Points

### 1. Values

Put only differences in your deployment's `config.env`. Compose interpolation
reads these files in order (later wins):

1. Base `config.env`
2. Base `config.gpu.env`, when GPU mode is selected
3. Kit `config.env`, if present
4. Kit `config.gpu.env`, if present and GPU mode is selected
5. `~/.config/openadkit/<kit-deployment>.env`, if present

Container ROS/DDS defaults come from the included services' `runtime.env`.
Shell exports do not hide values in the configuration files. The CLI injects
the ROS distro, host UID/GID, overlay mount paths, `OPENADKIT_BASE_ROOT` (the base root)
and `OPENADKIT_BASE_DEPLOYMENT` (the directory selected by `base`); release
component images and artifact references remain pinned.

### 2. Config Differences

Store overrides under
`config/autoware/<package>/<path-relative-to-package-share>`. For example,
`config/autoware/autoware_control_config/config/control_command_gate/control_command_gate.param.yaml`:

```yaml
/**:
  ros__parameters:
    nominal_filter:
      vel_lim: 8.0
```

On each start, the entrypoint hook copies the package share directory into
`/tmp/openadkit/<package>/share/<package>`. It applies the shared, base-deployment
and kit-deployment layers in that order. YAML mappings merge recursively;
scalars and lists replace the old value. Launch substitutions such as
`$(var ...)` stay intact. Non-YAML files replace their counterpart.

The copied prefixes go first on `AMENT_PREFIX_PATH`, and base launch arguments
use the same stable paths. No change is written into the image. Removing an
override and restarting returns to the remaining layers.

Unknown packages, files or YAML keys are warnings, not startup failures. The
hook logs them and writes `/tmp/openadkit/overlay-report.json` in each container.
Once the services are up, `run` collects those reports and warns about every
override without a counterpart: a package no service has changes nothing, and a
file or a parameter its package does not have is added. That is intended for a
new file such as a diagnostics graph; after a base version change it usually
means a renamed package, file or parameter. Every service gets the same layers, so a
package installed in only some images is not reported.

#### A New Vehicle

Autoware's defaults describe a passenger car. Review these for your vehicle;
their package and path depend on the base's Autoware version, so look them up
in its images and check `run`'s override warnings.

| Parameters | File | Why |
| --- | --- | --- |
| Dimensions, `wheel_base`, `max_steer_angle` | `vehicle_info.param.yaml` of your vehicle description | Planning and control use them as limits; a steering limit above the vehicle's makes control ask for angles it cannot reach. |
| Sensor poses | your sensor kit's `sensor_kit_calibration.yaml` and `sensors_calibration.yaml` | A wrong sign or offset shows up as a localization error of the same size. |
| `nominal_latency`, `assumed_limit_acc` | `control_validator.param.yaml` | Your actuation latency and achievable braking. With car values a slower or weaker vehicle fails validation and triggers an MRM. |
| `pose_measurement.pose_gate_dist` | `ekf_localizer.param.yaml` | The Mahalanobis gate for pose updates. A start pose far from the truth can be rejected for good. |
| Velocity, acceleration, jerk and steering-rate limits | `vehicle_cmd_gate.param.yaml` | The last limits before the vehicle interface. |

### 3. Overlay Workspace

Put ROS packages in `overlay_ws/src` and build them in the
`universe-common-devel` image from the **same build** as your runtime images.
A release pins that image next to its runtime images, so the CLI builds with
the right one:

```bash
openadkit build [--ros-distro humble]   # in the kit: its overlay_ws
openadkit build PATH                    # any workspace, with the pins of the kit around it
```

The CLI records the image and distro in `install/.openadkit-overlay.json`, and
`validate` and `run` warn after a base upgrade or a distro change until you
rebuild. Such a rebuild
starts from a clean `build/` and `install/`, since CMake caches record the paths
they were configured with. A source checkout pins no devel image: set
`DEVEL_IMAGE` to the matching `universe-common-devel` digest from the build
metadata. The hook sources `overlay_ws/install/local_setup.bash` on top of Autoware.

The workspace belongs to the kit: the one `overlay_ws` at the kit root serves
every deployment of the kit, since they all extend one base and its images.
Every Autoware service mounts it, and the hook sources it on top of Autoware,
so its packages are visible in every service. Whether your code runs depends on
what starts it:

- A changed copy of an Autoware package shadows the image's own. It runs where
  Autoware already launches that package, with nothing more to configure.
- A new node runs only where something starts it: an extra service (as the
  example's `acme-probe`), a launch file you override under `config/autoware`,
  or by hand with `openadkit shell <service> ros2 run <package> <node>`.

To try a workspace with a reference deployment, without writing a kit, mount it
with `--ws`:

```bash
openadkit build ~/my_ws
openadkit run planning-simulation --ws ~/my_ws
```

`--ws` is for a deployment without a workspace of its own; on a kit that has
one it is an error rather than a second layer.

The devel and runtime images install ROS packages from the same
[ROS snapshot](../getting-started/container-images.md#ros-package-snapshot), so
an overlay built in the devel image links the ROS versions the runtime image
ships. A dependency you add must also exist in the runtime image; the overlay
cannot install packages. The example's C++ node links `diagnostic_updater`
deliberately to test the devel/runtime ABI boundary, then publishes
`/acme/probe`.

### 4. Extra Services

Include the base's Compose file using `OPENADKIT_BASE_DEPLOYMENT`, then define your services
under `services:`. Keep communicating ROS services on the base ROS domain and
middleware. An extra Open AD Kit runtime service loads the kit workspace by
mounting `${OPENADKIT_OVERLAY_WS}` at `/openadkit/overlay_ws:ro`, as the
example's `acme-probe` does. It needs no image of its own: a runtime image and
the workspace are enough. Build your own image only for what the runtime images
lack, such as a system package or a non-ROS application, and declare it as an
artifact (point 5).

To replace one side of a base that runs as split-host nodes, include only the
other side's service layer instead of the base's Compose file. For example, a
kit that brings its own simulator to `carla-simulation` includes
`${OPENADKIT_BASE_DEPLOYMENT}/services.autoware.yaml`: no service in it depends
on a CARLA service. The base's `resetServices` that the kit's services leave
out are skipped; the kit's own must exist.

### 5. Image Replacement

Declare consumed images in your kit's `artifacts`, each with either one
digest-pinned `ref` or a `distros` map of digest-pinned references. An
artifact name matching a component image variable replaces that component;
other artifact names can supply images for new services. Use `${NAME:?}` in
Compose to require the declared reference.

A replaced base image needs your own runtime evidence: pinning alone does not
prove that it honors the entrypoint, launch or parameter interfaces.

## Validation and Evidence

`openadkit validate <deployment>` renders the deployment and checks its manifest
and data. It does not pull images or prove that the runtime works; `run` reports
overrides without a counterpart (see [Config Differences](#2-config-differences)).

The example kit's evidence cell checks its parameters, the fresh `/acme/probe`
publication of its C++ package and Planning Simulation's golden path. Humble and
Jazzy each build the workspace against their matching devel digest.

A base deployment's CI exemption stays with the kit; an exemption is not runtime
evidence. The [release gate](../releases/evidence.md) requires `PASSED`. See
[Evidence Workflow](../development/evidence-workflow.md) for reusing the verifier;
it does not yet accept arbitrary external kits.

## Upgrade Without Losing Your Work

Install the new base next to the old version, update `extends`, rebuild your
workspace against its devel digest, then validate and run your acceptance
checks. Your repository, host config, downloaded data and output directories
are outside the base release. Updating the default launcher does not change a
kit's explicit version pin. See [CLI & Maintenance](../getting-started/cli.md)
for the config and output directories and marker-protected data cleanup.
