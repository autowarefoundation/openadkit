# Container Image Tags

Open AD Kit publishes images to the GitHub Container Registry (`ghcr.io/autowarefoundation/openadkit`). Understanding the tag schema helps you choose the right level of stability and pinning for your deployment.

## Tag Reference

| Tag Pattern | Example | Description |
|-------------|---------|-------------|
| **Stable release** | `planning-control-humble-v2.0.0` | Immutable release tag. Use this when you need a fully reproducible deployment. |
| **Latest stable alias** | `planning-control-humble` | Always resolves to the latest stable release for the specified ROS distro. |
| **Latest stable + suffix** | `planning-control-humble-latest` | Same as above, explicit. |
| **Default ROS distro alias** | `planning-control` | Convenience alias that resolves to the current default ROS distro ({{ default_distro_title }}). |
| **Default + latest suffix** | `planning-control-latest` | Explicit default-distro latest alias. |
| **Immutable build tag** | `planning-control-humble-123456789-1` | Pin to a specific CI build. Format: `<target>-<ros_distro>-<run_id>-<run_attempt>`. |
| **CI development alias** | `planning-control-amd64-humble` | Per-platform mutable tag used during CI. **Do not use for pinned deployments.** |
| **Pre-release** | `planning-control-humble-v2.0.0-rc.1` | Pre-release tag for testing. Pre-releases do not update latest stable aliases. |

!!! note "ROS 2 distributions"
    Examples use **{{ default_distro_title }}** (the current default). **Jazzy** images are published in parallel — substitute `-jazzy` for `-humble` in any tag (e.g. `planning-control-jazzy`, `planning-control-jazzy-v2.0.0`).

## CUDA Images

CUDA-enabled variants follow the same patterns but are **amd64-only**:

| Tag Pattern | Example |
|-------------|---------|
| Stable release | `sensing-perception-cuda-humble-v2.0.0` |
| Latest alias | `sensing-perception-cuda-humble` |

## Common Prefix

All component images share the same repository prefix:

```text
ghcr.io/autowarefoundation/openadkit
```

## Choosing a Tag

<div class="oak-callout" markdown="1">

**Production / reproducible deployments** — Use a stable release tag (`vX.Y.Z`).

**Development / latest features** — Use a latest stable alias (`<target>-<ros_distro>`).

**Quick start / deployments** — Use a default ROS distro alias (`<target>`).

**Never pin to CI development aliases** (`*-amd64-*`) — Do not use mutable per-platform tags in committed deployment files.

</div>

### Decision Flow

```mermaid
flowchart TD
    A[Need fully reproducible deployment?] -->|Yes| B[Use stable release tag<br>vX.Y.Z]
    A -->|No| C[Need specific ROS distro?]
    C -->|Yes| D[Use latest stable alias<br>&lt;target&gt;-&lt;ros_distro&gt;]
    C -->|No| E[Use default alias<br>&lt;target&gt;]
```

<h2 class="oak-eyebrow" id="related">Related</h2>

- [Getting Started](index.md) — Environment setup and first deployment
- [Release Flow](release-flow.md) — How tags are created and promoted
