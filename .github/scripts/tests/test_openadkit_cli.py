"""Risk-focused CLI contracts; Docker is recorded, never started by this suite."""

import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "cli"))

import compose as cli_compose  # noqa: E402
import data as cli_data  # noqa: E402
import manifest as cli_manifest  # noqa: E402

ENTRYPOINT = ROOT / "openadkit"
COMPONENT_IMAGES = json.loads((ROOT / "openadkit.json").read_text())["componentImages"]
PIN = f"registry.example/image@sha256:{'a' * 64}"
OTHER_PIN = f"registry.example/custom@sha256:{'b' * 64}"
ARCH = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
ISOLATED_ENV = (
    "XDG_CONFIG_HOME", "XDG_STATE_HOME", "OPENADKIT_CONFIG_DIR", "OPENADKIT_STATE_DIR",
    "OPENADKIT_KIT", "OPENADKIT_DELEGATED", "OPENADKIT_INSTALL_DIR", "COMPOSE_FILE", "XDG_DATA_HOME",
)


def executable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def command(program, *args, home, bin_dir, cwd=None, **extra_env):
    home.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key not in ISOLATED_ENV}
    env.update(HOME=str(home), PATH=f"{bin_dir}:{os.environ['PATH']}")
    return subprocess.run(
        [str(program), *map(str, args)], cwd=cwd, env=env | extra_env,
        text=True, capture_output=True, timeout=30,
    )


def run_cli(root, *args, directory=None, **env):
    return command(root / "openadkit", *args, home=root.parent / "home",
                   bin_dir=root.parent / "bin", cwd=directory or root, **env)


def manifest(*, data=None, gpu=False, nodes=False):
    document = {
        "schemaVersion": 2, "name": "example", "description": "Test deployment",
        "compose": {"files": ["docker-compose.yaml"], "gpuFiles": ["gpu.yaml"] if gpu else [],
                    "profiles": [], "resetServices": [], "waitTimeout": 1},
        "requirements": {"architectures": ["amd64", "arm64"], "rosDistros": ["humble", "jazzy"],
                         "gpu": "optional" if gpu else "none"},
        "data": data or [],
    }
    if nodes:
        document["nodes"] = {
            name: {"rosDomainId": domain, "files": [f"compose.{name}.yaml"],
                   "resetServices": [], "requiredEnv": ["NODE_TOKEN"] if domain == 2 else []}
            for name, domain in (("primary", 1), ("secondary", 2))
        }
    return document


def runtime_tree(tmp_path, *, release=False, document=None, config="MAP_PATH=$HOME/data/map\n"):
    root = tmp_path / "runtime"
    root.mkdir(parents=True)
    shutil.copy2(ENTRYPOINT, root / "openadkit")
    shutil.copytree(ROOT / "cli", root / "cli", ignore=shutil.ignore_patterns("__pycache__"))
    directory = root / "deployments/example"
    directory.mkdir(parents=True)
    document = document or manifest()
    (directory / "deployment.json").write_text(json.dumps(document))
    (directory / "config.env").write_text(config)
    files = document["compose"]["files"] + document["compose"]["gpuFiles"]
    files += [file for node in document.get("nodes", {}).values() for file in node["files"]]
    for file in files:
        (directory / file).write_text("services:\n  app:\n    image: busybox:1.36.1\n")
    if document["compose"]["gpuFiles"]:
        (directory / "config.gpu.env").write_text("VALUE=base-gpu\nBASE_GPU=1\n")
    context = {
        "schemaVersion": 2, "kind": "release" if release else "repository",
        "defaultRosDistro": "humble", "componentImages": COMPONENT_IMAGES,
        "deployments": {"example": {"path": "deployments/example"}},
    }
    if release:
        context.update(version="v1.2.3", shared={},
                       autoware={"version": "1.8.0", "ref": "a" * 40, "lockSha256": "b" * 64},
                       images={distro: dict.fromkeys(COMPONENT_IMAGES.values(), PIN)
                               for distro in ("humble", "jazzy")})
        context["deployments"]["example"]["checksum"] = cli_manifest.deployment_checksum(directory)
    else:
        context["imagePrefixComponent"] = "registry.example/openadkit"
    (root / "openadkit.json").write_text(json.dumps(context))
    return root, directory


def edit_kit(root, change):
    path = root / "openadkit.json"
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document))


