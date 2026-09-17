"""End-to-end tests for the openadkit CLI.

Shared builders and fixtures live in cli_helpers.py and conftest.py.
"""

import hashlib
import json
import re
import subprocess
import sys
import zipfile

import pytest

from cli_helpers import (
    ENTRYPOINT,
    ROOT,
    assert_no_container_mutation,
    docker_env,
    executable,
    fake_docker,
    files_resource,
    host_architecture,
    minimal_manifest,
    role_manifest,
    run_cli,
    runtime_tree,
    write_runtime_state,
    zip_resource,
)


RUNNING_PROJECT = '[{"Name":"openadkit-example","Status":"running(1)"}]'
DEV_PREFIX = "ghcr.io/autowarefoundation/openadkit"


def test_cli_surface():
    top = subprocess.run(
        [ENTRYPOINT, "--help"], text=True, capture_output=True, check=True
    )
    for command in (
        "setup",
        "list",
        "version",
        "validate",
        "fetch",
        "run",
        "status",
        "logs",
        "stop",
    ):
        assert command in top.stdout
    for command in ("verify", "down", "install", "build"):
        assert f"  {command} " not in top.stdout
    assert subprocess.run([ENTRYPOINT, "data"], capture_output=True).returncode != 0
    empty = subprocess.run([ENTRYPOINT], text=True, capture_output=True)
    assert empty.returncode == 2
    assert "examples:" in empty.stdout


@pytest.mark.parametrize(
    ("command", "present", "absent"),
    [
        ("validate", ("--role", "--ros-distro", "--gpu"), ()),
        ("run", ("--role", "--ros-distro", "--gpu", "--force", "--pull"), ()),
        ("fetch", ("--ros-distro", "--force"), ("--gpu", "--role")),
        ("status", (), ("--ros-distro", "--gpu", "--role")),
        ("logs", (), ("--ros-distro", "--gpu", "--role")),
        ("stop", (), ("--ros-distro", "--gpu", "--role")),
    ],
)
def test_command_flag_surface(command, present, absent):
    result = subprocess.run(
        [ENTRYPOINT, command, "--help"], text=True, capture_output=True, check=True
    )
    for flag in present:
        assert flag in result.stdout
    for flag in absent:
        assert flag not in result.stdout


def test_run_help_lists_catalog():
    result = subprocess.run(
        [ENTRYPOINT, "run", "--help"], text=True, capture_output=True, check=True
    )
    assert "planning-simulation" in result.stdout


def test_version_reports_repository_and_release(tmp_path):
    repo, _ = runtime_tree(tmp_path / "repo")
    release, _ = runtime_tree(tmp_path / "release", release=True)
    assert run_cli(repo, ["version"]).stdout.startswith("Open AD Kit development")
    assert run_cli(release, ["version"]).stdout.startswith("Open AD Kit v1.2.3")


