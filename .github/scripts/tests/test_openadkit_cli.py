import hashlib
import io
import json
import os
import platform
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
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


def gnu_bundle(path, root_name, files):
    staging = path.parent / f"{path.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    root = staging / root_name
    root.mkdir(parents=True)
    for relative, payload in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        if relative == "openadkit":
            destination.chmod(0o755)
    subprocess.run(
        [
            "tar",
            "--format=gnu",
            "--sort=name",
            "-C",
            str(staging),
            "-czf",
            str(path),
            root_name,
        ],
        check=True,
    )
    shutil.rmtree(staging)


def fake_release_curl(bin_dir, release, bundle_name):
    executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "target=\nurl=\n"
        "while (($#)); do\n"
        '  if [[ "$1" == "-o" ]]; then target=$2; shift 2; continue; fi\n'
        '  [[ "$1" == http* ]] && url=$1\n'
        "  shift\n"
        "done\n"
        'case "$url" in\n'
        f'  *release-metadata.json) cp {json.dumps(str(release / "release-metadata.json"))} "$target" ;;\n'
        f'  *{bundle_name}) cp {json.dumps(str(release / bundle_name))} "$target" ;;\n'
        '  *) exit 2 ;;\n'
        "esac\n",
    )


def write_release_metadata(release, version, bundle_name, digest):
    (release / "release-metadata.json").write_text(
        json.dumps(
            {
                "openadkit_version": version,
                "bundles": [{"name": bundle_name, "sha256": digest}],
            }
        )
    )


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
        "install",
        "upgrade",
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
    for command in ("verify", "down", "build"):
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


def finish_release(tmp_path, release, version, bundle_name, bundle, *, digest=None):
    write_release_metadata(
        release,
        version,
        bundle_name,
        digest
        if digest is not None
        else hashlib.sha256(bundle.read_bytes()).hexdigest(),
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake_release_curl(bin_dir, release, bundle_name)
    return bin_dir


def standalone_release(tmp_path, version="v1.2.3", files=None, *, digest=None):
    release = tmp_path / "release"
    release.mkdir()
    root_name = f"openadkit-{version}"
    bundle_name = f"{root_name}.tar.gz"
    bundle = release / bundle_name
    if files is None:
        files = {
            "openadkit": ENTRYPOINT.read_bytes(),
            "openadkit.json": json.dumps(
                {"schemaVersion": 1, "kind": "release", "version": version}
            ).encode(),
            "cli/main.py": b'print("ok")\n',
        }
    gnu_bundle(bundle, root_name, files)
    bin_dir = finish_release(
        tmp_path, release, version, bundle_name, bundle, digest=digest
    )
    return release, bin_dir


def raw_bundle(tmp_path, version, entries):
    release = tmp_path / "release"
    release.mkdir()
    root_name = f"openadkit-{version}"
    bundle_name = f"{root_name}.tar.gz"
    bundle = release / bundle_name
    with tarfile.open(bundle, "w:gz") as archive:
        for entry in entries:
            info = tarfile.TarInfo(f"{root_name}/{entry['name']}")
            if entry["type"] == tarfile.SYMTYPE:
                info.type = tarfile.SYMTYPE
                info.linkname = entry["target"]
                archive.addfile(info)
                continue
            payload = entry["payload"]
            info.size = len(payload)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(payload))
    bin_dir = finish_release(tmp_path, release, version, bundle_name, bundle)
    return release, bin_dir


