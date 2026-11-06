# {{name}}

An Open AD Kit kit on top of `{{base}}` from Open AD Kit {{version}}.

| File | What it holds |
| --- | --- |
| `openadkit.json` | The Open AD Kit it extends and the extra images it pins (`artifacts`) |
| `deployment.json` | Its base deployment, Compose files and, optionally, its own `verify` step |
| `config.env` | Values that differ from the base |
| `docker-compose.yaml` | Includes the base; add your services here |
| `config/autoware/` | Parameter overrides: `<package>/<path in its share directory>`, with only the keys you change |
| `overlay_ws/src/` | Your ROS packages |

```bash
openadkit build                  # build overlay_ws in the matching devel image
openadkit validate {{name}}
openadkit run {{name}} --verify  # start, wait until ready, run the base's end-to-end check
openadkit stop
```

See the Integrator Guide for every extension point and how to upgrade.
