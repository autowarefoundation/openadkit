"""Shared helpers for the openadkit CLI end-to-end tests."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


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
UNREACHABLE_URL = "http://127.0.0.1:1/unreachable"
ZERO_SHA256 = "0" * 64


def host_architecture():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


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


def role_manifest():
    manifest = minimal_manifest()
    manifest["shared"] = ["base"]
    manifest["compose"]["roles"] = {
        "primary": {
            "files": ["compose.primary.yaml"],
            "services": ["app"],
            "resetServices": [],
            "requiredEnv": [],
        },
        "secondary": {
            "files": ["compose.secondary.yaml"],
            "services": ["app"],
            "resetServices": [],
            "requiredEnv": ["ROLE_TOKEN"],
        },
    }
    return manifest


def files_resource(
    url=UNREACHABLE_URL,
    sha256=ZERO_SHA256,
    *,
    name="dataset",
    path="required.txt",
    destination_env="MAP_PATH",
    gpu=False,
    roles=None,
):
    resource = {
        "name": name,
        "kind": "files",
        "destinationEnv": destination_env,
        "files": [{"path": path, "url": url, "sha256": sha256}],
        "requiredFiles": [path],
    }
    if gpu:
        resource["gpu"] = True
    if roles is not None:
        resource["roles"] = roles
    return resource


def zip_resource(url, sha256, *, member="dataset/required.txt", destination_env="MAP_PATH"):
    return {
        "name": "dataset",
        "kind": "zip",
        "destinationEnv": destination_env,
        "expectedRoot": member.split("/", 1)[0],
        "url": url,
        "sha256": sha256,
        "requiredFiles": [member.split("/", 1)[-1]],
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
    for role in (manifest["compose"].get("roles") or {}).values():
        for role_file in role.get("files", []):
            (deployment / role_file).write_text(
                "services:\n  app:\n    image: busybox:1.36.1\n"
            )
    for shared_name in manifest.get("shared", []):
        shared = root / "deployments" / shared_name
        shared.mkdir()
        (shared / "runtime.env").write_text("ROS_DOMAIN_ID=1\n")
        if shared_name == "base":
            (shared / "compose.zenoh.yaml").write_text(
                "services:\n  app:\n    image: busybox:1.36.1\n"
            )
    if manifest["compose"].get("roles"):
        config = deployment / "config"
        config.mkdir(exist_ok=True)
        (config / "zenoh.json5").write_text("{}\n")
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
    compose_ls="[]",
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "docker-calls"
    ls_path = tmp_path / "compose-ls.json"
    ls_path.write_text(compose_ls if compose_ls.endswith("\n") else compose_ls + "\n")
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
        'if [[ "$*" == "compose ls --format json" ]]; then '
        f"cat {json.dumps(str(ls_path))}; exit 0; fi\n"
        'if [[ "$*" == *"config --services"* ]]; then '
        f"printf '%b' {json.dumps(configured)}; fi\n"
        'if [[ "$*" == *"config --quiet"* ]]; then '
        f"exit {config_returncode}; fi\n"
        "exit 0\n",
    )
    return bin_dir, calls


def docker_env(bin_dir, **extra):
    return {"PATH": f"{bin_dir}:{os.environ['PATH']}", **extra}


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


def assert_no_container_mutation(calls):
    text = calls.read_text()
    assert " pull " not in f" {text} "
    assert " up " not in f" {text} "


def write_runtime_state(deployment, *, role=None, gpu=False):
    cache = deployment / ".cache"
    cache.mkdir(exist_ok=True)
    state = {"schemaVersion": 1, "rosDistro": "humble", "gpu": gpu}
    if role is not None:
        state["role"] = role
    (cache / "runtime.json").write_text(json.dumps(state) + "\n")