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

Here `extends` points at this source checkout (`../..`). In your own kit, pin a
release instead, for example `"extends": "v2.0.0"`; the CLI then runs the kit
with that release's CLI.

```bash
cd examples/custom-kit
../../openadkit validate custom-planning
../../openadkit run custom-planning
```
