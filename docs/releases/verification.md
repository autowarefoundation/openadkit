# Verify a Release

Verify downloaded files before executing the installer. Use a recent GitHub
CLI with `gh attestation` and `jq`. Older previews may not have these
attestations or metadata fields.

## Download and verify release artifacts

Replace the example version with the release you intend to use:

```bash
set -euo pipefail
VERSION=v2.0.0
LINE=$(echo "${VERSION#v}" | cut -d. -f1-2)  # the release/X.Y branch that released it
REPO=autowarefoundation/openadkit
gh release download "$VERSION" --repo "$REPO" \
  --pattern openadkit --pattern "openadkit-$VERSION.tar.gz" \
  --pattern release-plan.json --pattern release-metadata.json

for asset in openadkit "openadkit-$VERSION.tar.gz" release-plan.json release-metadata.json; do
  gh attestation verify "$asset" --repo "$REPO" \
    --signer-workflow "$REPO/.github/workflows/release.yaml" \
    --source-ref "refs/heads/release/$LINE" --deny-self-hosted-runners
done
```

The default predicate verifies SLSA build provenance. Provenance binds the bytes
to the release workflow; it does **not** establish that runtime tests passed.

Cross-check the plan and bundle hashes recorded in the verified metadata:

```bash
printf '%s  %s\n' "$(jq -r '.release_plan_sha256' release-metadata.json)" release-plan.json \
  | sha256sum --check
jq -r '.bundles[] | .sha256 + "  " + .name' release-metadata.json \
  | sha256sum --check
```

Review `.release`, `.releaseContext` and `.evidence` in the plan: the requested
version, promoted commit, default distro, passing cells and CI exemptions.
The metadata's `.evidence` must match the plan's `.evidence` exactly, and its
`url` links the evidence run the release gate accepted.

After verification, install the downloaded launcher or use the documented
[installation flow](../getting-started/index.md). Evidence is bounded to the
tested cells; it is not a vehicle-safety or security certification.
