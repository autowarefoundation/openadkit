# Custom kit

A single-deployment integrator example built on Planning Simulation without
copying it. The kit and deployment share one directory and one name:
`custom-kit`. Copy this directory to start your own kit.
Keep that directory name, or rename it together with the deployment name in
both JSON manifests; the CLI checks that they agree.

| File | Extension point |
| --- | --- |
| `openadkit.json` | Base version/path (`extends`), pinned extra images, and this deployment at `path: "."` |
| `deployment.json` | The base deployment (`planning-simulation`) and Compose entrypoint |
| `config.env` | Values that differ from the base |
| `docker-compose.yaml` | Includes the base and adds the pinned heartbeat and overlay node |
| `config/autoware/` | One parameter difference: the control command gate's `nominal_filter.vel_lim=8.0` |
| `overlay_ws/src/acme_probe` | A small C++ node publishing `/acme/probe` |

Here `extends` points at this source checkout (`../..`). After copying the
directory elsewhere, update it to your base checkout or pin a published
schema-v2 release, for example `"extends": "v2.0.0"`. That version is illustrative,
not a claim that it is published; the CLI uses the pinned release's own launcher.

## Validate, Run, Stop

For this source-checkout example, first build the matching runtime and devel
images from this checkout. Pre-v2 public image aliases do not have the overlay
hook; validation alone cannot detect that missing runtime interface.
A source checkout pins no devel image, so set `DEVEL_IMAGE` to the matching
`universe-common-devel` digest from that build's metadata/BOM before building
the workspace. A kit that extends a release needs no `DEVEL_IMAGE`.

```bash
cd deployments/custom-kit
DEVEL_IMAGE=ghcr.io/autowarefoundation/openadkit-common@sha256:<digest> \
  ../../openadkit build-overlay custom-kit
../../openadkit validate custom-kit
../../openadkit run custom-kit
../../openadkit stop custom-kit
```

Rebuild the workspace per ROS distro (`build-overlay custom-kit --ros-distro
jazzy`); CI builds it with `overlay_ws/build.sh` and a pinned devel image for
both Humble and Jazzy. Add `--ros-distro jazzy` to `validate` and `run` after
building the Jazzy workspace. `validate` only
renders/checks the model; it does not prove that the runtime or overlay works.

The evidence cell checks fresh `/acme/probe` publication, this kit's velocity
limit and an untouched base parameter, then runs the Planning Simulation golden path. Static contract
warnings and every container's hook report produce `overlayConformant`.

See the [Integrator Guide](../../docs/deployments/integrator-guide.md) for the
interface, validation warnings and upgrade procedure.