def fake_docker(tmp_path, *, projects=(), containers=(), daemon=0, config=0, runtimes='{"nvidia": {}}',
                services=("app", "acme")):
    """One stateful stub shared by runtime and integrator subprocess tests."""
    calls = tmp_path / "docker-calls"
    live = tmp_path / "projects.json"
    live.write_text(json.dumps([{"Name": name, "Status": "running(1)"} for name in projects]))
    service_lines = "\n".join(services)
    executable(tmp_path / "bin/docker", f'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
text = " ".join(args)
with open({str(calls)!r}, "a") as output:
    env = {{name: value for name, value in os.environ.items()
           if name.startswith("OPENADKIT_") or name in ("API_IMAGE", "VALUE", "ROS_DISTRO", "CYCLONEDDS_NETWORK_INTERFACE")}}
    output.write(json.dumps({{"args": args, "env": env}}) + "\\n")
live = Path({str(live)!r})
if text == "info":
    sys.exit({daemon})
if text == "info --format {{{{json .Runtimes}}}}":
    print({runtimes!r})
elif text == "compose ls --format json":
    print(live.read_text())
elif text == "ps -aq":
    print("\\n".join(row['Id'] for row in {list(containers)!r}))
elif args[0] == "inspect":
    print(json.dumps({list(containers)!r}))
elif "config --format json" in text:
    print('{{"services": {{}}}}')
elif "config --services" in text:
    print({service_lines!r})
elif "config --quiet" in text:
    sys.exit({config})
elif "up --detach" in text:
    project = args[args.index("--project-name") + 1]
    rows = json.loads(live.read_text())
    if not any(row["Name"] == project for row in rows):
        rows.append({{"Name": project, "Status": "running(1)"}})
    live.write_text(json.dumps(rows))
''')
    return calls


def recorded(calls):
    return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


def site_config(root, text, name="example"):
    path = root.parent / f"home/.config/openadkit/{name}.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def integrator_kit(tmp_path, root, *, extends=None, artifacts=None):
    kit = tmp_path / "kit"
    directory = kit / "deployments/custom"
    directory.mkdir(parents=True)
    (kit / "openadkit.json").write_text(json.dumps({
        "schemaVersion": 2, "kind": "kit", "extends": extends or str(root),
        "deployments": {"custom": {"path": "deployments/custom"}}, "artifacts": artifacts or {},
    }))
    (directory / "deployment.json").write_text(json.dumps({
        "schemaVersion": 2, "name": "custom", "description": "Integrator deployment",
        "base": "example", "compose": {"files": ["docker-compose.yaml"]},
    }))
    (directory / "config.env").write_text("VALUE=kit\n")
    (directory / "docker-compose.yaml").write_text(
        "include:\n  - ${OPENADKIT_BASE_DEPLOYMENT}/docker-compose.yaml\n"
        "services:\n  acme:\n    image: busybox:1.36.1\n"
    )
    return kit


# Install/upgrade fixtures deliberately contain no runtime deployment inventory.
def release_bin(tmp_path, version="v1.2.3", *, bad_checksum=False, member=None):
    release = tmp_path / version
    release.mkdir()
    root_name = f"openadkit-{version}"
    bundle = release / f"{root_name}.tar.gz"
    files = {"openadkit": ENTRYPOINT.read_bytes(), "cli/main.py": b'print("ok")\n',
             "openadkit.json": json.dumps({"schemaVersion": 2, "kind": "release", "version": version}).encode()}
    files.update({f"cli/{name}.py": (ROOT / f"cli/{name}.py").read_bytes() for name in ("compose", "manifest", "installation")})
    files["cli/completion.bash"] = (ROOT / "cli/completion.bash").read_bytes()
    if member:
        files[member] = "/etc/passwd" if member == "link" else b"escape"
    with tarfile.open(bundle, "w:gz", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload in files.items():
            info = tarfile.TarInfo(f"{root_name}/{name}")
            info.mode = 0o755 if name == "openadkit" else 0o644
            if isinstance(payload, str):
                info.type, info.linkname = tarfile.SYMTYPE, payload
                archive.addfile(info)
            else:
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
    (release / "release-metadata.json").write_text(json.dumps({
        "openadkit_version": version, "bundles": [{"name": bundle.name,
        "sha256": "0" * 64 if bad_checksum else hashlib.sha256(bundle.read_bytes()).hexdigest()}],
    }))
    bin_dir = release / "bin"
    executable(bin_dir / "curl", f'''#!/usr/bin/env python3
import shutil, sys
from pathlib import Path
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith("http"))
shutil.copyfile(Path({str(release)!r}) / url.rsplit("/", 1)[-1], args[args.index("-o") + 1])
''')
    return bin_dir


def install(tmp_path, bin_dir, *args):
    return command(ENTRYPOINT, "install", "--destination", tmp_path / "home/kit", *args,
                   home=tmp_path / "home", bin_dir=bin_dir)


def installed(tmp_path, version="v1.2.3"):
    return tmp_path / f"home/kit/openadkit-{version}/openadkit"


def test_install_upgrade_and_uninstall_preserve_kept_versions(tmp_path):
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    launcher = tmp_path / "home/.local/bin/openadkit"
    assert launcher.resolve() == installed(tmp_path)
    newer = release_bin(tmp_path, "v1.3.0")
    result = command(launcher, "upgrade", home=tmp_path / "home", bin_dir=newer)
    assert result.returncode == 0, result.stderr
    assert launcher.resolve() == installed(tmp_path, "v1.3.0")
    assert installed(tmp_path).is_file()
    fake_docker(tmp_path)
    result = command(launcher, "uninstall", home=tmp_path / "home", bin_dir=tmp_path / "bin")
    assert result.returncode == 0, result.stderr
    assert not launcher.exists() and not installed(tmp_path, "v1.3.0").exists()
    assert installed(tmp_path).is_file()


def test_install_adds_adkit_and_completion_and_uninstall_removes_only_its_links(tmp_path):
    home = tmp_path / "home"
    completions = home / ".local/share/bash-completion/completions"
    # A completion file of the user's own stays as it is.
    completions.mkdir(parents=True)
    (completions / "adkit").write_text("# the user's own\n")
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    short = home / ".local/bin/adkit"
    assert short.resolve() == installed(tmp_path)
    assert (completions / "openadkit").resolve() == installed(tmp_path).parent / "cli/completion.bash"
    assert (completions / "adkit").read_text() == "# the user's own\n"
    # The short name runs the same release (the fixture's main.py prints ok).
    result = command(short, "list", home=home, bin_dir=tmp_path / "bin")
    assert result.returncode == 0 and result.stdout == "ok\n"
    fake_docker(tmp_path)
    result = command(home / ".local/bin/openadkit", "uninstall", home=home, bin_dir=tmp_path / "bin")
    assert result.returncode == 0, result.stderr
    assert not short.is_symlink() and not (completions / "openadkit").is_symlink()
    assert (completions / "adkit").read_text() == "# the user's own\n"


def complete(root, words, directory=None):
    """COMPREPLY for words (the last one being completed), as bash-completion asks."""
    script = (
        f"source {ROOT / 'cli/completion.bash'}\n"
        'COMP_WORDS=("$@"); COMP_CWORD=$(($# - 1)); _openadkit; printf "%s\\n" "${COMPREPLY[@]}"\n'
    )
    result = subprocess.run(["bash", "-c", script, "bash", *words], cwd=directory or root, text=True,
                            capture_output=True, timeout=30,
                            env=dict(os.environ, PATH=f"{root}:{os.environ['PATH']}"))
    assert result.returncode == 0, result.stderr
    return set(result.stdout.split())


def test_completion_offers_commands_options_and_deployments(tmp_path):
    root, _ = runtime_tree(tmp_path)
    assert {"run", "build-overlay", "record"} <= complete(root, ["openadkit", ""])
    assert complete(root, ["adkit", "build-"]) == {"build-overlay"}
    assert complete(root, ["openadkit", "run", "--no-"]) == {"--no-visualizer"}
    assert complete(root, ["openadkit", "run", "--ros-distro", ""]) == {"humble", "jazzy"}
    assert complete(root, ["openadkit", "run", "ex"]) == {"example"}
    assert complete(root, ["openadkit", "run", "--ros-distro", "jazzy", ""]) == {"example"}
    # One deployment per command; list takes none.
    assert complete(root, ["openadkit", "run", "example", ""]) == set()
    assert complete(root, ["openadkit", "list", ""]) == set()


def test_completion_lists_every_command_and_option():
    import argparse

    import main as cli_main
    text = (ROOT / "cli/completion.bash").read_text()
    commands = re.search(r'local commands="([^"]+)"', text).group(1).split()
    listed = dict(re.findall(r"^\s+([a-z|\- ]+)\) options=\"([^\"]*)\"", text, re.MULTILINE))
    options = {name.strip(): set(value.split()) for names, value in listed.items() for name in names.split("|")}
    subparsers = next(action for action in cli_main.build_parser()._actions
                      if isinstance(action, argparse._SubParsersAction))
    assert set(commands) == set(subparsers.choices)
    # install, upgrade, setup and uninstall are parsed by the launcher and their own scripts.
    for name, parser in subparsers.choices.items():
        if name in ("install", "upgrade", "setup", "uninstall"):
            continue
        flags = {flag for action in parser._actions for flag in action.option_strings if flag.startswith("--")}
        assert flags - {"--help"} <= options[name], name


def test_install_defaults_to_the_root_kits_resolve_extends_from(tmp_path):
    root = tmp_path / "releases"
    result = command(ENTRYPOINT, "install", home=tmp_path / "home", bin_dir=release_bin(tmp_path),
                     OPENADKIT_INSTALL_DIR=str(root))
    assert result.returncode == 0, result.stderr
    assert (root / "openadkit-v1.2.3/openadkit").is_file()


@pytest.mark.parametrize(("options", "message"), [
    ({"bad_checksum": True}, "checksum verification failed"),
    ({"member": "../escape"}, "unsafe bundle member"),
    ({"member": "link"}, "unsupported bundle member"),
])
def test_install_rejects_corrupt_or_unsafe_bundle(tmp_path, options, message):
    result = install(tmp_path, release_bin(tmp_path, **options))
    assert result.returncode != 0 and message in result.stderr
    assert not (tmp_path / "home/kit").exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(("stop", "message"), [
    ("exit 1", "could not replace"),
    ("kill -TERM $PPID; exit 1", ""),
])
def test_failed_replacement_restores_previous_release(tmp_path, stop, message):
    bin_dir = release_bin(tmp_path)
    assert install(tmp_path, bin_dir).returncode == 0
    root = installed(tmp_path).parent
    (root / "marker").write_text("previous")
    executable(bin_dir / "mv", "#!/usr/bin/env bash\n"
               f'if [[ $# -eq 2 && "$2" == "{root}" && "$1" == *".openadkit-stage."* ]]; then {stop}; fi\n'
               f'exec {shutil.which("mv")} "$@"\n')
    result = install(tmp_path, bin_dir, "--force")
    assert result.returncode != 0 and message in result.stderr
    assert (root / "marker").read_text() == "previous"
    assert installed(tmp_path).is_file()
    assert (tmp_path / "home/.local/bin/openadkit").resolve() == installed(tmp_path)
    assert not list(root.parent.glob(".openadkit-*"))


def test_failed_upgrade_leaves_launcher_on_the_old_release(tmp_path):
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    result = command(installed(tmp_path), "upgrade", home=tmp_path / "home",
                     bin_dir=release_bin(tmp_path, "v1.3.0", bad_checksum=True))
    assert result.returncode != 0 and "checksum verification failed" in result.stderr
    assert (tmp_path / "home/.local/bin/openadkit").resolve() == installed(tmp_path)
    assert not installed(tmp_path, "v1.3.0").exists()


def test_upgrade_never_downgrades(tmp_path):
    assert install(tmp_path, release_bin(tmp_path, "v1.3.0")).returncode == 0
    result = command(installed(tmp_path, "v1.3.0"), "upgrade", home=tmp_path / "home", bin_dir=release_bin(tmp_path))
    assert result.returncode == 0 and "nothing to upgrade" in result.stdout
    assert (tmp_path / "home/.local/bin/openadkit").resolve() == installed(tmp_path, "v1.3.0")


@pytest.mark.parametrize("unsafe", ["running", "launcher"])
def test_uninstall_refuses_unsafe_state(tmp_path, unsafe):
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    launcher = tmp_path / "home/.local/bin/openadkit"
    fake_docker(tmp_path, projects=["openadkit-example"] if unsafe == "running" else [])
    if unsafe == "launcher":
        launcher.unlink()
        launcher.write_text("user launcher")
    result = command(installed(tmp_path), "uninstall", home=tmp_path / "home", bin_dir=tmp_path / "bin")
    assert result.returncode != 0
    assert ("stop running deployments" if unsafe == "running" else "non-symlink launcher") in result.stderr
    assert installed(tmp_path).is_file() and launcher.exists()


@pytest.mark.parametrize("release", [False, True])
def test_image_and_env_priority_reaches_compose(tmp_path, release):
    root, directory = runtime_tree(tmp_path, release=release, document=manifest(gpu=True),
                                   config="API_IMAGE=base\nVALUE=base\n")
    site_config(root, f"API_IMAGE={OTHER_PIN}\nVALUE=site\n")
    calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", "--gpu", API_IMAGE="shell", VALUE="shell")
    assert result.returncode == 0, result.stderr
    first = recorded(calls)[0]
    assert first["env"].get("VALUE") is None  # Compose, not the shell, loads file-defined values.
    assert first["env"].get("API_IMAGE") == (PIN if release else OTHER_PIN)
    env_files = [first["args"][index + 1] for index, arg in enumerate(first["args"]) if arg == "--env-file"]
    assert env_files == [str(directory / "config.env"), str(directory / "config.gpu.env"),
                         str(tmp_path / "home/.config/openadkit/example.env")]


@pytest.mark.parametrize("problem", ["mutable", "missing"])
def test_release_image_failures_prevent_compose(tmp_path, problem):
    root, _ = runtime_tree(tmp_path, release=True)
    edit_kit(root, lambda kit: kit["images"]["humble"].update(api="registry.example/api:latest")
             if problem == "mutable" else kit["images"]["humble"].pop("api"))
    calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example")
    assert result.returncode != 0
    assert ("digest-pinned" if problem == "mutable" else "missing component image") in result.stderr
    assert recorded(calls) == []


@pytest.mark.parametrize("constraint", ["distro", "gpu-architecture"])
def test_unsupported_runtime_selection_fails_before_compose(tmp_path, constraint):
    document = manifest(gpu=True)
    document["requirements"].update(architectures=[ARCH, "other-arch"], rosDistros=["humble"], gpuArchitectures=["other-arch"])
    root, _ = runtime_tree(tmp_path, document=document)
    calls = fake_docker(tmp_path)
    args = ["--ros-distro", "jazzy"] if constraint == "distro" else ["--gpu"]
    result = run_cli(root, "validate", "example", *args)
    assert result.returncode != 0
    assert ("does not support ROS distro jazzy" if constraint == "distro" else f"GPU mode does not support {ARCH}") in result.stderr
    assert recorded(calls) == []


@pytest.mark.parametrize(("options", "args", "message"), [
    ({"daemon": 1}, [], "Docker daemon"),
    ({"runtimes": "{}"}, ["--gpu"], "NVIDIA Container Toolkit"),
    ({"config": 1}, [], "failed"),
])
def test_run_preflight_does_not_touch_data_or_start_containers(tmp_path, options, args, message):
    root, _ = runtime_tree(tmp_path, document=manifest(gpu=True))
    calls = fake_docker(tmp_path, **options)
    result = run_cli(root, "run", "example", *args)
    assert result.returncode != 0 and message in result.stderr
    assert not any("up" in row["args"] or "pull" in row["args"] for row in recorded(calls))
    assert not (tmp_path / "home/data").exists()


@pytest.mark.parametrize("node", [None, "secondary"])
def test_a_split_node_keeps_dds_on_loopback(tmp_path, node):
    # A LAN interface in the host settings would put DDS on the network and
    # around the Zenoh allowlist; only a single-host run may opt in to that.
    root, _ = runtime_tree(tmp_path, document=manifest(nodes=node is not None))
    site = root.parent / "home/.config/openadkit/example.env"
    site.parent.mkdir(parents=True, exist_ok=True)
    site.write_text("CYCLONEDDS_NETWORK_INTERFACE=eth0\n")
    calls = fake_docker(tmp_path)
    args = ["--node", node] if node else []
    result = run_cli(root, "run", "example", *args, "--pull", "never", NODE_TOKEN="token")
    assert result.returncode == 0, result.stderr
    up = next(row for row in recorded(calls) if "up" in row["args"])
    assert up["env"].get("CYCLONEDDS_NETWORK_INTERFACE") == ("lo" if node else None)


def test_split_node_run_discovery_and_safe_stop(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest(nodes=True))
    calls = fake_docker(tmp_path)
    blocked = run_cli(root, "run", "example", "--node", "secondary", "--pull", "never")
    assert blocked.returncode != 0 and "NODE_TOKEN" in blocked.stderr
    assert recorded(calls) == []
    result = run_cli(root, "run", "example", "--node", "secondary", "--pull", "never", NODE_TOKEN="token")
    assert result.returncode == 0, result.stderr
    rows = recorded(calls)
    up = next(row for row in rows if "up" in row["args"])
    assert "openadkit-example-secondary" in up["args"]
    assert up["env"]["OPENADKIT_ROS_DOMAIN_ID"] == "2"
    assert str(root / "deployments/example/compose.secondary.yaml") in up["args"]
    assert not any("zenoh" in arg or arg.endswith("docker-compose.yaml") for arg in up["args"])
    calls.write_text("")
    result = run_cli(root, "stop", "example")
    assert result.returncode == 0, result.stderr
    down = next(row["args"] for row in recorded(calls) if "down" in row["args"])
    assert "openadkit-example-secondary" in down and "--volumes" not in down


@pytest.mark.parametrize("headless", [False, True])
def test_run_can_leave_out_the_visualizer(tmp_path, headless):
    root, _ = runtime_tree(tmp_path)
    calls = fake_docker(tmp_path, services=("app", "visualizer"))
    result = run_cli(root, "run", "example", *(["--no-visualizer"] if headless else []))
    assert result.returncode == 0, result.stderr
    rows = [row["args"] for row in recorded(calls)]
    up = next(args for args in rows if "up" in args)
    pull = next(args for args in rows if "pull" in args)
    assert ("--scale=visualizer=0" in up) is headless
    # A left-out service is not pulled either.
    assert pull[pull.index("missing") + 1:] == (["app"] if headless else [])
    assert ("visualizer: http://localhost:6080" in result.stdout) is not headless


def test_run_prints_https_only_for_a_site_certificate(tmp_path):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path, services=("app", "visualizer"))
    site_config(root, "NOVNC_CERT=/certs/novnc.crt\nNOVNC_KEY=/certs/novnc.key\n")
    result = run_cli(root, "run", "example")
    assert result.returncode == 0, result.stderr
    assert "visualizer: https://localhost:6080/vnc.html" in result.stdout


@pytest.mark.parametrize(("projects", "args", "message"), [
    (["openadkit-example-primary"], [], "already running as node primary"),
    (["openadkit-example"], ["--node", "primary"], "already running as single-host"),
    (["openadkit-other"], [], "already running"),
])
def test_incompatible_live_projects_cannot_be_started_over(tmp_path, projects, args, message):
    root, _ = runtime_tree(tmp_path, document=manifest(nodes=True))
    edit_kit(root, lambda kit: kit["deployments"].update(other={"path": "deployments/other"}))
    calls = fake_docker(tmp_path, projects=projects)
    result = run_cli(root, "run", "example", "--pull", "never", *args)
    assert result.returncode != 0 and message in result.stderr
    assert not any("up" in row["args"] for row in recorded(calls))


@pytest.mark.parametrize("target", ["base", "kit"])
def test_run_rejects_live_projects_from_the_other_kit_catalog(tmp_path, target):
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    kit = integrator_kit(tmp_path, root)
    name, other = ("example", "custom") if target == "base" else ("custom", "example")
    calls = fake_docker(tmp_path, projects=[f"openadkit-{other}"])
    result = run_cli(root, "run", name, "--pull", "never", directory=root if target == "base" else kit)
    assert result.returncode != 0 and f"openadkit-{other} is already running" in result.stderr
    assert not (tmp_path / "home/data").exists()
    assert not any("up" in row["args"] or "pull" in row["args"] for row in recorded(calls))


@pytest.mark.parametrize(("project", "allowed"), [("openadkit-example-primary", True),
                                                ("openadkit-example-secondary", True),
                                                ("openadkit-example-foreign", False)])
def test_exclusivity_only_allows_declared_nodes_of_the_selected_deployment(tmp_path, monkeypatch, project, allowed):
    root, _ = runtime_tree(tmp_path, document=manifest(nodes=True))
    kit = cli_manifest.load_kit(root)
    deployment = cli_manifest.get_deployment(root, kit, "example")
    monkeypatch.setattr(cli_compose, "live_projects", lambda: {project})
    assert cli_compose.other_projects(deployment) == ([] if allowed else [project])


def test_several_live_nodes_require_an_explicit_stop_target(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest(nodes=True))
    calls = fake_docker(tmp_path, projects=["openadkit-example-primary", "openadkit-example-secondary"])
    result = run_cli(root, "stop", "example")
    assert result.returncode != 0 and "choose one with --node" in result.stderr
    assert not any("down" in row["args"] for row in recorded(calls))


@pytest.mark.parametrize("unsafe", ["missing", "symlink", "escape"])
def test_required_node_files_are_checked_before_compose(tmp_path, unsafe):
    document = manifest(nodes=True)
    document["nodes"]["primary"]["requiredFiles"] = ["../outside" if unsafe == "escape" else "allowlist.json"]
    root, directory = runtime_tree(tmp_path, document=document)
    if unsafe == "symlink":
        outside = tmp_path / "outside"
        outside.write_text("{}")
        (directory / "allowlist.json").symlink_to(outside)
    calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", "--node", "primary")
    assert result.returncode != 0
    assert {"missing": "missing required node file", "symlink": "symlinked required node file",
            "escape": "safe relative path"}[unsafe] in result.stderr
    assert recorded(calls) == []


def files_resource(tmp_path, *, env="MAP_PATH", name="dataset", **extra):
    source = tmp_path / f"{name}.txt"
    source.write_text("replacement")
    return {"name": name, "kind": "files", "destinationEnv": env, "requiredFiles": ["required.txt"],
            "files": [{"path": "required.txt", "url": source.as_uri(),
                       "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}], **extra}


@pytest.mark.parametrize("name", ["../escape", "maps/town", "Map", ""])
def test_data_resource_names_must_be_safe_path_names(tmp_path, name):
    resource = files_resource(tmp_path) | {"name": name}
    with pytest.raises(cli_manifest.OpenADKitError, match="name"):
        cli_manifest._validate_data([resource], {})


def test_only_explicit_fetch_force_replaces_managed_data(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    target = tmp_path / "home/data/map"
    target.mkdir(parents=True)
    calls = fake_docker(tmp_path)
    # Data the CLI did not install: --force would refuse it, so do not advise it.
    for command in (("run", "example", "--pull", "never"), ("fetch", "example")):
        result = run_cli(root, *command)
        assert result.returncode != 0 and "remove it and run: openadkit fetch example\n" in result.stderr
        assert "--force" not in result.stderr
    assert not any("up" in row["args"] for row in recorded(calls))
    assert run_cli(root, "run", "example", "--force").returncode == 2
    assert "refusing to replace" in run_cli(root, "fetch", "example", "--force").stderr
    (target / cli_data.MARKER).write_text("{}")
    result = run_cli(root, "run", "example", "--pull", "never")
    assert result.returncode != 0 and "openadkit fetch example --force" in result.stderr
    result = run_cli(root, "fetch", "example", "--force")
    assert result.returncode == 0, result.stderr
    assert (target / "required.txt").read_text() == "replacement"
    marker = json.loads((target / cli_data.MARKER).read_text())
    assert marker == {"resource": "dataset", "source": cli_data.source_digest(files_resource(tmp_path))}
    (target / "required.txt").write_text("keep existing")
    assert run_cli(root, "fetch", "example").returncode == 0
    assert (target / "required.txt").read_text() == "keep existing"
    assert run_cli(root, "run", "example", "--pull", "never").returncode == 0


def test_data_installed_from_an_older_declaration_needs_fetch_force(tmp_path):
    resource = files_resource(tmp_path)
    root, directory = runtime_tree(tmp_path, document=manifest(data=[resource]))
    target = tmp_path / "home/data/map"
    fake_docker(tmp_path)
    assert run_cli(root, "fetch", "example").returncode == 0
    assert run_cli(root, "run", "example", "--pull", "never").returncode == 0
    # A mirror of the same bytes is the same data.
    moved = tmp_path / "mirror.txt"
    moved.write_bytes((tmp_path / "dataset.txt").read_bytes())
    resource["files"][0]["url"] = moved.as_uri()
    (directory / "deployment.json").write_text(json.dumps(manifest(data=[resource])))
    assert run_cli(root, "run", "example", "--pull", "never").returncode == 0

    fixed = tmp_path / "fixed.txt"
    fixed.write_text("fixed upstream")
    resource["files"][0] |= {"url": fixed.as_uri(), "sha256": hashlib.sha256(fixed.read_bytes()).hexdigest()}
    (directory / "deployment.json").write_text(json.dumps(manifest(data=[resource])))
    result = run_cli(root, "validate", "example", "--data")
    assert result.returncode == 1 and "data: dataset outdated" in result.stdout
    assert "openadkit fetch example --force" in result.stderr
    for command in (("run", "example", "--pull", "never"), ("fetch", "example")):
        result = run_cli(root, *command)
        assert result.returncode != 0 and "openadkit fetch example --force" in result.stderr
    assert (target / "required.txt").read_text() == "replacement"
    fake_docker(tmp_path)  # stopped
    assert run_cli(root, "fetch", "example", "--force").returncode == 0
    assert (target / "required.txt").read_text() == "fixed upstream"
    assert run_cli(root, "run", "example", "--pull", "never").returncode == 0


@pytest.mark.parametrize("content, outdated", [("replacement", False), ("older", True)])
def test_data_marked_before_sources_were_recorded_is_checked_by_checksum(tmp_path, content, outdated):
    resource = files_resource(tmp_path)
    target = tmp_path / "installed"
    target.mkdir()
    (target / cli_data.MARKER).write_text(json.dumps({"resource": "dataset"}))
    (target / "required.txt").write_text(content)
    assert cli_data.is_outdated(target, resource) is outdated
    # Unmarked data is the operator's own: never reported as outdated.
    (target / cli_data.MARKER).unlink()
    assert cli_data.is_outdated(target, resource) is False


@pytest.mark.parametrize("live", ["project", "container"])
def test_forced_fetch_refuses_data_in_use(tmp_path, live):
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    target = tmp_path / "home/data/map"
    target.mkdir(parents=True)
    (target / cli_data.MARKER).write_text("{}")
    (target / "required.txt").write_text("keep")
    if live == "project":
        fake_docker(tmp_path, projects=["openadkit-example"])
    else:
        container = {"Id": "abc", "Name": "/other", "State": {"Status": "running"},
                     "Mounts": [{"Type": "bind", "Source": str(target)}]}
        fake_docker(tmp_path, projects=["openadkit-other"], containers=[container])
    result = run_cli(root, "fetch", "example", "--force")
    assert result.returncode != 0
    assert ("example is running" if live == "project" else "is in use") in result.stderr
    assert (target / "required.txt").read_text() == "keep"


def test_checksum_failure_preserves_managed_data_and_cleans_staging(tmp_path, monkeypatch):
    # Exercise download validation, not the earlier unmanaged-target refusal.
    resource = files_resource(tmp_path)
    resource["files"][0]["sha256"] = "0" * 64
    resource["generatedFiles"] = {}
    target = tmp_path / "installed"
    target.mkdir()
    (target / cli_data.MARKER).write_text("{}")
    (target / "required.txt").write_text("original")
    monkeypatch.setattr(cli_data.time, "sleep", lambda _: None)
    selection = cli_manifest.Selection("humble", False, None, {}, {"MAP_PATH": str(target)})
    with pytest.raises(cli_manifest.OpenADKitError, match="checksum mismatch"):
        cli_data.install_resource(resource, selection, True)
    assert (target / "required.txt").read_text() == "original"
    assert not list(tmp_path.glob(".dataset.stage.*"))


def test_rerun_counts_only_restarts_since_up(monkeypatch):
    # "kept" restarted once before this `up` and was left in place; "crashed" restarted after it.
    # Reset services may exit, but not fail: "init" finished, "rosbag" crashed.
    inspect = ("kept api 1 running 0\ncrashed planning 1 running 0\nreset init 3 exited 0\n"
               "bag rosbag 0 exited 1\n")
    monkeypatch.setattr(cli_compose, "capture_process",
                        lambda *_, **__: subprocess.CompletedProcess([], 0, stdout=inspect))
    deployment = type("Deployment", (), {"reset_services": staticmethod(lambda node: {"init", "rosbag"})})()
    selection = cli_manifest.Selection("humble", False, None, {}, {})
    assert cli_compose.failed_services(deployment, selection, [], {"kept": 1}) == ["planning", "rosbag"]


def test_run_reports_overrides_that_changed_nothing(monkeypatch, capsys):
    hooked = [{"Destination": "/openadkit/config/deployment"}]
    containers = [{"Id": "map", "Mounts": hooked}, {"Id": "control", "Mounts": hooked},
                  {"Id": "carla", "Mounts": [{"Destination": "/data"}]}]
    reports = {
        "map": {"unknownPackages": ["autoware_control_config", "autoware_localization_config", "typo_pkg"],
                "unknownFiles": [], "unknownKeys": []},
        "control": {"unknownPackages": ["autoware_localization_config", "typo_pkg"], "unknownFiles": [],
                    "unknownKeys": ["control_validator.param.yaml: nominal_latency"]},
    }
    commands = []

    def capture(command, **_):
        commands.append(command)
        if command[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(containers))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(reports[command[2]]))

    monkeypatch.setattr(cli_compose, "compose_capture",
                        lambda *_, **__: subprocess.CompletedProcess([], 0, stdout="map\ncontrol\ncarla\n"))
    monkeypatch.setattr(cli_compose, "capture_process", capture)
    selection = cli_manifest.Selection("humble", False, None, {}, {})
    warnings = cli_compose.report_overrides(None, selection)
    # autoware_control_config is installed in the control image, so it is no mistake.
    assert warnings == ["package autoware_localization_config is in no service", "package typo_pkg is in no service",
                        "parameter control_validator.param.yaml: nominal_latency is not in its package"]
    assert "renamed packages" in capsys.readouterr().err
    assert not any(command[:3] == ["docker", "exec", "carla"] for command in commands)
    reports["map"] = reports["control"] = {"unknownPackages": [], "unknownFiles": [], "unknownKeys": []}
    assert cli_compose.report_overrides(None, selection) == []
    assert capsys.readouterr().err == ""


def test_status_shows_the_ad_api_state_in_one_line_each():
    state = {
        "localization": {"state": "initialized"},
        "routing": {"state": "set"},
        "mode": {"state": "stop", "autowareControl": False, "autonomousAvailable": True},
        "mrm": {"state": "operating", "behavior": "emergency stop"},
    }
    assert cli_compose.format_autoware_state(state) == [
        "localization initialized",
        "routing      set",
        "mode         stop (manual control, autonomous available)",
        "mrm          operating: emergency stop",
    ]
    assert cli_compose.format_autoware_state(dict.fromkeys(state))[1] == "routing      no data"


def test_logs_and_record_take_services_and_topics(tmp_path):
    root, _ = runtime_tree(tmp_path)
    calls = fake_docker(tmp_path, projects=["openadkit-example"])
    assert run_cli(root, "logs", "example", "map", "planning").returncode == 0
    assert recorded(calls)[-1]["args"][-3:] == ["logs", "map", "planning"]
    for arguments in ((), ("/tf", "--all")):
        result = run_cli(root, "record", "example", *arguments)
        assert result.returncode != 0 and "or pass --all" in result.stderr
    fake_docker(tmp_path)
    result = run_cli(root, "record", "example", "/tf")
    assert result.returncode != 0 and "example is not running" in result.stderr


def test_download_retries_cut_off_bodies_but_not_wrong_content(tmp_path, monkeypatch):
    payload = b"dataset"
    bodies = []

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    def urlopen(request, timeout):
        return Response(bodies.pop(0))

    monkeypatch.setattr(cli_data.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cli_data.time, "sleep", lambda _: None)
    destination = tmp_path / "download"
    bodies[:] = [payload[:3], payload]
    cli_data.download("https://example/data", destination, hashlib.sha256(payload).hexdigest())
    assert destination.read_bytes() == payload and not bodies
    bodies[:] = [payload, payload]
    with pytest.raises(cli_manifest.OpenADKitError, match="checksum mismatch"):
        cli_data.download("https://example/data", destination, "0" * 64)
    assert len(bodies) == 1 and not destination.exists()


@pytest.mark.parametrize("race", ["appeared", "replaced", "unmarked", "exchange"])
def test_forced_fetch_preserves_targets_changed_during_publication(tmp_path, monkeypatch, race):
    resource = files_resource(tmp_path)
    resource["generatedFiles"] = {}
    target = tmp_path / "installed"
    if race != "appeared":
        target.mkdir()
        (target / cli_data.MARKER).write_text("{}")
        (target / "user-file").write_text("original")
    def change_target():
        if race == "unmarked":
            (target / cli_data.MARKER).unlink()
        else:
            if target.exists():
                target.rename(tmp_path / "original")
            target.mkdir()
            (target / "user-file").write_text("new user data")
    download, rename = cli_data.download, cli_data.rename_atomic
    def download_with_race(*args):
        download(*args)
        if race != "exchange":
            change_target()
    def rename_with_race(candidate, destination, flags):
        if race == "exchange" and flags == 2 and destination == target and not (tmp_path / "original").exists():
            change_target()
        rename(candidate, destination, flags)
    monkeypatch.setattr(cli_data, "download", download_with_race)
    monkeypatch.setattr(cli_data, "rename_atomic", rename_with_race)
    selection = cli_manifest.Selection("humble", False, None, {}, {"MAP_PATH": str(target)})
    with pytest.raises(cli_manifest.OpenADKitError, match="changed|publication failed"):
        cli_data.install_resource(resource, selection, True)
    assert (target / "user-file").read_text() == ("original" if race == "unmarked" else "new user data")
    assert bool(list(tmp_path.glob(".dataset.stage.*"))) is (race == "exchange")


def test_failed_post_exchange_verification_never_cleans_displaced_data(tmp_path, monkeypatch):
    resource = files_resource(tmp_path)
    resource["generatedFiles"] = {}
    target = tmp_path / "installed"
    target.mkdir()
    (target / cli_data.MARKER).write_text("{}")
    (target / "user-file").write_text("keep")
    managed = cli_data.is_managed
    def unreadable_displaced(path):
        if path.name == "dataset":
            raise OSError("inspection failed")
        return managed(path)
    monkeypatch.setattr(cli_data, "is_managed", unreadable_displaced)
    selection = cli_manifest.Selection("humble", False, None, {}, {"MAP_PATH": str(target)})
    with pytest.raises(cli_manifest.OpenADKitError, match="staging preserved"):
        cli_data.install_resource(resource, selection, True)
    staged = next(tmp_path.glob(".dataset.stage.*"))
    assert (staged / "dataset/user-file").read_text() == "keep"


class SettingsDeployment:
    """The parts of a Deployment that settings resolution reads."""

    def __init__(self, directory, files, gpu_files):
        self.name, self.directory, self.has_gpu_files = "example", directory, True
        self.files, self.gpu_files = files, gpu_files

    def env_files(self, gpu=False):
        return self.files + (self.gpu_files if gpu else [])

    def configuration_environment(self, gpu=False):
        values = {}
        for path in self.env_files(gpu):
            values.update(cli_manifest.parse_dotenv(path))
        return values


@pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0,
    reason="needs Docker Compose",
)
def test_data_destinations_resolve_as_compose_resolves_them(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAP_ROOT", "/srv/maps")
    (tmp_path / "config.env").write_text(
        "DATA_PATH=$HOME/data\nMODEL_PATH=${DATA_PATH}/models\n"
        "MAP_PATH=${MAP_ROOT:-/tmp/openadkit-map}\nROSBAG_PATH=${ROSBAG_ROOT:-/tmp/rosbag}\n")
    (tmp_path / "config.gpu.env").write_text("ROSBAG_PATH=/srv/gpu-rosbag\n")
    deployment = SettingsDeployment(tmp_path, [tmp_path / "config.env"], [tmp_path / "config.gpu.env"])
    selection = cli_manifest.Selection("humble", False, None, {}, deployment.configuration_environment())
    resolved = cli_compose.resolve_settings(deployment, selection)
    destination = lambda name, gpu=False: cli_data.resolve_destination(  # noqa: E731
        {"name": name, "destinationEnv": name, "gpu": gpu}, resolved)
    assert destination("MODEL_PATH") == tmp_path / "data/models"
    assert destination("MAP_PATH") == Path("/srv/maps")
    assert destination("ROSBAG_PATH") == Path("/tmp/rosbag")
    # GPU-only data goes where a GPU run mounts it.
    assert destination("ROSBAG_PATH", gpu=True) == Path("/srv/gpu-rosbag")


@pytest.mark.skipif(os.geteuid() == 0, reason="every link a root test creates is root-owned")
def test_data_paths_reject_user_symlinks_but_trust_host_layout(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(cli_manifest.OpenADKitError, match="symlinked data path"):
        cli_data.ensure_no_symlink_components(tmp_path / "link/map")
    # A merged-/usr host's /bin -> usr/bin stands in for a relocated /home.
    system = Path("/bin")
    if not system.is_symlink() or system.lstat().st_uid != 0:
        pytest.skip("host has no root-owned top-level symlink")
    cli_data.ensure_no_symlink_components(system / "openadkit-map")


@pytest.mark.parametrize("unsafe", ["traversal", "absolute", "symlink", "duplicate"])
def test_zip_validation_rejects_unsafe_members(tmp_path, unsafe):
    archive = tmp_path / "unsafe.zip"
    info = zipfile.ZipInfo({"traversal": "dataset/../escape", "absolute": "/escape"}.get(unsafe, "dataset/file"))
    if unsafe == "symlink":
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(info, "payload")
        if unsafe == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                output.writestr(info, "again")
    stage = tmp_path / "stage"
    with pytest.raises(cli_manifest.OpenADKitError, match="ZIP member"):
        cli_data.extract_zip(archive, stage, "dataset")
    assert not stage.exists() and not (tmp_path / "escape").exists()


def test_zip_fetch_publishes_validated_data(tmp_path):
    archive = tmp_path / "data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("dataset/required.txt", "map")
    resource = {"name": "dataset", "kind": "zip", "destinationEnv": "MAP_PATH", "expectedRoot": "dataset",
                "url": archive.as_uri(), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "requiredFiles": ["required.txt"]}
    root, _ = runtime_tree(tmp_path, document=manifest(data=[resource]))
    result = run_cli(root, "fetch", "example")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/map/required.txt").read_text() == "map"
    fake_docker(tmp_path)
    result = run_cli(root, "clean", "example", "--data")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home/data/map").exists()


@pytest.mark.parametrize("unsafe", ["unmanaged", "file", "symlink", "marker-symlink", "running"])
def test_clean_checks_all_targets_before_deleting_anything(tmp_path, unsafe):
    resources = [files_resource(tmp_path), files_resource(tmp_path, env="SECOND_PATH", name="second")]
    root, _ = runtime_tree(tmp_path, document=manifest(data=resources),
                           config="MAP_PATH=$HOME/data/map\nSECOND_PATH=$HOME/data/second\n")
    first, second = tmp_path / "home/data/map", tmp_path / "home/data/second"
    for target in (first, second):
        target.mkdir(parents=True)
        (target / cli_data.MARKER).write_text("{}")
        (target / "required.txt").write_text("keep")
    if unsafe == "unmanaged":
        (second / cli_data.MARKER).unlink()
    elif unsafe == "file":
        shutil.rmtree(second)
        second.write_text("keep")
    elif unsafe == "symlink":
        second.rename(tmp_path / "outside")
        second.symlink_to(tmp_path / "outside")
    elif unsafe == "marker-symlink":
        (second / cli_data.MARKER).unlink()
        (second / cli_data.MARKER).symlink_to(first / cli_data.MARKER)
    fake_docker(tmp_path, projects=["openadkit-example"] if unsafe == "running" else [])
    result = run_cli(root, "clean", "example", "--data")
    assert result.returncode != 0
    message = "example is running" if unsafe == "running" else (
        "refusing to remove symlinked data" if unsafe == "symlink" else "not installed by openadkit"
    )
    assert message in result.stderr
    assert (first / "required.txt").read_text() == "keep"
    assert second.exists()


@pytest.mark.parametrize(("name", "status", "shared"), [("custom", "running", True), ("example", "paused", True),
                                                        ("custom", "restarting", True), ("custom", "running", False),
                                                        ("custom", "exited", True)])
def test_clean_protects_shared_data_across_kit_catalogs(tmp_path, name, status, shared):
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    kit = integrator_kit(tmp_path, root)
    target = tmp_path / "home/data/map"
    target.mkdir(parents=True)
    (target / cli_data.MARKER).write_text("{}")
    (target / "required.txt").write_text("keep")
    other = "example" if name == "custom" else "custom"
    container = {"Id": "abc", "Name": f"/{other}", "State": {"Status": status},
                 "Mounts": [{"Type": "bind", "Source": str(target if shared else tmp_path / "unrelated")}]}
    fake_docker(tmp_path, projects=[f"openadkit-{other}"], containers=[container])
    result = run_cli(root, "clean", name, "--data", directory=kit if name == "custom" else root)
    blocked = shared and status != "exited"
    assert (result.returncode != 0) is blocked, result.stderr
    if blocked:
        assert "is in use" in result.stderr and (target / "required.txt").read_text() == "keep"
    else:
        assert not target.exists()


@pytest.mark.parametrize("output", ["not json", "[]"])
def test_cleanup_refuses_incomplete_container_inspection(tmp_path, monkeypatch, output):
    def capture(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "abc\n" if args[1] == "ps" else output, "")
    monkeypatch.setattr(cli_compose, "capture_process", capture)
    monkeypatch.setattr(cli_compose.shutil, "which", lambda _: "/bin/docker")
    with pytest.raises(cli_manifest.OpenADKitError, match="refusing cleanup"):
        cli_compose.require_data_unused([tmp_path / "data"])


def test_fetch_checks_every_destination_before_download(tmp_path):
    resources = [files_resource(tmp_path), files_resource(tmp_path, env="SECOND_PATH", name="second")]
    root, _ = runtime_tree(tmp_path, document=manifest(data=resources),
                           config="MAP_PATH=$HOME/data/map\nSECOND_PATH=relative\n")
    result = run_cli(root, "fetch", "example")
    assert result.returncode != 0 and "must be absolute" in result.stderr
    assert not (tmp_path / "home/data").exists()


@pytest.mark.parametrize("base_refs", [{"ref": PIN}, {"distros": {"humble": PIN, "jazzy": PIN}}])
def test_kit_artifact_fallback_and_wildcard_override(tmp_path, base_refs):
    root, _ = runtime_tree(tmp_path)
    edit_kit(root, lambda doc: doc.update(artifacts={"EXTERNAL_IMAGE": {"workload": "api", **base_refs}}))
    kit = integrator_kit(tmp_path, root, artifacts={"EXTERNAL_IMAGE": {"workload": "api", "distros": {"humble": OTHER_PIN}}})
    context = cli_manifest.load_kit(kit)
    assert context.artifact_environment("humble")["EXTERNAL_IMAGE"] == OTHER_PIN
    assert context.artifact_environment("jazzy")["EXTERNAL_IMAGE"] == PIN
    edit_kit(kit, lambda doc: doc.update(artifacts={"EXTERNAL_IMAGE": {"workload": "api", "ref": OTHER_PIN}}))
    assert cli_manifest.load_kit(kit).artifact_environment("jazzy")["EXTERNAL_IMAGE"] == OTHER_PIN
    # Every distro is `ref`, never a "*" distro.
    edit_kit(kit, lambda doc: doc.update(artifacts={"EXTERNAL_IMAGE": {"workload": "api", "distros": {"*": OTHER_PIN}}}))
    with pytest.raises(cli_manifest.OpenADKitError, match="invalid ROS distro"):
        cli_manifest.load_kit(kit)


@pytest.mark.parametrize("text", ["[]", "{"])
def test_a_broken_nearest_manifest_is_an_error_not_another_kit(tmp_path, text):
    root, _ = runtime_tree(tmp_path)
    (tmp_path / "kit").mkdir()
    (tmp_path / "kit/openadkit.json").write_text(text)
    result = run_cli(root, "list", directory=tmp_path / "kit")
    assert result.returncode == 1 and f"invalid manifest {tmp_path / 'kit/openadkit.json'}" in result.stderr


@pytest.mark.parametrize("release", [False, True])
def test_kit_inherits_pins_gpu_env_and_layers(tmp_path, monkeypatch, release):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)
    root, base = runtime_tree(tmp_path, release=release,
                              document=manifest(gpu=True, data=[files_resource(tmp_path)]), config="VALUE=base\nMAP_PATH=$HOME/data/map\n")
    edit_kit(root, lambda doc: doc.update(artifacts={"INHERITED_IMAGE": {"workload": "sim", "ref": PIN}}))
    kit = integrator_kit(tmp_path, root, artifacts={"API_IMAGE": {"workload": "api", "ref": OTHER_PIN}})
    directory = kit / "deployments/custom"
    (directory / "config.gpu.env").write_text("VALUE=kit-gpu\n")
    for path in (base / "config", directory / "config", kit / "overlay_ws", directory / "overlay_ws"):
        path.mkdir()
    site_config(root, "VALUE=site\n", name="custom")
    context = cli_manifest.load_kit(kit)
    deployment = cli_manifest.get_deployment(kit, context, "custom")
    assert deployment.requirements["gpu"] == "optional" and deployment.data[0]["name"] == "dataset"
    selection = deployment.select(context, "humble", True)
    assert deployment.compose_files(True) == [directory / "docker-compose.yaml", base / "gpu.yaml"]
    assert selection.environment["VALUE"] == "site" and selection.environment["BASE_GPU"] == "1"
    assert selection.injections["API_IMAGE"] == OTHER_PIN
    assert selection.injections["OPENADKIT_BASE_DEPLOYMENT"] == str(base)
    calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "custom", "--gpu", directory=kit)
    assert result.returncode == 0, result.stderr
    env = recorded(calls)[0]["env"]
    assert [env[name] for name in (
        "OPENADKIT_CONFIG_BASE", "OPENADKIT_CONFIG_DEPLOYMENT",
        "OPENADKIT_OVERLAY_WS", "OPENADKIT_OVERLAY_WS_DEPLOYMENT",
    )] == [
        str(base / "config"), str(directory / "config"),
        str(kit / "overlay_ws"), str(directory / "overlay_ws"),
    ]
    bom = json.loads(run_cli(root, "version", "--json", directory=kit).stdout)["bom"]
    assert bom["artifacts"]["INHERITED_IMAGE"]["ref"] == PIN
    assert (bom["images"] is not None) is release


def test_kit_may_leave_out_the_base_side_its_inherited_oneshots_belong_to(tmp_path):
    document = manifest()
    document["compose"]["resetServices"] = ["loader"]
    root, _ = runtime_tree(tmp_path, document=document)
    kit = integrator_kit(tmp_path, root)
    calls = fake_docker(tmp_path, services=("app", "acme"))
    # The base itself must still define its oneshots.
    result = run_cli(root, "validate", "example")
    assert result.returncode != 0 and "unknown Compose service(s): loader" in result.stderr
    assert run_cli(root, "validate", "custom", directory=kit).returncode == 0
    assert run_cli(root, "run", "custom", "--pull", "never", directory=kit).returncode == 0
    assert not any("rm" in row["args"] for row in recorded(calls))
    # A kit's own oneshot is checked like a base's.
    path = kit / "deployments/custom/deployment.json"
    document = json.loads(path.read_text())
    document["compose"]["resetServices"] = ["probe"]
    path.write_text(json.dumps(document))
    result = run_cli(root, "validate", "custom", directory=kit)
    assert result.returncode != 0 and "unknown Compose service(s): probe" in result.stderr


def test_build_overlay_builds_each_layer_in_the_pinned_devel_image(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    kit = integrator_kit(tmp_path, root)
    directory = kit / "deployments/custom"
    for workspace in (kit / "overlay_ws", directory / "overlay_ws"):
        (workspace / "src").mkdir(parents=True)
        (workspace / "install").mkdir()
    calls = fake_docker(tmp_path)
    # A release from before the devel pin: only an explicit image will do.
    result = run_cli(root, "build-overlay", "custom", directory=kit)
    assert result.returncode != 0 and "set DEVEL_IMAGE" in result.stderr

    devel = "ghcr.io/example/openadkit-common:universe-common-devel-humble@sha256:" + "d" * 64
    edit_kit(root, lambda doc: doc["images"]["humble"].update({"universe-common-devel": devel}))
    result = run_cli(root, "build-overlay", "custom", directory=kit)
    assert result.returncode == 0, result.stderr
    builds = [row["args"] for row in recorded(calls) if row["args"][:1] == ["run"]]
    assert len(builds) == 2 and all(devel in args for args in builds)
    # Each layer builds where the services mount it, on top of the layers below.
    assert f"{kit / 'overlay_ws'}:/openadkit/overlay_ws" in builds[0]
    assert f"{kit / 'overlay_ws'}:/openadkit/overlay_ws:ro" in builds[1]
    assert f"{directory / 'overlay_ws'}:/openadkit/overlay_ws_deployment" in builds[1]
    assert builds[1][-1] == "/openadkit/overlay_ws"
    stamp = json.loads((directory / "overlay_ws/install/.openadkit-overlay.json").read_text())
    assert stamp == {"image": devel, "rosDistro": "humble"}
    assert "overlay workspace" not in run_cli(root, "validate", "custom", directory=kit).stderr

    # After a base upgrade the installs are stale until rebuilt.
    edit_kit(root, lambda doc: doc["images"]["humble"].update({"universe-common-devel": devel[:-1] + "e"}))
    result = run_cli(root, "validate", "custom", directory=kit)
    assert result.returncode == 0 and "openadkit build-overlay custom" in result.stderr
    result = run_cli(root, "build-overlay", "custom", directory=kit, DEVEL_IMAGE="local/devel:test")
    assert result.returncode == 0 and "local/devel:test" in recorded(calls)[-1]["args"]

    # A build for another image starts clean, and so does every layer above it;
    # the same image builds incrementally.
    for workspace in (kit / "overlay_ws", directory / "overlay_ws"):
        (workspace / "build").mkdir(exist_ok=True)
        (workspace / "build/CMakeCache.txt").write_text("old")
    assert run_cli(root, "build-overlay", "custom", directory=kit).returncode == 0
    assert not (kit / "overlay_ws/build/CMakeCache.txt").exists()
    assert not (directory / "overlay_ws/build/CMakeCache.txt").exists()
    for workspace in (kit / "overlay_ws", directory / "overlay_ws"):
        (workspace / "install").mkdir(exist_ok=True)
        (workspace / "install/.openadkit-overlay.json").write_text(
            json.dumps({"image": devel[:-1] + "e", "rosDistro": "humble"}))
        (workspace / "build").mkdir(exist_ok=True)
        (workspace / "build/CMakeCache.txt").write_text("current")
    assert run_cli(root, "build-overlay", "custom", directory=kit).returncode == 0
    assert (kit / "overlay_ws/build/CMakeCache.txt").read_text() == "current"

    # Without a deployment a kit builds its own workspace, which all its deployments share.
    before = len(recorded(calls))
    result = run_cli(root, "build-overlay", directory=kit)
    assert result.returncode == 0, result.stderr
    builds = [row["args"] for row in recorded(calls)[before:] if row["args"][:1] == ["run"]]
    assert len(builds) == 1 and f"{kit / 'overlay_ws'}:/openadkit/overlay_ws" in builds[0]
    # Outside a kit there is no such workspace: a deployment is required.
    assert run_cli(root, "build-overlay").returncode == 2


OVERLAY_LAYERS = ("OPENADKIT_OVERLAY_WS", "OPENADKIT_OVERLAY_WS_DEPLOYMENT")


def overlay_layers(root, name, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for variable in ISOLATED_ENV:
        monkeypatch.delenv(variable, raising=False)
    context = cli_manifest.load_kit(root)
    injections = cli_manifest.get_deployment(root, context, name).select(context, "humble", False).injections
    return [injections[variable] for variable in OVERLAY_LAYERS], str(cli_manifest.state_root() / "empty")


@pytest.mark.parametrize("own", [False, True])
def test_kit_overlay_serves_every_deployment_and_one_may_layer_its_own(tmp_path, monkeypatch, own):
    root, _ = runtime_tree(tmp_path)
    kit = integrator_kit(tmp_path, root)
    directory = kit / "deployments/custom"
    (kit / "overlay_ws").mkdir()
    if own:
        (directory / "overlay_ws").mkdir()
    layers, empty = overlay_layers(kit, "custom", monkeypatch, tmp_path)
    assert layers == [str(kit / "overlay_ws"), str(directory / "overlay_ws") if own else empty]


def test_kit_whose_deployment_is_its_root_mounts_its_overlay_once(tmp_path, monkeypatch):
    root, _ = runtime_tree(tmp_path)
    kit = integrator_kit(tmp_path, root)
    directory = kit / "deployments/custom"
    for item in directory.iterdir():
        shutil.move(str(item), kit)
    shutil.rmtree(kit / "deployments")
    edit_kit(kit, lambda document: document["deployments"].update(custom={"path": "."}))
    # The deployment is the kit root, so the root is named after it (as deployments/custom-kit).
    kit = kit.rename(tmp_path / "custom")
    (kit / "overlay_ws").mkdir()
    layers, empty = overlay_layers(kit, "custom", monkeypatch, tmp_path)
    assert layers == [str(kit / "overlay_ws"), empty]


def test_base_deployment_keeps_its_own_overlay(tmp_path, monkeypatch):
    root, directory = runtime_tree(tmp_path)
    (directory / "overlay_ws").mkdir()
    layers, empty = overlay_layers(root, "example", monkeypatch, tmp_path)
    assert layers == [str(directory / "overlay_ws"), empty]


@pytest.mark.parametrize("available", [False, True])
def test_pinned_kit_uses_its_release_cli_or_fails_with_install_guidance(tmp_path, available):
    root, _ = runtime_tree(tmp_path)
    kit = integrator_kit(tmp_path, root, extends="v1.2.3")
    record = tmp_path / "delegated"
    if available:
        pinned = tmp_path / "home/.local/share/openadkit/openadkit-v1.2.3"
        pinned.mkdir(parents=True)
        (pinned / "openadkit.json").write_text('{"schemaVersion":2,"kind":"release"}')
        executable(pinned / "openadkit", "#!/usr/bin/env bash\n"
                   f'printf "%s|%s|%s\\n" "$OPENADKIT_KIT" "$OPENADKIT_DELEGATED" "$*" > "{record}"\n')
    result = run_cli(root, "run", "custom", "--pull", "never", directory=kit)
    assert (result.returncode == 0) is available, result.stderr
    if available:
        assert record.read_text().strip() == f"{kit}|1|run custom --pull never"
    else:
        assert "openadkit install --version v1.2.3" in result.stderr


def test_overlay_contract_leaves_the_hosts_site_settings_out(tmp_path, monkeypatch):
    # A documented image override in the site file is not a kit variable.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)
    root, _ = runtime_tree(tmp_path)
    kit = integrator_kit(tmp_path, root)
    (kit / "deployments/custom/config.env").write_text("VALUE=kit\nKIT_TYPO=1\n")
    site_config(root, f"API_IMAGE={OTHER_PIN}\nHOST_ONLY=1\n", name="custom")
    deployment = cli_manifest.get_deployment(kit, cli_manifest.load_kit(kit), "custom")
    used = cli_compose.kit_variables(deployment, False)
    assert {"VALUE", "KIT_TYPO", "OPENADKIT_BASE_DEPLOYMENT"} <= used
    assert not used & {"API_IMAGE", "HOST_ONLY"}


@pytest.mark.parametrize("site", [False, True])
def test_overlay_baseline_runs_the_hosts_images_but_not_the_kits(tmp_path, monkeypatch, site):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)
    root, _ = runtime_tree(tmp_path)
    kit = integrator_kit(tmp_path, root, artifacts={"API_IMAGE": {"workload": "api", "ref": OTHER_PIN}})
    host_image = "example.com/host/vehicle:1"
    if site:
        site_config(root, f"VEHICLE_SYSTEM_IMAGE={host_image}\n", name="custom")
    context = cli_manifest.load_kit(kit)
    deployment = cli_manifest.get_deployment(kit, context, "custom")
    selection = deployment.select(context, "humble", False)
    base_selection = deployment.base.select(context.base, "humble", False)
    baseline = cli_compose.baseline_injections(deployment, selection, context, base_selection)
    # The kit's artifact replaces the base's api image: the baseline keeps the base's.
    assert selection.injections["API_IMAGE"] == OTHER_PIN != baseline["API_IMAGE"]
    assert baseline["API_IMAGE"] == base_selection.injections["API_IMAGE"]
    # The host's override reaches both models, so it is no replacement.
    assert (baseline["VEHICLE_SYSTEM_IMAGE"] == selection.injections["VEHICLE_SYSTEM_IMAGE"] == host_image) is site


def test_overlay_contract_distinguishes_base_changes_from_added_services():
    mount = {"type": "bind", "source": "/base/dds.xml", "target": "/etc/dds.xml", "read_only": True}
    base = {"app": {"command": ["launch"], "image": PIN, "volumes": [mount]}}
    assert cli_compose.overlay_warnings(base, base, set()) == []
    changed = {"app": {"command": ["other"], "image": OTHER_PIN, "volumes": [
        mount, {"type": "bind", "source": "/kit", "target": "/opt/autoware/config"},
    ]}, "extra": {"command": ["custom"], "image": "custom"}}
    warnings = cli_compose.overlay_warnings(base, changed, {"TYPO"})
    assert [warning["rule"] for warning in warnings] == ["command", "image", "internal-mount", "variable"]
    assert all(warning.get("service") != "extra" for warning in warnings)
