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
- a BOM, signed runtime evidence summary, explicit CI exemptions and distro decision
- build provenance for the installer, bundle, plan and metadata

Installed releases move to the latest stable version with `openadkit upgrade`.
Tag naming is documented in
[Container Images & Versioning](../getting-started/container-images.md).
See [Evidence Policy](evidence.md) for the blocking gate and upgrade report, and
[Verify a Release](verification.md) before executing downloaded artifacts.

## Roadmap

The [toolchain RFC](../development/rfc-0001-toolchain-model.md) records the
selected design and its delivery boundaries. Roadmap entries are not claims of
published releases, external team approval or vehicle certification.

| Phase or milestone | Status | Focus |
|-------|--------|-------|
| **v2.0 foundation** | <span class="oak-badge oak-badge--testing">Release validation pending</span> | Reference/integrator kits, pinned inputs, user-data boundaries, Compose nodes, L0-L2 evidence and blocking releases |
| **v2.0.x confidence** | <span class="oak-badge oak-badge--neutral">Planned</span> | Evidence-backed upstream updates, richer upgrade/scenario metrics and image SBOMs |
| **CES 2027 demo** | <span class="oak-badge oak-badge--neutral">Milestone</span> | Hardware integration and partner evidence; not a general vehicle-support claim |
| **v2.1 delivery** | <span class="oak-badge oak-badge--neutral">Planned</span> | OCI package, vehicle-path flattening, Quadlet/BlueChi backend and pinned upstream applications |
| **Later evidence views** | <span class="oak-badge oak-badge--neutral">Planned</span> | Generated compatibility views and partner-backed HIL/field coverage; fleet orchestration remains external |
