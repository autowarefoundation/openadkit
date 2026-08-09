import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = ROOT / "openadkit"
COMPONENT_TARGETS = (
    "localization-mapping",
    "planning-control",
    "vehicle-system",
    "api",
    "visualizer",
    "simulator",
    "sensing-perception",
    "sensing-perception-cuda",
)


def executable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def minimal_manifest(
    name="example", *, hooks=None, data=None, groups=None, features=None
):
    return {
        "schemaVersion": 1,
        "name": name,
        "description": "Test deployment",
        "compose": {
            "files": ["docker-compose.yaml"],
            "gpuFiles": [],
            "profiles": [],
            "services": ["app"],
            "verifyServices": ["app"],
            "resetServices": [],
            "waitTimeout": 30,
            "groups": groups or {},
            "features": features or {},
        },
        "requirements": {
            "architectures": ["amd64", "arm64"],
            "rosDistros": ["humble", "jazzy"],
            "gpu": "none",
        },
        "data": data or [],
        "hooks": hooks or {},
    }


def runtime_tree(tmp_path, *, release=False, manifest=None):
    root = tmp_path / "openadkit-test"
    root.mkdir(parents=True)
    shutil.copy2(ENTRYPOINT, root / "openadkit")
    shutil.copytree(ROOT / "openadkit.d", root / "openadkit.d")
    deployment = root / "deployments/example"
    deployment.mkdir(parents=True)
    manifest = manifest or minimal_manifest()
    (deployment / "openadkit.json").write_text(json.dumps(manifest))
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
    shared_hashes = {}
    for shared_name in manifest.get("shared", []):
        shared = root / "deployments" / shared_name
        shared.mkdir()
        (shared / "runtime.env").write_text("ROS_DOMAIN_ID=1\n")
        shared_hashes[shared_name] = deployment_checksum(shared)
    if release:
        checksum = deployment_checksum(deployment)
        (root / "openadkit.d/context.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "release",
                    "version": "v1.2.3",
                    "defaultRosDistro": "humble",
                    "images": {
                        distro: {
                            target: f"registry.example/{target}:{distro}@sha256:{'1' * 64}"
                            for target in COMPONENT_TARGETS
                        }
                        for distro in ("humble", "jazzy")
                    },
                    "deployments": {"example": checksum},
                    "shared": shared_hashes,
                }
            )
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
    running="app",
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
        f'printf "%s|%s|%s|%s|%s|%s|%s\\n" "${{SCENARIO_SIMULATION:-}}" '
        '"${ROS_DISTRO:-}" "${DISTRO_VALUE:-}" "${FEATURE_VALUE:-}" '
        '"${API_IMAGE:-}" "${LOCALIZATION_MAPPING_IMAGE:-}" '
        f'"$*" >> {json.dumps(str(calls))}\n'
        'if [[ "$*" == "info" ]]; then '
        f"exit {daemon_returncode}; fi\n"
        'if [[ "$*" == "info --format {{json .Runtimes}}" ]]; then '
        f"printf '%s\\n' {json.dumps(runtimes)}; exit 0; fi\n"
        'if [[ "$*" == *"config --services"* ]]; then '
        f"printf '%b' {json.dumps(configured)}; fi\n"
        'if [[ "$*" == *"config --quiet"* ]]; then '
        f"exit {config_returncode}; fi\n"
        'if [[ "$*" == *"ps --status running --services"* ]]; then '
        f"printf '%s\\n' {json.dumps(running)}; fi\n"
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
        "list",
        "version",
        "validate",
        "data",
        "run",
        "verify",
        "status",
        "logs",
        "stop",
        "down",
    ):
        assert command in result.stdout
    assert "install" not in result.stdout
    assert "build" not in result.stdout


def test_repo_and_release_use_the_same_entrypoint(tmp_path):
    repo, _ = runtime_tree(tmp_path / "repo")
    release, _ = runtime_tree(tmp_path / "release", release=True)
    assert (repo / "openadkit").read_bytes() == (release / "openadkit").read_bytes()
    assert run_cli(repo, ["version"]).stdout.startswith("Open AD Kit development")
    assert run_cli(release, ["version"]).stdout.startswith("Open AD Kit v1.2.3")


