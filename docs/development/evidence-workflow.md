# Run the Evidence Workflow

The reusable `.github/workflows/evidence.yaml` verifies a specific Open AD Kit
build and publishes the run's summary. It runs automatically after a
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

jobs:
  evidence:
    uses: ./.github/workflows/evidence.yaml
    with:
      build_tag: ${{ inputs.build_tag }}
```

{% endraw %}

This runs containers on the caller's runners. A fork's evidence runs belong to
that fork; only runs on a `release/X.Y` branch of the releasing repository can
be release evidence.

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
`evidence-summary-<build_tag>` artifact with the summary and a JUnit view. The
release gate reads that summary; see the [release policy](../releases/evidence.md).

Runner cells use `schemaVersion: 1`, and the summary (`schemaVersion: 3`)
carries them as written. Readers accept only these versioned payloads: a cell
without `schemaVersion: 1` and `metrics` is rejected. Summary readers should use
`metrics` rather than top-level timings.
