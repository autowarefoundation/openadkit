# CI ownership

The pipeline is **build → scan + runtime evidence → validate → package → publish**.
Workflows own triggers, job ordering, runners and permissions. Scripts own the
data and behavior contracts; local actions own repeated execution recipes.

Every action is pinned by commit, with its version in a comment
(`owner/action@<sha> # vX.Y.Z`): a tag can move, a commit cannot. Dependabot
raises both, and `test_pinned_actions.py` fails on a tag.

| Responsibility | Owner |
| --- | --- |
| Build matrices, changed-target selection, contexts and Bake overrides | `scripts/build.py` |
| CI image tags, Bake execution and ccache restore/save/prune | `actions/build-image/` |
| Source lock import, Buildx and registry login | `actions/setup-build-env/` |
| Image metadata capture, inventory coverage, scan rows and artifact validation | `scripts/images.py` |
| Validation and evidence cell plans (roles, checks) and the catalog inventory | `scripts/validation_matrix.py` |
| Executing one evidence cell: validate/start/cleanup and the L0–L3 checks it names | `scripts/evidence/run_cell.sh` |
| Cell payloads, the run summary and its report | `scripts/evidence/` |
| External release checks and sequencing | `scripts/validate_release.sh` |
| Immutable release plan, runtime pins, and bundle staging and integrity | `scripts/release_plan.py` |
| Packaging, image promotion and GitHub publication | `scripts/*release*.sh` |

The shared build action never grants permissions. A pull request from this
repository pushes the images it builds to the CI package `openadkit-ci`;
`scripts/assemble_pr_build.sh` completes that build there with the base
branch's other images, copied by digest, and `images.py capture` writes its
metadata, so `evidence.yaml` runs on it unchanged before merge. A fork's pull
request loads its images (no push, read-only token) and stops at the scan,
which applies the release gate's policy. Only pipeline changes (`PIPELINE_INPUTS`
in `build.py`) build a single image, `localization-mapping`, which proves the pipeline end to end.
Published builds carry exact upstream contexts, source/lock labels and security-refresh
stamps, with a bounded cache policy. `components/docker-bake.hcl` owns the
Dockerfiles and dependency edges.

`images.py` writes unversioned, snake-case build/scan JSON.
It records **observed** registry platforms, not the inventory's expected list.
The scanner and release validator use the same digest/platform records; the
validator also checks raw-byte sidecar hashes and exact inventory coverage.
The shell scripts own registry retries and errors, and GitHub run selection.

Shared parsing is **not** shared authorization: release validation requires
the latest eligible full scan to pass and a successful evidence run whose summary
passed the promoted build. Packaging reparses image records and rechecks that
summary against the build and commit. Registry preflight runs at both
validation and promotion.

Release packaging and evidence staging assemble the release tree through one
`release_plan.py --stage` step, so evidence runs the tree the release ships;
evidence adds only the example kits. Both run the build commit's own scripts:
a later packaging change on the branch does not reach an older build. The bundle, the release plan and the
evidence subjects all read one catalog inventory.

Each evidence matrix row is the complete cell plan: identity, the role list in
manifest order and the deployment's verify step. L1 is `openadkit run`, which
waits for the deployment's healthchecks; L2 is `run --verify`; L3 is the example
kit's `checks/dev_loop.sh`. `run_cell.sh` executes the row with a common
validate/start/cleanup lifecycle; it does not derive policy from deployment
names, except the replay rate it sets for Logging Simulation. Scenario isolation and drive-to-goal checks stay distinct. Hosted split
evidence is two roles on one runner, not proof of two physical hosts.

The integrator example is made in CI, not kept in `deployments/`: the staged
CLI's `openadkit new example-kit` makes it under `kits/`, and the fixture in
`.github/scripts/evidence/example-kit/` adds every extension point on top, and
a second deployment on another base that the cells validate. Lint validates the
same kit made from the checkout.

`registry-cleanup.yaml` deletes a pull request's CI images when it closes, CI
images after 14 days, branch builds after 90 days (the age a release may still
promote), the compile bases of builds older than that, the caches of images and
branches that no longer exist, and overwritten caches; release tags, latest
aliases and the moving `<target>-<arch>-<distro>` tags stay. Its weekly run
only lists until the repository variable `REGISTRY_CLEANUP` is `delete`.
`GITHUB_TOKEN` deletes
only in packages that give the repository the **Admin** role under the
package's *Manage Actions access*: set it on `openadkit`, `openadkit-buildcache`
and `openadkit-ci` in every repository that builds.

After changing a shared build owner, update both workflow path triggers and the
changed-input patterns in `build.py`. Python helpers needed by release and scan
must also be included in their trusted policy sparse checkouts.

The docs site is built from `main` when a stable release is published:
`deploy-docs.yaml` runs from the release workflow or by dispatch, not on a push
to `main`. Production docs
builds record their checkout SHA in `openadkit-docs-source.txt`.
Inside the shared `gh-pages` publishing lane, `deploy-docs.yaml` rejects sources
older than, or divergent from, that published revision. Rebuilding the same SHA
is allowed. Before the first marked publication, the current default-branch head
is the baseline. A marker that is absent from the repository, such as one
inherited with a fork's `gh-pages`, is not comparable and also uses the
default-branch head as the baseline. PR previews do not replace the production
marker.

## Evidence runs

- **Input:** `build_tag`, `<run_id>-<run_attempt>`, whose `build-metadata-<build_tag>`
  artifact must be available in the repository.
- **What it tests:** the workflow checks out the build's `openadkit_sha` and takes
  the image digests from the same metadata, never latest aliases.
- **How it runs:** hosted runners execute the L0–L3 cells, retry a failed cell
  once, and aggregate every expected cell; a missing cell fails the run.
- **Output:** per-cell diagnostics and the `evidence-summary-<build_tag>`
  artifact, which the release gate reads.

Cells use `schemaVersion: 1`, and the summary (`schemaVersion: 3`) carries them
as written. Readers accept only these versioned payloads: a cell without
`schemaVersion: 1` and `metrics` is rejected. Read timings from `metrics`.
Source and config checksums leave out the
`build`, `install` and `log` products of a workspace.

## Split-host allowlists

Scenario Simulation's split evidence cell checks that every topic on its Zenoh
allowlist exists in one of the two role graphs, so an Autoware rename fails CI
instead of silently stopping a topic. CI cannot run CARLA, so its allowlist is
checked by hand against a two-host run after an Autoware update.
