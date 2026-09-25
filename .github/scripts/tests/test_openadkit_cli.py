import hashlib
import io
import json
import os
import platform
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "cli"))

import compose as cli_compose  # noqa: E402
import manifest as cli_manifest  # noqa: E402

ENTRYPOINT = ROOT / "openadkit"
PREFIX = "ghcr.io/autowarefoundation/openadkit"
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
ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
    platform.machine().lower(), platform.machine().lower()
)
UNREACHABLE = "http://127.0.0.1:1/unreachable"
RUNNING = '[{"Name":"openadkit-example","Status":"running(1)"}]'
CLEAN_ENV = "MAP_PATH=$HOME/data/example\nGPU_MODEL_PATH=$HOME/data/gpu-model\n"


# --- Runtime trees -----------------------------------------------------------


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


def gpu_manifest(data=None):
    manifest = minimal_manifest(data=data)
    manifest["requirements"]["gpu"] = "optional"
    manifest["compose"]["gpuFiles"] = ["docker-compose.gpu.yaml"]
    return manifest


def files_resource(
    name="dataset", env="MAP_PATH", path="required.txt", url=UNREACHABLE,
    sha256="0" * 64, **extra,
):
    return {
        "name": name,
        "kind": "files",
        "destinationEnv": env,
        "files": [{"path": path, "url": url, "sha256": sha256}],
        "requiredFiles": [path],
        **extra,
    }


def clean_manifest():
    return gpu_manifest(
        [
            files_resource("sample-map", path="lanelet2_map.osm"),
            files_resource(
                "gpu-model", env="GPU_MODEL_PATH", path="model.onnx",
                sha256="1" * 64, gpu=True,
            ),
        ]
    )


def kit_document(root, *, release, manifest):
    deployments = {"example": {"path": "deployments/example"}}
    document = {
        "schemaVersion": 1,
        "kind": "release" if release else "repository",
        "defaultRosDistro": "humble",
        "componentImages": COMPONENT_IMAGES,
        "deployments": deployments,
    }
    if not release:
        document["imagePrefixComponent"] = PREFIX
        return document
    deployments["example"]["checksum"] = cli_manifest.deployment_checksum(
        root / "deployments/example"
    )
    document["version"] = "v1.2.3"
    document["images"] = {
        distro: {
            target: f"registry.example/{target}:{distro}@sha256:{'1' * 64}"
            for target in COMPONENT_IMAGES.values()
        }
        for distro in ("humble", "jazzy")
    }
    document["shared"] = {
        name: cli_manifest.deployment_checksum(root / "deployments" / name)
        for name in manifest.get("shared", [])
    }
    return document


def runtime_tree(
    tmp_path, *, release=False, manifest=None,
    config_env="MAP_PATH=$HOME/data/example\nREMOTE_PASSWORD=default\n",
):
    root = tmp_path / "openadkit-test"
    root.mkdir(parents=True)
    shutil.copy2(ENTRYPOINT, root / "openadkit")
    shutil.copytree(ROOT / "cli", root / "cli")
    deployment = root / "deployments/example"
    deployment.mkdir(parents=True)
    manifest = manifest or minimal_manifest()
    (deployment / "deployment.json").write_text(json.dumps(manifest))
    (deployment / "config.env").write_text(config_env)
    (deployment / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: busybox:1.36.1\n"
    )
    for gpu_file in manifest["compose"]["gpuFiles"]:
        (deployment / gpu_file).write_text(
            "services:\n  app:\n    environment:\n      GPU: 'true'\n"
        )
        (deployment / "config.gpu.env").write_text("GPU_MODE=true\n")
    for shared_name in manifest.get("shared", []):
        shared = root / "deployments" / shared_name
        shared.mkdir()
        (shared / "runtime.env").write_text("ROS_DOMAIN_ID=1\n")
    (root / "openadkit.json").write_text(
        json.dumps(kit_document(root, release=release, manifest=manifest))
    )
    return root, deployment


def edit_kit(root, change):
    path = root / "openadkit.json"
    kit = json.loads(path.read_text())
    change(kit)
    path.write_text(json.dumps(kit))


def fake_docker(
    tmp_path, *, configured="app\n", daemon_returncode=0, config_returncode=0,
    runtimes='{"nvidia": {}}', compose_ls="[]", config_json='{"services": {}}',
    container_ids="", inspect="",
):
    """Record docker calls as distro|value|api|localization|gpu-image|args."""
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "docker-calls"
    ids = tmp_path / "docker-ids"
    ls_path = tmp_path / "compose-ls.json"
    ls_path.write_text(compose_ls + "\n")
    config_path = tmp_path / "compose-config.json"
    config_path.write_text(config_json + "\n")
    responses = {
        '*"config --format json"*': f"cat {json.dumps(str(config_path))}; exit 0",
        '"info"': f"exit {daemon_returncode}",
        '"info --format {{json .Runtimes}}"': f"printf '%s\\n' {json.dumps(runtimes)}; exit 0",
        '"compose ls --format json"': f"cat {json.dumps(str(ls_path))}; exit 0",
        '*"config --services"*': f"printf '%b' {json.dumps(configured)}",
        '*"config --quiet"*': f"exit {config_returncode}",
        '*"ps --all --quiet"*': f"printf '%b' {json.dumps(container_ids)}",
        'inspect" "*': f"printf '%b' {json.dumps(inspect)}",
    }
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'printf "%s|%s|%s|%s|%s|%s\\n" "${ROS_DISTRO:-}" "${DISTRO_VALUE:-}" '
        '"${API_IMAGE:-}" "${LOCALIZATION_MAPPING_IMAGE:-}" '
        f'"${{SENSING_PERCEPTION_GPU_IMAGE:-}}" "$*" >> {json.dumps(str(calls))}\n'
        'printf "%s:%s\\n" "${OPENADKIT_UID:-}" "${OPENADKIT_GID:-}" '
        f">> {json.dumps(str(ids))}\n"
        + "".join(
            f'if [[ "$*" == {pattern} ]]; then {action}; fi\n'
            for pattern, action in responses.items()
        )
        + "exit 0\n",
    )
    return bin_dir, calls


