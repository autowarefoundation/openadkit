# Custom Deployment

Start with the single
[custom-kit example](https://github.com/autowarefoundation/openadkit/tree/main/deployments/custom-kit).
Copy that directory into your own repository and keep only your differences.
It extends Planning Simulation without copying its Compose files or modifying
an installed release.

## One Directory, One Deployment

```text
custom-kit/
├── openadkit.json
├── deployment.json
├── docker-compose.yaml
├── config.env
├── config/
└── overlay_ws/
```

- `openadkit.json` selects the base (`extends`), pins the extra heartbeat image,
  and points the `custom-kit` deployment at `"."` — this same directory.
- `deployment.json` selects `planning-simulation` as `base` and names the
  Compose entrypoint. Architecture, ROS distro, GPU and downloads are inherited.
- `docker-compose.yaml` includes `${OPENADKIT_BASE_DEPLOYMENT}/docker-compose.yaml`
  and adds the heartbeat and overlay node. The CLI resolves that base directory;
`KIT_openadkit` names the base root for shared assets.
- `config.env` contains only changed values, such as `VEHICLE_ID=acme-01`.
- `config/autoware/` changes one parameter, the control command gate's
  `nominal_filter.vel_lim=8.0`.
- `overlay_ws/` builds a small C++ node publishing `/acme/probe`.

Keep the directory named `custom-kit`. To use another name, rename the directory,
the deployment key in `openadkit.json` and `name` in `deployment.json` together.
The CLI checks that they agree.

## Pin Your Base

In this checkout the example uses `"extends": "../.."`. After copying it
elsewhere, change that value to your base checkout or a published schema-v2
release tag, such as `"v2.0.0"`. That version is illustrative, not a claim that
it is released. Install the selected release with
`openadkit install --version <tag>`; the CLI then uses that base's own launcher.
Keep the example's other fields, including its pinned artifact, when changing
`extends`.

## Validate, Run, Stop

For the source-checkout example, first build matching base runtime/devel images
with the overlay hook. Build the example workspace in the devel image from that
same build; set `DEVEL_IMAGE` to its digest from the build metadata/BOM. The
script's moving default tag is for source development, not a production pin.

```bash
cd deployments/custom-kit
bash overlay_ws/build.sh humble
../../openadkit validate custom-kit
../../openadkit run custom-kit
../../openadkit stop
```

For your copied kit, run `openadkit validate/run/stop custom-kit` from its root,
or set `OPENADKIT_KIT` to that directory. Add `--ros-distro jazzy` to `validate`
and `run` after building a fresh Jazzy workspace. Static validation renders the
Compose model; it is not runtime or ABI evidence. CI exercises the example on
both Humble and Jazzy, including the parameters, fresh C++ publication and the
Planning Simulation golden path.

Keep parameter and package changes in `config/` and `overlay_ws/` rather than
mounting over `/opt/autoware` or replacing base service commands. See the
[Integrator Guide](integrator-guide.md) for configuration order, pinned image
replacement and contract warnings.