def test_list_marks_release_inventory_and_custom_deployment(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    custom = root / "deployments/custom"
    custom.mkdir()
    (custom / "openadkit.json").write_text(json.dumps(minimal_manifest("custom")))
    (custom / "config.env").write_text("MAP_PATH=$HOME/custom\n")
    (custom / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.1\n"
    )
    result = run_cli(root, ["list"])
    assert result.returncode == 0, result.stderr
    assert "example\tverified" in result.stdout
    assert "custom\tcustom/unverified" in result.stdout


def test_release_deployment_change_is_marked_unverified(tmp_path):
    root, deployment = runtime_tree(tmp_path, release=True)
    (deployment / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.2\n"
    )
    result = run_cli(root, ["list"])
    assert result.returncode == 0, result.stderr
    assert "example\tcustom/unverified" in result.stdout


def test_release_shared_asset_change_is_marked_unverified(tmp_path):
    manifest = minimal_manifest()
    manifest["shared"] = ["base"]
    root, _ = runtime_tree(tmp_path, release=True, manifest=manifest)
    (root / "deployments/base/runtime.env").write_text("ROS_DOMAIN_ID=2\n")
    result = run_cli(root, ["list"])
    assert result.returncode == 0, result.stderr
    assert "example\tcustom/unverified" in result.stdout


def test_duplicate_json_keys_are_rejected(tmp_path):
    root, deployment = runtime_tree(tmp_path)
    text = json.dumps(minimal_manifest())
    (deployment / "openadkit.json").write_text(text.replace('"name": "example"', '"name": "example", "name": "other"'))
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


def test_run_orders_pull_up_and_verify_hook(tmp_path):
    manifest = minimal_manifest(hooks={"verify": "hooks/verify"})
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    hook_log = tmp_path / "hook-log"
    executable(
        deployment / "hooks/verify",
        f"#!/usr/bin/env bash\nprintf 'verify\\n' >> {json.dumps(str(hook_log))}\n",
    )
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["run", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert text.index("config --quiet") < text.index("pull --policy missing")
    assert text.index("pull --policy missing") < text.index("up --detach --wait")
    assert hook_log.read_text() == "verify\n"


@pytest.mark.parametrize(
    ("policy", "expects_pull"),
    [("missing", True), ("always", True), ("never", False)],
)
def test_run_pull_policy_is_explicit_for_up(tmp_path, policy, expects_pull):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["run", "example", "--pull", policy, "--skip-verify"],
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
        ["run", "example", "--pull", "never", "--skip-verify"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert "rm --stop --force map-check" in calls.read_text()


def test_group_selection_reconciles_services_and_applies_feature_environment(
    tmp_path,
):
    groups = {"small": {"services": ["app"]}}
    features = {
        "no-sim": {
            "services": [],
            "excludeServices": ["simulator"],
            "environment": {"SCENARIO_SIMULATION": "false"},
        }
    }
    manifest = minimal_manifest(groups=groups, features=features)
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    (deployment / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.1\n"
        "  simulator:\n    image: busybox:1.36.1\n"
    )
    bin_dir, calls = fake_docker(tmp_path, configured="app\nsimulator\n")
    result = run_cli(
        root,
        [
            "run",
            "example",
            "--group",
            "small",
            "--enable",
            "no-sim",
            "--pull",
            "never",
            "--skip-verify",
        ],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    assert "false|" in text
    assert "stop simulator" in text
    assert "rm --force simulator" in text


def test_group_verify_requires_persistent_services(tmp_path):
    groups = {"small": {"services": ["app"], "verifyServices": ["app"]}}
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(groups=groups))
    bin_dir, _ = fake_docker(tmp_path, running="")
    result = run_cli(
        root,
        ["verify", "example", "--group", "small"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "required service(s) are not running: app" in result.stderr


def test_cloud_group_skips_edge_only_data(tmp_path):
    groups = {
        "cloud": {"services": ["app"]},
        "edge": {"services": ["app"]},
    }
    data = [
        {
            "name": "edge-data",
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
            "groups": ["edge"],
        }
    ]
    root, _ = runtime_tree(
        tmp_path, manifest=minimal_manifest(groups=groups, data=data)
    )
    bin_dir, _ = fake_docker(tmp_path, configured="app\n")
    result = run_cli(
        root,
        [
            "run",
            "example",
            "--group",
            "cloud",
            "--pull",
            "never",
            "--skip-verify",
        ],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home/data/example").exists()


def test_verify_failure_leaves_stack_running(tmp_path):
    manifest = minimal_manifest(hooks={"verify": "hooks/verify"})
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    executable(deployment / "hooks/verify", "#!/usr/bin/env bash\nexit 9\n")
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["run", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert " down " not in f" {calls.read_text()} "
    assert " stop " not in f" {calls.read_text()} "


def test_down_removes_project_but_not_volumes(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["down", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert "down --remove-orphans" in calls.read_text()
    assert "--volumes" not in calls.read_text()


def test_setup_development_is_rejected_in_release_before_sudo(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo_log = tmp_path / "sudo-log"
    executable(
        bin_dir / "sudo",
        f"#!/usr/bin/env bash\nprintf called > {json.dumps(str(sudo_log))}\n",
    )
    result = run_cli(
        root,
        ["setup", "--development"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "requires a Git source checkout" in result.stderr
    assert not sudo_log.exists()


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


def test_hook_with_sudo_is_rejected(tmp_path):
    manifest = minimal_manifest(hooks={"preflight": "hooks/preflight"})
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    executable(deployment / "hooks/preflight", "#!/usr/bin/env bash\nsudo true\n")
    result = run_cli(root, ["list"])
    assert "must not invoke sudo" in result.stdout


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


def test_data_zip_is_checksum_verified_and_published_atomically(tmp_path, http_files):
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
    result = run_cli(root, ["data", "example"])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/example/required.txt").read_text() == "ok"


def test_data_checksum_failure_preserves_existing_data(tmp_path, http_files):
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
    result = run_cli(root, ["data", "example", "--force"])
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
    result = run_cli(root, ["data", "example"])
    assert result.returncode != 0
    assert "unsafe ZIP member" in result.stderr
    assert not (tmp_path / "home/data/example").exists()


@pytest.mark.parametrize(
    "command",
    ("validate", "data", "run", "verify", "status", "logs", "stop", "down"),
)
def test_runtime_commands_accept_ros_distro(command):
    result = subprocess.run(
        [str(ENTRYPOINT), command, "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--ros-distro" in result.stdout


def test_repository_injects_selected_distro_feature_and_component_environment(
    tmp_path,
):
    features = {
        "tuned": {
            "services": [],
            "excludeServices": [],
            "verifyServices": [],
            "environment": {"FEATURE_VALUE": "feature-value"},
            "requiredEnv": ["FEATURE_VALUE"],
        }
    }
    manifest = minimal_manifest(features=features)
    manifest["requirements"]["requiredEnv"] = ["API_IMAGE"]
    manifest["distroEnvironment"] = {
        "jazzy": {"DISTRO_VALUE": "jazzy-value"}
    }
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example", "--ros-distro", "jazzy", "--enable", "tuned"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert (
        "|jazzy|jazzy-value|feature-value|"
        "ghcr.io/autowarefoundation/openadkit:api-jazzy|"
        "ghcr.io/autowarefoundation/openadkit:localization-mapping-jazzy|"
        in calls.read_text()
    )


def test_context_default_ros_distro_is_used(tmp_path):
    root, _ = runtime_tree(tmp_path)
    context = json.loads((root / "openadkit.d/context.json").read_text())
    context["defaultRosDistro"] = "jazzy"
    (root / "openadkit.d/context.json").write_text(json.dumps(context))
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert "|jazzy|" in calls.read_text()


def test_release_injects_exact_component_references(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["API_IMAGE"]
    root, _ = runtime_tree(tmp_path, release=True, manifest=manifest)
    context_path = root / "openadkit.d/context.json"
    current = json.loads(context_path.read_text())
    exact = f"registry.example/api@sha256:{'a' * 64}"
    current["images"]["humble"]["api"] = exact
    context_path.write_text(json.dumps(current))
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    fields = calls.read_text().split("|", 6)
    assert fields[4] == exact


def test_release_rejects_mutable_component_reference(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    context_path = root / "openadkit.d/context.json"
    current = json.loads(context_path.read_text())
    current["images"]["humble"]["api"] = "registry.example/api:humble"
    context_path.write_text(json.dumps(current))
    result = run_cli(root, ["list"])
    assert result.returncode != 0
    assert "digest-pinned image references" in result.stderr


def test_missing_required_release_target_fails_before_compose(tmp_path):
    manifest = minimal_manifest()
    root, _ = runtime_tree(tmp_path, release=True, manifest=manifest)
    context_path = root / "openadkit.d/context.json"
    current = json.loads(context_path.read_text())
    current["images"] = {"humble": {}}
    context_path.write_text(json.dumps(current))
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
    assert calls.read_text().split("|", 6)[4] == exact


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


def test_run_checks_daemon_before_preflight_and_mutation(tmp_path):
    manifest = minimal_manifest(hooks={"preflight": "hooks/preflight"})
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    snapshot = tmp_path / "preflight-snapshot"
    executable(
        deployment / "hooks/preflight",
        "#!/usr/bin/env bash\n"
        f"/bin/cp -- {json.dumps(str(calls))} {json.dumps(str(snapshot))}\n",
    )
    result = run_cli(
        root,
        ["run", "example", "--pull", "never", "--skip-verify"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    preflight_calls = snapshot.read_text()
    assert preflight_calls.index("config --quiet") < preflight_calls.index("|info")
    assert " pull " not in f" {preflight_calls} "
    assert " up " not in f" {preflight_calls} "


def test_daemon_failure_prevents_preflight_data_and_container_commands(tmp_path):
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
    manifest = minimal_manifest(
        hooks={"preflight": "hooks/preflight"}, data=data_resources
    )
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    hook_log = tmp_path / "hook-log"
    executable(
        deployment / "hooks/preflight",
        f"#!/usr/bin/env bash\nprintf called > {json.dumps(str(hook_log))}\n",
    )
    bin_dir, calls = fake_docker(tmp_path, daemon_returncode=1)
    result = run_cli(
        root,
        ["run", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "could not access the Docker daemon" in result.stderr
    assert not hook_log.exists()
    assert not (tmp_path / "home/data").exists()
    text = calls.read_text()
    assert " pull " not in f" {text} "
    assert " up " not in f" {text} "
    assert " stop " not in f" {text} "
    assert " rm " not in f" {text} "


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


def test_preflight_failure_prevents_data_and_container_commands(tmp_path):
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
    manifest = minimal_manifest(
        hooks={"preflight": "hooks/preflight"}, data=data_resources
    )
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    executable(deployment / "hooks/preflight", "#!/usr/bin/env bash\nexit 8\n")
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["run", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert not (tmp_path / "home/data").exists()
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
    result = run_cli(root, ["data", "example"])
    assert result.returncode != 0
    assert "incomplete data" in result.stderr
    assert not (tmp_path / "home/data/first").exists()


def test_data_needs_no_docker_and_skips_gpu_only_resources(tmp_path):
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
    bin_dir, calls = fake_docker(tmp_path, config_returncode=99)
    result = run_cli(
        root,
        ["data", "example", "--ros-distro", "jazzy"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert not calls.exists()
    assert not (tmp_path / "home/data").exists()


def test_gpu_data_is_selected_with_gpu_without_docker(tmp_path, http_files):
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
        ["data", "example", "--gpu"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/gpu/required.txt").read_text() == "gpu data"
    assert not calls.exists()


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
    result = run_cli(root, ["data", "example"])
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


def test_verification_defaults_to_all_selected_services(tmp_path):
    manifest = minimal_manifest()
    manifest["compose"].pop("verifyServices")
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, _ = fake_docker(tmp_path, running="")
    result = run_cli(
        root,
        ["verify", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "required service(s) are not running: app" in result.stderr


def test_explicit_verification_must_be_subset_before_compose(tmp_path):
    manifest = minimal_manifest()
    manifest["compose"]["verifyServices"] = ["other"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0
    assert "verification service(s) are not selected: other" in result.stderr
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
    manifest["compose"]["verifyServices"] = ["typo"]
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


@pytest.mark.parametrize("scope", ("deployment", "group", "feature"))
def test_ros_distro_constraints_fail_before_compose(tmp_path, scope):
    groups = None
    features = None
    arguments = ["validate", "example", "--ros-distro", "jazzy"]
    manifest = minimal_manifest()
    if scope == "deployment":
        manifest["requirements"]["rosDistros"] = ["humble"]
    elif scope == "group":
        groups = {
            "small": {"services": ["app"], "rosDistros": ["humble"]}
        }
        manifest = minimal_manifest(groups=groups)
        arguments.extend(("--group", "small"))
    else:
        features = {
            "humble-only": {
                "services": [],
                "excludeServices": [],
                "verifyServices": [],
                "environment": {},
                "rosDistros": ["humble"],
            }
        }
        manifest = minimal_manifest(features=features)
        arguments.extend(("--enable", "humble-only"))
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        arguments,
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


@pytest.mark.parametrize(
    "groups,services,error",
    (
        ({}, [], "compose.services must not be empty"),
        ({"small": {"services": []}}, ["app"], "group small.services must not be empty"),
    ),
)
def test_service_definitions_must_be_nonempty(tmp_path, groups, services, error):
    manifest = minimal_manifest(groups=groups)
    manifest["compose"]["groups"] = groups
    manifest["compose"]["services"] = services
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    result = run_cli(root, ["list"])
    assert result.returncode == 0
    assert error in result.stdout


def test_before_run_hook_is_rejected(tmp_path):
    manifest = minimal_manifest(hooks={"beforeRun": "hooks/before-run"})
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    executable(deployment / "hooks/before-run", "#!/usr/bin/env bash\ntrue\n")
    result = run_cli(root, ["list"])
    assert result.returncode == 0
    assert "unknown hooks field(s): beforeRun" in result.stdout


def test_status_uses_selected_ros_distro_without_requiring_group(tmp_path):
    groups = {"small": {"services": ["app"]}}
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(groups=groups))
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["status", "example", "--ros-distro", "jazzy"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert "|jazzy|" in calls.read_text()
    assert calls.read_text().rstrip().endswith(" ps")
