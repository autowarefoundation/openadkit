"""Release shell boundaries: immutable plans, safe publication and packaging."""

import hashlib
import json
import os
import subprocess
import tarfile
import zipfile

import pytest
from release_fixtures import (
    BUILD_TAG,
    DIGEST,
    RELEASE_SHA,
    ROOT,
    VERSION,
    WRITE_NOTES,
    build_images,
    build_metadata,
    executable,
    packager_env,
    passing_summary,
    run_packager,
    run_validator,
    write_plan,
)


@pytest.mark.parametrize(("dispatch", "branch", "ref_type", "input_ref", "accepted"), [
    ("main", "main", "tag", "2.0.0", True),
    ("release/2.0", "release/2.0", "tag", "2.0.0", True),
    ("main", "release/2.0", "tag", "2.0.0", False),
    ("main", "main", "branch", "main", False),
    ("main", "main", "tag", "v2.0.0", False),
])
def test_a_release_is_a_build_of_its_branch_on_an_autoware_release(tmp_path, dispatch, branch, ref_type, input_ref, accepted):
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "build-metadata.json").write_text(json.dumps({
        "openadkit_sha": RELEASE_SHA, "autoware_input_ref": input_ref,
        "autoware_ref_type": ref_type, "autoware_version": "2.0.0",
    }))
    result = run_validator(tmp_path, f"source_branch={branch}; validate_release_rules", GITHUB_REF=f"refs/heads/{dispatch}")
    assert (result.returncode == 0) is accepted, result.stderr


@pytest.mark.parametrize("version", ["v2.0.0", "v2.1.0", "v3.0.0-rc.1"])
def test_a_version_is_open_ad_kits_own(tmp_path, version):
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "build-metadata.json").write_text(json.dumps({
        "openadkit_sha": RELEASE_SHA, "autoware_input_ref": "2.0.0",
        "autoware_ref_type": "tag", "autoware_version": "2.0.0",
    }))
    result = run_validator(tmp_path, "validate_inputs; source_branch=main; validate_release_rules",
                           VERSION=version, GITHUB_REF="refs/heads/main")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("ref", "accepted"), [
    ("refs/heads/main", True), ("refs/heads/release/2.0", True), ("refs/heads/feature", False), ("refs/tags/v2.0.0", False),
])
def test_releases_are_dispatched_from_main_or_a_maintenance_branch(tmp_path, ref, accepted):
    result = run_validator(tmp_path, "validate_inputs", GITHUB_REF=ref)
    assert (result.returncode == 0) is accepted, result.stderr


@pytest.mark.parametrize(("image_repo", "accepted"), [
    ("ghcr.io/autowarefoundation/openadkit", True),
    # A fork releases to its own namespace, as a rehearsal does.
    ("ghcr.io/a-fork/openadkit", True),
    ("ghcr.io/autowarefoundation/openadkit-ci", False),
    ("docker.io/autowarefoundation/openadkit", False),
])
def test_a_release_pushes_to_the_registry_and_package_the_manifest_names(tmp_path, image_repo, accepted):
    result = run_validator(tmp_path, "validate_manifest_consistency", IMAGE_REPO=image_repo,
                           RELEASE_SOURCE_ROOT=str(ROOT))
    assert (result.returncode == 0) is accepted, result.stderr
    assert accepted or "must name the registry and package" in result.stderr


@pytest.mark.parametrize("problem", [None, "missing", "duplicate"])
def test_plan_requires_complete_pinned_dual_distro_images(tmp_path, problem):
    images = build_images()
    if problem == "missing":
        images = [image for image in images if (image["target"], image["ros_distro"]) != ("control", "jazzy")]
    elif problem == "duplicate":
        images.append(dict(images[0]))
    result, output = write_plan(tmp_path, images=images)
    if problem:
        assert result.returncode != 0 and problem in result.stderr
        return
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_text())
    context = plan["releaseContext"]
    # The runtime images, and the devel image integrators build overlays in.
    expected = set(json.loads((ROOT / "openadkit.json").read_text())["componentImages"].values())
    expected.add("universe-common-devel")
    assert set(context["images"]) == {"humble", "jazzy"}
    for distro, refs in context["images"].items():
        assert set(refs) == expected
        assert all(ref.endswith(f"@{DIGEST}") and f"-{distro}-{VERSION}@" in ref for ref in refs.values())
    assert {row["rosDistro"] for row in plan["bundle"]["validation"]} == {"humble", "jazzy"}
    assert any(row["role"] for row in plan["bundle"]["validation"])
    # The BOM names the ROS apt snapshot every distro's images were built from.
    assert set(plan["rosSnapshots"]) == {"humble", "jazzy"}
    assert all(f'default = "{date}"' in (ROOT / "components/docker-bake.hcl").read_text() for date in plan["rosSnapshots"].values())


