# Run the Evidence Workflow

The reusable `.github/workflows/evidence.yaml` verifies a specific Open AD Kit
build and emits a signed in-toto Test Result. It runs automatically after a
successful `build-all-images` run, and can also be dispatched with `build_tag`.

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
verification the source ref must be `main` and the signer must be the expected
evidence workflow. Do not replace the signer check with merely an owner check.

The current reusable interface takes **only `build_tag`**. Metadata and source
come from the caller's build-owning repository. It stages that exact source's
reference deployments and `examples/*` kits, including `examples/custom-kit`.
It does **not** take an arbitrary external kit repository, revision or scenario
as input. Do not copy this example into an unrelated integrator repository and
claim it verifies that kit; external kit intake needs a dedicated, pinned,
trusted-builder implementation before such a claim is valid.

## Inputs, outputs and boundaries

`build_tag` has the form `<run_id>-<run_attempt>`. The matching
`build-metadata-<build_tag>` artifact must be available in the repository.
The workflow checks out its `openadkit_sha` and stages runtime image digests
from the same metadata, never moving image aliases.

Each example workspace builds against that build's matching distro-specific
`universe-common-devel` digest. Source/config checksums omit `build`, `install`
and `log` products. Hosted runners execute L0-L2 cells, retry a failed cell once,
and aggregate all expected cells, including missing-cell failures.

The workflow uploads per-cell diagnostics and the
`evidence-attestation-<build_tag>` artifact with predicate, subject list, summary,
JUnit and attestation bundle. Retention is bounded; release verification uses
the published attestations rather than assuming CI ZIP artifacts last forever.

Inspect the workflow summary and failures before release. A CI quarantine
warning never grants release permission: the
[release policy](../releases/evidence.md) requires `PASSED`.
