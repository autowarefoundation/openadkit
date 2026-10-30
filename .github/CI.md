# CI ownership

The pipeline is **build → scan + runtime evidence → validate → package → publish**.
Workflows own triggers, job ordering, runners and permissions. Scripts own the
data and behavior contracts; local actions own repeated execution recipes.

| Responsibility | Owner |
| --- | --- |
| Build matrices, changed-target selection, contexts and Bake overrides | `scripts/build.py` |
| CI image tags, Bake execution and ccache restore/save/prune | `actions/build-image/` |
| Source lock import, Buildx and registry login | `actions/setup-build-env/` |
| `main`'s weekly Autoware development snapshot and its pull request | `scripts/bump_autoware.py`, `workflows/bump-autoware.yaml` |
| Image metadata capture, inventory coverage, scan rows and artifact validation | `scripts/images.py` |
| Validation and evidence cell plans (nodes, checks) and the kit inventory | `scripts/validation_matrix.py` |
| Executing one evidence cell: validate/start/cleanup and the L0–L2 checks it names | `scripts/evidence/run_cell.sh` |
| Cell payloads, the run summary and its report | `scripts/evidence/` |
| External release checks and sequencing | `scripts/validate_release.sh` |
| Immutable release plan, runtime pins, and bundle staging and integrity | `scripts/release_plan.py` |
| Packaging, image promotion and GitHub publication | `scripts/*release*.sh` |

The shared build action never grants permissions. PR builds remain local
(`load`, no push), with temporary shared caches restricted to same-repository
PRs. Published builds retain exact upstream contexts, source/lock labels,
security-refresh stamps and the existing bounded cache policy. The local Bake
graph in `components/docker-bake.hcl` still owns Dockerfiles and dependency edges.

`images.py` keeps the existing unversioned, snake-case build/scan JSON formats.
It records **observed** registry platforms, not the inventory's expected list.
The scanner and release validator use the same digest/platform records; the
validator still checks raw-byte sidecar hashes and exact inventory coverage.
Shell retains the registry retry/error policy and GitHub run selection.

Shared parsing is **not** shared authorization: release validation still requires
the latest eligible full scan to pass and a successful evidence run whose summary
passed the promoted build. Packaging reparses image records and rechecks that
summary against the build and commit. Registry preflight remains at
both validation and promotion.

Release packaging and evidence staging assemble the kit through one
`release_plan.py --stage` step, so evidence runs the tree the release ships;
evidence adds only the example kits. The bundle, the release plan and the
evidence subjects all read one kit inventory.

Each evidence matrix row is the complete cell plan: identity, the node list in
manifest order and the L1/L2 checks. `run_cell.sh` executes the row with a
common validate/start/cleanup lifecycle; it does not derive policy from
deployment names. Scenario isolation and golden-path checks stay distinct.
Hosted split evidence is two nodes on one runner, not proof of two physical
hosts.

The one integrator example lives at `deployments/custom-kit/`, with its kit
manifest and deployment files side by side. CI stages it without host-built
workspace products and verifies its source checksum.

After changing a shared build owner, update both workflow path triggers and the
changed-input patterns in `build.py`. Python helpers needed by release and scan
must also be included in their trusted policy sparse checkouts.

Production docs builds record their checkout SHA in `openadkit-docs-source.txt`.
Inside the shared `gh-pages` publishing lane, `deploy-docs.yaml` rejects sources
older than, or divergent from, that published revision. Rebuilding the same SHA
is allowed. Before the first marked publication, the current default-branch head
is the baseline. PR previews do not replace the production marker.
