# Verify a Release

Verify downloaded files before executing the installer. Use a recent GitHub
CLI with `gh attestation`, `jq`, and a trusted checkout of Open AD Kit's release
policy scripts. Commands below apply to releases produced by the blocking gate;
older previews may not have these attestations or metadata fields.

## Download and verify release artifacts

Replace the example version with the release you intend to use:

```bash
set -euo pipefail
VERSION=v2.0.0
REPO=autowarefoundation/openadkit
gh release download "$VERSION" --repo "$REPO" \
  --pattern openadkit --pattern "openadkit-$VERSION.tar.gz" \
  --pattern release-plan.json --pattern release-metadata.json

for asset in openadkit "openadkit-$VERSION.tar.gz" release-plan.json release-metadata.json; do
  gh attestation verify "$asset" --repo "$REPO" \
    --signer-workflow "$REPO/.github/workflows/release.yaml" \
    --source-ref refs/heads/main --deny-self-hosted-runners
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
version, promoted commit, distro decision, required cells and CI exemptions.
The metadata's `.evidence` must match the plan's `.evidence` exactly.

## Verify the runtime Test Result

Use an image digest from the verified plan to retrieve the Test Result:

```bash
IMAGE=$(jq -r '.images[0] | "oci://" + .repo + "@" + .digest' release-plan.json)
gh attestation verify "$IMAGE" --repo "$REPO" \
  --predicate-type https://in-toto.io/attestation/test-result/v0.1 \
  --signer-workflow "$REPO/.github/workflows/evidence.yaml" \
  --source-ref refs/heads/main --deny-self-hosted-runners \
  --format json > evidence-verified.json
```

Authenticate with GHCR if the CLI requests registry access. **Successful
signature verification alone is insufficient:** GitHub also verifies signed
`FAILED` and `WARNED` claims.

In a trusted Open AD Kit source checkout, fetch the promoted commit into a
separate directory and run the same policy used by the release gate. Paths below
are relative to that trusted checkout; place the downloaded files there first:

```bash
SHA=$(jq -r '.release.releaseSha' release-plan.json)
git fetch origin "$SHA"
mkdir release-source
git archive "$SHA" | tar -x -C release-source

python3 .github/scripts/evidence/release_gate.py \
  --verified evidence-verified.json \
  --build-metadata release-metadata.json \
  --source-root release-source \
  --default-ros-distro "$(jq -r '.release.defaultRosDistro' release-plan.json)" \
  --repository "$REPO" --output evidence-report.json
```

This recomputes subjects and manifest-derived coverage and accepts only one
complete `PASSED` statement. It never verifies signatures itself: feed it only
the output of a successful `gh attestation verify` command with the identity
flags shown above. Several complete successful runs can exist; the selected
statement hash in the published plan identifies the run used for that release.

After verification, install the downloaded launcher or use the documented
[installation flow](../getting-started/index.md). Evidence is bounded to the
tested cells; it is not a vehicle-safety or security certification.