def run_cli(root, *args, **env):
    """Run the tree's entrypoint; a fake docker in <tmp>/bin comes first on PATH."""
    command_env = os.environ | {"HOME": str(root.parent / "home")}
    bin_dir = root.parent / "bin"
    if bin_dir.is_dir():
        command_env["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
    command_env.update(env)
    Path(command_env["HOME"]).mkdir(exist_ok=True)
    return subprocess.run(
        [str(root / "openadkit"), *args],
        cwd=root, env=command_env, text=True, capture_output=True,
    )


def entry(*args, **kwargs):
    return subprocess.run(
        [str(ENTRYPOINT), *args], text=True, capture_output=True, **kwargs
    )


def distro_line(distro, value=""):
    return (
        f"{distro}|{value}|{PREFIX}:api-{ARCH}-{distro}|"
        f"{PREFIX}:localization-mapping-{ARCH}-{distro}|"
    )


def started_nothing(calls):
    text = f" {calls.read_text()} " if calls.exists() else ""
    return " pull " not in text and " up " not in text


# --- Release installs --------------------------------------------------------


def standalone_release(base, version="v1.2.3", files=None, *, digest=None, entries=None):
    """Publish a release bundle and a curl that serves it from <base>/bin."""
    release = base / "release"
    release.mkdir()
    root_name = f"openadkit-{version}"
    bundle_name = f"{root_name}.tar.gz"
    bundle = release / bundle_name
    if entries is not None:
        with tarfile.open(bundle, "w:gz") as archive:
            for name, member in entries:
                info = tarfile.TarInfo(f"{root_name}/{name}")
                if isinstance(member, bytes):
                    info.size, info.mode = len(member), 0o755
                    archive.addfile(info, io.BytesIO(member))
                else:
                    info.type, info.linkname = tarfile.SYMTYPE, member.target
                    archive.addfile(info)
    else:
        files = files or {
            "openadkit": ENTRYPOINT.read_bytes(),
            "openadkit.json": json.dumps(
                {"schemaVersion": 1, "kind": "release", "version": version}
            ).encode(),
            "cli/main.py": b'print("ok")\n',
        }
        staging = base / "staging"
        for relative, payload in files.items():
            destination = staging / root_name / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            if relative == "openadkit":
                destination.chmod(0o755)
        subprocess.run(
            ["tar", "--format=gnu", "--sort=name", "-C", str(staging), "-czf",
             str(bundle), root_name],
            check=True,
        )
    (release / "release-metadata.json").write_text(
        json.dumps(
            {
                "openadkit_version": version,
                "bundles": [
                    {
                        "name": bundle_name,
                        "sha256": digest or hashlib.sha256(bundle.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
    )
    bin_dir = base / "bin"
    executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\nset -euo pipefail\ntarget=\nurl=\n"
        "while (($#)); do\n"
        '  if [[ "$1" == "-o" ]]; then target=$2; shift 2; continue; fi\n'
        '  [[ "$1" == http* ]] && url=$1\n'
        "  shift\n"
        "done\n"
        'case "$url" in\n'
        f'  *release-metadata.json) cp {json.dumps(str(release / "release-metadata.json"))} "$target" ;;\n'
        f'  *{bundle_name}) cp {json.dumps(str(bundle))} "$target" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
    )
    return release, bin_dir


class Symlink:
    def __init__(self, target):
        self.target = target


def release_bin(tmp_path, version):
    base = tmp_path / f"release-{version}"
    base.mkdir()
    return standalone_release(base, version)[1]


def run_with(command, home, bin_dir=None, **kwargs):
    env = os.environ | {"HOME": str(home)}
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
    env.update(kwargs.pop("env", {}))
    return subprocess.run(
        [str(part) for part in command], env=env, text=True, capture_output=True,
        **kwargs,
    )


def install(home, bin_dir, *args, **kwargs):
    return run_with(
        [ENTRYPOINT, "install", "--destination", home / "kit", *args],
        home, bin_dir, **kwargs,
    )


def installed(home, version):
    return home / "kit" / f"openadkit-{version}" / "openadkit"


def launcher(home):
    return home / ".local/bin/openadkit"


def install_standalone(tmp_path, version):
    home = tmp_path / "home"
    bin_dir = release_bin(tmp_path, version)
    result = install(home, bin_dir, "--version", version)
    assert result.returncode == 0, result.stderr
    return home, bin_dir


def idle_docker(tmp_path, projects="[]"):
    bin_dir = tmp_path / "idle-docker"
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == "compose ls --format json" ]]; then '
        f"printf '%s\\n' {json.dumps(projects)}; fi\n",
    )
    return bin_dir


def extracted_launcher(tmp_path, version):
    """A release unpacked by hand, not the active installation."""
    base = tmp_path / "manual"
    base.mkdir()
    release, _ = standalone_release(base, version)
    with tarfile.open(release / f"openadkit-{version}.tar.gz") as archive:
        archive.extractall(base / "extract", filter="data")
    return base / "extract" / f"openadkit-{version}" / "openadkit"


# --- Command surface ---------------------------------------------------------


def test_top_level_help_and_usage():
    result = entry("--help")
    for command in (
        "install", "upgrade", "setup", "uninstall", "list", "version", "validate",
        "fetch", "run", "clean", "status", "logs", "stop",
    ):
        assert command in result.stdout
    for command in ("verify", "down", "build"):
        assert f"  {command} " not in result.stdout
    assert entry("data").returncode != 0
    bare = entry()
    assert bare.returncode == 2
    assert "examples:" in bare.stdout
    version = entry("--version")
    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith("Open AD Kit ")


@pytest.mark.parametrize(
    ("command", "present", "absent"),
    [
        ("install", ("--version", "--destination", "--force"), ()),
        ("upgrade", ("--check",), ()),
        ("setup", ("--gpu", "--verify"), ()),
        ("uninstall", ("--all",), ()),
        (
            "run",
            ("planning-simulation", "--gpu", "--ros-distro", "--force",
             "replace existing data", "image pull policy", "GPU compose overlay"),
            (),
        ),
        ("validate", ("--ros-distro",), ()),
        ("fetch", ("--ros-distro", "--force"), ("--gpu",)),
        ("status", (), ("--ros-distro", "--gpu")),
        ("logs", (), ("--ros-distro", "--gpu")),
        ("stop", (), ("--ros-distro", "--gpu")),
    ],
)
def test_command_help(command, present, absent):
    result = entry(command, "--help")
    assert result.returncode == 0, result.stderr
    assert [flag for flag in present if flag not in result.stdout] == []
    assert [flag for flag in absent if flag in result.stdout] == []


@pytest.mark.parametrize("command", ("install", "upgrade", "setup", "uninstall"))
def test_unknown_option_is_a_usage_error(command):
    assert entry(command, "--nope").returncode == 2


# --- Install, upgrade, uninstall ---------------------------------------------


def test_install_verifies_bundle_and_installs_launcher(tmp_path):
    _, bin_dir = standalone_release(tmp_path)
    home = tmp_path / "home"
    result = install(home, bin_dir)
    assert result.returncode == 0, result.stderr
    assert os.access(installed(home, "v1.2.3"), os.X_OK)
    assert launcher(home).is_symlink()
    assert launcher(home).resolve() == installed(home, "v1.2.3")
    assert f"Add {home / '.local/bin'} to PATH" in result.stdout
    assert f"Next: {launcher(home)} setup --verify" in result.stdout
    launched = run_with([launcher(home)], home)
    assert launched.returncode == 0, launched.stderr
    assert launched.stdout.strip() == "ok"

    # With the launcher directory already on PATH, the hints are shorter.
    (home / "kit").rename(tmp_path / "old-kit")
    launcher(home).unlink()
    result = install(
        home, bin_dir, env={"PATH": f"{home / '.local/bin'}:{bin_dir}:{os.environ['PATH']}"}
    )
    assert result.returncode == 0, result.stderr
    assert "Next: openadkit setup --verify" in result.stdout
    assert "Add " not in result.stdout


@pytest.mark.parametrize("version", ("v1.2.3-rc.1", "v1.2.3-rc-1"))
def test_install_from_stdin_accepts_prereleases(tmp_path, version):
    _, bin_dir = standalone_release(
        tmp_path, version, files={"openadkit": b"#!/usr/bin/env bash\necho ok\n"}
    )
    home = tmp_path / "home"
    result = run_with(
        ["bash", "-s", "--", "install", "--version", version, "--destination", home / "kit"],
        home, bin_dir, input=ENTRYPOINT.read_text(),
    )
    assert result.returncode == 0, result.stderr
    assert "BASH_SOURCE" not in result.stderr
    assert installed(home, version).is_file()


def test_install_rejects_checksum_mismatch_and_cleans_up(tmp_path):
    _, bin_dir = standalone_release(tmp_path, digest="0" * 64)
    home = tmp_path / "home"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = install(home, bin_dir, env={"TMPDIR": str(scratch)})
    assert result.returncode != 0
    assert "checksum verification failed" in result.stderr
    assert not (home / "kit").exists()
    assert list(scratch.iterdir()) == []


def test_install_rejects_metadata_version_mismatch(tmp_path):
    _, bin_dir = standalone_release(tmp_path)
    home = tmp_path / "home"
    result = install(home, bin_dir, "--version", "v9.9.9")
    assert result.returncode != 0
    assert "release metadata is for v1.2.3, expected v9.9.9" in result.stderr
    assert not (home / "kit").exists()


@pytest.mark.parametrize(
    ("member", "message"),
    [
        (("evil-link", Symlink("/etc/passwd")), "unsupported bundle member: openadkit-v1.2.3/evil-link"),
        (("../escape", b"escape"), "unsafe bundle member: openadkit-v1.2.3/../escape"),
    ],
)
def test_install_rejects_unsafe_bundle_members(tmp_path, member, message):
    _, bin_dir = standalone_release(
        tmp_path, entries=[("openadkit", ENTRYPOINT.read_bytes()), member]
    )
    home = tmp_path / "home"
    result = install(home, bin_dir)
    assert result.returncode != 0
    assert message in result.stderr
    assert not (home / "kit").exists()


def test_install_restores_previous_version_when_swap_fails(tmp_path):
    home, bin_dir = install_standalone(tmp_path, "v1.2.3")
    root = installed(home, "v1.2.3").parent
    (root / "marker").write_text("previous")
    executable(
        bin_dir / "mv",
        "#!/usr/bin/env bash\n"
        f'if [[ $# -eq 2 && "$2" == {json.dumps(str(root))} && "$1" == *".openadkit-stage."* ]]; then\n'
        "  exit 1\n"
        "fi\n"
        f'exec {shutil.which("mv")} "$@"\n',
    )
    failed = install(home, bin_dir, "--version", "v1.2.3", "--force")
    assert failed.returncode != 0
    assert "could not replace" in failed.stderr
    assert (root / "marker").read_text() == "previous"
    assert (root / "openadkit").is_file()
    assert not [
        path for path in (home / "kit").iterdir()
        if path.name.startswith((".openadkit-stage.", ".openadkit-old."))
    ]


@pytest.mark.parametrize(("current", "latest"), [("v1.2.3", "v1.3.0"), ("v1.3.0-rc.1", "v1.3.0")])
def test_upgrade_installs_newer_release_and_keeps_the_old(tmp_path, current, latest):
    home, _ = install_standalone(tmp_path, current)
    result = run_with([installed(home, current), "upgrade"], home, release_bin(tmp_path, latest))
    assert result.returncode == 0, result.stderr
    assert launcher(home).resolve() == installed(home, latest)
    assert installed(home, current).is_file()
    assert f"Upgraded {current} -> {latest}" in result.stdout
    assert "Next:" not in result.stdout


@pytest.mark.parametrize(("current", "latest"), [("v1.3.0", "v1.2.3"), ("v1.4.0-rc.1", "v1.3.0")])
def test_upgrade_never_downgrades(tmp_path, current, latest):
    home, _ = install_standalone(tmp_path, current)
    result = run_with([installed(home, current), "upgrade"], home, release_bin(tmp_path, latest))
    assert result.returncode == 0, result.stderr
    assert "nothing to upgrade" in result.stdout
    assert launcher(home).resolve() == installed(home, current)


@pytest.mark.parametrize("args", (("upgrade",), ("upgrade", "--check")))
def test_upgrade_reports_up_to_date(tmp_path, args):
    home, bin_dir = install_standalone(tmp_path, "v1.2.3")
    result = run_with([installed(home, "v1.2.3"), *args], home, bin_dir)
    assert result.returncode == 0, result.stderr
    assert "up to date: v1.2.3" in result.stdout
    assert launcher(home).resolve() == installed(home, "v1.2.3")


def test_upgrade_check_reports_available_without_installing(tmp_path):
    home, _ = install_standalone(tmp_path, "v1.2.3")
    result = run_with(
        [installed(home, "v1.2.3"), "upgrade", "--check"], home, release_bin(tmp_path, "v1.3.0")
    )
    assert result.returncode == 0, result.stderr
    assert "Upgrade available: v1.2.3 -> v1.3.0" in result.stdout
    assert not installed(home, "v1.3.0").exists()
    assert launcher(home).resolve() == installed(home, "v1.2.3")


def test_rollback_to_a_kept_version_requires_force(tmp_path):
    home, old_bin = install_standalone(tmp_path, "v1.3.0")
    new_bin = release_bin(tmp_path, "v1.4.0")
    assert run_with([installed(home, "v1.3.0"), "upgrade"], home, new_bin).returncode == 0
    assert launcher(home).resolve() == installed(home, "v1.4.0")
    (installed(home, "v1.3.0").parent / "stale").write_text("stale")

    denied = install(home, old_bin, "--version", "v1.3.0")
    assert denied.returncode != 0
    assert "already exists; rerun with --force" in denied.stderr
    assert launcher(home).resolve() == installed(home, "v1.4.0")

    forced = install(home, old_bin, "--version", "v1.3.0", "--force")
    assert forced.returncode == 0, forced.stderr
    assert launcher(home).resolve() == installed(home, "v1.3.0")
    assert not (installed(home, "v1.3.0").parent / "stale").exists()

    # upgrade moves the launcher forward again after a rollback.
    upgraded = run_with([installed(home, "v1.3.0"), "upgrade"], home, new_bin)
    assert upgraded.returncode == 0, upgraded.stderr
    assert launcher(home).resolve() == installed(home, "v1.4.0")


@pytest.mark.parametrize(("args", "keeps_old"), [((), True), (("--all",), False)])
def test_uninstall_removes_active_release_and_launcher(tmp_path, args, keeps_old):
    home, _ = install_standalone(tmp_path, "v1.2.3")
    new_bin = release_bin(tmp_path, "v1.3.0")
    assert run_with([installed(home, "v1.2.3"), "upgrade"], home, new_bin).returncode == 0
    result = run_with(
        [installed(home, "v1.3.0"), "uninstall", *args], home, idle_docker(tmp_path)
    )
    assert result.returncode == 0, result.stderr
    assert not installed(home, "v1.3.0").exists()
    assert installed(home, "v1.2.3").exists() is keeps_old
    assert not launcher(home).exists()


def test_uninstall_refuses_while_a_deployment_is_running(tmp_path):
    home, _ = install_standalone(tmp_path, "v1.2.3")
    docker = idle_docker(
        tmp_path, '[{"Name":"openadkit-planning-simulation","Status":"running(1)"}]'
    )
    result = run_with([installed(home, "v1.2.3"), "uninstall"], home, docker)
    assert result.returncode != 0
    assert "stop running deployments before uninstall" in result.stderr
    assert "planning-simulation" in result.stderr
    assert installed(home, "v1.2.3").is_file()
    assert launcher(home).is_symlink()


def test_uninstall_rejects_non_symlink_launcher(tmp_path):
    home, _ = install_standalone(tmp_path, "v1.2.3")
    launcher(home).unlink()
    launcher(home).write_text("#!/usr/bin/env bash\nexit 0\n")
    result = run_with([installed(home, "v1.2.3"), "uninstall"], home)
    assert result.returncode != 0
    assert "refusing to remove non-symlink launcher" in result.stderr
    assert installed(home, "v1.2.3").is_file()


@pytest.mark.parametrize(
    ("command", "message"),
    [("upgrade", "active installation"), ("uninstall", "active installation is not")],
)
def test_lifecycle_commands_act_only_on_the_active_install(tmp_path, command, message):
    home, bin_dir = install_standalone(tmp_path, "v1.2.3")
    result = run_with([extracted_launcher(tmp_path, "v1.3.0"), command], home, bin_dir)
    assert result.returncode != 0
    assert message in result.stderr
    assert launcher(home).resolve() == installed(home, "v1.2.3")


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("upgrade", "update a source checkout with git pull"),
        ("uninstall", "uninstall is for release installs"),
    ],
)
def test_lifecycle_commands_reject_source_checkouts(tmp_path, command, message):
    root, _ = runtime_tree(tmp_path)
    result = run_cli(root, command)
    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.parametrize("command", ("upgrade", "uninstall"))
