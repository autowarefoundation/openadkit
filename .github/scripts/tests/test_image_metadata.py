"""Artifact contracts shared by capture, scanner and release planning."""
import copy
import hashlib
import json

import pytest
from release_fixtures import BUILD_TAG, DIGEST, ROOT, build_metadata, run_validator

import images


@pytest.fixture
def artifacts(tmp_path):
    metadata = build_metadata()
    metadata.update(run_id="123", run_attempt="1")
    upstream = [{"name": name, "ros_distro": distro, "ref": f"ghcr.io/autowarefoundation/autoware:{name}-{distro}-1.8.0",
                 "digest": DIGEST, "uri": f"docker-image://ghcr.io/autowarefoundation/autoware:{name}-{distro}-1.8.0@{DIGEST}"}
                for name in ("core-devel", "base", "base-cuda-runtime", "base-cuda-devel") for distro in ("humble", "jazzy")]
    metadata["upstream_images"] = upstream
    directory = tmp_path / "release-input/build"
    directory.mkdir(parents=True)
    for file, key, data in [
        ("autoware-lock.repos", "autoware_lock_sha256", b"repositories: {}\n"),
        ("image-inventory.json", "image_inventory_sha256", (ROOT / ".github/image-inventory.json").read_bytes()),
        ("upstream-images.json", "upstream_images_sha256", json.dumps(upstream).encode()),
    ]:
        (directory / file).write_bytes(data)
        metadata[key] = hashlib.sha256(data).hexdigest()
    # Independent wire fixture, not a shared-model producer.
    scan = {"build_tag": BUILD_TAG, "policy_sha": metadata["openadkit_sha"], "scan_scope": "all", "scan_status": "passed",
            "run_id": "456", "run_attempt": "1", "scanned_images": [
                {**{key: row[key] for key in ("repo", "target", "ros_distro", "digest")},
                 "image_ref": row["repo"] + "@" + DIGEST, "platform": platform}
                for row in metadata["images"] for platform in row["platforms"]]}
    return directory, metadata, scan


@pytest.mark.parametrize("problem", [None, "duplicate", "digest", "ref", "platform", "missing", "run_id", "upstream", "embedded", "hash", "policy", "scan_missing", "scan_extra", "scan_ref"])
def test_artifact_checks_stay_exact_at_the_shell_boundary(tmp_path, artifacts, problem):
    directory, metadata, scan = artifacts
    if problem == "duplicate":
        metadata["images"].append(copy.deepcopy(metadata["images"][0]))
    elif problem in ("digest", "ref", "platform"):
        metadata["images"][0]["platforms" if problem == "platform" else problem] = ["linux/arm64"] if problem == "platform" else "wrong"
    elif problem == "missing":
        metadata["images"].pop()
    elif problem == "run_id":
        metadata["run_id"] = 123
    elif problem == "upstream":
        metadata["upstream_images"].pop()
        data = json.dumps(metadata["upstream_images"]).encode()
        (directory / "upstream-images.json").write_bytes(data)
        metadata["upstream_images_sha256"] = hashlib.sha256(data).hexdigest()
    elif problem == "embedded":
        metadata["upstream_images"][0]["digest"] = "sha256:" + "f" * 64
    elif problem == "hash":
        (directory / "autoware-lock.repos").write_text("tampered")
    elif problem == "policy":
        scan["policy_sha"] = "f" * 40
    elif problem == "scan_missing":
        scan["scanned_images"].pop()
    elif problem == "scan_extra":
        scan["scanned_images"].append(dict(scan["scanned_images"][0], target="extra"))
    elif problem == "scan_ref":
        scan["scanned_images"][0]["image_ref"] = "mutable:tag"
    (directory / "build-metadata.json").write_text(json.dumps(metadata))
    scan_dir = tmp_path / "release-input/scan"
    scan_dir.mkdir()
    (scan_dir / "scan-metadata.json").write_text(json.dumps(scan))
    result = run_validator(tmp_path, "validate_metadata", IMAGE_PREFIX_COMPONENT="ghcr.io/example/openadkit")
    assert (result.returncode == 0) is (problem is None), result.stderr


def test_capture_uses_registry_platforms_and_scan_rows(artifacts, monkeypatch):
    directory, metadata, scan = artifacts
    by_ref = {row["ref"]: row for row in metadata["images"]}
    def inspect(command, **kwargs):
        row = by_ref[command[-1]]
        platforms = [{"platform": {"os": "linux", "architecture": platform.split("/")[1]}} for platform in row["platforms"]]
        return json.dumps({"manifest": {"digest": DIGEST, "manifests": [*platforms, {"platform": {"os": "unknown", "architecture": "unknown"}}]}})
    monkeypatch.setattr(images.subprocess, "check_output", inspect)
    env = {key.upper(): metadata[key] for key in ("build_tag", "openadkit_sha", "autoware_input_ref", "autoware_ref_type", "autoware_ref", "autoware_base_version")}
    env.update(GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1", SCAN_REQUESTED="false", PREPARED_LOCK_SHA256=metadata["autoware_lock_sha256"],
               COMMON="ghcr.io/example/openadkit-common", COMPONENT="ghcr.io/example/openadkit")
    captured = images.capture(directory, env)
    assert captured == metadata
    assert [{key: value for key, value in row.items() if key != "platform_label"} for row in images.scan_rows(captured)] == scan["scanned_images"]
    # "Re-run failed jobs" captures in a later attempt under the original tag.
    assert images.capture(directory, {**env, "GITHUB_RUN_ATTEMPT": "2"}) == metadata
    by_ref[metadata["images"][0]["ref"]]["platforms"] = ["linux/arm64"]
    assert images.capture(directory, env)["images"][0]["platforms"] == ["linux/arm64"]


def test_scan_duplicates_and_distro_overrides_are_supported(artifacts):
    directory, metadata, scan = artifacts
    (directory / "build-metadata.json").write_text(json.dumps(metadata))
    scan["scanned_images"].append(dict(scan["scanned_images"][0]))
    images.validate_artifacts(directory, scan, BUILD_TAG, "ghcr.io/example/openadkit-common", "ghcr.io/example/openadkit")
    assert images.inventory_images({"ros_distros": ["humble", "jazzy"], "images": [
        {"repo": "component", "target": "api", "ros_distros": ["jazzy"], "platforms": ["linux/amd64"]}]}, "common", "component") == [
        {"repo": "component", "target": "api", "ros_distro": "jazzy", "platforms": ["linux/amd64"]}]


def test_the_run_page_summary_names_the_build_and_each_image():
    text = images.summary({
        "build_tag": "1-1", "autoware_base_version": "2.0.0", "autoware_ref": "6f91fff359e8",
        "openadkit_sha": "5e3837ac7b80",
        "images": [{"target": "api", "ros_distro": "humble", "platforms": ["linux/amd64", "linux/arm64"],
                    "digest": "sha256:" + "a" * 64}],
    })
    assert "Build `1-1` · Autoware 2.0.0 (`6f91fff`) · Open AD Kit `5e3837a`" in text
    assert "| `api` | humble | amd64, arm64 | `sha256:aaaaaaaaaaaa` |" in text
