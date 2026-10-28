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

The loader resolves the inherited image/artifact set and ordered env, GPU and
config layers once. Runtime selection consumes that resolved model. The base
is retained only for provenance and comparison against the overlay contract.

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
the ROS distro, host UID/GID, overlay mount paths, `KIT_openadkit` (the base root)
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
override that changed nothing: a package no service has, a file or a parameter
its package does not have. After a base version change these usually are
renamed packages, files or parameters. Every service gets the same layers, so a
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
openadkit build-overlay [--ros-distro humble]               # the kit's workspace
openadkit build-overlay <deployment> [--ros-distro humble]  # and the deployment's own
```

Without a deployment it builds the kit's workspace, which all its deployments
share. With one, it builds each workspace that deployment mounts, the kit's
first. Each builds at the path the services mount it, and the CLI records the image and distro in
`install/.openadkit-overlay.json`. After a base upgrade or a distro change,
`validate` and `run` warn until you rebuild. A workspace builds
incrementally only on its own last build in the same image and distro;
otherwise (an upgrade, a build by hand, a rebuilt layer below) its `build/`
and `install/` are removed first, since CMake caches record the paths they
were configured with. Releases before this pin, and
source checkouts, pin no devel image: set `DEVEL_IMAGE` to the matching
`universe-common-devel` digest from the build metadata or release BOM. The
CLI mounts the workspace and the hook sources `overlay_ws/install/local_setup.bash`
on top of Autoware.

The workspace belongs to the kit: `overlay_ws` at the kit root serves every
deployment of the kit, since they all extend one base and its images. A
deployment may add its own `overlay_ws` in its directory; the hook sources it
after the kit's, so it can add packages or shadow the kit's. A kit whose
deployment is the root itself (`"path": "."`) has the one workspace.

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
middleware. An extra Open AD Kit runtime service can load the kit workspace by
mounting `${OPENADKIT_OVERLAY_WS}` at `/openadkit/overlay_ws:ro`; add
`${OPENADKIT_OVERLAY_WS_DEPLOYMENT}` at `/openadkit/overlay_ws_deployment:ro`
if it also needs the deployment's own packages. The example's `acme-probe`
service mounts the first: its kit has one workspace.

To replace one side of a base that runs as split-host nodes, include only the
other side's service layer instead of the base's Compose file. For example, a
kit that brings its own simulator to `carla-simulation` includes
`${OPENADKIT_BASE_DEPLOYMENT}/services.autoware.yaml`: no service in it depends
on a CARLA service. The base's `resetServices` that the kit's services leave
out are skipped; the kit's own must exist. `validate` then checks the kit
against that layer only, and a deployment that includes no base file inherits
no base service: a service of the same name the kit defines itself, such as
its own `carla`, is the kit's. The kit's Compose files are its entry files and
the kit files they include (a world file several deployments share). A
variable the kit both sets in its env file and reads in those files is its own
setting, and one read with a default or a message (`${DISPLAY:?...}`,
`${TOWN:-Town01}`) is meant to come from the host or the site file. A variable
only set, or only read plainly, and unknown to the base, is still reported as
a likely typo.

### 5. Image Replacement

Declare consumed images in your kit's `artifacts`, with a `workload` and either
one digest-pinned `ref` or a `distros` map of digest-pinned references. An
artifact name matching a component image variable replaces that component;
other artifact names can supply images for new services. Use `${NAME:?}` in
Compose to require the declared reference.

Replacing a base image is allowed but warns that the base overlay contract no
longer holds. It needs your own runtime evidence; pinning alone does not prove
that a replacement honors the entrypoint, launch or parameter interfaces.

## Validation and Evidence

`openadkit validate <deployment> --json` reports `overlayWarnings` and a static
`overlayConformant` value. It warns about:

- Replacing a base service's command
- Changing a base service's image
- Adding or changing mounts over image-internal paths on base services
- Using variables not declared by the base, kit artifacts or data destinations

These warnings do not make `validate` fail. Public value changes, inherited
mounts and commands/images of new services are not reported as replacements.
Validation does not pull images or inspect their parameter files.

The evidence runner combines the static result with every mounted service's
hook report and records `overlayConformant` in the signed Test Result. Missing
or invalid hook reports are nonconformant, not silently clean. The example
acceptance cell additionally requires conformance, checks shared/kit/inherited
parameters and fresh C++ publication, and runs Planning Simulation's golden
path. Humble and Jazzy each build the workspace against their matching devel
digest. The attestation binds the kit's source/config checksum, excluding
host-specific `build`, `install` and `log` products.

Base deployments with a reasoned CI evidence exemption retain that exemption
in the kit. An exemption is not evidence of runtime compatibility.

The [release gate](../releases/evidence.md) requires `PASSED`; static validation
alone is not runtime evidence. See [Evidence Workflow](../development/evidence-workflow.md)
for `workflow_call` and its current build-owning-repository/example-kit scope.
Arbitrary external kit input is not yet supported by that interface.

## Upgrade Without Losing Your Work

Install the new base next to the old version, update `extends`, rebuild your
workspace against its devel digest, then validate and run your acceptance
checks. A workspace kept in a nested deployment directory still loads as that
deployment's layer, but a kit service that mounts only
`${OPENADKIT_OVERLAY_WS}` will not see it: mount
`${OPENADKIT_OVERLAY_WS_DEPLOYMENT}` too, or move the shared workspace to the
kit root. Your repository, host config, downloaded data and output directories
are outside the base release. Updating the default launcher does not change a
kit's explicit version pin. See [CLI & Maintenance](../getting-started/cli.md)
for config/state roots and marker-protected data cleanup.
