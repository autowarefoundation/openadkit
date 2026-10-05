# Integrator Guide

An integrator kit owns its differences, while Open AD Kit owns the base CLI,
images and deployments. Start with [Custom Deployment](custom-deployment.md)
and the [custom-kit example](https://github.com/autowarefoundation/openadkit/tree/main/examples/custom-kit).
This interface requires manifest schema version 2; older manifests are rejected.

## Pin the Base

Set `kind` to `kit` and `extends` to a published schema-v2 release tag in your
root `openadkit.json`. The CLI locates that version under
`~/.local/share/openadkit/openadkit-<tag>` (`OPENADKIT_INSTALL_DIR` overrides the
install root) and delegates to its launcher. Install a missing version with
`openadkit install --version <tag>`.

A relative or absolute source path is also accepted for development. Only one
level of `extends` is supported: a kit extends Open AD Kit, not another kit.
Each kit deployment names a `base` deployment in the pinned release. Its
architecture, ROS distro and GPU requirements are inherited without narrowing
or widening. Base downloads and one-shot reset services are inherited; a kit
can add downloads with distinct destination variables and extra reset services.
Kit deployments currently use the single-host Compose view, not inherited
split-host nodes.

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
the ROS distro, host UID/GID, overlay mount paths and `KIT_openadkit`; release
component images and artifact references remain pinned.

### 2. Config Differences

Store overrides under
`config/autoware/<package>/<path-relative-to-package-share>`. For example,
`config/autoware/autoware_launch/config/control/vehicle_cmd_gate/vehicle_cmd_gate.param.yaml`:

```yaml
/**:
  ros__parameters:
    nominal:
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
After changing the base version, inspect those reports for renamed parameters.

### 3. Overlay Workspace

Put ROS packages in `overlay_ws/src` and build them in the
`universe-common-devel` image from the **same build** as your runtime images.
The example's build script accepts a digest-pinned `DEVEL_IMAGE`:

```bash
DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common@sha256:<digest> \
  bash deployments/custom-planning/overlay_ws/build.sh humble
```

Obtain the matching digest from the build metadata or release BOM. Without an
override, the example script uses a moving source-development tag; do not use
that default as a production pin. Keep separate workspace outputs for different
ROS distros. The CLI mounts the workspace and the hook sources
`overlay_ws/install/local_setup.bash` on top of Autoware.

The ROS link lock covers packages linked by Open AD Kit's compiled tree; it
does not guarantee ABI compatibility for every extra dependency you add. The
example's C++ node links `diagnostic_updater` deliberately to test the known
devel/runtime ABI boundary, then publishes `/acme/probe`.

### 4. Extra Services

Include the base's Compose file using `KIT_openadkit`, then define your services
under `services:`. Keep communicating ROS services on the base ROS domain and
middleware. An extra Open AD Kit runtime service can load the workspace by
mounting `${OPENADKIT_OVERLAY_WS}` at `/openadkit/overlay_ws:ro`; the example's
`acme-probe` service shows this pattern.

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

## Upgrade Without Losing Your Work

Install the new base next to the old version, update `extends`, rebuild your
workspace against its devel digest, then validate and run your acceptance
checks. Your repository, host config, downloaded data and output directories
are outside the base release. Updating the default launcher does not change a
kit's explicit version pin. See [CLI & Maintenance](../getting-started/cli.md)
for config/state roots and marker-protected data cleanup.