def test_lifecycle_commands_require_an_install(command):
    result = subprocess.run(
        ["bash", "-s", "--", command], input=ENTRYPOINT.read_text(),
        text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "Open AD Kit is not installed" in result.stderr


# --- Catalog and manifests ---------------------------------------------------


def test_version_reports_repository_and_release(tmp_path):
    repo, _ = runtime_tree(tmp_path / "repo")
    release, _ = runtime_tree(tmp_path / "release", release=True)
    assert (repo / "openadkit").read_bytes() == (release / "openadkit").read_bytes()
    assert run_cli(repo, "version").stdout.startswith("Open AD Kit development")
    assert run_cli(release, "version").stdout.startswith("Open AD Kit v1.2.3")
    for root, bundle, version in ((repo, "repository", None), (release, "release", "v1.2.3")):
        payload = json.loads(run_cli(root, "version", "--json").stdout)
        assert payload["schemaVersion"] == 1
        assert (payload["bundle"], payload["version"], payload["commit"]) == (bundle, version, None)


def test_list_uses_bundle_inventory_only(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    custom = root / "deployments/custom"
    custom.mkdir()
    (custom / "deployment.json").write_text(json.dumps(minimal_manifest("custom")))
    result = run_cli(root, "list")
    assert result.returncode == 0, result.stderr
    assert re.search(r"example\s+intact\s+none\s+Test deployment", result.stdout)
    assert "custom" not in result.stdout


def test_list_json_output(tmp_path):
    root, _ = runtime_tree(tmp_path)
    catalog = [
        {"name": "example", "kind": "source", "gpu": "none", "description": "Test deployment"}
    ]
    result = run_cli(root, "list", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"schemaVersion": 1, "deployments": catalog}
    # A missing deployment name still prints parseable JSON.
    result = run_cli(root, "validate", "--json")
    assert result.returncode == 2
    assert json.loads(result.stdout)["deployments"] == catalog
    assert "deployment name required" in result.stderr


def test_repository_catalog_matches_the_deployments():
    result = entry("list", cwd=ROOT, check=True)
    for name, gpu in (
        ("planning-simulation", "none"), ("logging-simulation", "optional"),
        ("scenario-simulation", "none"), ("carla-simulation", "required"),
    ):
        assert re.search(rf"{name}\s+source\s+{gpu}\s+", result.stdout)
    assert "zenoh" not in result.stdout
    carla = entry("validate", "carla-simulation", cwd=ROOT)
    assert carla.returncode != 0
    if ARCH == "amd64":
        assert "requires --gpu" in carla.stderr
        jazzy = entry("validate", "carla-simulation", "--gpu", "--ros-distro", "jazzy", cwd=ROOT)
        assert "does not support ROS distro jazzy" in jazzy.stderr


def test_unknown_deployment_is_rejected(tmp_path):
    root, _ = runtime_tree(tmp_path)
    result = run_cli(root, "run", "custom")
    assert result.returncode != 0
    assert "unknown deployment: custom" in result.stderr
    assert "available: example" in result.stderr


@pytest.mark.parametrize("command", ("run", "fetch", "validate", "clean"))
def test_catalog_command_without_deployment_lists_available(tmp_path, command):
    root, _ = runtime_tree(tmp_path)
    result = run_cli(root, command)
    assert result.returncode == 2
    assert "error: deployment name required" in result.stderr
    assert f"openadkit {command} <deployment>" in result.stderr
    assert re.search(r"example\s+source\s+none\s+Test deployment", result.stdout)


@pytest.mark.parametrize("command", ("status", "logs", "stop"))
def test_runtime_command_without_deployment(tmp_path, command):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path)
    result = run_cli(root, command)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "no running deployments"

    fake_docker(tmp_path, compose_ls=RUNNING)
    result = run_cli(root, command)
    assert result.returncode == 2
    assert "error: deployment name required" in result.stderr
    assert f"openadkit {command} <deployment>" in result.stderr
    assert re.search(r"example\s+source\s+none\s+Test deployment", result.stdout)


def test_logs_follow_without_deployment_requires_name(tmp_path):
    root, _ = runtime_tree(tmp_path)
    _, calls = fake_docker(tmp_path, compose_ls=RUNNING)
    result = run_cli(root, "logs", "--follow")
    assert result.returncode == 2
    assert "openadkit logs <deployment> --follow" in result.stderr
    assert " logs" not in f" {calls.read_text()} "


@pytest.mark.parametrize("changed", ("deployments/example/docker-compose.yaml", "deployments/shared/runtime.env"))
def test_changed_release_files_mark_the_deployment_modified(tmp_path, changed):
    manifest = minimal_manifest()
    manifest["shared"] = ["shared"]
    root, _ = runtime_tree(tmp_path, release=True, manifest=manifest)
    with (root / changed).open("a") as output:
        output.write("# edited\n")
    result = run_cli(root, "list")
    assert result.returncode == 0, result.stderr
    assert re.search(r"example\s+modified", result.stdout)


def test_modified_release_warns_but_still_runs(tmp_path):
    root, deployment = runtime_tree(tmp_path, release=True)
    (deployment / "docker-compose.yaml").write_text("services:\n  app:\n    image: busybox:1.36.2\n")
    fake_docker(tmp_path)
    result = run_cli(root, "run", "example", "--pull", "never")
    assert result.returncode == 0, result.stderr
    assert "has been modified from this release" in result.stderr
    assert "running: example" in result.stdout


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda text: text.replace('"name": "example"', '"name": "example", "name": "other"'), "duplicate JSON key"),
        (lambda text: text.replace('"docker-compose.yaml"', '"../outside.yaml"'), "safe relative path"),
        # The Compose project owns the service set; the manifest has no list.
        (lambda text: text.replace('"profiles"', '"services": ["app"], "profiles"'), "unknown compose field(s): services"),
    ],
)
def test_invalid_manifest_is_listed_with_the_reason(tmp_path, change, message):
    root, deployment = runtime_tree(tmp_path)
    manifest = deployment / "deployment.json"
    manifest.write_text(change(manifest.read_text()))
    result = run_cli(root, "list")
    assert result.returncode == 0
    assert message in result.stdout


