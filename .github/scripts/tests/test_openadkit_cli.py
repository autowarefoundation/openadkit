import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = ROOT / "openadkit"
COMPONENT_IMAGES = {
    "LOCALIZATION_MAPPING_IMAGE": "localization-mapping",
    "PLANNING_CONTROL_IMAGE": "planning-control",
    "VEHICLE_SYSTEM_IMAGE": "vehicle-system",
    "API_IMAGE": "api",
    "VISUALIZER_IMAGE": "visualizer",
    "SIMULATOR_IMAGE": "simulator",
    "SENSING_PERCEPTION_IMAGE": "sensing-perception",
    "SENSING_PERCEPTION_GPU_IMAGE": "sensing-perception-cuda",
}
COMPONENT_TARGETS = tuple(COMPONENT_IMAGES.values())


def executable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def minimal_manifest(name="example", *, data=None):
    return {
        "schemaVersion": 1,
        "name": name,
        "description": "Test deployment",
        "compose": {
            "files": ["docker-compose.yaml"],
            "gpuFiles": [],
            "profiles": [],
            "services": ["app"],
            "resetServices": [],
            "waitTimeout": 30,
        },
        "requirements": {
            "architectures": ["amd64", "arm64"],
            "rosDistros": ["humble", "jazzy"],
            "gpu": "none",
        },
        "data": data or [],
    }


def kit_document(root, *, release=False, manifest=None, extra_deployments=None):
    deployments = {
        "example": {"path": "deployments/example"},
    }
    shared = {}
    if extra_deployments:
        deployments.update(extra_deployments)
    if release:
        deployments["example"]["checksum"] = deployment_checksum(
            root / "deployments/example"
        )
        for shared_name in (manifest or {}).get("shared", []):
            shared[shared_name] = deployment_checksum(root / "deployments" / shared_name)
    document = {
        "schemaVersion": 1,
        "kind": "release" if release else "repository",
        "defaultRosDistro": "humble",
        "componentImages": COMPONENT_IMAGES,
        "deployments": deployments,
    }
    if release:
        document["version"] = "v1.2.3"
        document["images"] = {
            distro: {
                target: f"registry.example/{target}:{distro}@sha256:{'1' * 64}"
                for target in COMPONENT_TARGETS
            }
            for distro in ("humble", "jazzy")
        }
        document["shared"] = shared
    else:
        document["imagePrefixComponent"] = "ghcr.io/autowarefoundation/openadkit"
    return document


def runtime_tree(tmp_path, *, release=False, manifest=None):
    root = tmp_path / "openadkit-test"
    root.mkdir(parents=True)
    shutil.copy2(ENTRYPOINT, root / "openadkit")
    shutil.copytree(ROOT / "cli", root / "cli")
    deployment = root / "deployments/example"
    deployment.mkdir(parents=True)
    manifest = manifest or minimal_manifest()
    (deployment / "deployment.json").write_text(json.dumps(manifest))
    (deployment / "config.env").write_text(
        "MAP_PATH=$HOME/data/example\nREMOTE_PASSWORD=default\n"
    )
    (deployment / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.1\n"
    )
    for gpu_file in manifest["compose"].get("gpuFiles", []):
        (deployment / gpu_file).write_text(
            "services:\n  app:\n    environment:\n      GPU: 'true'\n"
        )
    for shared_name in manifest.get("shared", []):
        shared = root / "deployments" / shared_name
        shared.mkdir()
        (shared / "runtime.env").write_text("ROS_DOMAIN_ID=1\n")
    (root / "openadkit.json").write_text(
        json.dumps(kit_document(root, release=release, manifest=manifest))
    )
    return root, deployment


def deployment_checksum(directory):
    digest = hashlib.sha256()
    for candidate in sorted(
        directory.rglob("*"), key=lambda path: path.relative_to(directory).as_posix()
    ):
        relative = candidate.relative_to(directory)
        if (
            relative.name == "config.local.env"
            or "__pycache__" in relative.parts
            or relative.suffix == ".pyc"
            or relative.parts[0] in {".cache", "output"}
        ):
            continue
        if candidate.is_symlink():
            digest.update(
                f"000 symlink:{os.readlink(candidate)}  {relative.as_posix()}\n".encode()
            )
            continue
        if not candidate.is_file():
            continue
        mode = "755" if os.access(candidate, os.X_OK) else "644"
        file_digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        digest.update(f"{mode} {file_digest}  {relative.as_posix()}\n".encode())
    return digest.hexdigest()


