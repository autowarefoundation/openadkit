"""Release inputs shared by policy and shell-boundary tests, not other test modules."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

PACKAGER = ROOT / ".github/scripts/package_release_bundles.sh"
PLANNER = ROOT / ".github/scripts/release_plan.py"
VALIDATOR = ROOT / ".github/scripts/validate_release.sh"
WRITE_NOTES = ROOT / ".github/scripts/write_release_notes.sh"
DIGEST = "sha256:" + "a" * 64
RELEASE_SHA = "b" * 40
VERSION = "v9.8.7"
BUILD_TAG = "123-1"


def executable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def build_images():
    inventory = json.loads((ROOT / ".github/image-inventory.json").read_text())
    return [
        {"repo": f"ghcr.io/example/openadkit{'-common' if image['repo'] == 'common' else ''}",
         "target": image["target"], "ros_distro": distro,
         "ref": f"ghcr.io/example/openadkit{'-common' if image['repo'] == 'common' else ''}:{image['target']}-{distro}-{BUILD_TAG}",
         "digest": DIGEST, "platforms": image["platforms"]}
        for image in inventory["images"]
        for distro in image.get("ros_distros", inventory["ros_distros"])
    ]


def build_metadata(images=None):
    return {"build_tag": BUILD_TAG, "openadkit_sha": RELEASE_SHA,
            "autoware_input_ref": "1.8.0", "autoware_ref_type": "tag", "autoware_ref": "d" * 40,
            "autoware_base_version": "1.8.0", "autoware_lock_sha256": "e" * 64,
            "upstream_images_sha256": "f" * 64, "images": build_images() if images is None else images}


def passing_summary(metadata):
    """An evidence run's summary that passed this build at its own commit."""
    return {
        "schemaVersion": 3, "result": "PASSED", "release_evidence": True, "missing": [],
        "build_tag": metadata["build_tag"], "build_sha": metadata["openadkit_sha"],
        "source_sha": metadata["openadkit_sha"], "url": "https://github.com/example/repo/actions/runs/456",
        "cells": [{
            "schemaVersion": 1, "name": "planning-simulation-humble-linux-amd64",
            "deployment": "planning-simulation", "distro": "humble", "result": "PASSED",
            "levels": {"L0": {"ok": True}, "L1": {"ok": True}, "L2": {"ok": True}},
            "metrics": {"ready_s": 26, "arrival_s": 35, "peak_mib": 2151},
        }],
    }


def write_plan(tmp_path, *, images=None, summary=None):
    metadata = tmp_path / "build-metadata.json"
    metadata.write_text(json.dumps(build_metadata(images)))
    output = tmp_path / "release-plan.json"
    evidence = []
    if summary is not None:
        (tmp_path / "evidence-summary.json").write_text(json.dumps(summary))
        evidence = ["--evidence-summary", str(tmp_path / "evidence-summary.json")]
    result = subprocess.run([
        "python3", str(PLANNER), "--source-root", str(ROOT), "--build-metadata", str(metadata),
        "--version", VERSION, "--release-sha", RELEASE_SHA, "--packager-sha", "c" * 40,
        "--default-ros-distro", "humble", "--stable-release", "true",
        "--publish-latest-aliases", "true", "--output", str(output), *evidence,
    ], text=True, capture_output=True, timeout=30)
    return result, output


def run_validator(tmp_path, function, **env):
    kit = json.loads((ROOT / "openadkit.json").read_text())
    return subprocess.run([
        "bash", "-c", f'source "$1"; release_sha="$2"; {function}', "bash", str(VALIDATOR), RELEASE_SHA,
    ], cwd=tmp_path, text=True, capture_output=True, timeout=30, env=os.environ | {
        "BUILD_TAG": BUILD_TAG, "VERSION": VERSION, "GH_TOKEN": "test", "GITHUB_REF": "refs/heads/release/9.8",
        "GITHUB_REPOSITORY": "example/repo", "GITHUB_OUTPUT": str(tmp_path / "output"),
        "IMAGE_PREFIX_COMMON": "ghcr.io/example/openadkit-common",
        "IMAGE_PREFIX_COMPONENT": kit["imagePrefixComponent"], "DEFAULT_ROS_DISTRO": kit["defaultRosDistro"],
        **env,
    })


def packager_env(tmp_path):
    # The CLI resolves deployment settings with Compose itself.
    docker = shutil.which("docker")
    if docker is None or subprocess.run([docker, "compose", "version"], capture_output=True).returncode != 0:
        pytest.skip("needs Docker Compose")
    calls = tmp_path / "docker-calls"
    executable(tmp_path / "bin/docker", "#!/usr/bin/env bash\n"
               f'if [[ "$*" == *"config --environment"* ]]; then exec "{docker}" "$@"; fi\n'
               f'printf "%s|%s\\n" "${{ROS_DISTRO:-}}" "$*" >> "{calls}"\n'
               'if [[ "$*" == *"config --services"* ]]; then\n'
               "printf '%s\\n' map map-check planning vehicle system control simulator api visualizer sensing perception localization rosbag scenario_simulator carla carla-interface carla-map-loader zenoh-bridge\nfi\n")
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    metadata = build_metadata()
    (build / "build-metadata.json").write_text(json.dumps(metadata))
    (tmp_path / "release-input/evidence").mkdir()
    (tmp_path / "release-input/evidence/evidence-summary.json").write_text(json.dumps(passing_summary(metadata)))
    return os.environ | {
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "SOURCE_DIR": str(ROOT), "VERSION": VERSION,
        "RELEASE_SHA": RELEASE_SHA, "PACKAGER_SHA": "c" * 40, "DEFAULT_ROS_DISTRO": "humble",
        "PUBLISH_LATEST_ALIASES": "true", "STABLE_RELEASE": "true", "GITHUB_REPOSITORY": "example/repo",
    }, calls


def run_packager(tmp_path, env, *, umask="022"):
    return subprocess.run([
        "bash", "-c", 'umask "$1"; exec bash "$2"', "bash", umask, str(PACKAGER),
    ], cwd=tmp_path, env=env, text=True, capture_output=True, check=True, timeout=30)