@pytest.mark.parametrize("problem", [None, "failed", "not-release", "other-build", "other-commit"])
def test_plan_takes_only_this_release_passing_evidence(tmp_path, problem):
    summary = passing_summary(build_metadata())
    if problem == "failed":
        summary["result"] = "FAILED"
    elif problem == "not-release":
        summary["release_evidence"] = False
    elif problem == "other-build":
        summary["build_tag"] = "999-1"
    elif problem == "other-commit":
        summary["source_sha"] = "f" * 40
    result, output = write_plan(tmp_path, summary=summary)
    assert (result.returncode == 0) is (problem is None), result.stderr
    if problem is None:
        evidence = json.loads(output.read_text())["evidence"]
        assert evidence["result"] == "PASSED" and evidence["build_tag"] == BUILD_TAG
        assert evidence["cells"] == summary["cells"] and "exempt" in evidence


def test_a_stable_release_moves_one_alias_per_image_and_distro(tmp_path):
    result, output = write_plan(tmp_path, summary=passing_summary(build_metadata()))
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_text())
    assert plan["release"]["defaultRosDistro"] == json.loads((ROOT / "openadkit.json").read_text())["defaultRosDistro"]
    for image in plan["images"]:
        assert image["aliases"] == [f'{image["repo"]}:{image["target"]}-{image["rosDistro"]}']