def fake_docker(
    tmp_path,
    *,
    configured="app\n",
    daemon_returncode=0,
    config_returncode=0,
    runtimes='{"nvidia": {}}',
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "docker-calls"
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'printf "%s|%s|%s|%s|%s|%s\\n" '
        '"${ROS_DISTRO:-}" "${DISTRO_VALUE:-}" "${API_IMAGE:-}" '
        '"${LOCALIZATION_MAPPING_IMAGE:-}" "${SENSING_PERCEPTION_GPU_IMAGE:-}" '
        f'"$*" >> {json.dumps(str(calls))}\n'
        'if [[ "$*" == "info" ]]; then '
        f"exit {daemon_returncode}; fi\n"
        'if [[ "$*" == "info --format {{json .Runtimes}}" ]]; then '
        f"printf '%s\\n' {json.dumps(runtimes)}; exit 0; fi\n"
        'if [[ "$*" == *"config --services"* ]]; then '
        f"printf '%b' {json.dumps(configured)}; fi\n"
        'if [[ "$*" == *"config --quiet"* ]]; then '
        f"exit {config_returncode}; fi\n"
        "exit 0\n",
    )
    return bin_dir, calls


def run_cli(root, args, *, env=None):
    command_env = os.environ | {"HOME": str(root.parent / "home")}
    if env:
        command_env.update(env)
    Path(command_env["HOME"]).mkdir(exist_ok=True)
    return subprocess.run(
        [str(root / "openadkit"), *args],
        cwd=root,
        env=command_env,
        text=True,
        capture_output=True,
    )


