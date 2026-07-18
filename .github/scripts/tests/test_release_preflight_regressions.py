import hashlib
import json
import os
import pathlib
import re
import subprocess

import pytest
import yaml


ROOT = pathlib.Path(__file__).resolve().parents[3]
VALIDATE_RELEASE = ROOT / ".github/scripts/validate_release.sh"
RELEASE_TAG = ROOT / ".github/scripts/release_tag.sh"
PACKAGE_BUNDLES = ROOT / ".github/scripts/package_release_bundles.sh"
MANAGE_RELEASE = ROOT / ".github/scripts/manage_github_release.sh"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yaml"
OPENADKIT_REF = re.compile(
    r"ghcr\.io/example/openadkit:([a-z-]+)-(humble|jazzy)-v9\.8\.7"
)


def test_validate_git_tag_treats_api_404_as_missing_tag(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' '{\"message\":\"Not Found\",\"status\":\"404\"}'\n"
        "exit 1\n"
    )
    gh.chmod(0o755)
    env = os.environ | {
        "BUILD_TAG": "1-1",
        "VERSION": "v9.8.7-test",
        "GH_TOKEN": "test",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "IMAGE_PREFIX_COMMON": "example/common",
        "IMAGE_PREFIX_COMPONENT": "example/component",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; release_sha=abc123; validate_git_tag',
            "bash",
            str(VALIDATE_RELEASE),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
    )


@pytest.mark.parametrize("status", ["403", "500"])
def test_validate_git_tag_fails_closed_on_api_errors(tmp_path, status):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' '{{\"message\":\"API error\",\"status\":\"{status}\"}}'\n"
        "exit 1\n"
    )
    gh.chmod(0o755)
    env = os.environ | {
        "BUILD_TAG": "1-1",
        "VERSION": "v9.8.7-test",
        "GH_TOKEN": "test",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "IMAGE_PREFIX_COMMON": "example/common",
        "IMAGE_PREFIX_COMPONENT": "example/component",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; release_sha=abc123; validate_git_tag',
            "bash",
            str(VALIDATE_RELEASE),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert f"HTTP {status}" in result.stderr


def test_validate_git_tag_fails_closed_on_network_error(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/usr/bin/env bash\nexit 1\n")
    gh.chmod(0o755)
    env = os.environ | {
        "BUILD_TAG": "1-1",
        "VERSION": "v9.8.7-test",
        "GH_TOKEN": "test",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "IMAGE_PREFIX_COMMON": "example/common",
        "IMAGE_PREFIX_COMPONENT": "example/component",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; release_sha=abc123; validate_git_tag',
            "bash",
            str(VALIDATE_RELEASE),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "GitHub API request failed" in result.stderr


def test_validate_git_tag_resolves_annotated_tag(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    tag_sha = "b" * 40
    release_sha = "a" * 40
    gh.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${2:-}\" == */git/refs/tags/* ]]; then\n"
        f"  printf '%s\\n' '{{\"object\":{{\"type\":\"tag\",\"sha\":\"{tag_sha}\"}}}}'\n"
        "elif [[ \"${2:-}\" == */git/tags/* ]]; then\n"
        f"  printf '%s\\n' '{{\"object\":{{\"type\":\"commit\",\"sha\":\"{release_sha}\"}}}}'\n"
        "else\n"
        "  exit 2\n"
        "fi\n"
    )
    gh.chmod(0o755)
    env = os.environ | {
        "BUILD_TAG": "1-1",
        "VERSION": "v9.8.7-test",
        "GH_TOKEN": "test",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "IMAGE_PREFIX_COMMON": "example/common",
        "IMAGE_PREFIX_COMPONENT": "example/component",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    subprocess.run(
        [
            "bash",
            "-c",
            f'source "$1"; release_sha={release_sha}; validate_git_tag',
            "bash",
            str(VALIDATE_RELEASE),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
    )


def test_release_tag_program_creates_only_after_confirmed_404(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "gh-calls"
    gh = bin_dir / "gh"
    release_sha = "a" * 40
    gh.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"${GH_CALL_LOG}\"\n"
        "if [[ \"${2:-}\" == */git/refs/tags/* ]]; then\n"
        "  printf '%s\\n' '{\"message\":\"Not Found\",\"status\":\"404\"}'\n"
        "  exit 1\n"
        "fi\n"
        "[[ \"${2:-}\" == */git/refs ]]\n"
    )
    gh.chmod(0o755)
    env = os.environ | {
        "VERSION": "v9.8.7-test",
        "RELEASE_SHA": release_sha,
        "GH_TOKEN": "test",
        "GITHUB_REPOSITORY": "example/repo",
        "GH_CALL_LOG": str(call_log),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["bash", str(RELEASE_TAG)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert f"Created tag v9.8.7-test at {release_sha}" in result.stdout
    create_call = call_log.read_text().splitlines()[-1]
    assert "api repos/example/repo/git/refs" in create_call
    assert "-f ref=refs/tags/v9.8.7-test" in create_call
    assert f"-f sha={release_sha}" in create_call


def test_release_verifies_git_tag_before_promoting_images():
    jobs = yaml.safe_load(RELEASE_WORKFLOW.read_text())["jobs"]

    assert jobs["release-tag"]["needs"] == ["validate", "package-bundles"]
    assert jobs["prepare-github-release"]["needs"] == [
        "validate",
        "package-bundles",
        "release-tag",
    ]
    assert jobs["release-images"]["needs"] == [
        "validate",
        "prepare-github-release",
    ]
    assert jobs["release-github"]["needs"] == [
        "validate",
        "prepare-github-release",
        "release-images",
    ]
    assert "Create or verify git tag" not in [
        step.get("name") for step in jobs["release-github"]["steps"]
    ]
    assert jobs["package-bundles"]["outputs"]["packager_sha"] == (
        "${{ steps.packager.outputs.packager_sha }}"
    )
    notes_step = next(
        step
        for step in jobs["prepare-github-release"]["steps"]
        if step.get("name") == "Create release metadata and notes"
    )
    assert notes_step["env"]["PACKAGER_SHA"] == (
        "${{ needs.package-bundles.outputs.packager_sha }}"
    )
    assert jobs["prepare-github-release"]["outputs"]["release_id"] == (
        "${{ steps.prepare-release.outputs.release_id }}"
    )


def test_existing_github_release_is_verified_without_mutation():
    jobs = yaml.safe_load(RELEASE_WORKFLOW.read_text())["jobs"]
    prepare_step = next(
        step
        for step in jobs["prepare-github-release"]["steps"]
        if step.get("name") == "Verify existing release or create draft"
    )
    manager = MANAGE_RELEASE.read_text()

    assert prepare_step["run"] == "bash .github/scripts/manage_github_release.sh prepare"
    assert "gh release download" in manager
    assert "--rawfile expected_body release-notes.md" in manager
    assert 'cmp <(jq -S . "${existing_dir}/release-metadata.json")' in manager
    assert 'gh api --method DELETE "repos/${GITHUB_REPOSITORY}/releases/${release_id}"' in manager
    assert "verify_owned_draft" in manager
    assert "targetCommitish == $release_sha" in manager
    assert "RELEASE_WORKFLOW_MARKER" in manager
    assert "--draft" in manager

    publish_step = next(
        step
        for step in jobs["release-github"]["steps"]
        if step.get("name") == "Publish prepared GitHub Release"
    )
    assert publish_step["if"] == (
        "needs.prepare-github-release.outputs.created == 'true'"
    )
    assert publish_step["run"] == "bash .github/scripts/manage_github_release.sh publish"
    assert 'gh api --method PATCH "repos/${GITHUB_REPOSITORY}/releases/${RELEASE_ID}"' in manager


def test_validate_inventory_coverage_handles_global_and_image_distros(tmp_path):
    build_dir = tmp_path / "release-input/build"
    build_dir.mkdir(parents=True)
    (build_dir / "image-inventory.json").write_text(
        json.dumps(
            {
                "ros_distros": ["humble", "jazzy"],
                "images": [
                    {
                        "repo": "common",
                        "target": "universe-common",
                        "platforms": ["linux/arm64", "linux/amd64"],
                    },
                    {
                        "repo": "component",
                        "target": "carla-interface",
                        "ros_distros": ["humble"],
                        "platforms": ["linux/amd64"],
                    },
                ],
            }
        )
    )
    (build_dir / "build-metadata.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "repo": "example/common",
                        "target": "universe-common",
                        "ros_distro": distro,
                        "platforms": ["linux/amd64", "linux/arm64"],
                    }
                    for distro in ("humble", "jazzy")
                ]
                + [
                    {
                        "repo": "example/component",
                        "target": "carla-interface",
                        "ros_distro": "humble",
                        "platforms": ["linux/amd64"],
                    }
                ]
            }
        )
    )
    env = os.environ | {
        "BUILD_TAG": "1-1",
        "VERSION": "v9.8.7",
        "GH_TOKEN": "test",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "IMAGE_PREFIX_COMMON": "example/common",
        "IMAGE_PREFIX_COMPONENT": "example/component",
    }

    subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; validate_inventory_coverage',
            "bash",
            str(VALIDATE_RELEASE),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
    )


def test_jazzy_release_bundles_keep_carla_humble_and_bind_mounts(tmp_path):
    third_party_refs = [
        "ghcr.io/autowarefoundation/autoware:universe",
        "eclipse/zenoh-bridge-ros2dds:latest",
        "ghcr.io/evshary/autoware_manual_control:latest",
        "ghcr.io/tier4/scenario_simulator_v2:humble-25.0.20-runtime",
        "carlasim/carla:0.9.16",
        "busybox:1.36.1",
    ]
    digest = "sha256:" + "a" * 64
    env = os.environ | {
        "SOURCE_DIR": str(ROOT),
        "VERSION": "v9.8.7",
        "DEFAULT_ROS_DISTRO": "jazzy",
        "IMAGE_PREFIX_COMPONENT": "ghcr.io/example/openadkit",
        "THIRD_PARTY_IMAGE_DIGESTS_JSON": json.dumps(
            {ref: digest for ref in third_party_refs}
        ),
    }
    result = subprocess.run(
        ["bash", str(PACKAGE_BUNDLES)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    bundle_names = {
        "planning-simulation",
        "scenario-simulation",
        "logging-simulation",
        "carla-simulation",
        "zenoh-bridge",
    }
    assert {path.stem.removesuffix(".tar") for path in (tmp_path / "dist").glob("*.tar.gz")} == bundle_names
    assert result.stdout.count("packaged dist/") == len(bundle_names)

    for name in bundle_names:
        bundle_dir = tmp_path / "staging" / name
        refs = []
        for path in bundle_dir.rglob("*"):
            if path.suffix in {".yaml", ".env"} or path.name == ".env":
                content = path.read_text()
                assert "ghcr.io/autowarefoundation/openadkit:" not in content
                refs.extend(OPENADKIT_REF.findall(content))
        assert refs, f"no pinned Open AD Kit refs found in {name}"
        expected_distro = "humble" if name == "carla-simulation" else "jazzy"
        assert {distro for _, distro in refs} == {expected_distro}
        combined = "\n".join(
            path.read_text()
            for path in bundle_dir.rglob("*")
            if path.is_file() and (path.suffix in {".yaml", ".env"} or path.name == ".env")
        )
        for ref in third_party_refs:
            if ref in combined:
                assert f"{ref}@{digest}" in combined

    assert (tmp_path / "staging/zenoh-bridge/.env").is_file()

    carla_dir = tmp_path / "staging/carla-simulation"
    carla_compose = (carla_dir / "docker-compose.yaml").read_text()
    assert "../base/" not in carla_compose
    assert "./base/cyclonedds.xml" in carla_compose
    rendered = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "carla-simulation.env",
            "config",
            "--format",
            "json",
        ],
        cwd=carla_dir,
        text=True,
        capture_output=True,
        check=True,
    )
    services = json.loads(rendered.stdout)["services"]
    cyclonedds_mount = next(
        mount
        for mount in services["carla-interface"]["volumes"]
        if mount["target"] == "/etc/cyclonedds/cyclonedds.xml"
    )
    assert cyclonedds_mount["type"] == "bind"
    assert pathlib.Path(cyclonedds_mount["source"]) == carla_dir / "base/cyclonedds.xml"

    sibling_base = tmp_path / "staging/base"
    sibling_base.mkdir()
    marker = tmp_path / "sibling-base-executed"
    (sibling_base / "base.env").write_text(f"MALICIOUS=$(touch {marker})\n")
    carla_dry_run = subprocess.run(
        [
            str(carla_dir / "start-carla-e2e-demo.sh"),
            "--dry-run",
            "--skip-verify",
            "--no-visualizer",
        ],
        cwd=carla_dir,
        text=True,
        capture_output=True,
        check=True,
    )
    compose_commands = [
        line
        for line in carla_dry_run.stdout.splitlines()
        if line.startswith("+ docker compose")
    ]
    assert compose_commands
    assert all(command.count("--env-file") == 1 for command in compose_commands)
    assert all("../base/base.env" not in command for command in compose_commands)
    assert not marker.exists()

    helper = tmp_path / "staging/planning-simulation/start-planning-e2e-demo.sh"
    dry_run = subprocess.run(
        [str(helper), "--dry-run"],
        text=True,
        capture_output=True,
        check=True,
    )
    compose_command = next(
        line for line in dry_run.stdout.splitlines() if line.startswith("[DRY-RUN]")
    )
    assert compose_command.count("--env-file") == 1
    assert "planning-simulation.env" in compose_command
    assert "base.env" not in compose_command

    first_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (tmp_path / "dist").glob("*.tar.gz")
    }
    subprocess.run(
        ["bash", str(PACKAGE_BUNDLES)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    second_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (tmp_path / "dist").glob("*.tar.gz")
    }
    assert second_hashes == first_hashes