def test_gpu_overlay_requires_gpu_env(tmp_path):
    root, deployment = runtime_tree(tmp_path, manifest=gpu_manifest())
    (deployment / "config.gpu.env").unlink()
    result = run_cli(root, "validate", "example")
    assert result.returncode == 1
    assert "GPU environment file" in result.stderr


def test_deployment_checksum_ignores_runtime_output(tmp_path):
    (tmp_path / "config.env").write_text("x=1\n")
    (tmp_path / "output").mkdir()
    baseline = cli_manifest.deployment_checksum(tmp_path)
    (tmp_path / "output/result.json").write_text("{}\n")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache/tmp").write_text("n\n")
    assert cli_manifest.deployment_checksum(tmp_path) == baseline


# --- Environment files and images --------------------------------------------


def test_env_files_are_ordered_and_override_the_shell(tmp_path):
    root, deployment = runtime_tree(
        tmp_path, manifest=gpu_manifest(),
        config_env="MAP_PATH=$HOME/autoware_map/sample\nLIDAR_DETECTION_MODEL=clustering\n",
    )
    (deployment / "config.gpu.env").write_text("LIDAR_DETECTION_MODEL=centerpoint\n")
    (deployment / "config.local.env").write_text(
        "LIDAR_DETECTION_MODEL=from-local\nREMOTE_PASSWORD='pa$word'\n"
    )
    seen = tmp_path / "seen-env"
    executable(
        tmp_path / "bin/docker",
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "${MAP_PATH-unset}" "${LIDAR_DETECTION_MODEL-unset}" '
        f'"${{REMOTE_PASSWORD-unset}}" "$*" > {json.dumps(str(seen))}\n',
    )
    shell = {"MAP_PATH": "/tmp/from-shell", "LIDAR_DETECTION_MODEL": "from-shell", "REMOTE_PASSWORD": "from-shell"}

    def env_files(*args):
        result = run_cli(root, "validate", "example", *args, **shell)
        assert result.returncode == 0, result.stderr
        recorded = seen.read_text().splitlines()
        # Shell values for file-defined names are dropped; Compose reads the
        # env files itself, so quoting and $VAR expansion follow Compose rules.
        assert recorded[:3] == ["unset", "unset", "unset"]
        return [Path(item.split()[0]).name for item in recorded[3].split("--env-file ")[1:]]

    assert env_files() == ["config.env", "config.local.env"]
    assert env_files("--gpu") == ["config.env", "config.gpu.env", "config.local.env"]