def test_command_surface_is_exact():
    result = subprocess.run(
        [str(ENTRYPOINT), "--help"], text=True, capture_output=True, check=True
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
        assert command in result.stdout
    for command in ("verify", "down", "install", "build"):
        assert f"  {command} " not in result.stdout
    unknown = subprocess.run(
        [str(ENTRYPOINT), "data"], text=True, capture_output=True
    )
    assert unknown.returncode != 0


def test_repo_and_release_use_the_same_entrypoint(tmp_path):
    repo, _ = runtime_tree(tmp_path / "repo")
    release, _ = runtime_tree(tmp_path / "release", release=True)
    assert (repo / "openadkit").read_bytes() == (release / "openadkit").read_bytes()
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
    assert "example\tintact\tnone\tTest deployment" in result.stdout
    assert "custom" not in result.stdout


def test_no_command_prints_help():
    result = subprocess.run([str(ENTRYPOINT)], text=True, capture_output=True)
    assert result.returncode == 2
    assert "setup" in result.stdout
    assert "list" in result.stdout
    assert "examples:" in result.stdout


def test_unknown_deployment_is_rejected(tmp_path):
    root, _ = runtime_tree(tmp_path)
    result = run_cli(root, ["run", "custom"])
    assert result.returncode != 0
    assert "unknown deployment: custom" in result.stderr
    assert "available: example" in result.stderr


def test_release_deployment_change_is_marked_modified(tmp_path):
    root, deployment = runtime_tree(tmp_path, release=True)
    (deployment / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.2\n"
    )
    result = run_cli(root, ["list"])
    assert result.returncode == 0, result.stderr
    assert "example\tmodified" in result.stdout


def test_release_shared_asset_change_is_marked_modified(tmp_path):
    manifest = minimal_manifest()
    manifest["shared"] = ["base"]
    root, _ = runtime_tree(tmp_path, release=True, manifest=manifest)
    (root / "deployments/base/runtime.env").write_text("ROS_DOMAIN_ID=2\n")
    result = run_cli(root, ["list"])
    assert result.returncode == 0, result.stderr
    assert "example\tmodified" in result.stdout


def test_modified_release_warns_but_still_runs(tmp_path):
    root, deployment = runtime_tree(tmp_path, release=True)
    (deployment / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.2\n"
    )
    bin_dir, _ = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["run", "example", "--pull", "never"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert "has been modified from this release" in result.stderr
    assert "running: example" in result.stdout


def test_duplicate_json_keys_are_rejected(tmp_path):
    root, deployment = runtime_tree(tmp_path)
    text = json.dumps(minimal_manifest())
    (deployment / "deployment.json").write_text(
        text.replace('"name": "example"', '"name": "example", "name": "other"')
    )
    result = run_cli(root, ["list"])
    assert "duplicate JSON key" in result.stdout


def test_manifest_paths_cannot_escape_deployment(tmp_path):
    manifest = minimal_manifest()
    manifest["compose"]["files"] = ["../outside.yaml"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    result = run_cli(root, ["list"])
    assert "safe relative path" in result.stdout


def test_config_local_env_is_applied_last(tmp_path):
    root, deployment = runtime_tree(tmp_path)
    (deployment / "config.local.env").write_text("REMOTE_PASSWORD=local\n")
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    call = calls.read_text()
    assert call.index("config.env") < call.index("config.local.env")


def test_run_orders_render_daemon_pull_and_up(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["run", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert text.index("config --quiet") < text.index("|info")
    assert text.index("|info") < text.index("pull --policy missing")
    assert text.index("pull --policy missing") < text.index("up --detach --wait")


@pytest.mark.parametrize(
    ("policy", "expects_pull"),
    [("missing", True), ("always", True), ("never", False)],
)
def test_run_pull_policy_is_explicit_for_up(tmp_path, policy, expects_pull):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["run", "example", "--pull", policy],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert ("pull --policy" in text) is expects_pull
    assert (
        "up --detach --wait --wait-timeout 30 --pull never --remove-orphans app"
        in text
    )


def test_run_resets_declared_one_shot_services(tmp_path):
    manifest = minimal_manifest()
    manifest["compose"]["resetServices"] = ["map-check"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path, configured="app\nmap-check\n")
    result = run_cli(
        root,
        ["run", "example", "--pull", "never"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert "rm --stop --force map-check" in calls.read_text()


def test_stop_removes_project_but_not_volumes(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["stop", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert "down --remove-orphans" in calls.read_text()
    assert "--volumes" not in calls.read_text()


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
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "OPENADKIT_CI_FORCE_DOCKER_INSTALL": "true",
            "CI": "false",
        },
    )
    assert result.returncode != 0
    assert "restricted to disposable CI hosts" in result.stderr
    assert not sudo_log.exists()


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture
def http_files(tmp_path):
    directory = tmp_path / "http"
    directory.mkdir()
    handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
        *args, directory=str(directory), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield directory, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def test_fetch_zip_is_checksum_verified_and_published_atomically(tmp_path, http_files):
    directory, base_url = http_files
    archive = directory / "data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("dataset/required.txt", "ok")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    data = [
        {
            "name": "dataset",
            "kind": "zip",
            "destinationEnv": "MAP_PATH",
            "expectedRoot": "dataset",
            "url": f"{base_url}/data.zip",
            "sha256": checksum,
            "requiredFiles": ["required.txt"],
        }
    ]
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(data=data))
    result = run_cli(root, ["fetch", "example"])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/example/required.txt").read_text() == "ok"


def test_fetch_skips_required_gpu_flag(tmp_path, http_files):
    directory, base_url = http_files
    archive = directory / "data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("dataset/required.txt", "ok")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    data = [
        {
            "name": "dataset",
            "kind": "zip",
            "destinationEnv": "MAP_PATH",
            "expectedRoot": "dataset",
            "url": f"{base_url}/data.zip",
            "sha256": checksum,
            "requiredFiles": ["required.txt"],
        }
    ]
    manifest = minimal_manifest(data=data)
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
    data = [
        {
            "name": "dataset",
            "kind": "zip",
            "destinationEnv": "MAP_PATH",
            "expectedRoot": "dataset",
            "url": f"{base_url}/data.zip",
            "sha256": "0" * 64,
            "requiredFiles": ["required.txt"],
        }
    ]
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(data=data))
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
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    data = [
        {
            "name": "dataset",
            "kind": "zip",
            "destinationEnv": "MAP_PATH",
            "expectedRoot": "dataset",
            "url": f"{base_url}/data.zip",
            "sha256": checksum,
            "requiredFiles": ["required.txt"],
        }
    ]
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(data=data))
    result = run_cli(root, ["fetch", "example"])
    assert result.returncode != 0
    assert "unsafe ZIP member" in result.stderr
    assert not (tmp_path / "home/data/example").exists()


def test_run_accepts_force():
    result = subprocess.run(
        [str(ENTRYPOINT), "run", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--force" in result.stdout
    assert "replace existing data" in result.stdout
    assert "image pull policy" in result.stdout
    assert "GPU compose overlay" in result.stdout


def test_run_force_reinstalls_incomplete_data(tmp_path, http_files):
    directory, base_url = http_files
    payload = directory / "required.txt"
    payload.write_text("replaced")
    data = [
        {
            "name": "dataset",
            "kind": "files",
            "destinationEnv": "MAP_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": f"{base_url}/required.txt",
                    "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                }
            ],
            "requiredFiles": ["required.txt"],
        }
    ]
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(data=data))
    target = tmp_path / "home/data/example"
    target.mkdir(parents=True)
    bin_dir, _ = fake_docker(tmp_path)
    path_env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    blocked = run_cli(root, ["run", "example", "--pull", "never"], env=path_env)
    assert blocked.returncode != 0
    assert "incomplete data" in blocked.stderr
    assert "rerun with --force" in blocked.stderr
    result = run_cli(
        root, ["run", "example", "--pull", "never", "--force"], env=path_env
    )
    assert result.returncode == 0, result.stderr
    assert (target / "required.txt").read_text() == "replaced"


def test_fetch_does_not_take_gpu_flag():
    result = subprocess.run(
        [str(ENTRYPOINT), "fetch", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--gpu" not in result.stdout
    assert "--ros-distro" in result.stdout
    assert "--force" in result.stdout


@pytest.mark.parametrize("command", ("validate", "fetch", "run"))
def test_selected_commands_accept_ros_distro(command):
    result = subprocess.run(
        [str(ENTRYPOINT), command, "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--ros-distro" in result.stdout


@pytest.mark.parametrize("command", ("status", "logs", "stop"))
def test_operational_commands_do_not_take_selection_flags(command):
    result = subprocess.run(
        [str(ENTRYPOINT), command, "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--ros-distro" not in result.stdout
    assert "--gpu" not in result.stdout


def test_repository_injects_selected_distro_and_component_environment(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["API_IMAGE"]
    manifest["distroEnvironment"] = {"jazzy": {"DISTRO_VALUE": "jazzy-value"}}
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example", "--ros-distro", "jazzy"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert (
        "jazzy|jazzy-value|"
        "ghcr.io/autowarefoundation/openadkit:api-jazzy|"
        "ghcr.io/autowarefoundation/openadkit:localization-mapping-jazzy|"
        in calls.read_text()
    )


def test_kit_default_ros_distro_is_used(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = json.loads((root / "openadkit.json").read_text())
    kit["defaultRosDistro"] = "jazzy"
    (root / "openadkit.json").write_text(json.dumps(kit))
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert calls.read_text().startswith("jazzy|")


def test_release_injects_exact_component_references(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["API_IMAGE"]
    root, _ = runtime_tree(tmp_path, release=True, manifest=manifest)
    kit_path = root / "openadkit.json"
    current = json.loads(kit_path.read_text())
    exact = f"registry.example/api@sha256:{'a' * 64}"
    current["images"]["humble"]["api"] = exact
    kit_path.write_text(json.dumps(current))
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    fields = calls.read_text().split("|", 5)
    assert fields[2] == exact


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
    manifest = minimal_manifest()
    root, _ = runtime_tree(tmp_path, release=True, manifest=manifest)
    kit_path = root / "openadkit.json"
    current = json.loads(kit_path.read_text())
    current["images"] = {"humble": {}}
    kit_path.write_text(json.dumps(current))
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "missing component image target(s)" in result.stderr
    assert not calls.exists()


def test_repository_component_image_override_is_preserved(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["API_IMAGE"]
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    exact = f"registry.example/custom-api@sha256:{'b' * 64}"
    (deployment / "config.local.env").write_text(f"API_IMAGE={exact}\n")
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert calls.read_text().split("|", 5)[2] == exact


def test_validate_renders_without_accessing_docker_daemon(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path, daemon_returncode=37)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert "config --quiet" in calls.read_text()
    assert "|info\n" not in calls.read_text()


def test_daemon_failure_prevents_data_and_container_commands(tmp_path):
    data_resources = [
        {
            "name": "dataset",
            "kind": "files",
            "destinationEnv": "MAP_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": "http://127.0.0.1:1/unreachable",
                    "sha256": "0" * 64,
                }
            ],
            "requiredFiles": ["required.txt"],
        }
    ]
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(data=data_resources))
    bin_dir, calls = fake_docker(tmp_path, daemon_returncode=1)
    result = run_cli(
        root,
        ["run", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "could not access the Docker daemon" in result.stderr
    assert not (tmp_path / "home/data").exists()
    text = calls.read_text()
    assert " pull " not in f" {text} "
    assert " up " not in f" {text} "


def test_missing_gpu_runtime_prevents_data_and_container_commands(tmp_path):
    resources = [
        {
            "name": "gpu-dataset",
            "kind": "files",
            "destinationEnv": "GPU_DATA_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": "http://127.0.0.1:1/unreachable",
                    "sha256": "0" * 64,
                }
            ],
            "requiredFiles": ["required.txt"],
            "gpu": True,
        }
    ]
    manifest = minimal_manifest(data=resources)
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    with (deployment / "config.env").open("a") as output:
        output.write("GPU_DATA_PATH=$HOME/data/gpu\n")
    bin_dir, calls = fake_docker(tmp_path, runtimes="{}")
    result = run_cli(
        root,
        ["run", "example", "--gpu"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "NVIDIA Container Toolkit is unavailable" in result.stderr
    assert not (tmp_path / "home/data/gpu").exists()
    text = calls.read_text()
    assert " pull " not in f" {text} "
    assert " up " not in f" {text} "


def test_all_data_targets_are_checked_before_first_download(tmp_path):
    resources = [
        {
            "name": "first",
            "kind": "files",
            "destinationEnv": "FIRST_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": "http://127.0.0.1:1/unreachable",
                    "sha256": "0" * 64,
                }
            ],
            "requiredFiles": ["required.txt"],
        },
        {
            "name": "second",
            "kind": "files",
            "destinationEnv": "SECOND_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": "http://127.0.0.1:1/unreachable",
                    "sha256": "0" * 64,
                }
            ],
            "requiredFiles": ["required.txt"],
        },
    ]
    root, deployment = runtime_tree(tmp_path, manifest=minimal_manifest(data=resources))
    (deployment / "config.env").write_text(
        "FIRST_PATH=$HOME/data/first\nSECOND_PATH=$HOME/data/second\n"
    )
    incomplete = tmp_path / "home/data/second"
    incomplete.mkdir(parents=True)
    result = run_cli(root, ["fetch", "example"])
    assert result.returncode != 0
    assert "incomplete data" in result.stderr
    assert not (tmp_path / "home/data/first").exists()


def test_fetch_includes_gpu_data_without_docker(tmp_path, http_files):
    directory, base_url = http_files
    payload = directory / "required.txt"
    payload.write_text("gpu data")
    resources = [
        {
            "name": "gpu-dataset",
            "kind": "files",
            "destinationEnv": "GPU_DATA_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": f"{base_url}/required.txt",
                    "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                }
            ],
            "requiredFiles": ["required.txt"],
            "gpu": True,
        }
    ]
    manifest = minimal_manifest(data=resources)
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    with (deployment / "config.env").open("a") as output:
        output.write("GPU_DATA_PATH=$HOME/data/gpu\n")
    bin_dir, calls = fake_docker(tmp_path, config_returncode=99)
    result = run_cli(
        root,
        ["fetch", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/gpu/required.txt").read_text() == "gpu data"
    assert not calls.exists()


def test_run_without_gpu_skips_gpu_only_data(tmp_path):
    resources = [
        {
            "name": "gpu-dataset",
            "kind": "files",
            "destinationEnv": "MAP_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": "http://127.0.0.1:1/unreachable",
                    "sha256": "0" * 64,
                }
            ],
            "requiredFiles": ["required.txt"],
            "gpu": True,
        }
    ]
    manifest = minimal_manifest(data=resources)
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, _ = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["run", "example", "--pull", "never"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home/data").exists()


def test_relative_data_destination_is_rejected_before_download(tmp_path):
    resources = [
        {
            "name": "dataset",
            "kind": "files",
            "destinationEnv": "MAP_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": "http://127.0.0.1:1/unreachable",
                    "sha256": "0" * 64,
                }
            ],
            "requiredFiles": ["required.txt"],
        }
    ]
    root, deployment = runtime_tree(
        tmp_path, manifest=minimal_manifest(data=resources)
    )
    (deployment / "config.env").write_text("MAP_PATH=relative/data\n")
    result = run_cli(root, ["fetch", "example"])
    assert result.returncode != 0
    assert "must be absolute after HOME expansion" in result.stderr
    assert not (root / "relative").exists()


def test_validate_rejects_active_relative_data_destination_before_compose(tmp_path):
    resources = [
        {
            "name": "dataset",
            "kind": "files",
            "destinationEnv": "MAP_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": "http://127.0.0.1:1/unreachable",
                    "sha256": "0" * 64,
                }
            ],
            "requiredFiles": ["required.txt"],
        }
    ]
    root, deployment = runtime_tree(
        tmp_path, manifest=minimal_manifest(data=resources)
    )
    (deployment / "config.env").write_text("MAP_PATH=relative/data\n")
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "must be absolute after HOME expansion" in result.stderr
    assert not calls.exists()


def test_unknown_manifest_service_fails_before_data_pull_or_up(tmp_path):
    resources = [
        {
            "name": "dataset",
            "kind": "files",
            "destinationEnv": "MAP_PATH",
            "files": [
                {
                    "path": "required.txt",
                    "url": "http://127.0.0.1:1/unreachable",
                    "sha256": "0" * 64,
                }
            ],
            "requiredFiles": ["required.txt"],
        }
    ]
    manifest = minimal_manifest(data=resources)
    manifest["compose"]["services"] = ["typo"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path, configured="app\n")
    result = run_cli(
        root,
        ["run", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "unknown Compose service(s): typo" in result.stderr
    assert not (tmp_path / "home/data/example").exists()
    text = calls.read_text()
    assert " pull " not in f" {text} "
    assert " up " not in f" {text} "


def test_ros_distro_constraints_fail_before_compose(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["rosDistros"] = ["humble"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example", "--ros-distro", "jazzy"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "does not support ROS distro jazzy" in result.stderr
    assert not calls.exists()


def test_required_environment_fails_before_compose(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["DEPLOYMENT_TOKEN"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "required environment variable(s) are missing: DEPLOYMENT_TOKEN" in result.stderr
    assert not calls.exists()


def test_gpu_architecture_constraint_fails_before_compose(tmp_path):
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        architecture = "amd64"
    elif machine in ("aarch64", "arm64"):
        architecture = "arm64"
    else:
        architecture = machine
    other = "unsupported-test-architecture"
    manifest = minimal_manifest()
    manifest["requirements"].update(
        {
            "architectures": [architecture, other],
            "gpu": "optional",
            "gpuArchitectures": [other],
        }
    )
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example", "--gpu"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert f"GPU mode does not support {architecture}" in result.stderr
    assert not calls.exists()


def test_empty_services_are_rejected(tmp_path):
    manifest = minimal_manifest()
    manifest["compose"]["services"] = []
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    result = run_cli(root, ["list"])
    assert result.returncode == 0
    assert "compose.services must not be empty" in result.stdout


def test_status_uses_last_run_gpu_selection(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    path_env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}

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


def _host_architecture():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


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


def test_repository_inventory_includes_carla_and_excludes_zenoh():
    result = subprocess.run(
        [str(ENTRYPOINT), "list"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "planning-simulation\tsource\tnone\t" in result.stdout
    assert "logging-simulation\tsource\toptional\t" in result.stdout
    assert "scenario-simulation\tsource\tnone\t" in result.stdout
    assert "carla-simulation\tsource\trequired\t" in result.stdout
    assert "zenoh" not in result.stdout


def test_carla_requires_gpu():
    result = subprocess.run(
        [str(ENTRYPOINT), "validate", "carla-simulation"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    if _host_architecture() == "amd64":
        assert "requires --gpu" in result.stderr


def test_carla_is_humble_only():
    if _host_architecture() != "amd64":
        pytest.skip("carla-simulation is amd64-only")
    result = subprocess.run(
        [
            str(ENTRYPOINT),
            "validate",
            "carla-simulation",
            "--gpu",
            "--ros-distro",
            "jazzy",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "does not support ROS distro jazzy" in result.stderr
