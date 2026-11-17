# Manifest and Output Reference

The fields of a kit's manifest and of the CLI's JSON output that
[Compatibility](../releases/compatibility.md) covers.

## Kit Manifest

A kit's `openadkit.json`:

| Field | Meaning |
| --- | --- |
| `schemaVersion` | `2` |
| `kind` | `kit` |
| `extends` | The release the kit pins, as `vX.Y.Z`, or the path of a source checkout while developing |
| `deployments` | The kit's deployments by name; each value is a [deployment entry](#deployment-entry) |
| `externalImages` | Images the kit uses but does not build, by Compose variable name; see [External Images](#external-images) |

## Deployment Entry

One entry of a kit's `deployments`. A catalog deployment holds the same
fields, except `base`, in its `deployment.json`.

| Field | Default | Meaning |
| --- | --- | --- |
| `base` | Required in a kit | The catalog deployment this one runs, with the kit's files on top |
| `description` | `<base> with this kit's files on top` | One line, which `openadkit list` shows |
| `waitTimeout` | The base's; `300` in the catalog | Seconds the services may take to become ready |
| `requirements` | The base's | Where the deployment runs; see [Requirements](#requirements) |
| `data` | The base's | What `run` and `fetch` download; see [Data](#data) |
| `verify` | The base's | What `run --verify` runs; see [Verify Step](#verify-step) |

An entry with data and a verify step of its own:

```json
"my-kit-logging-simulation": {
  "base": "logging-simulation",
  "description": "My vehicle on a recorded drive",
  "data": [
    {
      "name": "my-drive",
      "kind": "zip",
      "destinationEnv": "ROSBAG_PATH",
      "url": "https://example.com/my-drive.zip",
      "sha256": "<64 hex digits>",
      "expectedRoot": "my-drive",
      "requiredFiles": ["metadata.yaml"]
    }
  ],
  "verify": {
    "service": "api",
    "command": ["ros2", "topic", "echo", "--once", "/my_vehicle/status"]
  }
}
```

A catalog deployment may also hold `roles`, the hosts of a
[split-host](../deployments/split-host.md) deployment (experimental). Each
role lists the Compose files it starts (`files`), its ROS domain
(`rosDomainId`) and the settings it needs (`requiredEnv`). A catalog
deployment may also hold `evidence.exempt`, the reason it has no hosted
[evidence cell](../releases/evidence.md#ci-exemptions).

### Requirements

| Field | Meaning |
| --- | --- |
| `architectures` | `amd64`, `arm64` or both |
| `rosDistros` | The ROS distros it runs on, such as `humble` and `jazzy` |
| `gpu` | `none`: no GPU mode. `optional`: `--gpu` selects it. `required`: it always runs with a GPU |
| `gpuArchitectures` | The architectures of the GPU mode, when fewer than `architectures` |

A kit deployment may name fewer architectures or ROS distros than its base,
and set `gpu` to `none` or `required` where the base says `optional`. It
cannot add any.

### Data

`data` is a list of resources. Each is one directory on the host:

| Field | Meaning |
| --- | --- |
| `name` | The resource's name, unique in the deployment |
| `destinationEnv` | The setting that holds the directory's path, such as `MAP_PATH`. One resource per setting; a kit's resource replaces its base's with the same setting |
| `kind` | `zip`: one archive. `files`: a list of files |
| `url`, `sha256` | `zip` only: the archive and its checksum |
| `expectedRoot` | `zip` only: the archive's one top-level directory, whose contents become the resource |
| `files` | `files` only: the files, each with a `path` in the resource and exactly one of `url` (to download), `source` (a file of the kit or the release, by its path from the manifest's directory) and `content` (the file's text). `url` and `source` need a `sha256` |
| `requiredFiles` | Paths that must exist, and not be empty, in data the CLI installed |
| `gpu` | `true`: only the GPU mode uses it |
| `roles` | Catalog only: the split-host roles that use it |

A URL is `http`, `https` or `file`. The CLI checks every checksum, and
downloads again when a release declares other content for a resource. A
directory it did not install is yours and is used as it is; see
[Downloaded Data](../getting-started/cli.md#downloaded-data).

### Verify Step

| Field | Meaning |
| --- | --- |
| `service` | The service that verifies the deployment |
| `command` | The command `run --verify` runs in that service, as a list of words. Without it, the step is the service's own exit status |

## External Images

Each entry of `externalImages` is named after the Compose variable that
receives it, and holds one of:

| Field | Meaning |
| --- | --- |
| `ref` | One digest-pinned image reference (`…@sha256:…`) for every ROS distro |
| `distros` | A digest-pinned reference per ROS distro |

A name that matches a component image variable, such as `PLANNING_IMAGE`,
replaces that component; see
[Image Replacement](kit-guide.md#5-image-replacement).

## Release Manifest

A release's own `openadkit.json` is written by its packaging; a kit reads it
only through the CLI. What a kit's Compose files use from it are the component
image variables: `SENSING_PERCEPTION_IMAGE`, `LOCALIZATION_MAPPING_IMAGE`,
`PLANNING_IMAGE`, `CONTROL_IMAGE`, `VEHICLE_SYSTEM_IMAGE`, `SIMULATOR_IMAGE`
and `VISUALIZER_IMAGE`, with `SENSING_PERCEPTION_GPU_IMAGE` and
`PLANNING_GPU_IMAGE` for the GPU mode.

## JSON Output

Each document carries `schemaVersion: 1`.

### `list --json`

`deployments` is a list of:

| Field | Meaning |
| --- | --- |
| `name`, `description` | The deployment's name and its one line |
| `requirements` | Its [requirements](#requirements), as in the manifest |
| `modified` | `true` when a release's deployment differs from the files it came with, else `false`. `null` in a source checkout and for a kit's deployments, which nothing vouches for |
| `error` | Only when the deployment cannot be read; `requirements`, `description` and `modified` are then `null` |

### `version --json`

| Field | Meaning |
| --- | --- |
| `kind` | `release`, `source` or `kit` |
| `version` | The release, or `null` in a source checkout. In a kit, the release it pins |
| `commit` | The commit of a source checkout, also of the one a kit extends; else `null` |
| `extends` | In a kit, what it pins, as its manifest says; else `null` |
| `bom` | What the release runs: `autoware` (the pinned Autoware release: `version`, `ref`, `lockSha256`), `images` (the digest-pinned component images per ROS distro) and `externalImages` |

### `validate --json`

One document covers one deployment, so a kit with several needs a name here;
plain `validate` checks each of them.

| Field | Meaning |
| --- | --- |
| `deployment` | The deployment's name. When `valid` is `false`, the argument as given, or `null` without one |
| `valid` | `false` with an `error` when it cannot run as asked; the fields below are then missing |
| `base` | A kit deployment's base, else `null` |
| `rosDistro`, `gpu`, `role` | How it was validated; `gpu` is `true` for the GPU mode |
| `dataValid` | With `--data`: whether every resource can be used; else `null` |
| `data` | With `--data`: each resource's `name` and `status`: `ok`, `missing`, `incomplete`, `outdated`, or `own` for a directory of yours |

### `results/run.json`

| Field | Meaning |
| --- | --- |
| `deployment`, `role`, `rosDistro`, `gpu` | What ran; `gpu` is `true` for the GPU mode |
| `version`, `extends` | The release, and what a kit pins |
| `images` | The image of each service |
| `modelSha256` | The digest of the resolved Compose model |
| `configSha256` | The content digest of each config override layer: `base`, `kit` and `deployment` |
| `overlaySha256` | The content digest of the overlay workspace, without its `build` and `log` directories |
| `readySeconds` | How long the services took to become ready |
| `verify` | With `--verify`: the step's `service`, `seconds`, `exitCode` and `result`, `PASSED` or `FAILED` |