def test_list_uses_bundle_inventory_and_ignores_unlisted_deployments(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    custom = root / "deployments/custom"
    custom.mkdir()
    (custom / "deployment.json").write_text(json.dumps(minimal_manifest("custom")))
    (custom / "config.env").write_text("MAP_PATH=$HOME/custom\n")
    (custom / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.1\n"
    )
    result = run_cli(root, ["list"])
    assert result.returncode == 0, result.stderr
    assert re.search(r"example\s+intact\s+none\s+Test deployment", result.stdout)
    assert "custom" not in result.stdout


@pytest.mark.parametrize("command", ("run", "fetch", "validate"))
def test_catalog_command_without_deployment_lists_available(tmp_path, command):
    root, _ = runtime_tree(tmp_path)
    result = run_cli(root, [command])
    assert result.returncode == 2
    assert "error: deployment name required" in result.stderr
    assert f"./openadkit {command} <deployment>" in result.stderr
    assert re.search(r"example\s+source\s+none\s+Test deployment", result.stdout)


def test_unknown_deployment_is_rejected(tmp_path):
    root, _ = runtime_tree(tmp_path)
    result = run_cli(root, ["run", "custom"])
    assert result.returncode != 0
    assert "unknown deployment: custom" in result.stderr
    assert "available: example" in result.stderr


@pytest.mark.parametrize(
    ("command", "compose_ls", "extra", "expected_code", "expected"),
    [
        ("status", "[]", [], 0, "no running deployments"),
        ("logs", "[]", [], 0, "no running deployments"),
        ("stop", "[]", [], 0, "no running deployments"),
        ("status", RUNNING_PROJECT, [], 2, "error: deployment name required"),
        ("logs", RUNNING_PROJECT, [], 2, "error: deployment name required"),
        ("stop", RUNNING_PROJECT, [], 2, "error: deployment name required"),
        (
            "logs",
            RUNNING_PROJECT,
            ["--follow"],
            2,
            "./openadkit logs <deployment> --follow",
        ),
    ],
)
def test_runtime_command_without_deployment(
    tmp_path, command, compose_ls, extra, expected_code, expected
):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path, compose_ls=compose_ls)
    result = run_cli(root, [command, *extra], env=docker_env(bin_dir))
    assert result.returncode == expected_code, result.stderr
    if expected_code == 0:
        assert result.stdout.strip() == expected
    else:
        assert expected in result.stderr
        assert re.search(r"example\s+source\s+none\s+Test deployment", result.stdout)
    if command == "logs" and extra:
        assert " logs" not in f" {calls.read_text()} "


