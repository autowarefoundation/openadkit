"""Release policy: signature verification is necessary, never sufficient."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))
from evidence_fixtures import passing_statement  # noqa: E402

from evidence import release_gate  # noqa: E402

# Load existing subprocess fixtures without coupling tests to collection order.
spec = importlib.util.spec_from_file_location("release_pipeline_fixtures", Path(__file__).with_name("test_release_pipeline.py"))
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


@pytest.fixture
def metadata():
    return {"build_tag": pipeline.BUILD_TAG, "openadkit_sha": pipeline.RELEASE_SHA, "images": pipeline.build_images()}


def verify(statement, metadata):
    return release_gate.verified_report(
        [{"verificationResult": {"statement": statement}}], metadata, ROOT, "humble", "example/repo",
    )


def test_complete_passing_statement_produces_release_metadata(metadata):
    report = verify(passing_statement(metadata), metadata)
    assert report["result"] == "PASSED"
    assert len(report["cells"]) == 8
    assert {row["deployment"] for row in report["exempt"]} == {"carla-simulation", "logging-simulation"}
    assert report["defaultRosDistroDecision"]["selected"] == "humble"
    release_gate.validate_report(report, metadata, ROOT, "humble")


@pytest.mark.parametrize("result", ["FAILED", "WARNED", "UNKNOWN", "passed", None, ""])
def test_only_exact_passed_is_accepted(metadata, result):
    statement = passing_statement(metadata)
    statement["predicate"]["result"] = result
    with pytest.raises(ValueError, match="requires PASSED"):
        verify(statement, metadata)


@pytest.mark.parametrize("case", ["subject", "duplicate-subject", "digest", "cell", "duplicate-cell", "passedTests", "warnedTests", "failedTests", "level", "overlay", "distro", "platform", "build", "source", "kit", "predicate"])
def test_incomplete_or_inconsistent_signed_claim_is_rejected(metadata, case):
    statement = passing_statement(metadata)
    predicate = statement["predicate"]
    config = predicate["configuration"]
    if case == "subject":
        statement["subject"].pop()
    elif case == "duplicate-subject":
        statement["subject"].append(statement["subject"][0])
    elif case == "digest":
        statement["subject"][0]["digest"]["sha256"] = "f" * 64
    elif case == "cell":
        config.pop()
    elif case == "duplicate-cell":
        config.append(config[0])
    elif case in ("passedTests", "warnedTests", "failedTests"):
        predicate[case] = ["not-a-required-cell"]
    elif case == "level":
        config[0]["annotations"]["levels"]["L2"] = None
    elif case == "overlay":
        next(cell for cell in config if cell["annotations"]["kit"])["annotations"]["overlayConformant"] = False
    elif case == "predicate":
        statement["predicateType"] = "https://slsa.dev/provenance/v1"
    else:
        field = {"distro": "rosDistro", "platform": "platform", "build": "buildTag", "source": "sourceSha", "kit": "kit"}[case]
        config[0]["annotations"][field] = "wrong"
    with pytest.raises(ValueError):
        verify(statement, metadata)


def test_statements_cannot_be_unioned_to_fill_missing_coverage(metadata):
    first = passing_statement(metadata)
    second = copy.deepcopy(first)
    first["subject"] = first["subject"][:10]
    second["subject"] = second["subject"][10:]
    with pytest.raises(ValueError, match="no complete PASSED"):
        release_gate.verified_report(
            [{"verificationResult": {"statement": statement}} for statement in (first, second)],
            metadata, ROOT, "humble", "example/repo",
        )


def test_one_complete_successful_retry_is_sufficient(metadata):
    failed = passing_statement(metadata)
    failed["predicate"]["result"] = "FAILED"
    passed = passing_statement(metadata)
    report = release_gate.verified_report(
        [{"verificationResult": {"statement": statement}} for statement in (failed, passed)],
        metadata, ROOT, "humble", "example/repo",
    )
    assert report["statement"] == passed


@pytest.mark.parametrize("verified", [[], {}, None, [{}], [{"verificationResult": {"statement": None}}]])
def test_empty_or_malformed_verification_cannot_pass(metadata, verified):
    with pytest.raises((ValueError, AttributeError)):
        release_gate.verified_report(verified, metadata, ROOT, "humble", "example/repo")


def test_plan_rejects_tampered_validated_report(metadata):
    report = verify(passing_statement(metadata), metadata)
    report["cells"][0]["ready_s"] = 0
    with pytest.raises(ValueError, match="differs"):
        release_gate.validate_report(report, metadata, ROOT, "humble")


def test_changed_release_source_cannot_reuse_old_evidence(tmp_path, metadata):
    source = tmp_path / "source"
    source.mkdir()
    pipeline.shutil.copy2(ROOT / "openadkit.json", source / "openadkit.json")
    for directory in ("cli", "deployments", "examples"):
        pipeline.shutil.copytree(ROOT / directory, source / directory)
    statement = passing_statement(metadata)
    path = source / "examples/custom-kit/README.md"
    path.write_text(path.read_text() + "\nchanged kit\n")
    with pytest.raises(ValueError, match="subjects differ"):
        release_gate.verified_report(
            [{"verificationResult": {"statement": statement}}], metadata, source, "humble", "example/repo",
        )


def test_release_default_cannot_silently_switch_distros(metadata):
    with pytest.raises(ValueError, match="default distro must match"):
        release_gate.verified_report(
            [{"verificationResult": {"statement": passing_statement(metadata)}}],
            metadata, ROOT, "jazzy", "example/repo",
        )


def test_missing_evidence_report_blocks_packaging(tmp_path):
    env, _ = pipeline.packager_env(tmp_path)
    (tmp_path / "release-input/evidence-report.json").unlink()
    result = subprocess.run(["bash", str(pipeline.PACKAGER)], cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "evidence-report.json" in result.stderr
    assert not list((tmp_path / "dist").glob("*.tar.gz"))


def test_release_notes_cannot_replace_verified_current_metrics_with_unsigned_summary(tmp_path):
    env, _ = pipeline.packager_env(tmp_path)
    pipeline.run_packager(tmp_path, env)
    scan = tmp_path / "release-input/scan"
    scan.mkdir()
    (scan / "scan-metadata.json").write_text('{"scan_status":"passed"}')
    unsigned = tmp_path / "unsigned.json"
    unsigned.write_text('{"result":"FAILED","cells":[]}')
    result = subprocess.run(["bash", str(pipeline.WRITE_NOTES)], cwd=tmp_path,
                            env=env | {"EVIDENCE_CURRENT_SUMMARY": str(unsigned)}, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    notes = (tmp_path / "release-notes.md").read_text()
    assert "Evidence result: **PASSED**" in notes
    assert "Passing cells: **8/8**" in notes
    assert "Evidence result: **FAILED**" not in notes


def test_release_source_is_archived_from_promoted_sha_without_changing_dispatch_checkout(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    git = ["git", "-C", str(repository)]
    subprocess.run([*git, "init", "--initial-branch=main"], check=True, capture_output=True)
    subprocess.run([*git, "config", "user.name", "Test"], check=True)
    subprocess.run([*git, "config", "user.email", "test@example.invalid"], check=True)
    path = repository / "openadkit.json"
    path.write_text('{"revision":"promoted"}')
    subprocess.run([*git, "add", "openadkit.json"], check=True)
    subprocess.run([*git, "commit", "-m", "promoted", "--no-gpg-sign"], check=True, capture_output=True)
    promoted = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    path.write_text('{"revision":"dispatch"}')
    subprocess.run([*git, "commit", "-am", "dispatch", "--no-gpg-sign"], check=True, capture_output=True)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", str(repository), str(checkout)], check=True, capture_output=True)
    result = pipeline.run_validator(checkout, 'release_sha="$PROMOTED_SHA"; checkout_release_source', PROMOTED_SHA=promoted)
    assert result.returncode == 0, result.stderr
    assert json.loads((checkout / "openadkit.json").read_text())["revision"] == "dispatch"
    assert json.loads((checkout / "release-source/openadkit.json").read_text())["revision"] == "promoted"


@pytest.mark.parametrize(("job", "script"), [("validate", "evidence/release_gate.py"), ("package-bundles", "release_plan.py")])
def test_actual_workflow_sparse_paths_include_python_dependencies(tmp_path, job, script):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yaml").read_text())
    patterns = workflow["jobs"][job]["steps"][0]["with"]["sparse-checkout"].splitlines()
    for pattern in patterns:
        path = pattern.strip("/")
        source = ROOT / path
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            pipeline.shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            pipeline.shutil.copy2(source, target)
    result = subprocess.run(["python3", str(tmp_path / ".github/scripts" / script), "--help"],
                            cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_real_aggregator_output_passes_the_gate_with_workflow_matrix(tmp_path, metadata):
    cells = release_gate.expected_cells(ROOT)
    for name, row in cells.items():
        directory = tmp_path / "cells" / name
        directory.mkdir(parents=True)
        (directory / "cell.json").write_text(json.dumps({
            "name": name, "deployment": row["deployment"], "distro": row["distro"],
            "node": row.get("node") or "", "kit": row.get("kit") or "", "platform": "linux/amd64",
            "build_tag": metadata["build_tag"], "source_sha": metadata["openadkit_sha"],
            "result": "PASSED", "overlayConformant": True,
            "levels": {level: {"ok": True} for level in ("L0", "L1", "L2")},
        }))
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata))
    output = tmp_path / "attestation"
    result = subprocess.run([
        "python3", str(ROOT / ".github/scripts/evidence/test_result.py"), "--cells-dir", str(tmp_path / "cells"),
        "--build-metadata", str(metadata_path), "--source-root", str(ROOT),
        "--expected-cells", json.dumps({"include": list(cells.values())}), "--output-dir", str(output),
    ], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    statement = passing_statement(metadata)
    statement["predicate"] = json.loads((output / "evidence-predicate.json").read_text())
    assert verify(statement, metadata)["result"] == "PASSED"


@pytest.mark.parametrize("gh_status", [0, 1])
def test_shell_gate_requires_verifier_success_and_trusted_identity(tmp_path, metadata, gh_status):
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "build-metadata.json").write_text(json.dumps(metadata))
    fixture = tmp_path / "verified.json"
    fixture.write_text(json.dumps([{"verificationResult": {"statement": passing_statement(metadata)}}]))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh-args"
    pipeline.executable(bin_dir / "gh", f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" > "{log}"\ncat "{fixture}"\nexit {gh_status}\n')
    # A previous success must not survive a failed signature verification.
    report_path = tmp_path / "release-input/evidence-report.json"
    report_path.write_text('{"result":"PASSED"}')
    result = pipeline.run_validator(
        tmp_path, "verify_evidence", RELEASE_SOURCE_ROOT=str(ROOT),
        PATH=f"{bin_dir}:{pipeline.os.environ['PATH']}",
    )
    assert (result.returncode == 0) is (gh_status == 0), result.stderr
    assert report_path.exists() is (gh_status == 0)
    for flag in ("--repo example/repo", "--signer-workflow example/repo/.github/workflows/evidence.yaml", "--source-ref refs/heads/main", "--deny-self-hosted-runners", f"--predicate-type {release_gate.PREDICATE_TYPE}"):
        assert flag in log.read_text()
