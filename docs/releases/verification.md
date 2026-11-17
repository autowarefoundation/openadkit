# Verify a Release

Verify downloaded files before executing the installer. The full check needs
a recent GitHub CLI with `gh attestation`, and `jq`.

## Provenance and Checksums

Replace the example version with the release you intend to use:

```bash
set -euo pipefail
VERSION=v2.0.0
BRANCH=main  # or the release/X.Y branch that released it
REPO=autowarefoundation/openadkit
gh release download "$VERSION" --repo "$REPO" \
  --pattern openadkit --pattern "openadkit-$VERSION.tar.gz" \
  --pattern release-metadata.json

for asset in openadkit "openadkit-$VERSION.tar.gz" release-metadata.json; do
  gh attestation verify "$asset" --repo "$REPO" \
    --signer-workflow "$REPO/.github/workflows/release.yaml" \
    --source-ref "refs/heads/$BRANCH" --deny-self-hosted-runners
done
```

The default predicate verifies SLSA build provenance. Provenance binds the bytes
to the release workflow; it does **not** establish that runtime tests passed.

Cross-check the bundle hash recorded in the verified metadata:

```bash
jq -r --arg name "openadkit-$VERSION.tar.gz" \
  '.bundles[] | select(.name == $name) | .sha256 + "  " + .name' release-metadata.json \
  | sha256sum --check
```

Review the metadata: `.version` names the requested version, `.bom`
the pinned Autoware release and image digests, and `.evidence` the tested
commit (`source_sha`), the passing cells, the CI exemptions (`exempt`) and the
`url` of the evidence run the release gate accepted.

After verification, install with the downloaded `openadkit` or follow the
[Quickstart](../getting-started/index.md). Evidence is bounded to the tested
cells; it is not a vehicle-safety or security certification.

## Checksum Only

Without the GitHub CLI you can still check the bundle against the release
metadata. This proves the bundle is the one the release names, not where it
was built:

```bash
VERSION=$(curl -fsSL \
  https://api.github.com/repos/autowarefoundation/openadkit/releases/latest \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')
curl -fLO "https://github.com/autowarefoundation/openadkit/releases/download/${VERSION}/openadkit-${VERSION}.tar.gz"
curl -fLO "https://github.com/autowarefoundation/openadkit/releases/download/${VERSION}/release-metadata.json"
EXPECTED=$(python3 - "openadkit-${VERSION}.tar.gz" <<'PY'
import json, sys
bundles = json.load(open("release-metadata.json"))["bundles"]
print(next(bundle["sha256"] for bundle in bundles if bundle["name"] == sys.argv[1]))
PY
)
printf '%s  %s\n' "$EXPECTED" "openadkit-${VERSION}.tar.gz" | sha256sum --check -
tar -xzf "openadkit-${VERSION}.tar.gz"
cd "openadkit-${VERSION}"
```

The extracted directory is a complete runtime; run it with `./openadkit`. The
installer makes this same check before it installs a bundle.
