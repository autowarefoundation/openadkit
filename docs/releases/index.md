# Releases & Roadmap

**No stable release has been published yet.** Until the first release, run Open
AD Kit from a [source checkout](../getting-started/index.md).

## Releases

[GitHub Releases](https://github.com/autowarefoundation/openadkit/releases) is
the canonical source for published versions, release notes, and provenance
metadata. Each stable release publishes:

- a versionless `openadkit` installer
- the versioned `openadkit-vX.Y.Z.tar.gz` bundle
- the pinned Autoware meta-release, ROS 2 distro(s), and image tags and digests
- a BOM, the passing runtime evidence summary, explicit CI exemptions and default distro
- build provenance for the installer, bundle, plan and metadata

Installed releases move to the latest stable version with `openadkit upgrade`.
Tag naming is documented in
[Container Images & Versioning](../getting-started/container-images.md).
See [Evidence Policy](evidence.md) for the blocking gate and verification report, and
[Verify a Release](verification.md) before executing downloaded artifacts.

## Roadmap

These are plans, not claims of published releases, external team approval or
vehicle certification.

### Before v2.0

| Work | Status |
|------|--------|
| Release evidence: releases need a passing evidence run of their build; build provenance stays | Done |
| Kit: drop the static overlay-contract check and shorten the integrator guide | Done |
| R-Car X5H board support moves to its own repository; AutoSD planning simulation stays | Done |
| CLI: `build`, `run --ws`, `restart`, `shell`, deployment paths, and commands that find the running stack from any directory | Done |
| Split-host: visualizer on the simulator node, Autoware outputs and the vector map bridged, allowlist checked in CI | Done |
| Safety Island: its DDS domain bridge and configuration become a generic part of the kit | Planned |
| AutoSD: Quadlet units for the component images, with Compose as the single source | Planned |

### After v2.0

- **Performance visibility:** latency and resource use per component in runs and evidence.
- **Vehicle integration:** a supported path from simulation to a real vehicle interface.
- **Validation ladder:** SIL, virtual vehicle network, bench HIL, small-scale and
  then full-scale vehicle, replacing the vehicle node rather than the application.
- **Vehicle delivery:** an OCI package of the digest-pinned system and its BOM that
  can be mirrored offline; fleet rollout stays with the integrator's OTA system.
- **rmw_zenoh:** evaluate it for split-host on Jazzy (Humble needs a launch patch); if it holds up,
  replace the zenoh-bridge-ros2dds bridge.
- **Image SBOMs.**
- **CES 2027 demo:** hardware integration and partner evidence; not a general
  vehicle-support claim.

### Non-goals

No custom OTA service, Kubernetes stack, fork of upstream workloads, or ASIL or
NCAP certification claim. Safety Island owns its safety boundary; Open AD Kit
integrates it.