def test_standalone_install_verifies_bundle_and_installs_launcher(tmp_path):
    _, bin_dir = standalone_release(tmp_path)
    home = tmp_path / "home"
    destination = home / "kit"
    result = subprocess.run(
        [str(ENTRYPOINT), "install", "--destination", str(destination)],
        env=os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    installed = destination / "openadkit-v1.2.3/openadkit"
    assert installed.is_file()
    assert os.access(installed, os.X_OK)
    launcher = home / ".local/bin/openadkit"
    assert launcher.is_symlink()
    assert launcher.resolve() == installed
    assert f"Add {home / '.local/bin'} to PATH" in result.stdout
    assert f"Next: {launcher} setup --verify" in result.stdout
    launched = subprocess.run(
        [str(launcher)],
        env=os.environ | {"HOME": str(home), "PATH": os.environ["PATH"]},
        text=True,
        capture_output=True,
    )
    assert launched.returncode == 0, launched.stderr
    assert launched.stdout.strip() == "ok"


def test_standalone_install_reports_path_guidance(tmp_path):
    _, bin_dir = standalone_release(tmp_path)
    home = tmp_path / "home"
    launcher_dir = home / ".local/bin"
    launcher_dir.mkdir(parents=True)
    result = subprocess.run(
        [str(ENTRYPOINT), "install", "--destination", str(home / "kit")],
        env=os.environ
        | {
            "HOME": str(home),
            "PATH": f"{launcher_dir}:{bin_dir}:{os.environ['PATH']}",
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Next: openadkit setup --verify" in result.stdout
    assert "Add " not in result.stdout


def test_standalone_install_accepts_prerelease_and_stdin(tmp_path):
    version = "v1.2.3-rc.1"
    _, bin_dir = standalone_release(
        tmp_path,
        version=version,
        files={"openadkit": b"#!/usr/bin/env bash\necho installed runtime\n"},
    )
    home = tmp_path / "home"
    destination = home / "kit"
    result = subprocess.run(
        ["bash", "-s", "--", "install", "--version", version, "--destination", str(destination)],
        input=ENTRYPOINT.read_text(),
        env=os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "BASH_SOURCE" not in result.stderr
    assert (destination / f"openadkit-{version}" / "openadkit").is_file()


def test_standalone_install_accepts_hyphenated_prerelease(tmp_path):
    version = "v1.2.3-rc-1"
    _, bin_dir = standalone_release(tmp_path, version=version)
    home = tmp_path / "home"
    result = subprocess.run(
        [
            str(ENTRYPOINT),
            "install",
            "--version",
            version,
            "--destination",
            str(home / "kit"),
        ],
        env=os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert (home / "kit" / f"openadkit-{version}" / "openadkit").is_file()


def test_standalone_install_rejects_checksum_mismatch_and_cleans_up(tmp_path):
    _, bin_dir = standalone_release(
        tmp_path, files={"openadkit": b"#!/usr/bin/env bash\nexit 0\n"}, digest="0" * 64
    )
    home = tmp_path / "home"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = subprocess.run(
        [str(ENTRYPOINT), "install", "--destination", str(home / "kit")],
        env=os.environ
        | {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "TMPDIR": str(scratch),
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "checksum verification failed" in result.stderr
    assert not (home / "kit").exists()
    assert list(scratch.iterdir()) == []


def test_standalone_install_rejects_metadata_version_mismatch(tmp_path):
    _, bin_dir = standalone_release(tmp_path, version="v1.2.3")
    home = tmp_path / "home"
    result = subprocess.run(
        [
            str(ENTRYPOINT),
            "install",
            "--version",
            "v9.9.9",
            "--destination",
            str(home / "kit"),
        ],
        env=os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "release metadata is for v1.2.3, expected v9.9.9" in result.stderr
    assert not (home / "kit").exists()


def test_standalone_install_requires_force_to_replace(tmp_path):
    _, bin_dir = standalone_release(tmp_path)
    home = tmp_path / "home"
    destination = home / "kit"
    env = os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    command = [str(ENTRYPOINT), "install", "--destination", str(destination)]
    first = subprocess.run(command, env=env, text=True, capture_output=True)
    assert first.returncode == 0, first.stderr
    root = destination / "openadkit-v1.2.3"
    (root / "stale").write_text("stale")
    replaced = subprocess.run(command, env=env, text=True, capture_output=True)
    assert replaced.returncode != 0
    assert "already exists; rerun with --force" in replaced.stderr
    assert (root / "stale").is_file()
    forced = subprocess.run(
        [*command, "--force"], env=env, text=True, capture_output=True
    )
    assert forced.returncode == 0, forced.stderr
    assert not (root / "stale").exists()
    assert (root / "openadkit").is_file()


def test_standalone_install_restores_previous_version_when_swap_fails(tmp_path):
    _, bin_dir = standalone_release(tmp_path)
    home = tmp_path / "home"
    destination = home / "kit"
    env = os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    command = [str(ENTRYPOINT), "install", "--destination", str(destination)]
    first = subprocess.run(command, env=env, text=True, capture_output=True)
    assert first.returncode == 0, first.stderr
    root = destination / "openadkit-v1.2.3"
    (root / "marker").write_text("previous")
    real_mv = shutil.which("mv")
    executable(
        bin_dir / "mv",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'target={json.dumps(str(root))}\n'
        'if [[ $# -eq 2 && "$2" == "$target" && "$1" == *".openadkit-stage."* ]]; then\n'
        '  exit 1\n'
        "fi\n"
        f'exec {real_mv} "$@"\n',
    )
    failed = subprocess.run(
        [*command, "--force"], env=env, text=True, capture_output=True
    )
    assert failed.returncode != 0
    assert "could not replace" in failed.stderr
    assert (root / "marker").read_text() == "previous"
    assert (root / "openadkit").is_file()
    leftovers = [
        path.name
        for path in destination.iterdir()
        if path.name.startswith((".openadkit-stage.", ".openadkit-old."))
    ]
    assert leftovers == []


def install_standalone(tmp_path, version):
    base = tmp_path / f"install-{version}"
    base.mkdir()
    _, bin_dir = standalone_release(base, version=version)
    home = tmp_path / "home"
    destination = home / "kit"
    result = subprocess.run(
        [
            str(ENTRYPOINT),
            "install",
            "--version",
            version,
            "--destination",
            str(destination),
        ],
        env=os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return home, destination, bin_dir


def run_installed_upgrade(home, destination, version, bin_dir):
    return subprocess.run(
        [str(destination / f"openadkit-{version}" / "openadkit"), "upgrade"],
        env=os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )


def test_standalone_upgrade_installs_newest_release(tmp_path):
    home, destination, _ = install_standalone(tmp_path, "v1.2.3")
    base = tmp_path / "latest"
    base.mkdir()
    _, latest_bin = standalone_release(base, version="v1.3.0")
    result = run_installed_upgrade(home, destination, "v1.2.3", latest_bin)
    assert result.returncode == 0, result.stderr
    launcher = home / ".local/bin/openadkit"
    assert launcher.resolve() == destination / "openadkit-v1.3.0/openadkit"
    assert (destination / "openadkit-v1.2.3/openadkit").is_file()
    assert "Upgraded v1.2.3 -> v1.3.0" in result.stdout
    assert "Next:" not in result.stdout


def test_standalone_upgrade_reports_up_to_date(tmp_path):
    home, destination, bin_dir = install_standalone(tmp_path, "v1.2.3")
    launcher = home / ".local/bin/openadkit"
    before = launcher.resolve()
    result = run_installed_upgrade(home, destination, "v1.2.3", bin_dir)
    assert result.returncode == 0, result.stderr
    assert "up to date: v1.2.3" in result.stdout
    assert launcher.resolve() == before


@pytest.mark.parametrize(
    ("current", "latest"),
    (
        ("v1.3.0", "v1.2.3"),
        ("v1.4.0-rc.1", "v1.3.0"),
    ),
)
def test_standalone_upgrade_never_downgrades(tmp_path, current, latest):
    home, destination, _ = install_standalone(tmp_path, current)
    base = tmp_path / "latest"
    base.mkdir()
    _, latest_bin = standalone_release(base, version=latest)
    result = run_installed_upgrade(home, destination, current, latest_bin)
    assert result.returncode == 0, result.stderr
    assert "nothing to upgrade" in result.stdout
    launcher = home / ".local/bin/openadkit"
    assert launcher.resolve() == destination / f"openadkit-{current}/openadkit"


def test_standalone_upgrade_promotes_prerelease_to_stable(tmp_path):
    home, destination, _ = install_standalone(tmp_path, "v1.3.0-rc.1")
    base = tmp_path / "latest"
    base.mkdir()
    _, latest_bin = standalone_release(base, version="v1.3.0")
    result = run_installed_upgrade(home, destination, "v1.3.0-rc.1", latest_bin)
    assert result.returncode == 0, result.stderr
    launcher = home / ".local/bin/openadkit"
    assert launcher.resolve() == destination / "openadkit-v1.3.0/openadkit"


def test_standalone_upgrade_reinstalls_after_rollback(tmp_path):
    home, destination, latest_bin = install_standalone(tmp_path, "v1.3.0")
    older = tmp_path / "older"
    older.mkdir()
    _, older_bin = standalone_release(older, version="v1.2.3")
    rollback = subprocess.run(
        [
            str(ENTRYPOINT),
            "install",
            "--version",
            "v1.2.3",
            "--destination",
            str(destination),
        ],
        env=os.environ | {"HOME": str(home), "PATH": f"{older_bin}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert rollback.returncode == 0, rollback.stderr
    assert (home / ".local/bin/openadkit").resolve() == destination / "openadkit-v1.2.3/openadkit"
    result = run_installed_upgrade(home, destination, "v1.2.3", latest_bin)
    assert result.returncode == 0, result.stderr
    assert (home / ".local/bin/openadkit").resolve() == destination / "openadkit-v1.3.0/openadkit"


def test_standalone_rollback_to_kept_version_requires_force(tmp_path):
    home, destination, bin_dir = install_standalone(tmp_path, "v1.3.0")
    base = tmp_path / "latest"
    base.mkdir()
    _, latest_bin = standalone_release(base, version="v1.4.0")
    upgrade = run_installed_upgrade(home, destination, "v1.3.0", latest_bin)
    assert upgrade.returncode == 0, upgrade.stderr
    launcher = home / ".local/bin/openadkit"
    assert launcher.resolve() == destination / "openadkit-v1.4.0/openadkit"
    assert (destination / "openadkit-v1.3.0").is_dir()

    command = [
        str(ENTRYPOINT),
        "install",
        "--version",
        "v1.3.0",
        "--destination",
        str(destination),
    ]
    env = os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    denied = subprocess.run(command, env=env, text=True, capture_output=True)
    assert denied.returncode != 0
    assert "already exists; rerun with --force" in denied.stderr
    assert launcher.resolve() == destination / "openadkit-v1.4.0/openadkit"

    forced = subprocess.run(command + ["--force"], env=env, text=True, capture_output=True)
    assert forced.returncode == 0, forced.stderr
    assert launcher.resolve() == destination / "openadkit-v1.3.0/openadkit"


def test_standalone_upgrade_requires_the_active_installation(tmp_path):
    home, destination, bin_dir = install_standalone(tmp_path, "v1.2.3")
    launcher = home / ".local/bin/openadkit"
    before = launcher.resolve()
    base = tmp_path / "manual"
    base.mkdir()
    release, _ = standalone_release(base, version="v1.3.0")
    extracted = tmp_path / "manual-extract"
    with tarfile.open(release / "openadkit-v1.3.0.tar.gz") as archive:
        archive.extractall(extracted, filter="data")
    result = subprocess.run(
        [str(extracted / "openadkit-v1.3.0" / "openadkit"), "upgrade"],
        env=os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "active installation" in result.stderr
    assert launcher.resolve() == before


def test_standalone_upgrade_rejects_repository_checkout(tmp_path):
    root, _ = runtime_tree(tmp_path)
    result = subprocess.run(
        [str(root / "openadkit"), "upgrade"],
        cwd=root,
        env=os.environ | {"HOME": str(tmp_path / "home")},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "update a source checkout with git pull" in result.stderr


def test_standalone_upgrade_requires_an_install(tmp_path):
    result = subprocess.run(
        ["bash", "-s", "--", "upgrade"],
        input=ENTRYPOINT.read_text(),
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Open AD Kit is not installed" in result.stderr


def test_standalone_install_rejects_symlink_bundle(tmp_path):
    _, bin_dir = raw_bundle(
        tmp_path,
        "v1.2.3",
        (
            {"name": "openadkit", "type": tarfile.REGTYPE, "payload": ENTRYPOINT.read_bytes()},
            {"name": "evil-link", "type": tarfile.SYMTYPE, "target": "/etc/passwd"},
        ),
    )
    home = tmp_path / "home"
    result = subprocess.run(
        [str(ENTRYPOINT), "install", "--destination", str(home / "kit")],
        env=os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "unsupported bundle member: openadkit-v1.2.3/evil-link" in result.stderr
    assert not (home / "kit").exists()


def test_standalone_install_rejects_parent_traversal_bundle(tmp_path):
    _, bin_dir = raw_bundle(
        tmp_path,
        "v1.2.3",
        (
            {"name": "openadkit", "type": tarfile.REGTYPE, "payload": ENTRYPOINT.read_bytes()},
            {"name": "../escape", "type": tarfile.REGTYPE, "payload": b"escape"},
        ),
    )
    home = tmp_path / "home"
    result = subprocess.run(
        [str(ENTRYPOINT), "install", "--destination", str(home / "kit")],
        env=os.environ | {"HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "unsafe bundle member: openadkit-v1.2.3/../escape" in result.stderr
    assert not (home / "kit").exists()


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
    assert re.search(
        r"example\s+intact\s+none\s+Test deployment", result.stdout
    )
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


@pytest.mark.parametrize("command", ("run", "fetch", "validate"))
def test_catalog_command_without_deployment_lists_available(tmp_path, command):
    root, _ = runtime_tree(tmp_path)
    result = run_cli(root, [command])
    assert result.returncode == 2
    assert "error: deployment name required" in result.stderr
    assert f"openadkit {command} <deployment>" in result.stderr
    assert re.search(
        r"example\s+source\s+none\s+Test deployment", result.stdout
    )


def test_run_help_lists_catalog():
    result = subprocess.run(
        [str(ENTRYPOINT), "run", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "planning-simulation" in result.stdout
    assert "--gpu" in result.stdout


@pytest.mark.parametrize("command", ("status", "logs", "stop"))
def test_runtime_command_without_deployment_when_none_running(tmp_path, command):
    root, _ = runtime_tree(tmp_path)
    bin_dir, _ = fake_docker(tmp_path)
    result = run_cli(
        root,
        [command],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "no running deployments"


@pytest.mark.parametrize("command", ("status", "logs", "stop"))
def test_runtime_command_without_deployment_lists_running(tmp_path, command):
    root, _ = runtime_tree(tmp_path)
    bin_dir, _ = fake_docker(
        tmp_path,
        compose_ls='[{"Name":"openadkit-example","Status":"running(1)"}]',
    )
    result = run_cli(
        root,
        [command],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 2
    assert "error: deployment name required" in result.stderr
    assert f"openadkit {command} <deployment>" in result.stderr
    assert re.search(
        r"example\s+source\s+none\s+Test deployment", result.stdout
    )


def test_logs_follow_without_deployment_requires_name(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(
        tmp_path,
        compose_ls='[{"Name":"openadkit-example","Status":"running(1)"}]',
    )
    result = run_cli(
        root,
        ["logs", "--follow"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 2
    assert "error: deployment name required" in result.stderr
    assert "openadkit logs <deployment> --follow" in result.stderr
    assert re.search(
        r"example\s+source\s+none\s+Test deployment", result.stdout
    )
    assert " logs" not in f" {calls.read_text()} "


def test_named_stop_downs_even_when_compose_ls_is_empty(tmp_path):
    root, _ = runtime_tree(tmp_path)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["stop", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert "down --remove-orphans" in calls.read_text()


def test_release_deployment_change_is_marked_modified(tmp_path):
    root, deployment = runtime_tree(tmp_path, release=True)
    (deployment / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.2\n"
    )
    result = run_cli(root, ["list"])
    assert result.returncode == 0, result.stderr
    assert re.search(r"example\s+modified", result.stdout)


def test_release_shared_asset_change_is_marked_modified(tmp_path):
    manifest = minimal_manifest()
    manifest["shared"] = ["base"]
    root, _ = runtime_tree(tmp_path, release=True, manifest=manifest)
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


def test_repository_default_distro_uses_development_image_alias(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["API_IMAGE"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    architecture = _host_architecture()
    assert (
        "humble||"
        f"ghcr.io/autowarefoundation/openadkit:api-{architecture}-humble|"
        "ghcr.io/autowarefoundation/openadkit:"
        f"localization-mapping-{architecture}-humble|"
        in calls.read_text()
    )


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
    architecture = _host_architecture()
    assert (
        "jazzy|jazzy-value|"
        f"ghcr.io/autowarefoundation/openadkit:api-{architecture}-jazzy|"
        "ghcr.io/autowarefoundation/openadkit:"
        f"localization-mapping-{architecture}-jazzy|"
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


def test_release_ignores_env_file_component_images(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["requiredEnv"] = ["API_IMAGE"]
    root, deployment = runtime_tree(tmp_path, release=True, manifest=manifest)
    kit_path = root / "openadkit.json"
    current = json.loads(kit_path.read_text())
    exact = f"registry.example/api@sha256:{'a' * 64}"
    current["images"]["humble"]["api"] = exact
    kit_path.write_text(json.dumps(current))
    (deployment / "config.env").write_text(
        (deployment / "config.env").read_text() + "API_IMAGE=registry.example/from-config\n"
    )
    (deployment / "config.local.env").write_text("API_IMAGE=registry.example/from-local\n")
    bin_dir, calls = fake_docker(tmp_path)
    result = run_cli(
        root,
        ["validate", "example"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    assert calls.read_text().split("|", 5)[2] == exact


def test_gpu_component_image_injected_only_with_gpu(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    path_env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    expected = (
        "ghcr.io/autowarefoundation/openadkit:"
        f"sensing-perception-cuda-{_host_architecture()}-humble"
    )

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


def test_operational_commands_ignore_previous_gpu_selection(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, deployment = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, calls = fake_docker(tmp_path)
    path_env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}

    result = run_cli(root, ["run", "example", "--gpu", "--pull", "never"], env=path_env)
    assert result.returncode == 0, result.stderr
    # Operational commands are stateless: run must not persist a selection.
    assert not (deployment / ".cache").exists()

    calls.write_text("")
    result = run_cli(root, ["status", "example"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert "docker-compose.gpu.yaml" not in calls.read_text()
    assert calls.read_text().rstrip().endswith(" ps")


def test_operational_commands_work_when_release_lacks_default_distro_images(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    document = json.loads((root / "openadkit.json").read_text())
    del document["images"]["humble"]
    (root / "openadkit.json").write_text(json.dumps(document))
    bin_dir, calls = fake_docker(tmp_path)
    path_env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}

    result = run_cli(root, ["status", "example"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert calls.read_text().rstrip().endswith(" ps")


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
    assert re.search(r"planning-simulation\s+source\s+none\s+", result.stdout)
    assert re.search(r"logging-simulation\s+source\s+optional\s+", result.stdout)
    assert re.search(r"scenario-simulation\s+source\s+none\s+", result.stdout)
    assert re.search(r"carla-simulation\s+source\s+required\s+", result.stdout)
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


def test_validate_data_reports_missing_incomplete_and_ok(tmp_path):
    resource = {
        "name": "sample-map",
        "kind": "files",
        "destinationEnv": "MAP_PATH",
        "files": [
            {
                "path": "lanelet2_map.osm",
                "url": "http://example.invalid/lanelet2_map.osm",
                "sha256": "0" * 64,
            }
        ],
        "requiredFiles": ["lanelet2_map.osm"],
    }
    manifest = minimal_manifest(data=[resource])
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    bin_dir, _ = fake_docker(tmp_path)
    path_env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    target = root.parent / "home" / "data" / "example"

    result = run_cli(root, ["validate", "example", "--data"], env=path_env)
    assert result.returncode == 1, result.stdout
    assert "valid: example (humble, cpu)" in result.stdout
    assert "data: sample-map missing" in result.stdout

    target.mkdir(parents=True)
    result = run_cli(root, ["validate", "example", "--data"], env=path_env)
    assert result.returncode == 1, result.stdout
    assert "data: sample-map incomplete" in result.stdout

    (target / "lanelet2_map.osm").write_text("map\n")
    result = run_cli(root, ["validate", "example", "--data"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert "data: sample-map ok" in result.stdout

    result = run_cli(root, ["validate", "example"], env=path_env)
    assert result.returncode == 0, result.stderr
    assert "data:" not in result.stdout


def test_validate_data_respects_gpu_selection(tmp_path):
    resources = [
        {
            "name": "cpu-model",
            "kind": "files",
            "destinationEnv": "MAP_PATH",
            "files": [
                {
                    "path": "model.bin",
                    "url": "http://example.invalid/model.bin",
                    "sha256": "0" * 64,
                }
            ],
            "requiredFiles": ["model.bin"],
        },
        {
            "name": "gpu-model",
            "kind": "files",
            "destinationEnv": "GPU_MODEL_PATH",
            "gpu": True,
            "files": [
                {
                    "path": "model.onnx",
                    "url": "http://example.invalid/model.onnx",
                    "sha256": "1" * 64,
                }
            ],
            "requiredFiles": ["model.onnx"],
        },
    ]
    manifest = minimal_manifest(data=resources)
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    (root / "deployments/example/config.env").write_text(
        "MAP_PATH=$HOME/data/example\nGPU_MODEL_PATH=$HOME/data/gpu-model\n"
    )
    bin_dir, _ = fake_docker(tmp_path)
    path_env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}

    result = run_cli(root, ["validate", "example", "--data"], env=path_env)
    assert result.returncode == 1, result.stdout
    assert "data: cpu-model missing" in result.stdout
    assert "gpu-model" not in result.stdout

    result = run_cli(root, ["validate", "example", "--data", "--gpu"], env=path_env)
    assert result.returncode == 1, result.stdout
    assert "data: gpu-model missing" in result.stdout


def test_usage_errors_exit_with_code_two():
    for command in ("install", "upgrade", "setup"):
        result = subprocess.run(
            [str(ENTRYPOINT), command, "--nope"],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 2, (command, result.stderr)


def test_version_flag_reports_bundle():
    result = subprocess.run(
        [str(ENTRYPOINT), "--version"], text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Open AD Kit ")


def test_entrypoint_help_documents_handled_command_flags():
    checks = {
        "install": ("--version", "--destination", "--force"),
        "setup": ("--gpu", "--verify"),
    }
    for command, flags in checks.items():
        result = subprocess.run(
            [str(ENTRYPOINT), command, "--help"],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, (command, result.stderr)
        for flag in flags:
            assert flag in result.stdout, (command, flag)


def test_capture_process_surfaces_command_stderr():
    sys.path.insert(0, str(ROOT / "cli"))
    import compose as openadkit_compose

    with pytest.raises(openadkit_compose.OpenADKitError) as error:
        openadkit_compose.capture_process(
            ["bash", "-c", "echo 'boom detail' >&2; exit 3"]
        )
    assert "exit code 3" in str(error.value)
    assert "boom detail" in str(error.value)
