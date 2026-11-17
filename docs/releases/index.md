# Releases

[GitHub Releases](https://github.com/autowarefoundation/openadkit/releases) is
the canonical source for published versions, release notes and provenance
metadata. Each stable release publishes:

- a versionless `openadkit` installer
- the versioned `openadkit-vX.Y.Z.tar.gz` bundle: the CLI and the catalog of
  deployments
- `release-metadata.json`: the pinned Autoware release, ROS distros, image
  digests, the BOM, the bundle's checksum, the passing evidence summary and
  the CI exemptions
- `autoware-lock.repos` and `upstream-images.json`: the Autoware sources and
  the upstream images the build started from
- build provenance for the installer, bundle and metadata

The release notes open with the Autoware release, ROS 2 distros and
architectures, then the highlights and the install command; they list the
merged pull requests by type and summarize the evidence. An installed release
moves to the latest stable version with `openadkit upgrade`.

- [Container Images](container-images.md) — image tags, what to pin and the
  image reference
- [Compatibility](compatibility.md) — what a version number promises
- [Evidence Policy](evidence.md) — what a build must pass to be released
- [Verify a Release](verification.md) — check the files before you run them

## Versions

Open AD Kit versions follow [Semantic Versioning](https://semver.org/) on their
own, starting at `v2.0.0`: a backward-incompatible change to the CLI, the
manifests or a deployment raises the major version, and a move to a new
Autoware release raises at least the minor version. The release notes list what
breaks, and [Compatibility](compatibility.md) lists what a major
version keeps working.

- **One Autoware release per release.** Releases come from `main`, which pins
  one Autoware release in `.github/autoware.ref`. The
  [GitHub Release](https://github.com/autowarefoundation/openadkit/releases)
  notes open with it, and `openadkit install` and `openadkit version` pair the
  two, `Open AD Kit v2.0.1 · Autoware 2.0.0`.
- **Pinned inputs.** A release also pins the ROS distros and every image
  digest, and its images carry the Autoware version they are built from in
  `org.autoware.openadkit.autoware-version`.
- **Backports.** A fix that is upstream but not yet in an Autoware release can
  be [backported](../development/release-process.md#backporting-an-autoware-fix);
  the release notes list it, and the Autoware version stays the tag's.
- **Older versions.** A `release/X.Y` branch is created from a release tag only
  to fix an older version.

## Support

The latest stable release is supported: fixes, including CVE remediation, ship
in a new release, and older releases are not patched.
[Supported Platforms](../platforms/index.md) gives each platform's tier.
Community help is in
[SUPPORT.md](https://github.com/autowarefoundation/openadkit/blob/main/.github/SUPPORT.md);
report security vulnerabilities through the
[private reporting policy](https://github.com/autowarefoundation/openadkit/blob/main/.github/SECURITY.md).
Open AD Kit makes no safety-certification, functional-safety or
production-readiness claim.