def select_latest(tmp_path, name, workflow, file, runs, eligible, passed, directory):
    """Run the gate's artifact selection against stubbed runs, newest first:
    (run conclusion, branch, artifact content[, event, head repository])."""
    artifacts, run_json = [], {}
    for index, (conclusion, branch, content, *origin) in enumerate(runs):
        event, repository, head_sha = (*origin, "on-branch")[:3] if origin else ("workflow_dispatch", "example/repo", "on-branch")
        artifact, run = 100 + index, 200 + index
        with zipfile.ZipFile(tmp_path / f"{artifact}.zip", "w") as archive:
            archive.writestr(file, json.dumps(content))
        artifacts.append(f"{artifact}\t2026-10-{30 - index:02d}T00:00:00Z")
        run_json[str(artifact)] = run
        run_json[str(run)] = {"path": workflow, "head_branch": branch, "event": event, "head_sha": head_sha,
                              "head_repository": {"full_name": repository},
                              "status": "completed", "conclusion": conclusion}
    (tmp_path / "runs.json").write_text(json.dumps(run_json))
    executable(tmp_path / "bin/gh", f'''#!/usr/bin/env python3
import json, sys
path = [arg for arg in sys.argv[1:] if arg.startswith("repos/")][0]
runs = json.load(open({str(tmp_path / "runs.json")!r}))
if "/branches/" in path:
    print("tip")
elif "/compare/" in path:
    print("diverged" if path.split("/compare/")[1].startswith("off-") else "ahead")
elif "artifacts?name={name}" in path:
    print("\\n".join({artifacts!r}))
elif path.endswith("/zip"):
    sys.stdout.buffer.write(open({str(tmp_path)!r} + "/" + path.split("/")[-2] + ".zip", "rb").read())
elif "/artifacts/" in path:
    print(runs[path.split("/")[-1]])
else:
    print(json.dumps(runs[path.split("/")[-1]]))
''')
    result = run_validator(
        tmp_path,
        f"source_branch=release/9.8; select_latest_artifact {name} {workflow} {file} {eligible} {passed} {directory}",
        PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    return result, tmp_path / directory / file


# (run conclusion, branch, summary result, tested the build's own commit), newest first.
@pytest.mark.parametrize(("runs", "accepted"), [
    ([("success", "release/9.8", "PASSED", True)], True),
    ([("failure", "release/9.8", "FAILED", True)], False),
    ([("success", "main", "PASSED", True)], False),
    ([("success", "release/9.8", "PASSED", False)], False),
    # The newest run of this release decides: a passing rerun supersedes a
    # failed run, and a newer failure blocks an older pass.
    ([("success", "release/9.8", "PASSED", True), ("failure", "release/9.8", "FAILED", True)], True),
    ([("failure", "release/9.8", "FAILED", True), ("success", "release/9.8", "PASSED", True)], False),
    # A run that tested another commit against the build is not about this release.
    ([("failure", "release/9.8", "FAILED", False), ("success", "release/9.8", "PASSED", True)], True),
])
def test_evidence_gate_takes_the_newest_run_of_this_release(tmp_path, runs, accepted):
    summaries = [(conclusion, branch, passing_summary(build_metadata()) | {"result": result, "release_evidence": release})
                 for conclusion, branch, result, release in runs]
    result, selected = select_latest(
        tmp_path, f"evidence-summary-{BUILD_TAG}", ".github/workflows/evidence.yaml", "evidence-summary.json",
        summaries, "evidence_is_release", "evidence_passed", "release-input/evidence")
    assert (result.returncode == 0) is accepted, result.stderr
    assert selected.exists() is accepted


# A pull request's run is never release evidence, whatever its branch is called
# and whatever its summary says: it runs the pull request's own code.
@pytest.mark.parametrize(("event", "repository"), [
    ("pull_request", "fork/repo"),
    ("pull_request", "example/repo"),
    ("workflow_dispatch", "fork/repo"),
])
def test_evidence_gate_ignores_pull_request_and_fork_runs(tmp_path, event, repository):
    forged = passing_summary(build_metadata()) | {"result": "FAILED", "release_evidence": True}
    genuine = passing_summary(build_metadata()) | {"result": "PASSED", "release_evidence": True}
    result, selected = select_latest(
        tmp_path, f"evidence-summary-{BUILD_TAG}", ".github/workflows/evidence.yaml", "evidence-summary.json",
        [("success", "release/9.8", forged, event, repository), ("success", "release/9.8", genuine)],
        "evidence_is_release", "evidence_passed", "release-input/evidence")
    assert result.returncode == 0, result.stderr
    assert json.loads(selected.read_text())["result"] == "PASSED"


def test_evidence_gate_ignores_a_run_off_the_branch(tmp_path):
    # A tag named like the branch reports the branch's name as its head_branch.
    forged = passing_summary(build_metadata()) | {"result": "PASSED", "release_evidence": True}
    genuine = passing_summary(build_metadata()) | {"result": "FAILED", "release_evidence": True}
    result, _ = select_latest(
        tmp_path, f"evidence-summary-{BUILD_TAG}", ".github/workflows/evidence.yaml", "evidence-summary.json",
        [("success", "release/9.8", forged, "workflow_dispatch", "example/repo", "off-tag"),
         ("failure", "release/9.8", genuine)],
        "evidence_is_release", "evidence_passed", "release-input/evidence")
    assert result.returncode != 0 and "did not pass" in result.stderr


@pytest.mark.parametrize(("sha", "status", "accepted"), [
    ("on-branch", "ahead", True), ("tip", "identical", True), ("off-tag", "diverged", False), ("newer", "behind", False)])
def test_a_build_commit_must_be_on_its_branch(tmp_path, sha, status, accepted):
    executable(tmp_path / "bin/gh", f'''#!/usr/bin/env python3
import sys
path = [arg for arg in sys.argv[1:] if arg.startswith("repos/")][0]
print("tip" if "/branches/" in path else {status!r})
''')
    result = run_validator(tmp_path, f'source_branch=main; on_branch {sha} || fail "not on branch"',
                           PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    assert (result.returncode == 0) is accepted, result.stderr


# (run conclusion, scan status), newest first; a partial scan is not about the release.
@pytest.mark.parametrize(("runs", "accepted"), [
    ([("success", "passed")], True),
    ([("failure", "failed")], False),
    ([("failure", "failed"), ("success", "passed")], False),
    ([("success", "partial"), ("success", "passed")], True),
])
def test_scan_gate_takes_the_newest_full_scan(tmp_path, runs, accepted):
    def scan(status):
        return {"build_tag": BUILD_TAG, "policy_sha": "c" * 40, "run_id": "300", "run_attempt": "1",
                "scan_scope": "all" if status != "partial" else "changed", "scan_status": "passed" if status == "partial" else status,
                "scanned_images": [{"repo": "ghcr.io/example/openadkit", "target": "api", "ros_distro": "humble",
                                    "digest": DIGEST, "platform": "linux/amd64",
                                    "image_ref": f"ghcr.io/example/openadkit@{DIGEST}"}]}
    result, selected = select_latest(
        tmp_path, f"scan-metadata-{BUILD_TAG}", ".github/workflows/scan-images.yaml", "scan-metadata.json",
        [(conclusion, "release/9.8", scan(status)) for conclusion, status in runs],
        "scan_is_full", "scan_passed", "release-input/scan")
    assert (result.returncode == 0) is accepted, result.stderr
    assert selected.exists() is accepted


# (existing tag, workflow files of the build commit): publishing tags the build
# commit with the run's token, which GitHub allows only with the run's own
# workflow files; an existing tag must already be on the build commit.
@pytest.mark.parametrize(("tag", "build_workflows", "accepted"), [
    (None, "run", True),
    (None, "older", False),
    (RELEASE_SHA, "older", True),
    ("f" * 40, "run", False),
])
def test_publishing_can_tag_the_build_commit(tmp_path, tag, build_workflows, accepted):
    executable(tmp_path / "bin/gh", f'''#!/usr/bin/env python3
import sys
path = [arg for arg in sys.argv[1:] if arg.startswith("repos/")][0]
if "/matching-refs/" in path:
    print(0 if {tag!r} is None else 1)
elif "/commits/refs/tags/" in path:
    print({tag!r})
elif path.endswith("?ref={RELEASE_SHA}"):
    print({build_workflows!r})
elif "/contents/.github?ref=" in path:
    print("run")
else:
    sys.exit("unexpected request " + path)
''')
    result = run_validator(tmp_path, "source_branch=release/9.8; validate_git_tag",
                           PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    assert (result.returncode == 0) is accepted, result.stderr
    if build_workflows == "older" and not accepted:
        assert "build release/9.8 again" in result.stderr


@pytest.mark.parametrize(("problem", "messages"), [
    (None, []),
    ("source", ["Source digest mismatch"]),
    ("conflict", ["Release tag conflict"]),
    # Every conflict is reported before failing, not only the first one.
    ("missing-and-conflict", ["Source image not found", "Release tag conflict"]),
])
def test_release_validation_preflights_registry_state(tmp_path, problem, messages):
    repo = "ghcr.io/example/openadkit"
    images = [{"repo": repo, "target": target, "ros_distro": "humble", "digest": DIGEST,
               "ref": f"{repo}:{target}-humble-{BUILD_TAG}"} for target in ("api", "simulator")]
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "build-metadata.json").write_text(json.dumps({"images": images}))
    missing = images[0]["ref"] if problem == "missing-and-conflict" else None
    conflict = f"{repo}:simulator-humble-{VERSION}" if problem in ("conflict", "missing-and-conflict") else None
    executable(tmp_path / "bin/docker", f'''#!/usr/bin/env python3
import json, sys
ref = sys.argv[4]
if ref == {missing!r} or (ref.endswith({VERSION!r}) and ref != {conflict!r}):
    sys.exit("ERROR: " + ref + ": not found")
mismatch = {problem!r} == "source" and ref.endswith({BUILD_TAG!r})
digest = "sha256:" + "f" * 64 if mismatch or ref == {conflict!r} else {DIGEST!r}
print(json.dumps({{"manifest": {{"digest": digest}}}}))
''')
    result = run_validator(tmp_path, "validate_registry_conflicts",
                           PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", REGISTRY_LOOKUP_MAX_ATTEMPTS="1")
    assert (result.returncode == 0) is (problem is None), result.stderr
    assert all(message in result.stderr for message in messages), result.stderr


def run_manager(tmp_path, operation, *, existing, stable=True, immutable=True):
    asset = tmp_path / "bundle.tar.gz"
    asset.write_bytes(b"validated bundle")
    (tmp_path / "release-notes.md").write_text("notes\n")
    (tmp_path / "release-plan.json").write_text(json.dumps({
        "schemaVersion": 1, "release": {"version": VERSION, "releaseSha": RELEASE_SHA,
                                       "stable": stable, "publishLatestAliases": stable},
        "githubAssets": [{"name": asset.name, "path": asset.name}],
        "releaseContext": {"autoware": {"version": "1.9.0"}},
    }))
    log = tmp_path / "gh-calls"
    executable(tmp_path / "bin/gh", f'''#!/usr/bin/env python3
import sys
args = " ".join(sys.argv[1:])
if args.startswith("release view"):
    existing = {existing!r}
    if existing is None:
        sys.exit("release not found")
    print(existing)
elif args.startswith("api "):
    print({str(immutable).lower()!r})
else:
    with open({str(log)!r}, "a") as output:
        output.write(args + "\\n")
''')
    result = subprocess.run(["bash", str(ROOT / ".github/scripts/manage_github_release.sh"), operation],
                            cwd=tmp_path, text=True, capture_output=True, timeout=30,
                            env=os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "IMMUTABLE_RETRY_SECONDS": "0"})
    return result, log.read_text().splitlines() if log.exists() else []


def test_a_new_release_starts_as_a_draft_with_its_title_and_assets(tmp_path):
    result, calls = run_manager(tmp_path, "draft", existing=None)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1 and calls[0].startswith(f"release create {VERSION} --target {RELEASE_SHA}")
    assert f"--title {VERSION} --notes-file" in calls[0]
    assert "--draft bundle.tar.gz" in calls[0]


def test_a_draft_of_an_earlier_attempt_is_replaced(tmp_path):
    result, calls = run_manager(tmp_path, "draft", existing="true")
    assert result.returncode == 0, result.stderr
    assert calls[0] == f"release delete {VERSION} --yes" and calls[1].startswith("release create")


def test_a_published_release_is_never_touched(tmp_path):
    result, calls = run_manager(tmp_path, "draft", existing="false")
    assert result.returncode != 0 and "release the next version" in result.stderr
    assert calls == []


@pytest.mark.parametrize(("stable", "flags"), [
    (True, "--draft=false --prerelease=false --latest=true"),
    (False, "--draft=false --prerelease=true --latest=false"),
])
def test_publishing_marks_a_stable_release_latest(tmp_path, stable, flags):
    result, calls = run_manager(tmp_path, "publish", existing="true", stable=stable)
    assert result.returncode == 0, result.stderr
    assert calls == [f"release edit {VERSION} {flags}"]


def test_publishing_fails_when_the_release_is_not_immutable(tmp_path):
    result, _ = run_manager(tmp_path, "publish", existing="true", immutable=False)
    assert result.returncode != 0 and "turn on immutable releases" in result.stderr


@pytest.mark.parametrize("problem", [None, "source", "conflict", "create", "policy"])
def test_promotion_never_updates_aliases_after_preflight_or_version_failure(tmp_path, problem):
    repo = "ghcr.io/example/openadkit"
    release_ref, alias = f"{repo}:api-humble-{VERSION}", f"{repo}:api-humble"
    (tmp_path / "release-plan.json").write_text(json.dumps({
        "schemaVersion": 1, "release": {"version": VERSION, "defaultRosDistro": "humble",
                                       "stable": True, "publishLatestAliases": True},
        "images": [{"repo": repo, "rosDistro": "humble", "digest": DIGEST,
                    "sourceRef": f"{repo}:api-humble-{BUILD_TAG}", "releaseRef": release_ref, "aliases": [alias]}],
    }))
    calls = tmp_path / "created"
    executable(tmp_path / "bin/docker", f'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
args = sys.argv[1:]
created = Path({str(calls)!r})
if args[:3] == ["buildx", "imagetools", "inspect"]:
    ref = args[3]
    if {problem!r} == "conflict" and ref == {release_ref!r}:
        print(json.dumps({{"manifest": {{"digest": "sha256:" + "f" * 64}}}}))
    elif ref.endswith({BUILD_TAG!r}) or (created.exists() and ref in created.read_text().splitlines()):
        digest = "sha256:" + "f" * 64 if {problem!r} == "source" else {DIGEST!r}
        print(json.dumps({{"manifest": {{"digest": digest}}}}))
    else:
        sys.exit("ERROR: " + ref + ": not found")
elif args[:3] == ["buildx", "imagetools", "create"]:
    if {problem!r} == "create":
        sys.exit("create failed")
    with created.open("a") as output:
        output.write(args[4] + "\\n")
else:
    sys.exit("unexpected docker call")
''')
    executable(tmp_path / "bin/gh", f"#!/usr/bin/env bash\nprintf '%s\\n' {'v9.9.0' if problem == 'policy' else VERSION}\n")
    executable(tmp_path / "bin/sleep", "#!/usr/bin/env bash\nexit 0\n")
    result = subprocess.run(["bash", str(ROOT / ".github/scripts/promote_release_images.sh")],
                            cwd=tmp_path, text=True, capture_output=True, timeout=30, env=os.environ | {
                                "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "GITHUB_REPOSITORY": "example/repo",
                                "REGISTRY_LOOKUP_MAX_ATTEMPTS": "1", "REGISTRY_LOOKUP_RETRY_DELAY_SECONDS": "0",
                            })
    assert (result.returncode == 0) is (problem is None), result.stderr
    assert (calls.read_text().splitlines() if calls.exists() else []) == ([] if problem else [release_ref, alias])
    if problem:
        assert {"source": "Source digest mismatch", "conflict": "Release tag conflict",
                "create": "did not converge", "policy": "Latest alias policy changed"}[problem] in result.stderr


def test_bundle_pins_integrity_and_reproducibility(tmp_path):
    env, calls = packager_env(tmp_path)
    run_packager(tmp_path, env)
    asset = tmp_path / f"dist/openadkit-{VERSION}.tar.gz"
    first_asset = hashlib.sha256(asset.read_bytes()).hexdigest()
    first_plan = (tmp_path / "release-plan.json").read_bytes()
    with tarfile.open(asset) as archive:
        members = archive.getmembers()
        assert members and all(member.mtime == 0 and member.uid == 0 and member.gid == 0 for member in members)
        assert all(not member.issym() and not member.islnk() for member in members)
        assert all("__pycache__" not in member.name and not member.name.endswith(".pyc") for member in members)
        archive.extractall(tmp_path / "extract", filter="data")
    root = tmp_path / f"extract/openadkit-{VERSION}"
    # The launcher is the release commit's, set to install from the repository that released it.
    launcher = (ROOT / "openadkit").read_text().replace(
        "readonly OPENADKIT_REPOSITORY=autowarefoundation/openadkit\n", "readonly OPENADKIT_REPOSITORY=example/repo\n")
    assert launcher != (ROOT / "openadkit").read_text()
    assert (root / "openadkit").read_text() == launcher and (tmp_path / "dist/openadkit").read_text() == launcher
    assert os.access(root / "openadkit", os.X_OK)
    context = json.loads((root / "openadkit.json").read_text())
    assert context["kind"] == "release" and set(context["images"]) == {"humble", "jazzy"}
    listed = subprocess.run([str(root / "openadkit"), "list", "--json"], env=env, text=True, capture_output=True, check=True)
    deployments = json.loads(listed.stdout)["deployments"]
    assert [entry["modified"] for entry in deployments] == [False] * len(context["deployments"])
    # The bundle lists deployments in the catalog's order.
    catalog = json.loads((ROOT / "openadkit.json").read_text())["deployments"]
    assert [entry["name"] for entry in deployments] == list(catalog)
    assert "humble|" in calls.read_text() and "jazzy|" in calls.read_text()
    (tmp_path / "dist/stale.tar.gz").write_bytes(b"stale")
    run_packager(tmp_path, env, umask="077")
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == first_asset
    assert (tmp_path / "release-plan.json").read_bytes() == first_plan
    assert sorted(path.name for path in (tmp_path / "dist").iterdir()) == ["openadkit", asset.name]
    scan = tmp_path / "release-input/scan"
    scan.mkdir()
    (scan / "scan-metadata.json").write_text('{"scan_status":"passed"}')
    # No earlier release: the notes list no changes and ask GitHub for none.
    executable(tmp_path / "bin/gh", "#!/usr/bin/env bash\n[[ \"$*\" == *\"/releases --jq\"* ]] || exit 1\n")
    subprocess.run(["bash", str(WRITE_NOTES)], cwd=tmp_path, env=env, check=True, capture_output=True)
    notes = (tmp_path / "release-notes.md").read_text()
    assert f"install --version {VERSION}" in notes and "What's Changed" not in notes
    assert "**1/1** evidence cells passed" in notes
    metadata = json.loads((tmp_path / "release-metadata.json").read_text())
    assert metadata["bundles"] == [{"name": asset.name, "sha256": first_asset}]
    # The plan stays in the workflow: the metadata is the one file a release publishes about itself.
    assert "release-plan.json" not in [item["name"] for item in json.loads(first_plan)["githubAssets"]]
    assert "release_plan_sha256" not in metadata
    assert metadata["evidence"]["result"] == "PASSED"