def test_shell_map_path_does_not_redirect_data(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=clean_manifest(), config_env=CLEAN_ENV)
    result = run_cli(root, "clean", "example", MAP_PATH="/tmp/from-shell")
    assert result.returncode == 0, result.stderr
    assert str(root.parent / "home/data/example") in result.stdout
    assert "/tmp/from-shell" not in result.stdout


def test_dotenv_follows_compose_comment_and_export_rules(tmp_path):
    root, _ = runtime_tree(
        tmp_path, manifest=clean_manifest(),
        config_env=(
            "export MAP_PATH=$HOME/data/map # sample map\n"
            'GPU_MODEL_PATH="$HOME/data/gpu # model" # quoted keeps the hash\n'
            'export\tREMOTE_PASSWORD="pa\\"ss"\n'
        ),
    )
    result = run_cli(root, "clean", "example")
    assert result.returncode == 0, result.stderr
    home = root.parent / "home"
    assert f"({home}/data/map)" in result.stdout
    assert f"({home}/data/gpu # model)" in result.stdout


@pytest.mark.parametrize(
    ("args", "default", "expected"),
    [
        ((), "humble", distro_line("humble")),
        (("--ros-distro", "jazzy"), "humble", distro_line("jazzy", "jazzy-value")),
        ((), "jazzy", distro_line("jazzy", "jazzy-value")),
    ],
)
def test_repository_injects_distro_and_development_images(tmp_path, args, default, expected):
    manifest = minimal_manifest()
    manifest["distroEnvironment"] = {"jazzy": {"DISTRO_VALUE": "jazzy-value"}}
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    edit_kit(root, lambda kit: kit.update(defaultRosDistro=default))
    _, calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", *args)
    assert result.returncode == 0, result.stderr
    assert calls.read_text().startswith(expected)


def test_repository_component_image_override_is_preserved(tmp_path):
    root, deployment = runtime_tree(tmp_path)
    exact = f"registry.example/custom-api@sha256:{'b' * 64}"
    (deployment / "config.local.env").write_text(f"API_IMAGE={exact}\n")
    _, calls = fake_docker(tmp_path)
    assert run_cli(root, "validate", "example").returncode == 0
    assert calls.read_text().split("|", 5)[2] == exact


