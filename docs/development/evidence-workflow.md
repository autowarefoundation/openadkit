# Run the Evidence Workflow

The reusable `.github/workflows/evidence.yaml` verifies a specific Open AD Kit
build and emits a signed in-toto Test Result. It runs automatically after a
successful `build-all-images` run on `main`. For a release, dispatch it with
`build_tag` on the `release/X.Y` branch that built it.

## Reuse it in the build-owning repository

A caller workflow in the same repository (or a fork hosting the same build and
evidence workflows) can call it without duplicating the runner:

{% raw %}

```yaml
name: verify-existing-build
on:
  workflow_dispatch:
    inputs:
      build_tag:
        description: Build run ID and attempt, e.g. 123456789-1
        required: true
        type: string

permissions:
  actions: read
  contents: read
  attestations: write
  id-token: write

jobs:
  evidence:
    uses: ./.github/workflows/evidence.yaml
    with:
      build_tag: ${{ inputs.build_tag }}
```

{% endraw %}

This runs containers and publishes attestations. A fork's attestations belong
to that fork, not the Autoware Foundation release identity. For release
verification the source ref must be a `release/X.Y` branch and the signer must be the expected
evidence workflow. Do not replace the signer check with merely an owner check.

The current reusable interface takes **only `build_tag`**. Metadata and source
come from the caller's build-owning repository. It stages that exact source's
reference deployments and the single flat example at `deployments/custom-kit`.
It does **not** take an arbitrary external kit repository, revision or scenario
as input. Do not copy this example into an unrelated integrator repository and
claim it verifies that kit; external kit intake needs a dedicated, pinned,
trusted-builder implementation before such a claim is valid.

## Inputs, outputs and boundaries

`build_tag` has the form `<run_id>-<run_attempt>`. The matching
`build-metadata-<build_tag>` artifact must be available in the repository.
The workflow checks out its `openadkit_sha` and stages runtime image digests
from the same metadata, never moving image aliases. It stages and verifies the
kit with the same step that assembles release bundles, so the cells run the
tree a release of that build ships, plus the example kit.

The example workspace builds against that build's matching distro-specific
`universe-common-devel` digest. Source/config checksums omit `build`, `install`
and `log` products. Hosted runners execute L0-L2 cells, retry a failed cell once,
and aggregate all expected cells, including missing-cell failures.

The workflow uploads per-cell diagnostics and the
`evidence-attestation-<build_tag>` artifact with predicate, subject list, summary,
JUnit and attestation bundle. Retention is bounded; release verification uses
the published attestations rather than assuming CI ZIP artifacts last forever.

New runner cells use `schemaVersion: 1`. The same payload is embedded under
Test Result `configuration[].annotations.openadkitCell` and stored in the
schema-v2 summary; CI, JUnit and release views are derived from it. Release
reports store the original verified statement and its hash, not a second cell
copy. Readers accept only these versioned payloads: a cell without
`schemaVersion: 1` and `metrics`, or a report that does not match its verified
statement, is rejected. Summary readers should use `metrics` rather than
top-level timings.

Inspect the workflow summary and failures before release. A CI quarantine
warning never grants release permission: the
[release policy](../releases/evidence.md) requires `PASSED`.
