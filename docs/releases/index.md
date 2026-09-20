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

Installed releases move to the latest stable version with `openadkit upgrade`.
Tag naming is documented in
[Container Images & Versioning](../getting-started/container-images.md).

## Roadmap

Open AD Kit matures in four phases between May 2026 and May 2027, with a CES 2027
demo milestone.

| Phase or milestone | Status | Focus |
|-------|--------|-------|
| **Trustworthy Foundation** | <span class="oak-badge oak-badge--verified">Complete</span> | Pinned images, scans, unified bundles, compose validation, CARLA 0.9.16 |
| **Compatibility & Validation** | <span class="oak-badge oak-badge--testing">In progress</span> | Lockfiles, manifests, platform matrix, Scenario V2 CI gate, health readiness, Zenoh split |
| **CES 2027 demo** | <span class="oak-badge oak-badge--neutral">Milestone</span> | Flagship demo: Autoware Safety Island + CARLA |
| **Trust Signals & Platform Profiles** | <span class="oak-badge oak-badge--neutral">Planned</span> | SBOM, provenance, cosign signing, vulnerability policy, AutoSD/Podman profiles, BlueChi |
| **Full OTA Support** | <span class="oak-badge oak-badge--neutral">Planned</span> | Staged apply, health promotion, verified rollback, end-to-end closed loop |

## Related

- [Container Images & Versioning](../getting-started/container-images.md) — Tag schema and pinning guidance
- [Getting Started](../getting-started/index.md) — Run Open AD Kit from a source checkout
- [Supported Platforms](../platforms/index.md) — Deployment targets and their tiers
