# {{name}}

A kit on Open AD Kit {{version}}. It has one deployment, `{{name}}-{{base}}`,
which runs `{{base}}` with this kit's files on top.

| File | What it holds | Applies to |
| --- | --- | --- |
| `openadkit.json` | The release the kit extends, its deployments with the base of each, and the extra images it pins (`externalImages`) | |
| `settings.env` | Settings that differ from the base | Every deployment |
| `config/autoware/` | Config overrides: `<package>/<path in its share directory>`, with only the keys you change | Every deployment |
| `overlay_ws/src/` | Your ROS packages | Every deployment |
| `deployments/<name>/settings.env` | Settings one deployment alone needs | That deployment |
| `deployments/<name>/config/autoware/` | Config overrides one deployment alone needs | That deployment |
| `deployments/<name>/compose.yaml` | Its services, when it adds or changes any | That deployment |

Settings apply in this order, and a later one wins: the base, the kit, the
deployment, then your host settings file. Config overrides apply in the same
order, without the host settings file.

```bash
openadkit build                  # build overlay_ws in the matching devel image
openadkit validate
openadkit run --verify           # start, wait until ready, run the base's verify step
openadkit stop
```

## Add a Service

A deployment without a `compose.yaml` runs its base's services. To add one,
write `deployments/{{name}}-{{base}}/compose.yaml`:

```yaml
include:
  - ${OPENADKIT_BASE_DEPLOYMENT}/compose.yaml

services:
  my-service:
    image: ${MY_SERVICE_IMAGE:?pinned in openadkit.json externalImages}
    init: true
```

## Add a Deployment

To run the same vehicle on another base, add an entry to `deployments` in
`openadkit.json`, for example
`"{{name}}-logging-simulation": { "base": "logging-simulation" }`. It gets the
kit's settings, config overrides and packages. Make its directory under
`deployments/` only when it needs files of its own. With several deployments,
`run` takes the name of one; `validate` and `fetch` act on all of them.

See the [Kit Guide](https://autowarefoundation.github.io/openadkit/kits/kit-guide/)
for every extension point and how to upgrade.
