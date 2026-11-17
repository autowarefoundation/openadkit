# Support

Open AD Kit is an Autoware Foundation open-source project. Support is
community-based; there is no response-time or service-level guarantee.

## Getting help

- Start with the [documentation](https://autowarefoundation.github.io/openadkit/)
  and [troubleshooting guide](https://autowarefoundation.github.io/openadkit/getting-started/troubleshooting/).
- Ask usage and design questions in the
  [Autoware Discord](https://discord.gg/Q94UsPvReQ).
- Report reproducible bugs and request changes in
  [GitHub Issues](https://github.com/autowarefoundation/openadkit/issues).
- Report security vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
  Do not put exploit details in a public issue or chat.

For a bug report, include `openadkit version --json`, the deployment, ROS
distro, host architecture, Docker/Compose versions, reproduction steps, and
relevant logs. Remove credentials and personal or sensitive data first.
For a kit, also include the pinned release version and the result of
`openadkit validate --json`, run in the kit.

## Supported versions and configurations

The latest stable release receives fixes through a new patch or minor release.
Older releases are not maintained separately. Source checkouts and release
candidates are development previews.

Release evidence covers specific deployment, ROS distro, role topology and
platform cells, not every hardware or environment combination. The hosted
evidence cells run on `linux/amd64` and `linux/arm64` runners; GPU modes,
boards and two-machine setups are outside them. A documented CI exemption
means **not verified in CI**, not a passing test. See the
[evidence policy](https://autowarefoundation.github.io/openadkit/releases/evidence/)
and [platform matrix](https://autowarefoundation.github.io/openadkit/platforms/).

Use the documented extension points and the pinned release's matching devel
image for custom ROS packages. Replacing component images or commands requires your
own runtime evidence.

Open AD Kit makes no functional-safety certification, ASIL, roadworthiness or
production-readiness claim. Deployment on a vehicle requires the integrator's
own safety, security and operational validation.