def test_stop_downs_project_by_name_without_volumes(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(root, ["stop", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert "down --remove-orphans" in text
    assert "--volumes" not in text


@pytest.mark.parametrize("target", ("deployment", "shared"))
def test_release_modification_is_marked(tmp_path, target):
    manifest = minimal_manifest()
    if target == "shared":
        manifest["shared"] = ["base"]
    root, deployment = runtime_tree(tmp_path, release=True, manifest=manifest)
    if target == "deployment":
        (deployment / "docker-compose.yaml").write_text(
            "services:\n  app:\n    image: busybox:1.36.2\n"
        )
    else:
        (root / "deployments/base/runtime.env").write_text("ROS_DOMAIN_ID=2\n")
    result = run_cli(root, ["list"])
    assert result.returncode == 0, result.stderr
    assert re.search(r"example\s+modified", result.stdout)


def test_modified_release_warns_but_still_runs(tmp_path):
    root, deployment = runtime_tree(tmp_path, release=True)
    (deployment / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.2\n"
    )
    bin_dir, _ = fake_docker(tmp_path)
    result = run_cli(root, ["run", "example", "--pull", "never"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert "has been modified from this release" in result.stderr
    assert "running: example" in result.stdout


def test_invalid_manifest_is_reported(tmp_path):
    duplicate, deployment = runtime_tree(tmp_path / "duplicate")
    text = json.dumps(minimal_manifest())
    (deployment / "deployment.json").write_text(
        text.replace('"name": "example"', '"name": "example", "name": "other"')
    )
    assert "duplicate JSON key" in run_cli(duplicate, ["list"]).stdout

    escape_manifest = minimal_manifest()
    escape_manifest["compose"]["files"] = ["../outside.yaml"]
    escape, _ = runtime_tree(tmp_path / "escape", manifest=escape_manifest)
    assert "safe relative path" in run_cli(escape, ["list"]).stdout

    empty_manifest = minimal_manifest()
    empty_manifest["compose"]["services"] = []
    empty, _ = runtime_tree(tmp_path / "empty", manifest=empty_manifest)
    assert "compose.services must not be empty" in run_cli(empty, ["list"]).stdout


def test_config_local_env_is_applied_last(tmp_path):
    root, deployment = runtime_tree(tmp_path)
    (deployment / "config.local.env").write_text("REMOTE_PASSWORD=local\n")
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(root, ["validate", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    call = calls.read_text()
    assert call.index("config.env") < call.index("config.local.env")


def test_run_orders_render_daemon_pull_and_up(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(root, ["run", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert text.index("config --quiet") < text.index("|info")
    assert text.index("|info") < text.index("pull --policy missing")
    assert text.index("pull --policy missing") < text.index(
        "up --detach --pull never --remove-orphans"
    )
    assert text.index("up --detach --pull never --remove-orphans") < text.index(
        "up --detach --wait"
    )


@pytest.mark.parametrize(
    ("policy", "expects_pull"),
    [("missing", True), ("always", True), ("never", False)],
)
def test_run_pull_policy_is_explicit_for_up(tmp_path, policy, expects_pull):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(root, ["run", "example", "--pull", policy], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert ("pull --policy" in text) is expects_pull
    assert "up --detach --pull never --remove-orphans app" in text
    assert "up --detach --wait --wait-timeout 30 --pull never app" in text


def test_run_resets_declared_one_shot_services(tmp_path):
    manifest = minimal_manifest()
    manifest["compose"]["resetServices"] = ["map-check"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path, configured="app\nmap-check\n")
    result = run_cli(root, ["run", "example", "--pull", "never"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert "rm --stop --force map-check" in calls.read_text()


def test_setup_rejects_unknown_development_option(tmp_path):
    root, _ = runtime_tree(tmp_path)
    result = run_cli(root, ["setup", "--development"])
    assert result.returncode != 0
    assert "unknown setup option: --development" in result.stderr


def test_forced_docker_install_is_restricted_to_ci(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo_log = tmp_path / "sudo-log"
    executable(
        bin_dir / "sudo",
        f"#!/usr/bin/env bash\nprintf called > {json.dumps(str(sudo_log))}\n",
    )
    result = run_cli(
        root,
        ["setup"],
        env=docker_env(
            bin_dir, OPENADKIT_CI_FORCE_DOCKER_INSTALL="true", CI="false"
        ),
    )
    assert result.returncode != 0
    assert "restricted to disposable CI hosts" in result.stderr
    assert not sudo_log.exists()


def test_fetch_zip_is_checksum_verified_and_published_atomically(tmp_path, http_files):
    directory, base_url = http_files
    archive = directory / "data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("dataset/required.txt", "ok")
    manifest = minimal_manifest(
        data=[
            zip_resource(
                f"{base_url}/data.zip", hashlib.sha256(archive.read_bytes()).hexdigest()
            )
        ]
    )
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    result = run_cli(root, ["fetch", "example"])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/example/required.txt").read_text() == "ok"


def test_fetch_skips_required_gpu_flag(tmp_path, http_files):
    directory, base_url = http_files
    archive = directory / "data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("dataset/required.txt", "ok")
    manifest = minimal_manifest(
        data=[
            zip_resource(
                f"{base_url}/data.zip", hashlib.sha256(archive.read_bytes()).hexdigest()
            )
        ]
    )
    manifest["requirements"]["gpu"] = "required"
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    result = run_cli(root, ["fetch", "example"])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/example/required.txt").read_text() == "ok"
    blocked = run_cli(root, ["validate", "example"])
    assert blocked.returncode != 0
    assert "requires --gpu" in blocked.stderr


def test_fetch_checksum_failure_preserves_existing_data(tmp_path, http_files):
    directory, base_url = http_files
    archive = directory / "data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("dataset/required.txt", "replacement")
    root, _ = runtime_tree(
        tmp_path,
        manifest=minimal_manifest(data=[zip_resource(f"{base_url}/data.zip", "0" * 64)]),
    )
    target = tmp_path / "home/data/example"
    target.mkdir(parents=True)
    (target / "required.txt").write_text("original")
    result = run_cli(root, ["fetch", "example", "--force"])
    assert result.returncode != 0
    assert (target / "required.txt").read_text() == "original"


def test_unsafe_zip_member_is_rejected(tmp_path, http_files):
    directory, base_url = http_files
    archive = directory / "data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("dataset/../escape", "bad")
    root, _ = runtime_tree(
        tmp_path,
        manifest=minimal_manifest(
            data=[
                zip_resource(
                    f"{base_url}/data.zip",
                    hashlib.sha256(archive.read_bytes()).hexdigest(),
                )
            ]
        ),
    )
    result = run_cli(root, ["fetch", "example"])
    assert result.returncode != 0
    assert "unsafe ZIP member" in result.stderr
    assert not (tmp_path / "home/data/example").exists()


def test_run_force_reinstalls_incomplete_data(tmp_path, http_files):
    directory, base_url = http_files
    payload = directory / "required.txt"
    payload.write_text("replaced")
    root, _ = runtime_tree(
        tmp_path,
        manifest=minimal_manifest(
            data=[
                files_resource(
                    f"{base_url}/required.txt",
                    hashlib.sha256(payload.read_bytes()).hexdigest(),
                )
            ]
        ),
    )
    target = tmp_path / "home/data/example"
    target.mkdir(parents=True)
    bin_dir, _ = fake_docker(tmp_path)
    path_env = docker_env(bin_dir)
    blocked = run_cli(root, ["run", "example", "--pull", "never"], env=path_env)
    assert blocked.returncode != 0
    assert "incomplete data" in blocked.stderr
    assert "rerun with --force" in blocked.stderr
    result = run_cli(root, ["run", "example", "--pull", "never", "--force"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert (target / "required.txt").read_text() == "replaced"


def test_all_data_targets_are_checked_before_first_download(tmp_path):
    resources = [
        files_resource(name="first", destination_env="FIRST_PATH"),
        files_resource(name="second", destination_env="SECOND_PATH"),
    ]
    root, deployment = runtime_tree(tmp_path, manifest=minimal_manifest(data=resources))
    (deployment / "config.env").write_text(
        "FIRST_PATH=$HOME/data/first\nSECOND_PATH=$HOME/data/second\n"
    )
    (tmp_path / "home/data/second").mkdir(parents=True)
    result = run_cli(root, ["fetch", "example"])
    assert result.returncode != 0
    assert "incomplete data" in result.stderr
    assert not (tmp_path / "home/data/first").exists()


def test_fetch_includes_gpu_data_without_docker(tmp_path, http_files):
    directory, base_url = http_files
    payload = directory / "required.txt"
    payload.write_text("gpu data")
    manifest = minimal_manifest(
        data=[
            files_resource(
                f"{base_url}/required.txt",
                hashlib.sha256(payload.read_bytes()).hexdigest(),
                destination_env="GPU_DATA_PATH",
                gpu=True,
            )
        ]
    )
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    with (deployment / "config.env").open("a") as output:
        output.write("GPU_DATA_PATH=$HOME/data/gpu\n")
    bin_dir, calls = fake_docker(tmp_path, config_returncode=99)
    result = run_cli(root, ["fetch", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/gpu/required.txt").read_text() == "gpu data"
    assert not calls.exists()


def test_run_without_gpu_skips_gpu_only_data(tmp_path):
    manifest = minimal_manifest(data=[files_resource(gpu=True)])
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, _ = fake_docker(tmp_path)
    result = run_cli(root, ["run", "example", "--pull", "never"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home/data").exists()


def test_relative_data_destination_is_rejected_before_download(tmp_path):
    root, deployment = runtime_tree(
        tmp_path, manifest=minimal_manifest(data=[files_resource()])
    )
    (deployment / "config.env").write_text("MAP_PATH=relative/data\n")
    fetched = run_cli(root, ["fetch", "example"])
    assert fetched.returncode != 0
    assert "must be absolute after HOME expansion" in fetched.stderr
    assert not (root / "relative").exists()

    bin_dir, calls = fake_docker(tmp_path)
    validated = run_cli(root, ["validate", "example"], env=docker_env(bin_dir))
    assert validated.returncode != 0
    assert "must be absolute after HOME expansion" in validated.stderr
    assert not calls.exists()


def test_daemon_failure_prevents_data_and_container_commands(tmp_path):
    root, _ = runtime_tree(
        tmp_path, manifest=minimal_manifest(data=[files_resource()])
    )
    bin_dir, calls = fake_docker(tmp_path, daemon_returncode=1)
    result = run_cli(root, ["run", "example"], env=docker_env(bin_dir))
    assert result.returncode != 0
    assert "could not access the Docker daemon" in result.stderr
    assert not (tmp_path / "home/data").exists()
    assert_no_container_mutation(calls)


def test_missing_gpu_runtime_prevents_data_and_container_commands(tmp_path):
    manifest = minimal_manifest(
        data=[files_resource(destination_env="GPU_DATA_PATH", gpu=True)]
    )
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    with (deployment / "config.env").open("a") as output:
        output.write("GPU_DATA_PATH=$HOME/data/gpu\n")
    bin_dir, calls = fake_docker(tmp_path, runtimes="{}")
    result = run_cli(root, ["run", "example", "--gpu"], env=docker_env(bin_dir))
    assert result.returncode != 0
    assert "NVIDIA Container Toolkit is unavailable" in result.stderr
    assert not (tmp_path / "home/data/gpu").exists()
    assert_no_container_mutation(calls)


def test_unknown_manifest_service_fails_before_data_pull_or_up(tmp_path):
    manifest = minimal_manifest(data=[files_resource()])
    manifest["compose"]["services"] = ["typo"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path, configured="app\n")
    result = run_cli(root, ["run", "example"], env=docker_env(bin_dir))
    assert result.returncode != 0
    assert "unknown Compose service(s): typo" in result.stderr
    assert not (tmp_path / "home/data/example").exists()
    assert_no_container_mutation(calls)


def assert_validate_fails_before_compose(tmp_path, manifest, args, message):
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(root, ["validate", "example", *args], env=docker_env(bin_dir))
    assert result.returncode != 0
    assert message in result.stderr
    assert not calls.exists()


def test_ros_distro_constraints_fail_before_compose(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["rosDistros"] = ["humble"]
    assert_validate_fails_before_compose(
        tmp_path, manifest, ["--ros-distro", "jazzy"], "does not support ROS distro jazzy"
    )


def test_required_environment_fails_before_compose(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["DEPLOYMENT_TOKEN"]
    assert_validate_fails_before_compose(
        tmp_path,
        manifest,
        [],
        "required environment variable(s) are missing: DEPLOYMENT_TOKEN",
    )


def test_gpu_architecture_constraint_fails_before_compose(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"].update(
        {
            "architectures": [host_architecture(), "unsupported-test-architecture"],
            "gpu": "optional",
            "gpuArchitectures": ["unsupported-test-architecture"],
        }
    )
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    assert_validate_fails_before_compose(
        tmp_path, manifest, ["--gpu"], f"GPU mode does not support {host_architecture()}"
    )


@pytest.mark.parametrize(
    ("kit_distro", "args", "expected_distro"),
    [
        (None, [], "humble"),
        (None, ["--ros-distro", "jazzy"], "jazzy"),
        ("jazzy", [], "jazzy"),
    ],
)
def test_component_image_injection(tmp_path, kit_distro, args, expected_distro):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["API_IMAGE"]
    manifest["distroEnvironment"] = {"jazzy": {"DISTRO_VALUE": "jazzy-value"}}
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    if kit_distro:
        kit = json.loads((root / "openadkit.json").read_text())
        kit["defaultRosDistro"] = kit_distro
        (root / "openadkit.json").write_text(json.dumps(kit))
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(root, ["validate", "example", *args], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    fields = calls.read_text().split("|", 5)
    assert fields[0] == expected_distro
    assert fields[1] == ("jazzy-value" if expected_distro == "jazzy" else "")
    assert fields[2] == f"{DEV_PREFIX}:api-{host_architecture()}-{expected_distro}"
    assert (
        fields[3]
        == f"{DEV_PREFIX}:localization-mapping-{host_architecture()}-{expected_distro}"
    )


def test_component_image_precedence(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["API_IMAGE"]

    # A release's exact references win over deployment env files.
    root, deployment = runtime_tree(tmp_path / "release", release=True, manifest=manifest)
    kit_path = root / "openadkit.json"
    current = json.loads(kit_path.read_text())
    exact = f"registry.example/api@sha256:{'a' * 64}"
    current["images"]["humble"]["api"] = exact
    kit_path.write_text(json.dumps(current))
    (deployment / "config.env").write_text(
        (deployment / "config.env").read_text() + "API_IMAGE=registry.example/from-config\n"
    )
    (deployment / "config.local.env").write_text("API_IMAGE=registry.example/from-local\n")
    bin_dir, calls = fake_docker(tmp_path / "release")
    result = run_cli(root, ["validate", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert calls.read_text().split("|", 5)[2] == exact

    # A repository deployment's config.local.env overrides the development alias.
    root, deployment = runtime_tree(tmp_path / "repo", manifest=manifest)
    exact = f"registry.example/custom-api@sha256:{'b' * 64}"
    (deployment / "config.local.env").write_text(f"API_IMAGE={exact}\n")
    bin_dir, calls = fake_docker(tmp_path / "repo")
    result = run_cli(root, ["validate", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert calls.read_text().split("|", 5)[2] == exact


def test_release_rejects_mutable_component_reference(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    kit_path = root / "openadkit.json"
    current = json.loads(kit_path.read_text())
    current["images"]["humble"]["api"] = "registry.example/api:humble"
    kit_path.write_text(json.dumps(current))
    result = run_cli(root, ["list"])
    assert result.returncode != 0
    assert "digest-pinned image references" in result.stderr


def test_missing_required_release_target_fails_before_compose(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    kit_path = root / "openadkit.json"
    current = json.loads(kit_path.read_text())
    current["images"] = {"humble": {}}
    kit_path.write_text(json.dumps(current))
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(root, ["validate", "example"], env=docker_env(bin_dir))
    assert result.returncode != 0
    assert "missing component image target(s)" in result.stderr
    assert not calls.exists()


def test_gpu_component_image_injected_only_with_gpu(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    path_env = docker_env(bin_dir)
    expected = f"{DEV_PREFIX}:sensing-perception-cuda-{host_architecture()}-humble"

    result = run_cli(root, ["validate", "example"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert calls.read_text().split("|", 5)[4] == ""

    calls.write_text("")
    result = run_cli(root, ["validate", "example", "--gpu"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert calls.read_text().split("|", 5)[4] == expected


def test_validate_renders_without_accessing_docker_daemon(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path, daemon_returncode=37)
    result = run_cli(root, ["validate", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert "config --quiet" in calls.read_text()
    assert "|info\n" not in calls.read_text()


def test_status_uses_last_run_gpu_selection(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    path_env = docker_env(bin_dir)

    result = run_cli(root, ["status", "example"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert "docker-compose.gpu.yaml" not in calls.read_text()
    assert calls.read_text().rstrip().endswith(" ps")

    calls.write_text("")
    result = run_cli(root, ["run", "example", "--gpu", "--pull", "never"], env=path_env)
    assert result.returncode == 0, result.stderr

    calls.write_text("")
    result = run_cli(root, ["status", "example"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert "docker-compose.gpu.yaml" in calls.read_text()

    calls.write_text("")
    result = run_cli(root, ["run", "example", "--pull", "never"], env=path_env)
    assert result.returncode == 0, result.stderr

    calls.write_text("")
    result = run_cli(root, ["status", "example"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert "docker-compose.gpu.yaml" not in calls.read_text()


def test_deployment_checksum_ignores_runtime_output(tmp_path):
    sys.path.insert(0, str(ROOT / "cli"))
    import manifest as openadkit_manifest

    directory = tmp_path / "scenario"
    directory.mkdir()
    (directory / "config.env").write_text("x=1\n")
    (directory / "output").mkdir()
    (directory / "output" / ".gitkeep").write_text("")
    baseline = openadkit_manifest.deployment_checksum(directory)
    (directory / "output" / "result.json").write_text("{}\n")
    (directory / ".cache").mkdir()
    (directory / ".cache" / "tmp").write_text("n\n")
    assert openadkit_manifest.deployment_checksum(directory) == baseline


def test_repository_catalog_contract():
    listed = subprocess.run(
        [ENTRYPOINT, "list"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout
    assert re.search(r"planning-simulation\s+source\s+none\s+", listed)
    assert re.search(r"logging-simulation\s+source\s+optional\s+", listed)
    assert re.search(r"scenario-simulation\s+source\s+none\s+", listed)
    assert re.search(r"carla-simulation\s+source\s+required\s+", listed)
    assert "zenoh" not in listed

    gpu = subprocess.run(
        [ENTRYPOINT, "validate", "carla-simulation"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert gpu.returncode != 0
    if host_architecture() == "amd64":
        assert "requires --gpu" in gpu.stderr
    else:
        return

    jazzy = subprocess.run(
        [ENTRYPOINT, "validate", "carla-simulation", "--gpu", "--ros-distro", "jazzy"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert jazzy.returncode != 0
    assert "does not support ROS distro jazzy" in jazzy.stderr


def test_role_lookup_errors(tmp_path):
    root, _ = runtime_tree(tmp_path / "plain")
    result = run_cli(root, ["validate", "example", "--role", "scenario"])
    assert result.returncode != 0
    assert "has no role scenario" in result.stderr
    assert "available roles: none" in result.stderr

    root, _ = runtime_tree(tmp_path / "roles", manifest=role_manifest())
    result = run_cli(root, ["validate", "example", "--role", "carla"])
    assert result.returncode != 0
    assert "has no role carla" in result.stderr
    assert "available roles: primary, secondary" in result.stderr


def test_role_view_selects_service_file_and_appends_base_fragment(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=role_manifest())
    bin_dir, calls = fake_docker(tmp_path)
    path_env = docker_env(bin_dir)
    result = run_cli(root, ["validate", "example", "--role", "primary"], env=path_env)
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert "compose.primary.yaml" in text
    assert "compose.secondary.yaml" not in text
    assert "docker-compose.yaml" not in text
    assert "deployments/base/compose.zenoh.yaml" in text

    calls.write_text("")
    result = run_cli(root, ["validate", "example"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert "compose.zenoh.yaml" not in calls.read_text()


def test_role_required_environment_is_checked(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=role_manifest())
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root, ["validate", "example", "--role", "secondary"], env=docker_env(bin_dir)
    )
    assert result.returncode != 0
    assert "ROLE_TOKEN" in result.stderr
    assert not calls.exists()
    result = run_cli(
        root,
        ["validate", "example", "--role", "secondary"],
        env=docker_env(bin_dir, ROLE_TOKEN="token"),
    )
    assert result.returncode == 0, result.stderr


def test_operational_commands_restore_saved_role(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=role_manifest())
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["run", "example", "--role", "secondary", "--pull", "never"],
        env=docker_env(bin_dir, ROLE_TOKEN="token"),
    )
    assert result.returncode == 0, result.stderr
    calls.write_text("")
    # Operational commands restore the role but must not require its
    # role-scoped environment.
    result = run_cli(root, ["status", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert "compose.secondary.yaml" in calls.read_text()


@pytest.mark.parametrize(
    ("saved_role", "args", "expected_code", "expected_message"),
    [
        ("primary", ["--role", "secondary"], 1, "already running as primary"),
        ("primary", [], 1, "before starting single-host"),
        (None, [], 1, "saved runtime state is missing or unreadable"),
        ("primary", ["--role", "primary"], 0, "up --detach"),
    ],
)
def test_run_live_state_guard(
    tmp_path, saved_role, args, expected_code, expected_message
):
    root, deployment = runtime_tree(tmp_path, manifest=role_manifest())
    if saved_role is not None:
        write_runtime_state(deployment, role=saved_role)
    bin_dir, calls = fake_docker(tmp_path, compose_ls=RUNNING_PROJECT)
    result = run_cli(
        root,
        ["run", "example", "--pull", "never", *args],
        env=docker_env(bin_dir, ROLE_TOKEN="token"),
    )
    assert result.returncode == expected_code, result.stderr
    if expected_code == 0:
        assert expected_message in calls.read_text()
    else:
        assert expected_message in result.stderr
        assert_no_container_mutation(calls)


def test_wait_timeout_still_records_runtime_role(tmp_path):
    root, deployment = runtime_tree(tmp_path, manifest=role_manifest())
    bin_dir, calls = fake_docker(tmp_path, wait_returncode=1)
    result = run_cli(
        root,
        ["run", "example", "--role", "secondary", "--pull", "never"],
        env=docker_env(bin_dir, ROLE_TOKEN="token"),
    )
    assert result.returncode != 0
    assert "up --detach --wait" in calls.read_text()
    saved = json.loads((deployment / ".cache" / "runtime.json").read_text())
    assert saved["role"] == "secondary"
    calls.write_text("")
    result = run_cli(root, ["status", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert "compose.secondary.yaml" in calls.read_text()


def test_status_and_logs_refuse_live_project_without_runtime_state(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=role_manifest())
    bin_dir, calls = fake_docker(tmp_path, compose_ls=RUNNING_PROJECT)
    for command in (["status", "example"], ["logs", "example"]):
        calls.write_text("")
        result = run_cli(root, command, env=docker_env(bin_dir))
        assert result.returncode == 1, result.stderr
        assert "saved runtime state is missing or unreadable" in result.stderr
        text = calls.read_text()
        assert " ps" not in text
        assert " logs" not in text


def test_vanished_saved_role_stops_by_project_name(tmp_path):
    root, deployment = runtime_tree(tmp_path, manifest=role_manifest())
    write_runtime_state(deployment, role="gone")
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(root, ["stop", "example"], env=docker_env(bin_dir))
    assert result.returncode == 0, result.stderr
    assert "warning: saved role gone is no longer defined" in result.stderr
    assert "down --remove-orphans" in calls.read_text()


def test_role_data_applicability_skips_other_roles(tmp_path):
    manifest = role_manifest()
    manifest["data"] = [
        files_resource(name="role-map", destination_env="MAP_PATH", roles=["primary"])
    ]
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    (deployment / "config.env").write_text("REMOTE_PASSWORD=default\n")
    target = tmp_path / "home/data/example"
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("keep")
    bin_dir, _ = fake_docker(tmp_path)
    env = docker_env(bin_dir, ROLE_TOKEN="token")

    result = run_cli(
        root,
        ["run", "example", "--role", "secondary", "--pull", "never", "--force"],
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (target / "keep.txt").read_text() == "keep"

    result = run_cli(root, ["validate", "example", "--role", "primary"], env=env)
    assert result.returncode != 0
    assert "MAP_PATH is required" in result.stderr

    result = run_cli(root, ["fetch", "example"], env=env)
    assert result.returncode != 0
    assert "MAP_PATH is required" in result.stderr


def test_role_scoped_data_cannot_share_a_destination(tmp_path):
    manifest = role_manifest()
    manifest["data"] = [
        files_resource(
            name="primary-map", destination_env="MAP_PATH", roles=["primary"]
        ),
        files_resource(
            name="secondary-map", destination_env="MAP_PATH", roles=["secondary"]
        ),
    ]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    assert "duplicate data destination environment: MAP_PATH" in run_cli(
        root, ["list"]
    ).stdout


def test_role_schema_errors_are_reported(tmp_path):
    unknown = role_manifest()
    unknown["compose"]["roles"]["primary"]["image"] = "busybox"
    root, _ = runtime_tree(tmp_path / "unknown", manifest=unknown)
    assert "unknown compose.roles.primary field(s): image" in run_cli(root, ["list"]).stdout

    root, deployment = runtime_tree(tmp_path / "missing", manifest=role_manifest())
    (deployment / "compose.primary.yaml").unlink()
    assert "missing Compose file" in run_cli(root, ["list"]).stdout

    escape = role_manifest()
    escape["compose"]["roles"]["primary"]["files"] = ["../outside.yaml"]
    root, _ = runtime_tree(tmp_path / "escape", manifest=escape)
    assert "safe relative path" in run_cli(root, ["list"]).stdout

    undeclared = role_manifest()
    undeclared["data"] = [files_resource(name="role-map", roles=["ghost"])]
    root, _ = runtime_tree(tmp_path / "undeclared", manifest=undeclared)
    assert "undeclared role(s): ghost" in run_cli(root, ["list"]).stdout

    no_base = role_manifest()
    no_base["shared"] = []
    root, _ = runtime_tree(tmp_path / "no-base", manifest=no_base)
    assert "compose.roles requires the base shared assets" in run_cli(root, ["list"]).stdout