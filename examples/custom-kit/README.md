# Custom kit

A minimal integrator kit: one deployment, `custom-planning`, built on
Planning Simulation without copying it. It is the acceptance test of the
integrator layer, so it stays small and every file shows one extension point.

| File | Extension point |
| --- | --- |
| `openadkit.json` | The pinned Open AD Kit (`extends`) and the kit's own pinned images (`artifacts`) |
| `deployments/custom-planning/deployment.json` | The base deployment it builds on (`base`) |
| `deployments/custom-planning/config.env` | Values that differ from the base |
| `deployments/custom-planning/docker-compose.yaml` | Includes the base and adds a service |
| `deployments/custom-planning/config/autoware/` | A parameter-level difference: `nominal.vel_lim=8.0` |
| `deployments/custom-planning/overlay_ws/src/acme_probe` | A C++ node built in devel and loaded by the runtime hook |

Here `extends` points at this source checkout (`../..`). In your own kit, pin a
release instead, for example `"extends": "v2.0.0"`; the CLI then runs the kit
with that release's CLI.

For this source-checkout example, first build the matching runtime and devel
images from this checkout. Pre-v2 public image aliases do not have the overlay
hook; validation alone cannot detect that missing runtime interface.

```bash
cd examples/custom-kit
bash deployments/custom-planning/overlay_ws/build.sh humble
../../openadkit validate custom-planning
../../openadkit run custom-planning
../../openadkit stop custom-planning
```

The build script's default image tag is for source development. For a pinned
base, set `DEVEL_IMAGE` to the `universe-common-devel` digest from the same
build's metadata/BOM as its runtime images. Use a fresh workspace per ROS
distro. CI does this for both Humble and Jazzy.

The evidence cell checks fresh `/acme/probe` publication, the shared
`use_emergency_handling=false` value, this kit's velocity limit and an untouched
base parameter, then runs the Planning Simulation golden path. Static contract
warnings and every container's hook report produce `overlayConformant`; the
kit source/config checksum is an attestation subject.

See the [Integrator Guide](../../docs/deployments/integrator-guide.md) for the
interface, validation warnings and upgrade procedure.