def test_release_injects_exact_images_over_env_files(tmp_path):
    root, deployment = runtime_tree(tmp_path, release=True)
    exact = f"registry.example/api@sha256:{'a' * 64}"
    edit_kit(root, lambda kit: kit["images"]["humble"].update(api=exact))
    with (deployment / "config.env").open("a") as output:
        output.write("API_IMAGE=registry.example/from-config\n")
    (deployment / "config.local.env").write_text("API_IMAGE=registry.example/from-local\n")
    _, calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example")
    assert result.returncode == 0, result.stderr
    assert calls.read_text().split("|", 5)[2] == exact


def test_release_rejects_mutable_image_reference(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    edit_kit(root, lambda kit: kit["images"]["humble"].update(api="registry.example/api:humble"))
    result = run_cli(root, "list")
    assert result.returncode != 0
    assert "digest-pinned image references" in result.stderr


def test_missing_release_image_fails_before_compose(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    edit_kit(root, lambda kit: kit.update(images={"humble": {}}))
    _, calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example")
    assert result.returncode != 0
    assert "missing component image target(s)" in result.stderr
    assert not calls.exists()


def test_gpu_image_is_injected_only_with_gpu(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=gpu_manifest())
    _, calls = fake_docker(tmp_path)
    assert run_cli(root, "validate", "example").returncode == 0
    assert calls.read_text().split("|", 5)[4] == ""
    calls.write_text("")
    assert run_cli(root, "validate", "example", "--gpu").returncode == 0
    assert calls.read_text().split("|", 5)[4] == f"{PREFIX}:sensing-perception-cuda-{ARCH}-humble"


def test_ros_distro_constraint_fails_before_compose(tmp_path):
    manifest = minimal_manifest()
    manifest["requirements"]["rosDistros"] = ["humble"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    _, calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", "--ros-distro", "jazzy")
    assert result.returncode != 0
    assert "does not support ROS distro jazzy" in result.stderr
    assert not calls.exists()


def test_gpu_architecture_constraint_fails_before_compose(tmp_path):
    manifest = gpu_manifest()
    manifest["requirements"].update(
        architectures=[ARCH, "other-arch"], gpuArchitectures=["other-arch"]
    )
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    _, calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", "--gpu")
    assert result.returncode != 0
    assert f"GPU mode does not support {ARCH}" in result.stderr
    assert not calls.exists()


# --- Runtime ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "pulls"),
    [((), True), (("--pull", "always"), True), (("--pull", "never"), False)],
)
def test_run_renders_checks_daemon_pulls_and_starts(tmp_path, args, pulls):
    root, _ = runtime_tree(tmp_path)
    _, calls = fake_docker(tmp_path)
    result = run_cli(root, "run", "example", *args)
    assert result.returncode == 0, result.stderr
    text = calls.read_text()
    up = "up --detach --wait --wait-timeout 30 --pull never --remove-orphans\n"
    assert text.index("config --quiet") < text.index("|info") < text.index(up)
    assert ("pull --policy" in text) is pulls
    if pulls:
        assert text.index("|info") < text.index("pull --policy") < text.index(up)


def test_run_resets_declared_one_shot_services(tmp_path):
    manifest = minimal_manifest()
    manifest["compose"]["resetServices"] = ["map-check"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    _, calls = fake_docker(tmp_path, configured="app\nmap-check\n")
    assert run_cli(root, "run", "example", "--pull", "never").returncode == 0
    assert "rm --stop --force map-check" in calls.read_text()


def test_run_fails_when_a_service_crashes_after_start(tmp_path):
    manifest = minimal_manifest()
    manifest["compose"]["resetServices"] = ["map-check"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    fake_docker(
        tmp_path, configured="app\nmap-check\n", container_ids="c1\nc2\n",
        # A one-shot that exited with an error is left to `up --wait`.
        inspect="app 2 running 0\nmap-check 0 exited 1\n",
    )
    result = run_cli(root, "run", "example", "--pull", "never")
    assert result.returncode == 1
    assert "error: app failed after start; see: openadkit logs example" in result.stderr


@pytest.mark.parametrize(
    ("running", "error"),
    [("other", "other is already running; stop it first: openadkit stop other"), ("example", None)],
)
def test_run_allows_one_deployment_at_a_time(tmp_path, running, error):
    root, _ = runtime_tree(tmp_path)
    edit_kit(root, lambda kit: kit["deployments"].update(other={"path": "deployments/other"}))
    _, calls = fake_docker(
        tmp_path, compose_ls=f'[{{"Name":"openadkit-{running}","Status":"running(3)"}}]'
    )
    result = run_cli(root, "run", "example", "--pull", "never")
    if error:
        assert result.returncode == 1
        assert error in result.stderr
        assert "up --detach" not in calls.read_text()
    else:
        assert result.returncode == 0, result.stderr
        assert "up --detach" in calls.read_text()


@pytest.mark.parametrize(
    ("kind", "read_only", "created"),
    [("missing", False, True), ("missing", True, False), ("file", False, False)],
)
def test_run_creates_only_missing_writable_mounts(tmp_path, kind, read_only, created):
    root, _ = runtime_tree(tmp_path)
    source = tmp_path / "home/autoware_data"
    if kind == "file":
        source.parent.mkdir(parents=True)
        source.write_text("")
    volume = {"type": "bind", "source": str(source), "target": "/data", "read_only": read_only}
    fake_docker(tmp_path, config_json=json.dumps({"services": {"writer": {"volumes": [volume]}}}))
    result = run_cli(root, "run", "example", "--pull", "never")
    assert result.returncode == 0, result.stderr
    assert source.is_dir() is created
    assert source.is_file() is (kind == "file")
    if created:
        # Created by the CLI as the user, so Docker never creates it as root.
        assert source.stat().st_uid == os.getuid()
    assert f"{os.getuid()}:{os.getgid()}" in (tmp_path / "docker-ids").read_text()


def test_stop_removes_project_but_not_volumes(tmp_path):
    root, _ = runtime_tree(tmp_path)
    _, calls = fake_docker(tmp_path)
    result = run_cli(root, "stop", "example")
    assert result.returncode == 0, result.stderr
    assert "down --remove-orphans" in calls.read_text()
    assert "--volumes" not in calls.read_text()


def test_operational_commands_are_stateless(tmp_path):
    root, deployment = runtime_tree(tmp_path, manifest=gpu_manifest())
    _, calls = fake_docker(tmp_path)
    assert run_cli(root, "run", "example", "--gpu", "--pull", "never").returncode == 0
    assert not (deployment / ".cache").exists()
    calls.write_text("")
    assert run_cli(root, "status", "example").returncode == 0
    assert "docker-compose.gpu.yaml" not in calls.read_text()
    assert calls.read_text().rstrip().endswith(" ps")


def test_operational_commands_work_without_default_distro_images(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    edit_kit(root, lambda kit: kit["images"].pop("humble"))
    _, calls = fake_docker(tmp_path)
    result = run_cli(root, "status", "example")
    assert result.returncode == 0, result.stderr
    assert calls.read_text().rstrip().endswith(" ps")


def test_validate_renders_without_the_docker_daemon(tmp_path):
    root, _ = runtime_tree(tmp_path)
    _, calls = fake_docker(tmp_path, daemon_returncode=37)
    result = run_cli(root, "validate", "example")
    assert result.returncode == 0, result.stderr
    assert "config --quiet" in calls.read_text()
    assert "|info\n" not in calls.read_text()


def test_ctrl_c_exits_quietly(tmp_path):
    root, _ = runtime_tree(tmp_path)
    started = tmp_path / "docker-started"
    executable(
        tmp_path / "bin/docker",
        f"#!/usr/bin/env bash\ntouch {json.dumps(str(started))}\nexec sleep 30\n",
    )
    (tmp_path / "home").mkdir()
    process = subprocess.Popen(
        [str(root / "openadkit"), "logs", "example", "--follow"],
        cwd=root,
        env=os.environ | {"HOME": str(tmp_path / "home"), "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"},
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # Wait until Python has started docker, then interrupt it like Ctrl+C.
    for _ in range(200):
        if started.exists() or process.poll() is not None:
            break
        time.sleep(0.05)
    process.send_signal(signal.SIGINT)
    _, stderr = process.communicate(timeout=10)
    assert process.returncode == 130
    assert "Traceback" not in stderr


def test_forced_docker_install_is_restricted_to_ci(tmp_path):
    root, _ = runtime_tree(tmp_path)
    sudo_log = tmp_path / "sudo-log"
    executable(tmp_path / "bin/sudo", f"#!/usr/bin/env bash\nprintf called > {json.dumps(str(sudo_log))}\n")
    result = run_cli(root, "setup", OPENADKIT_CI_FORCE_DOCKER_INSTALL="true", CI="false")
    assert result.returncode != 0
    assert "restricted to disposable CI hosts" in result.stderr
    assert not sudo_log.exists()


def test_capture_process_surfaces_command_stderr():
    with pytest.raises(cli_compose.OpenADKitError) as error:
        cli_compose.capture_process(["bash", "-c", "echo 'boom detail' >&2; exit 3"])
    assert "exit code 3" in str(error.value)
    assert "boom detail" in str(error.value)


# --- Data ---------------------------------------------------------------------


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture
def http(tmp_path):
    """Serve <tmp>/http and return (directory, base URL)."""
    directory = tmp_path / "http"
    directory.mkdir()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        lambda *args, **kwargs: QuietHandler(*args, directory=str(directory), **kwargs),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield directory, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()


def zip_resource(http, members, sha256=None):
    directory, base_url = http
    archive = directory / "data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name, text in members.items():
            output.writestr(name, text)
    return {
        "name": "dataset",
        "kind": "zip",
        "destinationEnv": "MAP_PATH",
        "expectedRoot": "dataset",
        "url": f"{base_url}/data.zip",
        "sha256": sha256 or hashlib.sha256(archive.read_bytes()).hexdigest(),
        "requiredFiles": ["required.txt"],
    }


def served_resource(http, text, **extra):
    directory, base_url = http
    (directory / "required.txt").write_text(text)
    return files_resource(
        url=f"{base_url}/required.txt",
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        **extra,
    )


def test_fetch_verifies_and_publishes_zip_data(tmp_path, http):
    manifest = minimal_manifest(data=[zip_resource(http, {"dataset/required.txt": "ok"})])
    # fetch downloads everything, even for a deployment that requires --gpu.
    manifest["requirements"]["gpu"] = "required"
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    result = run_cli(root, "fetch", "example")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/example/required.txt").read_text() == "ok"
    assert "requires --gpu" in run_cli(root, "validate", "example").stderr


def test_fetch_checksum_failure_preserves_existing_data(tmp_path, http):
    resource = zip_resource(http, {"dataset/required.txt": "replacement"}, sha256="0" * 64)
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(data=[resource]))
    target = tmp_path / "home/data/example"
    target.mkdir(parents=True)
    (target / "required.txt").write_text("original")
    assert run_cli(root, "fetch", "example", "--force").returncode != 0
    assert (target / "required.txt").read_text() == "original"


def test_fetch_rejects_unsafe_zip_member(tmp_path, http):
    resource = zip_resource(http, {"dataset/../escape": "bad"})
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(data=[resource]))
    result = run_cli(root, "fetch", "example")
    assert result.returncode != 0
    assert "unsafe ZIP member" in result.stderr
    assert not (tmp_path / "home/data/example").exists()


def test_fetch_includes_gpu_data_without_docker(tmp_path, http):
    manifest = gpu_manifest([served_resource(http, "gpu data", env="GPU_DATA_PATH", gpu=True)])
    root, _ = runtime_tree(tmp_path, manifest=manifest, config_env="GPU_DATA_PATH=$HOME/data/gpu\n")
    _, calls = fake_docker(tmp_path, config_returncode=99)
    result = run_cli(root, "fetch", "example")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/gpu/required.txt").read_text() == "gpu data"
    assert not calls.exists()


def test_run_force_reinstalls_incomplete_data(tmp_path, http):
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(data=[served_resource(http, "replaced")]))
    target = tmp_path / "home/data/example"
    target.mkdir(parents=True)
    fake_docker(tmp_path)
    blocked = run_cli(root, "run", "example", "--pull", "never")
    assert blocked.returncode != 0
    assert "incomplete data" in blocked.stderr
    assert "rerun with --force" in blocked.stderr
    result = run_cli(root, "run", "example", "--pull", "never", "--force")
    assert result.returncode == 0, result.stderr
    assert (target / "required.txt").read_text() == "replaced"


def test_run_without_gpu_skips_gpu_only_data(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=gpu_manifest([files_resource(gpu=True)]))
    fake_docker(tmp_path)
    result = run_cli(root, "run", "example", "--pull", "never")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home/data").exists()


@pytest.mark.parametrize(
    ("docker", "args", "message"),
    [
        ({"daemon_returncode": 1}, (), "could not access the Docker daemon"),
        ({"runtimes": "{}"}, ("--gpu",), "NVIDIA Container Toolkit is unavailable"),
        ({"configured": "app\n"}, (), "unknown Compose service(s): typo"),
    ],
)
def test_run_checks_docker_and_services_before_data_or_containers(tmp_path, docker, args, message):
    manifest = gpu_manifest([files_resource()])
    if "configured" in docker:
        manifest["compose"]["resetServices"] = ["typo"]
    root, _ = runtime_tree(tmp_path, manifest=manifest)
    _, calls = fake_docker(tmp_path, **docker)
    result = run_cli(root, "run", "example", *args)
    assert result.returncode != 0
    assert message in result.stderr
    assert not (tmp_path / "home/data").exists()
    assert started_nothing(calls)


def test_all_data_targets_are_checked_before_first_download(tmp_path):
    manifest = minimal_manifest(
        data=[files_resource("first", env="FIRST_PATH"), files_resource("second", env="SECOND_PATH")]
    )
    root, _ = runtime_tree(
        tmp_path, manifest=manifest,
        config_env="FIRST_PATH=$HOME/data/first\nSECOND_PATH=$HOME/data/second\n",
    )
    (tmp_path / "home/data/second").mkdir(parents=True)
    result = run_cli(root, "fetch", "example")
    assert result.returncode != 0
    assert "incomplete data" in result.stderr
    assert not (tmp_path / "home/data/first").exists()


@pytest.mark.parametrize("command", ("fetch", "validate"))
def test_relative_data_destination_is_rejected_before_download_or_compose(tmp_path, command):
    root, _ = runtime_tree(
        tmp_path, manifest=minimal_manifest(data=[files_resource()]), config_env="MAP_PATH=relative/data\n"
    )
    _, calls = fake_docker(tmp_path)
    result = run_cli(root, command, "example")
    assert result.returncode != 0
    assert "must be absolute after HOME expansion" in result.stderr
    assert not (root / "relative").exists()
    assert not calls.exists()


def test_validate_data_reports_missing_incomplete_and_ok(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=clean_manifest(), config_env=CLEAN_ENV)
    fake_docker(tmp_path)
    target = tmp_path / "home/data/example"

    result = run_cli(root, "validate", "example", "--data")
    assert result.returncode == 1, result.stdout
    assert "valid: example (humble, cpu)" in result.stdout
    assert "data: sample-map missing" in result.stdout
    # GPU-only data is checked only with --gpu.
    assert "gpu-model" not in result.stdout
    assert "openadkit fetch example" in result.stderr
    assert "--force" not in result.stderr
    assert "data: gpu-model missing" in run_cli(root, "validate", "example", "--data", "--gpu").stdout

    target.mkdir(parents=True)
    result = run_cli(root, "validate", "example", "--data")
    assert result.returncode == 1, result.stdout
    assert "data: sample-map incomplete" in result.stdout
    assert "openadkit fetch example --force" in result.stderr

    (target / "lanelet2_map.osm").write_text("map\n")
    result = run_cli(root, "validate", "example", "--data")
    assert result.returncode == 0, result.stderr
    assert "data: sample-map ok" in result.stdout
    assert "data:" not in run_cli(root, "validate", "example").stdout


def test_validate_data_tells_operator_to_remove_nondirectory(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=clean_manifest(), config_env=CLEAN_ENV)
    fake_docker(tmp_path)
    home = tmp_path / "home"
    (home / "data").mkdir(parents=True)
    target = home / "data/example"
    target.write_text("corrupted\n")
    result = run_cli(root, "validate", "example", "--data")
    assert result.returncode == 1, result.stdout
    assert "data: sample-map incomplete" in result.stdout
    assert f"{target} cannot be replaced in place" in result.stderr
    assert "remove it and run: openadkit fetch example" in result.stderr
    assert "--force" not in result.stderr

    target.unlink()
    (home / "real-data").mkdir()
    target.symlink_to(home / "real-data")
    result = run_cli(root, "validate", "example", "--data")
    assert result.returncode == 1, result.stdout
    assert f"{target} cannot be replaced in place" in result.stderr
    assert "--force" not in result.stderr
    assert target.is_symlink()


def test_validate_json_output(tmp_path):
    root, _ = runtime_tree(tmp_path, manifest=minimal_manifest(data=[files_resource("sample-map")]))
    fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schemaVersion": 1, "deployment": "example", "manifestValid": True,
        "rosDistro": "humble", "gpu": False, "dataValid": None, "data": [],
    }
    result = run_cli(root, "validate", "example", "--data", "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["dataValid"] is False
    assert payload["data"] == [{"name": "sample-map", "status": "missing"}]


# --- clean ---------------------------------------------------------------------


def clean_tree(tmp_path, *, compose_ls="[]"):
    """Deployment with a map and a GPU model, both present on disk."""
    root, _ = runtime_tree(tmp_path, manifest=clean_manifest(), config_env=CLEAN_ENV)
    fake_docker(tmp_path, compose_ls=compose_ls)
    home = tmp_path / "home"
    map_dir, gpu_dir = home / "data/example", home / "data/gpu-model"
    map_dir.mkdir(parents=True)
    (map_dir / "lanelet2_map.osm").write_text("map\n")
    gpu_dir.mkdir()
    (gpu_dir / "model.onnx").write_text("model\n")
    return root, map_dir, gpu_dir


def test_clean_lists_and_removes_all_declared_data(tmp_path):
    root, map_dir, gpu_dir = clean_tree(tmp_path)
    result = run_cli(root, "clean", "example")
    assert result.returncode == 0, result.stderr
    assert "sample-map: ok" in result.stdout
    assert "gpu-model: ok" in result.stdout
    assert map_dir.is_dir() and gpu_dir.is_dir()

    result = run_cli(root, "clean", "example", "--data")
    assert result.returncode == 0, result.stderr
    assert f"removed data: {map_dir}" in result.stdout
    assert f"removed data: {gpu_dir}" in result.stdout
    assert not map_dir.exists() and not gpu_dir.exists()


def test_clean_removes_a_file_target(tmp_path):
    root, map_dir, _ = clean_tree(tmp_path)
    shutil.rmtree(map_dir)
    map_dir.write_text("corrupted\n")
    result = run_cli(root, "clean", "example", "--data")
    assert result.returncode == 0, result.stderr
    assert f"removed data: {map_dir}" in result.stdout
    assert not map_dir.exists()


def test_clean_refuses_a_symlink_before_deleting_anything(tmp_path):
    root, map_dir, gpu_dir = clean_tree(tmp_path)
    outside = tmp_path / "home/real-model"
    gpu_dir.rename(outside)
    gpu_dir.symlink_to(outside)
    result = run_cli(root, "clean", "example", "--data")
    assert result.returncode != 0
    assert "refusing to remove symlinked data" in result.stderr
    assert (map_dir / "lanelet2_map.osm").is_file()
    assert gpu_dir.is_symlink()
    assert (outside / "model.onnx").is_file()


def test_clean_refuses_a_running_deployment(tmp_path):
    root, map_dir, gpu_dir = clean_tree(tmp_path, compose_ls=RUNNING)
    result = run_cli(root, "clean", "example", "--data")
    assert result.returncode != 0
    assert "example is running" in result.stderr
    assert (map_dir / "lanelet2_map.osm").is_file()
    assert (gpu_dir / "model.onnx").is_file()


def test_permission_errors_are_reported_without_traceback(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can remove any file")
    root, map_dir, _ = clean_tree(tmp_path)
    locked = map_dir / "locked"
    locked.mkdir()
    (locked / "file").write_text("x")
    locked.chmod(0o555)
    try:
        result = run_cli(root, "clean", "example", "--data")
    finally:
        locked.chmod(0o755)
    assert result.returncode == 1
    assert "error: permission denied:" in result.stderr
    assert "Traceback" not in result.stderr
