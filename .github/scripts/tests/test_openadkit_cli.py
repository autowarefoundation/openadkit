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
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "cli"))

import catalog as cli_catalog  # noqa: E402
import compose as cli_compose  # noqa: E402
import data as cli_data  # noqa: E402
import live as cli_live  # noqa: E402
import manifest as cli_manifest  # noqa: E402
import settings as cli_settings  # noqa: E402

ENTRYPOINT = ROOT / "openadkit"
COMPONENT_IMAGES = json.loads((ROOT / "openadkit.json").read_text())["componentImages"]
PIN = f"registry.example/image@sha256:{'a' * 64}"
OTHER_PIN = f"registry.example/custom@sha256:{'b' * 64}"
ARCH = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
ISOLATED_ENV = (
    "XDG_CONFIG_HOME", "XDG_STATE_HOME", "OPENADKIT_HOME",
    "OPENADKIT_KIT", "OPENADKIT_DELEGATED", "COMPOSE_FILE", "XDG_DATA_HOME",
)


NEEDS_COMPOSE = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0,
    reason="needs Docker Compose",
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
        text=True, capture_output=True, timeout=30, stdin=subprocess.DEVNULL,
    )


def run_cli(root, *args, directory=None, **env):
    return command(root / "openadkit", *args, home=root.parent / "home",
                   bin_dir=root.parent / "bin", cwd=directory or root, **env)


def manifest(*, data=None, gpu=False, roles=False):
    document = {
        "description": "Test deployment", "waitTimeout": 1,
        "requirements": {"architectures": ["amd64", "arm64"], "rosDistros": ["humble", "jazzy"],
                         "gpu": "optional" if gpu else "none"},
        "data": data or [],
    }
    if roles:
        document["roles"] = {
            name: {"files": [f"compose.{name}.yaml"], "rosDomainId": domain,
                   "requiredEnv": ["ROLE_TOKEN"] if domain == 2 else []}
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
    (directory / "settings.env").write_text(config)
    # A deployment's own Compose files go by name, and an optional GPU mode
    # has an overlay; a role lists its files.
    gpu = document["requirements"]["gpu"] == "optional"
    files = ["compose.yaml", *(["compose.gpu.yaml"] if gpu else [])]
    files += [file for role in document.get("roles", {}).values() for file in role["files"]]
    for file in dict.fromkeys(files):
        (directory / file).write_text("services:\n  app:\n    image: busybox:1.36.1\n")
    if gpu:
        (directory / "settings.gpu.env").write_text("VALUE=base-gpu\nBASE_GPU=1\n")
    context = {
        "schemaVersion": 2, "kind": "release" if release else "source",
        "defaultRosDistro": "humble", "componentImages": COMPONENT_IMAGES,
        "deployments": {"example": {"path": "deployments/example"}},
    }
    if release:
        context.update(version="v1.2.3", shared={},
                       autoware={"version": "1.8.0", "ref": "a" * 40, "lockSha256": "b" * 64},
                       images={distro: dict.fromkeys(COMPONENT_IMAGES.values(), PIN)
                               for distro in ("humble", "jazzy")})
        context["deployments"]["example"]["checksum"] = cli_catalog.deployment_checksum(directory)
    else:
        context["imageRepository"] = "registry.example/openadkit"
    (root / "openadkit.json").write_text(json.dumps(context))
    return root, directory


def edit_manifest(root, change):
    path = root / "openadkit.json"
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document))


def edit_kit_deployment(kit, name="custom", **changes):
    """Change one deployment's entry in a kit's manifest."""
    edit_manifest(kit, lambda document: document["deployments"][name].update(changes))


def fake_docker(tmp_path, *, projects=(), stopped=(), containers=(), daemon=0, config=0, runtimes='{"nvidia": {}}',
                services=("app", "acme")):
    """One stateful stub shared by runtime and kit subprocess tests."""
    calls = tmp_path / "docker-calls"
    live = tmp_path / "projects.json"
    live.write_text(json.dumps([{"Name": name, "Status": "running(1)"} for name in projects]))
    # Projects whose containers are left but none runs: `compose ls` lists them only with --all.
    left = [{"Name": name, "Status": "exited(1)"} for name in stopped]
    service_lines = "\n".join(services)
    executable(tmp_path / "bin/docker", f'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
text = " ".join(args)
missing = os.environ.get("FAKE_MISSING", "").split(",")
exited = os.environ.get("FAKE_EXITED", "").split(",")
# Reading what the env files set, in a clean environment, is not a call to check.
if not ("config --environment" in text and "OPENADKIT_UID" not in os.environ):
    with open({str(calls)!r}, "a") as output:
        env = {{name: value for name, value in os.environ.items()
               if name.startswith("OPENADKIT_") or name in ("VEHICLE_SYSTEM_IMAGE", "VALUE", "ROS_DISTRO", "CYCLONEDDS_NETWORK_INTERFACE")}}
        output.write(json.dumps({{"args": args, "env": env}}) + "\\n")
live = Path({str(live)!r})
if "config --environment" in text:
    values = dict(os.environ)
    for index, argument in enumerate(args):
        if argument == "--env-file":
            for line in Path(args[index + 1]).read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    name, value = line.removeprefix("export ").split("=", 1)
                    name = name.strip()
                    if "OPENADKIT_UID" not in os.environ or name not in os.environ:
                        values[name] = value.strip().strip('"').replace("$HOME", os.environ["HOME"])
    print(chr(10).join(f"{{name}}={{value}}" for name, value in values.items() if chr(10) not in value))
elif text == "info":
    sys.exit({daemon})
if text == "info --format {{{{json .Runtimes}}}}":
    print({runtimes!r})
elif text == "compose ls --format json":
    print(live.read_text())
elif text == "compose ls --all --format json":
    print(json.dumps(json.loads(live.read_text()) + {left!r}))
elif text == "ps -aq":
    print("\\n".join(row['Id'] for row in {list(containers)!r}))
elif args[0] == "compose" and "ps" in args and "--format" in args:
    for name in {service_lines!r}.split():
        if name in missing:
            continue
        state, status = ("exited", "Exited (1) 5 seconds ago") if name in exited else ("running", "Up 1 minute")
        print(json.dumps({{"Service": name, "Name": "autoware-" + name, "State": state, "Status": status}}))
elif args[0] == "compose" and "ps" in args and "--services" in args:
    print("\\n".join(name for name in {service_lines!r}.split() if name not in missing and name not in exited))
elif args[0] == "compose" and "ps" in args and "--quiet" in args:
    print("\\n".join(row['Id'] for row in {list(containers)!r}))
elif args[0] == "inspect" and "--format" in args:
    template = args[args.index("--format") + 1]
    for row in {list(containers)!r}:
        labels = row.get("Config", {{}}).get("Labels", {{}})
        fields = {{
            "{{{{.Id}}}}": row["Id"], "{{{{.RestartCount}}}}": "0", "{{{{.State.Status}}}}": "running",
            "{{{{.State.ExitCode}}}}": "0", '{{{{with index .State "Health"}}}}{{{{.Status}}}}{{{{else}}}}none{{{{end}}}}': "none",
            '{{{{index .Config.Labels "com.docker.compose.service"}}}}': labels.get("com.docker.compose.service", row["Id"]),
            '{{{{index .Config.Labels "com.docker.compose.config-hash"}}}}': labels.get("com.docker.compose.config-hash", "same"),
        }}
        line = template
        for field, value in fields.items():
            line = line.replace(field, value)
        print(line)
elif args[0] == "inspect":
    print(json.dumps({list(containers)!r}))
elif "config --hash" in text:
    changed = os.environ.get("FAKE_CHANGED", "").split(",")
    for name in {service_lines!r}.split():
        print(name, "new" if name in changed else "same")
elif "config --format json" in text:
    # Services with restart: "no" run once and exit.
    once = os.environ.get("FAKE_ONE_SHOT", "").split(",")
    image = {{"image": os.environ["FAKE_IMAGE"]}} if os.environ.get("FAKE_IMAGE") else {{}}
    print(json.dumps({{"services": {{name: ({{"restart": "no"}} if name in once else {{}}) | image
                                    for name in {service_lines!r}.split()}}}}))
elif "config --services" in text:
    print({service_lines!r})
elif "config --quiet" in text:
    sys.exit({config})
elif args[:2] == ["image", "inspect"]:
    sys.exit(1 if os.environ.get("FAKE_NO_IMAGES") else 0)
elif args[0] == "compose" and "exec" in args:
    sys.exit(int(os.environ.get("FAKE_EXEC_EXIT", "0")))
elif args[0] == "run":
    sys.exit(int(os.environ.get("FAKE_RUN_EXIT", "0")))
elif "up --detach" in text:
    project = args[args.index("--project-name") + 1]
    files = ",".join(args[index + 1] for index, arg in enumerate(args) if arg == "--file")
    rows = json.loads(live.read_text())
    if not any(row["Name"] == project for row in rows):
        rows.append({{"Name": project, "Status": "running(1)", "ConfigFiles": files}})
    live.write_text(json.dumps(rows))
''')
    return calls


def recorded(calls):
    return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


def host_settings(root, text, name="example"):
    path = root.parent / f"home/.config/openadkit/{name}.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def extending_kit(tmp_path, root, *, extends=None, external_images=None):
    kit = tmp_path / "kit"
    directory = kit / "deployments/custom"
    directory.mkdir(parents=True)
    (kit / "openadkit.json").write_text(json.dumps({
        "schemaVersion": 2, "kind": "kit", "extends": extends or str(root),
        "deployments": {"custom": {"description": "Kit deployment", "base": "example"}},
        "externalImages": external_images or {},
    }))
    (directory / "settings.env").write_text("VALUE=kit\n")
    (directory / "compose.yaml").write_text(
        "include:\n  - ${OPENADKIT_BASE_DEPLOYMENT}/compose.yaml\n"
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
    files.update({f"cli/{name}.py": (ROOT / f"cli/{name}.py").read_bytes() for name in ("catalog", "compose", "manifest", "installation", "settings")})
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
    # A later release may list more bundles; the installer takes the one it knows by name.
    (release / "release-metadata.json").write_text(json.dumps({
        "version": version, "bom": {"autoware": {"version": "1.9.0"}}, "bundles": [
            {"name": f"{root_name}-extra.tar.gz", "sha256": "f" * 64},
            {"name": bundle.name,
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
    return command(ENTRYPOINT, "install", *args, home=tmp_path / "home", bin_dir=bin_dir,
                   OPENADKIT_HOME=str(tmp_path / "home/kit"))


def installed(tmp_path, version="v1.2.3"):
    return tmp_path / f"home/kit/releases/openadkit-{version}/openadkit"


def test_install_upgrade_and_uninstall_preserve_kept_versions(tmp_path):
    result = install(tmp_path, release_bin(tmp_path))
    assert result.returncode == 0 and "installed v1.2.3 (Autoware 1.9.0)" in result.stdout
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
    # The images take more space than the release; the message says they stay.
    assert "and the Docker images" in result.stdout and "docker image rm" in result.stdout



def test_an_installed_version_becomes_active_without_a_download(tmp_path):
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    launcher = tmp_path / "home/.local/bin/openadkit"
    newer = release_bin(tmp_path, "v1.3.0")
    assert command(launcher, "upgrade", home=tmp_path / "home", bin_dir=newer).returncode == 0
    kept = installed(tmp_path).parent / "marker"
    kept.write_text("kept")
    # Back to the kept version while offline: nothing is downloaded or replaced.
    offline = tmp_path / "offline"
    executable(offline / "curl", "#!/usr/bin/env bash\nexit 22\n")
    result = install(tmp_path, offline, "--version", "v1.2.3")
    assert result.returncode == 0 and "v1.2.3 is already installed" in result.stdout, result.stderr
    assert launcher.resolve() == installed(tmp_path) and kept.read_text() == "kept"
    # The latest version, once resolved, is used the same way; --force replaces it.
    marker = installed(tmp_path, "v1.3.0").parent / "marker"
    marker.write_text("kept")
    result = install(tmp_path, newer)
    assert result.returncode == 0 and launcher.resolve() == installed(tmp_path, "v1.3.0")
    assert marker.read_text() == "kept"
    assert install(tmp_path, newer, "--force").returncode == 0 and not marker.exists()
    # A directory that is no release is never taken for one.
    installed(tmp_path, "v1.3.0").unlink()
    result = install(tmp_path, newer)
    assert result.returncode != 0 and "is not an installed release" in result.stderr


def test_upgrade_uses_an_installed_latest_version_as_it_is(tmp_path):
    older, newer = release_bin(tmp_path), release_bin(tmp_path, "v1.3.0")
    assert install(tmp_path, older).returncode == 0
    launcher = tmp_path / "home/.local/bin/openadkit"
    # The latest version is installed but not active, as a kit pins it.
    assert install(tmp_path, newer, "--version", "v1.3.0").returncode == 0
    assert install(tmp_path, older, "--version", "v1.2.3").returncode == 0
    marker = installed(tmp_path, "v1.3.0").parent / "marker"
    marker.write_text("in use")
    result = command(launcher, "upgrade", home=tmp_path / "home", bin_dir=newer)
    assert result.returncode == 0, result.stderr
    assert launcher.resolve() == installed(tmp_path, "v1.3.0") and marker.read_text() == "in use"
    # A leftover that is not a release is replaced.
    assert install(tmp_path, older, "--version", "v1.2.3").returncode == 0
    installed(tmp_path, "v1.3.0").unlink()
    result = command(launcher, "upgrade", home=tmp_path / "home", bin_dir=newer)
    assert result.returncode == 0, result.stderr
    assert installed(tmp_path, "v1.3.0").is_file() and not marker.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root removes a read-only directory anyway")
def test_uninstall_removes_the_launcher_before_the_release(tmp_path):
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    launcher = tmp_path / "home/.local/bin/openadkit"
    stuck = installed(tmp_path).parent / "stuck"
    (stuck / "inner").mkdir(parents=True)
    stuck.chmod(0o500)
    fake_docker(tmp_path)
    try:
        result = command(launcher, "uninstall", home=tmp_path / "home", bin_dir=tmp_path / "bin")
    finally:
        stuck.chmod(0o700)
    assert result.returncode != 0 and f"could not remove {installed(tmp_path).parent}" in result.stderr
    assert not launcher.exists() and not launcher.is_symlink()


def test_a_failed_download_exits_1_with_an_error_line(tmp_path):
    offline = tmp_path / "offline"
    executable(offline / "curl", "#!/usr/bin/env bash\nexit 22\n")
    result = install(tmp_path, offline)
    assert result.returncode == 1, result.stderr
    assert "error: could not download the release metadata of the latest release" in result.stderr
    result = install(tmp_path, offline, "--version", "v1.2.3")
    assert result.returncode == 1 and "error: could not download the release metadata of v1.2.3" in result.stderr
    # upgrade resolves the latest release through the same installer.
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    launcher = tmp_path / "home/.local/bin/openadkit"
    result = command(launcher, "upgrade", home=tmp_path / "home", bin_dir=offline)
    assert result.returncode == 1 and "error: could not download the release metadata" in result.stderr


def test_uninstall_all_removes_kept_releases_but_not_lookalike_directories(tmp_path):
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    launcher = tmp_path / "home/.local/bin/openadkit"
    assert command(launcher, "upgrade", home=tmp_path / "home", bin_dir=release_bin(tmp_path, "v1.3.0")).returncode == 0
    backup = tmp_path / "home/kit/releases/openadkit-v1.2.3-backup"
    backup.mkdir()
    (backup / "notes.txt").write_text("the user's own")
    fake_docker(tmp_path)
    result = command(launcher, "uninstall", "--all", home=tmp_path / "home", bin_dir=tmp_path / "bin")
    assert result.returncode == 0, result.stderr
    assert not installed(tmp_path).exists() and not installed(tmp_path, "v1.3.0").exists()
    assert (backup / "notes.txt").read_text() == "the user's own"

def test_install_adds_completion_and_uninstall_removes_only_its_link(tmp_path):
    home = tmp_path / "home"
    completions = home / ".local/share/bash-completion/completions"
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    assert (completions / "openadkit").resolve() == installed(tmp_path).parent / "cli/completion.bash"
    assert not (home / ".local/bin/adkit").exists()
    fake_docker(tmp_path)
    result = command(home / ".local/bin/openadkit", "uninstall", home=home, bin_dir=tmp_path / "bin")
    assert result.returncode == 0, result.stderr
    assert not (completions / "openadkit").is_symlink()
    # A completion file of the user's own stays as it is.
    (completions / "openadkit").write_text("# the user's own\n")
    assert install(tmp_path, release_bin(tmp_path, "v1.3.0")).returncode == 0
    assert (completions / "openadkit").read_text() == "# the user's own\n"


def test_the_install_root_comes_only_from_the_environment(tmp_path):
    home = tmp_path / "home"
    result = command(ENTRYPOINT, "install", "--destination", str(home / "kit"), home=home, bin_dir=release_bin(tmp_path))
    assert result.returncode == 2 and "unknown install option: --destination" in result.stderr
    result = command(ENTRYPOINT, "install", home=home, bin_dir=tmp_path / "bin", OPENADKIT_HOME="relative")
    assert result.returncode != 0 and "OPENADKIT_HOME must be an absolute path" in result.stderr

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
    assert {"run", "build", "record"} <= complete(root, ["openadkit", ""])
    assert complete(root, ["openadkit", "bui"]) == {"build"}
    assert complete(root, ["openadkit", "run", "--no-"]) == {"--no-visualizer"}
    assert complete(root, ["openadkit", "run", "--ros-distro", ""]) == {"humble", "jazzy"}
    assert complete(root, ["openadkit", "run", "ex"]) == {"example"}
    assert complete(root, ["openadkit", "run", "--ros-distro", "jazzy", ""]) == {"example"}
    assert complete(root, ["openadkit", "config", ""]) == {"example"}
    # One deployment per command; list takes none.
    assert complete(root, ["openadkit", "run", "example", ""]) == set()
    assert complete(root, ["openadkit", "list", ""]) == set()


def test_version_pairs_the_release_with_its_autoware_also_in_a_kit(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    assert run_cli(root, "version").stdout.splitlines()[0] == "Open AD Kit v1.2.3 · Autoware 1.8.0"
    kit = extending_kit(tmp_path, root)
    output = run_cli(root, "version", directory=kit).stdout
    assert f"autoware: 1.8.0 ({'a' * 40})" in output.splitlines()
    # A line's backported fixes show with the Autoware they patch.
    edit_manifest(root, lambda doc: doc["autoware"].update(backports=[
        {"repository": "universe/autoware_universe", "subject": "fix", "upstream": "https://example.com/pull/1"}]))
    assert f"autoware: 1.8.0 ({'a' * 40}, 1 backported fix)" in run_cli(root, "version").stdout.splitlines()


@pytest.mark.parametrize("verbose", [[], ["--verbose"]])
def test_docker_commands_show_only_when_verbose(tmp_path, verbose):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path, services=("app",))
    result = run_cli(root, "validate", "example", *verbose)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "example is valid (ROS 2 Humble, without GPU)\n"
    assert ("+ docker compose" in result.stderr) is bool(verbose)


@pytest.mark.parametrize("name", [[], ["missing"]])
def test_validate_json_reports_an_invalid_deployment_as_json(tmp_path, name):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path)
    result = run_cli(root, "validate", *name, "--json")
    # A missing name is a usage error; it too comes as one JSON document.
    assert result.returncode == (1 if name else 2)
    document = json.loads(result.stdout)
    assert document["valid"] is False and document["error"]
    assert name or document["error"] == "deployment name required; available: example"
    valid = json.loads(run_cli(root, "validate", "example", "--json").stdout)
    assert valid["valid"] is True and valid["deployment"] == "example"
    listed = json.loads(run_cli(root, "list", "--json").stdout)["deployments"]
    # Nothing vouches for a source checkout's files.
    assert [entry["modified"] for entry in listed] == [None]


def test_the_json_output_has_the_fields_the_reference_lists(tmp_path):
    # docs/releases/reference.md lists these fields, and 2.0 freezes them: a
    # field that goes or changes its name is a breaking change.
    document = manifest(data=[files_resource(tmp_path)]) | {"verify": {"service": "app", "command": ["true"]}}
    root, _ = runtime_tree(tmp_path, release=True, document=document)
    fake_docker(tmp_path, services=("app",))

    def output(*args):
        return json.loads(run_cli(root, *args).stdout)

    listed = output("list", "--json")
    assert set(listed) == {"schemaVersion", "deployments"}
    assert set(listed["deployments"][0]) == {"name", "description", "requirements", "modified"}
    # As in the manifest: one name for one thing.
    assert set(listed["deployments"][0]["requirements"]) == {"architectures", "rosDistros", "gpu"}
    version = output("version", "--json")
    assert set(version) == {"schemaVersion", "kind", "version", "commit", "extends", "bom"}
    assert set(version["bom"]) == {"autoware", "images", "externalImages"}
    assert set(version["bom"]["autoware"]) == {"version", "ref", "lockSha256"}
    valid = output("validate", "example", "--data", "--json")
    assert set(valid) == {"schemaVersion", "deployment", "valid", "base", "rosDistro", "gpu", "role", "dataValid", "data"}
    assert set(valid["data"][0]) == {"name", "status"}
    assert set(output("validate", "missing", "--json")) == {"schemaVersion", "deployment", "valid", "error"}
    assert run_cli(root, "run", "example", "--verify").returncode == 0
    record = json.loads((root.parent / "home/openadkit-output/example/results/run.json").read_text())
    assert set(record) == {"schemaVersion", "deployment", "role", "rosDistro", "gpu", "version", "extends", "images",
                           "modelSha256", "configSha256", "overlaySha256", "readySeconds", "verify"}
    assert set(record["configSha256"]) == {"base", "kit", "deployment"}
    assert set(record["verify"]) == {"service", "seconds", "exitCode", "result"}
    for document in (listed, version, valid, record):
        assert document["schemaVersion"] == 1


def test_list_shows_name_gpu_and_description(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest(gpu=True))
    lines = run_cli(root, "list").stdout.splitlines()
    assert lines[0].split() == ["NAME", "GPU", "DESCRIPTION"]
    assert lines[1].split()[:2] == ["example", "optional"]


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
        assert flags | {"--help"} == options[name], name
    # Deployment names are offered to exactly the commands that take one.
    named = re.search(r"case \$\{command\} in\n\s+([a-z| ]+)\) ;;\n\s+\*\) return ;;", text).group(1)
    assert {name.strip() for name in named.split("|")} == {
        name for name, command in cli_main.COMMANDS.items() if command.group == "deployment"}


def test_install_defaults_to_the_root_kits_resolve_extends_from(tmp_path):
    result = command(ENTRYPOINT, "install", home=tmp_path / "home", bin_dir=release_bin(tmp_path))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/.local/share/openadkit/openadkit-v1.2.3/openadkit").is_file()
    # OPENADKIT_HOME puts everything under one directory, the releases included.
    result = command(ENTRYPOINT, "install", home=tmp_path / "home", bin_dir=release_bin(tmp_path, "v1.3.0"),
                     OPENADKIT_HOME=str(tmp_path / "oak"))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "oak/releases/openadkit-v1.3.0/openadkit").is_file()


def test_openadkit_home_holds_settings_state_output_and_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENADKIT_HOME", raising=False)
    assert cli_catalog.data_root() == tmp_path / "home/autoware_data"
    assert cli_catalog.output_root() == tmp_path / "home/openadkit-output"
    monkeypatch.setenv("OPENADKIT_HOME", str(tmp_path / "oak"))
    assert [cli_catalog.settings_root(), cli_catalog.state_root(), cli_catalog.output_root(),
            cli_catalog.data_root(), cli_catalog.install_root()] == [
        tmp_path / "oak" / part for part in ("settings", "state", "output", "data", "releases")]
    monkeypatch.setenv("OPENADKIT_HOME", "relative")
    with pytest.raises(cli_manifest.OpenADKitError, match="must be an absolute path"):
        cli_catalog.data_root()


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
               f'if [[ $# -eq 3 && "$1" == -T && "$3" == "{root}" && "$2" == *".openadkit-stage."* ]]; then {stop}; fi\n'
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


def test_upgrade_crosses_a_major_version_and_says_so(tmp_path):
    assert install(tmp_path, release_bin(tmp_path)).returncode == 0
    launcher = tmp_path / "home/.local/bin/openadkit"
    minor, major = release_bin(tmp_path, "v1.3.0"), release_bin(tmp_path, "v2.0.0")
    note = "v2.0.0 is a major release: its release notes list the breaking changes"
    result = command(launcher, "upgrade", "--check", home=tmp_path / "home", bin_dir=minor)
    assert result.returncode == 0 and "major release" not in result.stdout, result.stderr
    result = command(launcher, "upgrade", "--check", home=tmp_path / "home", bin_dir=major)
    assert result.returncode == 0 and note in result.stdout, result.stderr
    result = command(launcher, "upgrade", home=tmp_path / "home", bin_dir=major)
    assert result.returncode == 0, result.stderr
    assert f"{note}. To go back, run: openadkit install --version v1.2.3" in result.stdout
    assert launcher.resolve() == installed(tmp_path, "v2.0.0")


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
                                   config="VEHICLE_SYSTEM_IMAGE=base\nVALUE=base\n")
    host_settings(root, f"VEHICLE_SYSTEM_IMAGE={OTHER_PIN}\nVALUE=site\n")
    calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", "--gpu", VEHICLE_SYSTEM_IMAGE="shell", VALUE="shell")
    assert result.returncode == 0, result.stderr
    first = recorded(calls)[0]
    assert first["env"].get("VALUE") is None  # Compose, not the shell, loads file-defined values.
    # A release pins its images; a source checkout's env files may set their own.
    assert first["env"].get("VEHICLE_SYSTEM_IMAGE") == (PIN if release else None)
    env_files = [first["args"][index + 1] for index, arg in enumerate(first["args"]) if arg == "--env-file"]
    assert env_files == [str(directory / "settings.env"), str(directory / "settings.gpu.env"),
                         str(tmp_path / "home/.config/openadkit/example.env")]


@pytest.mark.parametrize("problem", ["mutable", "missing"])
def test_release_image_failures_prevent_compose(tmp_path, problem):
    root, _ = runtime_tree(tmp_path, release=True)
    edit_manifest(root, lambda kit: kit["images"]["humble"].update(control="registry.example/control:latest")
             if problem == "mutable" else kit["images"]["humble"].pop("control"))
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
    ({"runtimes": "{}"}, ["--gpu"], "NVIDIA Container Toolkit is unavailable for the selected GPU mode; run: openadkit setup --gpu"),
    ({"config": 1}, [], "failed"),
])
def test_run_preflight_does_not_touch_data_or_start_containers(tmp_path, options, args, message):
    root, _ = runtime_tree(tmp_path, document=manifest(gpu=True))
    calls = fake_docker(tmp_path, **options)
    result = run_cli(root, "run", "example", *args)
    assert result.returncode != 0 and message in result.stderr
    assert not any("up" in row["args"] or "pull" in row["args"] for row in recorded(calls))
    assert not (tmp_path / "home/data").exists()


@pytest.mark.parametrize("role", [None, "secondary"])
def test_a_split_role_keeps_dds_on_loopback(tmp_path, role):
    # A LAN interface in the host settings would put DDS on the network and
    # around the Zenoh allowlist; only a single-host run may opt in to that.
    root, _ = runtime_tree(tmp_path, document=manifest(roles=role is not None))
    site = root.parent / "home/.config/openadkit/example.env"
    site.parent.mkdir(parents=True, exist_ok=True)
    site.write_text("CYCLONEDDS_NETWORK_INTERFACE=eth0\n")
    calls = fake_docker(tmp_path)
    args = ["--role", role] if role else []
    result = run_cli(root, "run", "example", *args, ROLE_TOKEN="token")
    assert result.returncode == 0, result.stderr
    up = next(row for row in recorded(calls) if "up" in row["args"])
    assert up["env"].get("CYCLONEDDS_NETWORK_INTERFACE") == ("lo" if role else None)


def test_split_role_run_discovery_and_safe_stop(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest(roles=True))
    calls = fake_docker(tmp_path)
    blocked = run_cli(root, "run", "example", "--role", "secondary")
    assert blocked.returncode != 0 and "ROLE_TOKEN" in blocked.stderr
    # Only the settings were read; nothing started.
    assert all("--environment" in row["args"] for row in recorded(calls))
    result = run_cli(root, "run", "example", "--role", "secondary", ROLE_TOKEN="token")
    assert result.returncode == 0, result.stderr
    rows = recorded(calls)
    up = next(row for row in rows if "up" in row["args"])
    assert "openadkit-example_secondary" in up["args"]
    assert up["env"]["OPENADKIT_ROS_DOMAIN_ID"] == "2"
    assert str(root / "deployments/example/compose.secondary.yaml") in up["args"]
    assert not any("zenoh" in arg or arg.endswith("compose.yaml") for arg in up["args"])
    calls.write_text("")
    # stop finds the stack from Docker, from any directory.
    result = run_cli(root, "stop", directory=tmp_path)
    assert result.returncode == 0, result.stderr
    down = next(row["args"] for row in recorded(calls) if "down" in row["args"])
    assert "openadkit-example_secondary" in down and "--volumes" not in down


@pytest.mark.parametrize("exit_code", [0, 7])
def test_run_verify_runs_the_command_in_its_service_once_ready(tmp_path, exit_code):
    document = manifest() | {"verify": {"service": "app", "command": ["python3", "/openadkit/checks/drive_to_goal.py"]}}
    root, _ = runtime_tree(tmp_path, document=document)
    calls = fake_docker(tmp_path, services=("app",))
    result = run_cli(root, "run", "example", "--verify", FAKE_EXEC_EXIT=str(exit_code))
    assert result.returncode == exit_code, result.stderr
    rows = [row["args"] for row in recorded(calls)]
    up = next(index for index, args in enumerate(rows) if "up" in args)
    exec_index, exec_args = next((index, args) for index, args in enumerate(rows) if "exec" in args)
    # Readiness is `up --wait`; the step runs after it, in the service, with ROS sourced.
    assert up < exec_index and "--wait" in rows[up]
    assert exec_args[exec_args.index("exec") + 1:exec_args.index("exec") + 3] == ["-T", "app"]
    assert exec_args[-2:] == ["python3", "/openadkit/checks/drive_to_goal.py"]
    record = json.loads((root.parent / "home/openadkit-output/example/results/run.json").read_text())
    assert record["deployment"] == "example" and record["rosDistro"] == "humble"
    assert record["verify"]["service"] == "app" and record["verify"]["exitCode"] == exit_code
    assert record["verify"]["result"] == ("PASSED" if exit_code == 0 else "FAILED")


def test_every_run_records_what_it_started(tmp_path):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path, services=("app",))
    result = run_cli(root, "run", "example")
    assert result.returncode == 0, result.stderr
    record = json.loads((root.parent / "home/openadkit-output/example/results/run.json").read_text())
    # The fake model's service names no image; its digest still identifies the model.
    model = json.dumps({"services": {"app": {}}}) + "\n"
    assert record["images"] == {"app": None} and record["modelSha256"] == hashlib.sha256(model.encode()).hexdigest()
    assert record["role"] is None and record["gpu"] is False and "verify" not in record
    # What the services mount from the host is identified by its content.
    assert set(record["configSha256"]) == {"base", "kit", "deployment"}
    override = root / "deployments/example/config/autoware/pkg/params.yaml"
    override.parent.mkdir(parents=True)
    override.write_text("rate: 1\n")
    assert run_cli(root, "run", "example").returncode == 0
    changed = json.loads((root.parent / "home/openadkit-output/example/results/run.json").read_text())
    assert changed["configSha256"]["deployment"] != record["configSha256"]["deployment"]
    assert changed["configSha256"]["base"] == record["configSha256"]["base"]
    assert changed["overlaySha256"] == record["overlaySha256"]


def test_run_verify_needs_a_verify_step(tmp_path):
    root, _ = runtime_tree(tmp_path)
    calls = fake_docker(tmp_path)
    result = run_cli(root, "run", "example", "--verify")
    assert result.returncode != 0 and "example declares no verify step" in result.stderr
    assert not any("up" in row["args"] for row in recorded(calls))


def test_verify_waits_for_a_service_without_a_command(tmp_path, monkeypatch):
    document = manifest() | {"verify": {"service": "scenario"}}
    root, _ = runtime_tree(tmp_path, document=document)
    kit = cli_catalog.load_catalog(root)
    deployment = cli_catalog.get_deployment(root, kit, "example")
    monkeypatch.setenv("OPENADKIT_HOME", str(tmp_path / "oak"))
    captured = []
    monkeypatch.setattr(cli_compose, "run_compose", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "c1\n", ""))
    monkeypatch.setattr(cli_compose, "docker", lambda command, **kwargs: captured.append(command) or subprocess.CompletedProcess(command, 0, "3\n", ""))
    selection = cli_settings.Selection(ros_distro="humble", gpu=False, role=None, injections={}, environment={})
    record = {"deployment": "example"}
    assert cli_compose.verify(deployment, selection, {"scenario"}, record) == 3
    assert captured == [["docker", "wait", "c1"]]
    assert record["verify"]["exitCode"] == 3 and record["verify"]["result"] == "FAILED"
    # A role without the service has nothing to verify.
    assert cli_compose.verify(deployment, selection, {"other"}, {}) == 0


def test_a_kit_inherits_the_verify_step_of_its_base_unless_it_names_one(tmp_path):
    verify = {"service": "app", "command": ["python3", "drive_to_goal.py"]}
    root, _ = runtime_tree(tmp_path, document=manifest() | {"verify": verify})
    kit_root = extending_kit(tmp_path, root)
    kit = cli_catalog.load_catalog(kit_root)
    assert cli_catalog.get_deployment(kit_root, kit, "custom").verify == verify
    edit_kit_deployment(kit_root, verify={"service": "acme"})
    kit = cli_catalog.load_catalog(kit_root)
    assert cli_catalog.get_deployment(kit_root, kit, "custom").verify == {"service": "acme"}


def test_a_kit_that_leaves_out_its_bases_verify_service_has_no_verify_step(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest() | {"verify": {"service": "runner"}})
    kit = extending_kit(tmp_path, root)
    fake_docker(tmp_path, services=("app", "acme"))
    assert run_cli(root, "validate", "custom", directory=kit).returncode == 0
    result = run_cli(root, "run", "custom", "--verify", directory=kit)
    assert result.returncode != 0 and "custom declares no verify step" in result.stderr
    # A verify step the kit names itself is checked like a base's.
    edit_kit_deployment(kit, verify={"service": "runner"})
    result = run_cli(root, "validate", "custom", directory=kit)
    assert result.returncode != 0 and "unknown Compose service(s): runner" in result.stderr


@pytest.mark.parametrize(("verify", "message"), [
    ({"command": ["true"]}, "verify.service must be a nonempty string"),
    ({"service": "app", "command": []}, "verify.command"),
    ({"service": "app", "timeout": 5}, "unknown verify field(s): timeout"),
])
def test_invalid_verify_steps_are_rejected(tmp_path, verify, message):
    root, _ = runtime_tree(tmp_path, document=manifest() | {"verify": verify})
    with pytest.raises(cli_manifest.OpenADKitError, match=re.escape(message)):
        cli_catalog.get_deployment(root, cli_catalog.load_catalog(root), "example")


def test_a_verify_service_must_be_in_the_compose_graph(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest() | {"verify": {"service": "missing"}})
    fake_docker(tmp_path, services=("app",))
    result = run_cli(root, "validate", "example")
    assert result.returncode != 0 and "unknown Compose service(s): missing" in result.stderr


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
    host_settings(root, "NOVNC_CERT=/certs/novnc.crt\nNOVNC_KEY=/certs/novnc.key\n")
    result = run_cli(root, "run", "example")
    assert result.returncode == 0, result.stderr
    assert "visualizer: https://localhost:6080/vnc.html" in result.stdout


@pytest.mark.parametrize(("projects", "args", "message"), [
    (["openadkit-example_primary"], [], "already running as role primary"),
    (["openadkit-example"], ["--role", "primary"], "already running as single-host"),
    (["openadkit-other"], [], "already running"),
])
def test_incompatible_live_projects_cannot_be_started_over(tmp_path, projects, args, message):
    root, _ = runtime_tree(tmp_path, document=manifest(roles=True))
    edit_manifest(root, lambda kit: kit["deployments"].update(other={"path": "deployments/other"}))
    calls = fake_docker(tmp_path, projects=projects)
    result = run_cli(root, "run", "example", *args)
    assert result.returncode != 0 and message in result.stderr
    assert not any("up" in row["args"] for row in recorded(calls))


@pytest.mark.parametrize("target", ["base", "kit"])
def test_run_rejects_live_projects_from_the_other_kit_catalog(tmp_path, target):
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    kit = extending_kit(tmp_path, root)
    name, other = ("example", "custom") if target == "base" else ("custom", "example")
    calls = fake_docker(tmp_path, projects=[f"openadkit-{other}"])
    result = run_cli(root, "run", name, directory=root if target == "base" else kit)
    assert result.returncode != 0 and f"error: {other} is already running" in result.stderr
    assert not (tmp_path / "home/data").exists()
    assert not any("up" in row["args"] or "pull" in row["args"] for row in recorded(calls))


@pytest.mark.parametrize(("project", "allowed"), [("openadkit-example_primary", True),
                                                ("openadkit-example_secondary", True),
                                                ("openadkit-example_foreign", False)])
def test_exclusivity_only_allows_declared_roles_of_the_selected_deployment(tmp_path, monkeypatch, project, allowed):
    root, _ = runtime_tree(tmp_path, document=manifest(roles=True))
    kit = cli_catalog.load_catalog(root)
    deployment = cli_catalog.get_deployment(root, kit, "example")
    monkeypatch.setattr(cli_compose, "live_project_files", lambda: {project: []})
    assert cli_compose.other_projects(deployment) == ([] if allowed else [project])


@pytest.mark.parametrize("started_from", ["own", "elsewhere", "other-role"])
def test_run_treats_a_same_named_project_from_another_directory_as_foreign(tmp_path, monkeypatch, started_from):
    root, directory = runtime_tree(tmp_path, document=manifest(roles=True))
    kit = cli_catalog.load_catalog(root)
    deployment = cli_catalog.get_deployment(root, kit, "example")
    # Another kit's "example" has the same project name as this one's
    # single-host or primary project.
    entry = {"own": directory / "compose.yaml", "elsewhere": tmp_path / "other-kit/compose.yaml",
             "other-role": directory / "compose.secondary.yaml"}[started_from]
    live = {"openadkit-example": [str(entry)], "openadkit-example_primary": [str(entry).replace(
        "compose.yaml", "compose.primary.yaml")]}
    monkeypatch.setattr(cli_compose, "live_project_files", lambda: live)
    # run must not replace another stack in place; stop still reaches it by name.
    assert cli_compose.other_projects(deployment) == ([] if started_from == "own" else sorted(live))
    assert cli_compose.live_roles(deployment) == [None, "primary"]


@NEEDS_COMPOSE
def test_a_required_setting_may_be_built_on_a_shell_variable(tmp_path, monkeypatch):
    for variable in ISOLATED_ENV:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MY_TOKEN", "secret")
    monkeypatch.delenv("ROLE_TOKEN", raising=False)
    root, _ = runtime_tree(tmp_path, document=manifest(roles=True))
    host_settings(root, "ROLE_TOKEN=${MY_TOKEN}\n")
    kit = cli_catalog.load_catalog(root)
    deployment = cli_catalog.get_deployment(root, kit, "example")
    selection = cli_settings.resolve(deployment, kit, "humble", role="secondary")
    assert selection.environment["ROLE_TOKEN"] == "secret"


def test_a_role_is_never_read_from_a_deployment_name(monkeypatch):
    # planning-simulation running single-host is not role "simulation" of anything.
    monkeypatch.setattr(cli_live, "live_projects", lambda: {"openadkit-planning-simulation", "openadkit-split_simulation"})
    assert cli_live.running_projects("simulation") == ["openadkit-split_simulation"]


def test_several_live_roles_stop_together_but_take_one_target_otherwise(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest(roles=True))
    calls = fake_docker(tmp_path, projects=["openadkit-example_primary", "openadkit-example_secondary"])
    result = run_cli(root, "logs")
    assert result.returncode != 0 and "choose one with --role" in result.stderr
    assert run_cli(root, "logs", "--role", "primary").returncode == 0
    assert recorded(calls)[-1]["args"][:4] == ["compose", "--project-name", "openadkit-example_primary", "logs"]
    assert run_cli(root, "stop", "--role", "secondary").returncode == 0
    assert [row["args"][2] for row in recorded(calls) if "down" in row["args"]] == ["openadkit-example_secondary"]
    assert run_cli(root, "stop").returncode == 0
    assert [row["args"][2] for row in recorded(calls) if "down" in row["args"]][1:] == [
        "openadkit-example_primary", "openadkit-example_secondary"]


def test_a_role_starts_exactly_the_files_its_manifest_lists(tmp_path):
    # No file is found by its name: not the role's own, and none beside it.
    document = manifest(roles=True)
    document["roles"]["primary"]["files"] = ["autoware-side.yaml", "link.yaml"]
    root, directory = runtime_tree(tmp_path, document=document)
    for stray in ("compose.primary.yaml", "compose.zenoh.yaml", "compose.bridge.yaml"):
        (directory / stray).write_text("services: {}\n")
    deployment = cli_catalog.get_deployment(root, cli_catalog.load_catalog(root), "example")
    assert deployment.compose_files(False, "primary") == [directory / "autoware-side.yaml", directory / "link.yaml"]
    assert deployment.compose_files(False, "secondary") == [directory / "compose.secondary.yaml"]
    assert deployment.compose_files(False) == [directory / "compose.yaml"]
    calls = fake_docker(tmp_path)
    assert run_cli(root, "validate", "example", "--role", "primary").returncode == 0
    rendered = [row["args"] for row in recorded(calls) if "openadkit-example_primary" in row["args"]][-1]
    files = [rendered[index + 1] for index, flag in enumerate(rendered) if flag == "--file"]
    assert files == [str(directory / "autoware-side.yaml"), str(directory / "link.yaml")]


@pytest.mark.parametrize(("files", "message"), [
    (None, "roles.primary.files must be an array of nonempty strings"),
    ("compose.primary.yaml", "roles.primary.files must be an array of nonempty strings"),
    ([], "roles.primary.files must not be empty"),
    (["compose.primary.yaml", "compose.primary.yaml"], "roles.primary.files contains duplicate values"),
    (["absent.yaml"], "missing Compose file"),
    (["../outside.yaml"], "Compose file must be a safe relative path"),
    (["linked.yaml"], "symlinked Compose file is not allowed"),
])
def test_a_role_needs_its_files_before_compose(tmp_path, files, message):
    document = manifest(roles=True)
    root, directory = runtime_tree(tmp_path, document=document)
    (tmp_path / "outside.yaml").write_text("services: {}\n")
    (directory / "linked.yaml").symlink_to(tmp_path / "outside.yaml")
    if files is None:
        del document["roles"]["primary"]["files"]
    else:
        document["roles"]["primary"]["files"] = files
    (directory / "deployment.json").write_text(json.dumps(document))
    calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", "--role", "primary")
    assert result.returncode != 0 and message in result.stderr
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
        cli_manifest.validate_data([resource], {}, tmp_path)



def test_data_file_shipped_with_the_deployment_installs_by_checksum(tmp_path):
    shipped = {"name": "dataset", "kind": "files", "destinationEnv": "MAP_PATH", "requiredFiles": ["required.txt"],
               "files": [{"path": "required.txt", "source": "data/map.txt",
                          "sha256": hashlib.sha256(b"shipped").hexdigest()}]}
    root, directory = runtime_tree(tmp_path, document=manifest(data=[shipped]))
    fake_docker(tmp_path)
    result = run_cli(root, "fetch", "example")
    assert result.returncode != 0 and "missing data[0].files[0].source" in result.stderr
    (directory / "data").mkdir()
    (directory / "data/map.txt").write_text("changed")
    # Checked with the manifest, so validate fails as well as fetch.
    for command in (("validate", "example"), ("fetch", "example")):
        result = run_cli(root, *command)
        assert result.returncode != 0 and "data/map.txt does not match its sha256" in result.stderr
    (directory / "data/map.txt").write_text("shipped")
    result = run_cli(root, "fetch", "example")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/data/map/required.txt").read_text() == "shipped"


def test_data_file_takes_exactly_one_of_url_source_and_content(tmp_path):
    resource = files_resource(tmp_path)
    resource["files"][0]["source"] = "data/map.txt"
    with pytest.raises(cli_manifest.OpenADKitError, match="exactly one of url, source and content"):
        cli_manifest.validate_data([resource], {}, tmp_path)


def test_the_recipe_of_the_data_marker_is_frozen():
    # Releases on one host share installed data: another recipe would make each
    # of them take the other's data for outdated and download it again in turns.
    archive = {"name": "map", "kind": "zip", "destinationEnv": "MAP_PATH", "url": "https://example.com/a.zip",
               "sha256": "a" * 64, "expectedRoot": "map", "files": []}
    files = {"name": "map", "kind": "files", "destinationEnv": "MAP_PATH", "files": [
        {"path": "b.osm", "url": "https://example.com/b.osm", "sha256": "b" * 64},
        {"path": "a.yaml", "content": "projector_type: Local\n"}]}
    assert cli_data.source_digest(archive) == "48bdc21d1bd90c55265f864f54d4816771394bda85df61fbc1eb403ef1eb2fe6"
    assert cli_data.source_digest(files) == "7e6892c3375143b67166e636424e2f4b58e01843ed1ea076978cf70279e7556f"
    # A mirror of the same bytes is the same data.
    assert cli_data.source_digest(archive | {"url": "https://mirror.example.com/a.zip"}) == cli_data.source_digest(archive)


def test_a_data_file_can_be_written_out_from_the_manifest(tmp_path, monkeypatch):
    # A short file, such as a map's projection, needs no download and no checksum.
    resource = files_resource(tmp_path)
    resource["files"].append({"path": "projector.yaml", "content": "projector_type: Local\n"})
    # Files data needs every file it lists unless it names fewer.
    del resource["requiredFiles"]
    cli_manifest.validate_data([resource], {}, tmp_path)
    assert resource["requiredFiles"] == ["required.txt", "projector.yaml"]
    target = tmp_path / "installed"
    monkeypatch.setattr(cli_data, "resolve_destination", lambda *_: target)
    cli_data.install_resource(resource, None, force=False)
    assert (target / "projector.yaml").read_text() == "projector_type: Local\n"
    # Other content is another declaration: the installed data is then outdated.
    assert not cli_data.is_outdated(target, resource)
    resource["files"][-1]["content"] = "projector_type: MGRS\n"
    assert cli_data.is_outdated(target, resource)
    resource["files"][-1]["sha256"] = "0" * 64
    with pytest.raises(cli_manifest.OpenADKitError, match="sha256 is invalid with content"):
        cli_manifest.validate_data([resource], {}, tmp_path)


@pytest.mark.parametrize("url", ["foo", "ftp://example.com/map.txt", "https:///map.txt"])
def test_data_url_must_be_fetchable(tmp_path, url):
    resource = files_resource(tmp_path)
    resource["files"][0]["url"] = url
    with pytest.raises(cli_manifest.OpenADKitError, match="must be an http, https or file URL"):
        cli_manifest.validate_data([resource], {}, tmp_path)


def test_zip_expected_root_is_one_directory(tmp_path):
    resource = {"name": "dataset", "kind": "zip", "destinationEnv": "MAP_PATH", "expectedRoot": "dataset/inner",
                "url": "https://example.com/data.zip", "sha256": "0" * 64, "requiredFiles": ["required.txt"]}
    with pytest.raises(cli_manifest.OpenADKitError, match="expectedRoot must be one directory name"):
        cli_manifest.validate_data([resource], {}, tmp_path)


def test_env_file_settings_are_what_the_files_set_as_compose_reads_them(tmp_path, monkeypatch):
    monkeypatch.setenv("FROM_SHELL", "shell")
    monkeypatch.setenv("SET_IN_FILE", "shell")
    path = tmp_path / "settings.env"
    path.write_text('SET_IN_FILE=file\nQUOTED="a b" # note\nHOME_PATH=$HOME/data\nFROM_SHELL\n')
    assert cli_settings._env_file_settings((path,)) == {
        "SET_IN_FILE": "file", "QUOTED": "a b", "HOME_PATH": f"{os.environ['HOME']}/data",
    }


def test_env_file_compose_refuses_is_a_cli_error(tmp_path):
    path = tmp_path / "settings.env"
    path.write_text('NAME="unterminated\n')
    with pytest.raises(cli_manifest.OpenADKitError, match="could not read the settings"):
        cli_settings._env_file_settings((path,))

def test_only_explicit_fetch_force_replaces_managed_data(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    target = tmp_path / "home/data/map"
    target.parent.mkdir(parents=True)
    target.write_text("not a directory")
    calls = fake_docker(tmp_path)
    # Not data the CLI installed: --force would refuse it, so do not advise it.
    for command in (("run", "example"), ("fetch", "example")):
        result = run_cli(root, *command)
        assert result.returncode != 0 and "remove it and run: openadkit fetch example\n" in result.stderr
        assert "--force" not in result.stderr
    assert not any("up" in row["args"] for row in recorded(calls))
    assert run_cli(root, "run", "example", "--force").returncode == 2
    assert "unsafe data target" in run_cli(root, "fetch", "example", "--force").stderr
    target.unlink()
    target.mkdir()
    (target / cli_data.MARKER).write_text("{}")
    result = run_cli(root, "run", "example")
    assert result.returncode != 0 and "openadkit fetch example --force" in result.stderr
    result = run_cli(root, "fetch", "example", "--force")
    assert result.returncode == 0, result.stderr
    assert (target / "required.txt").read_text() == "replacement"
    marker = json.loads((target / cli_data.MARKER).read_text())
    assert marker == {"resource": "dataset", "source": cli_data.source_digest(files_resource(tmp_path))}
    (target / "required.txt").write_text("keep existing")
    assert run_cli(root, "fetch", "example").returncode == 0
    assert (target / "required.txt").read_text() == "keep existing"
    assert run_cli(root, "run", "example").returncode == 0


@pytest.mark.parametrize("command", [("run", "example"), ("fetch", "example")])
def test_run_and_fetch_replace_data_installed_from_an_older_declaration(tmp_path, command):
    resource = files_resource(tmp_path)
    root, directory = runtime_tree(tmp_path, document=manifest(data=[resource]))
    target = tmp_path / "home/data/map"
    fake_docker(tmp_path)
    assert run_cli(root, "fetch", "example").returncode == 0
    assert run_cli(root, "run", "example").returncode == 0
    # A mirror of the same bytes is the same data.
    moved = tmp_path / "mirror.txt"
    moved.write_bytes((tmp_path / "dataset.txt").read_bytes())
    resource["files"][0]["url"] = moved.as_uri()
    (directory / "deployment.json").write_text(json.dumps(manifest(data=[resource])))
    result = run_cli(root, "run", "example")
    assert result.returncode == 0 and "updating data" not in result.stdout

    fixed = tmp_path / "fixed.txt"
    fixed.write_text("fixed upstream")
    resource["files"][0] |= {"url": fixed.as_uri(), "sha256": hashlib.sha256(fixed.read_bytes()).hexdigest()}
    (directory / "deployment.json").write_text(json.dumps(manifest(data=[resource])))
    result = run_cli(root, "validate", "example", "--data")
    assert result.returncode == 1 and "data dataset: outdated" in result.stdout
    assert "run: openadkit fetch example" in result.stderr and "--force" not in result.stderr
    assert (target / "required.txt").read_text() == "replacement"
    fake_docker(tmp_path)  # stopped
    result = run_cli(root, *command)
    assert result.returncode == 0 and "updating data" in result.stdout, result.stderr
    assert (target / "required.txt").read_text() == "fixed upstream"
    assert run_cli(root, "validate", "example", "--data").returncode == 0


def test_outdated_data_is_not_replaced_under_a_live_container(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    target = tmp_path / "home/data/map"
    target.mkdir(parents=True)
    (target / cli_data.MARKER).write_text("{}")  # no source recorded: outdated
    (target / "required.txt").write_text("keep")
    container = {"Id": "abc", "Name": "/other", "State": {"Status": "running"},
                 "Mounts": [{"Type": "bind", "Source": str(target)}]}
    fake_docker(tmp_path, containers=[container])
    for command in (("fetch", "example"), ("run", "example")):
        result = run_cli(root, *command)
        assert result.returncode != 0 and "is in use" in result.stderr
        assert (target / "required.txt").read_text() == "keep"


def test_only_a_marker_naming_the_current_source_is_current(tmp_path):
    resource = files_resource(tmp_path)
    target = tmp_path / "installed"
    target.mkdir()
    for marker, outdated in (({"resource": "dataset", "source": cli_data.source_digest(resource)}, False),
                             ({"resource": "dataset"}, True), ("{truncated", True)):
        (target / cli_data.MARKER).write_text(marker if isinstance(marker, str) else json.dumps(marker))
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
    target = tmp_path / "installed"
    target.mkdir()
    (target / cli_data.MARKER).write_text("{}")
    (target / "required.txt").write_text("original")
    monkeypatch.setattr(cli_data.time, "sleep", lambda _: None)
    selection = cli_settings.Selection("humble", False, None, {}, {"MAP_PATH": str(target)})
    with pytest.raises(cli_manifest.OpenADKitError, match="checksum mismatch"):
        cli_data.install_resource(resource, selection, True)
    assert (target / "required.txt").read_text() == "original"
    assert not list(tmp_path.glob(".dataset.stage.*"))


def test_rerun_counts_only_restarts_since_up(monkeypatch):
    # "kept" restarted once before this `up` and was left in place; "crashed" restarted after it.
    # One-shot services may exit, but not fail: "init" finished, "rosbag" crashed.
    # A long-running service that exits cleanly is gone too: on-failure does not restart it.
    # A healthcheck that fails after up, and a dead container, fail too.
    inspect = ("kept api 1 running 0 healthy\ncrashed planning 1 running 0 none\nreset init 3 exited 0 none\n"
               "bag rosbag 0 exited 1 none\nquit system 0 exited 0 none\nsick map 0 running 0 unhealthy\n"
               "gone vehicle 0 dead 0 none\n")
    monkeypatch.setattr(cli_compose, "docker",
                        lambda *_, **__: subprocess.CompletedProcess([], 0, stdout=inspect))
    deployment = type("Deployment", (), {"one_shots": {(None, False): {"init", "rosbag"}}})()
    selection = cli_settings.Selection("humble", False, None, {}, {})
    assert cli_compose.failed_services(deployment, selection, [], {"kept": 1}) == [
        "map", "planning", "rosbag", "system", "vehicle"]


@pytest.mark.parametrize(("interrupt", "failed"), [(True, False), (False, True)])
def test_record_keeps_an_interrupted_bag_but_reports_a_recorder_failure(monkeypatch, tmp_path, interrupt, failed):
    monkeypatch.setattr(cli_live, "run_project",
                        lambda *_, **__: subprocess.CompletedProcess([], 0, stdout="api\n"))
    monkeypatch.setattr(cli_live, "docker", lambda *_, **__: subprocess.CompletedProcess(
        [], 0, stdout=json.dumps([{"Config": {"Image": "api-image", "Env": ["ROS_DOMAIN_ID=7"], "User": "1000"}}])))
    runs = []

    environments = []

    class Recorder:
        def __init__(self, command, **_):
            runs.append(command)
            environments.append(Path(command[command.index("--env-file") + 1]).read_text())
            (tmp_path / "bags" / Path(command[-2]).name).mkdir(parents=True)
            self.interrupt = interrupt

        def wait(self):
            if self.interrupt:
                self.interrupt = False
                raise KeyboardInterrupt
            return 2

    monkeypatch.setattr(cli_live.subprocess, "Popen", Recorder)
    if failed:
        with pytest.raises(cli_manifest.OpenADKitError, match="exit status 2; partial bag"):
            cli_live.record("openadkit-example", ["/clock"], tmp_path / "bags")
    else:
        bag = cli_live.record("openadkit-example", ["/clock"], tmp_path / "bags")
        assert bag.parent == tmp_path / "bags" and bag.name.startswith("example-")
    command = runs[0]
    assert command[:4] == ["docker", "run", "--rm", "--init"]
    assert ["--volumes-from", "api:ro"] == command[command.index("--volumes-from"):][:2]
    # The container's settings go through a file, never the command line.
    assert environments == ["ROS_DOMAIN_ID=7\n"] and "--env" not in command
    assert not Path(command[command.index("--env-file") + 1]).exists()
    assert command[-1] == "/clock" and command[-2].startswith("/openadkit/recordings/example-")


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

    monkeypatch.setattr(cli_compose, "run_compose",
                        lambda *_, **__: subprocess.CompletedProcess([], 0, stdout="map\ncontrol\ncarla\n"))
    monkeypatch.setattr(cli_compose, "docker", capture)
    selection = cli_settings.Selection("humble", False, None, {}, {})
    warnings = cli_compose.report_overrides(None, selection)
    # autoware_control_config is installed in the control image, so it is no mistake.
    assert warnings == ["override changed nothing: package autoware_localization_config is in no service",
                        "override changed nothing: package typo_pkg is in no service",
                        "override adds parameter control_validator.param.yaml: nominal_latency, which its file does not have"]
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
    assert cli_live.format_autoware_state(state) == [
        "localization initialized",
        "routing      set",
        "mode         stop (manual control, autonomous available)",
        "mrm          operating: emergency stop",
    ]
    assert cli_live.format_autoware_state(dict.fromkeys(state))[1] == "routing      no data"


def test_operational_commands_act_on_the_running_stack_without_a_name(tmp_path):
    root, _ = runtime_tree(tmp_path)
    calls = fake_docker(tmp_path, projects=["openadkit-example"], services=("app", "map", "planning"))
    assert run_cli(root, "logs", "map", "planning", directory=tmp_path).returncode == 0
    assert recorded(calls)[-1]["args"] == ["compose", "--project-name", "openadkit-example", "logs", "map", "planning"]
    # A service also goes by its container's name, which docker ps and the log lines show.
    assert run_cli(root, "logs", "autoware-planning", "planning").returncode == 0
    assert recorded(calls)[-1]["args"][3:] == ["logs", "planning"]
    # Following starts from the recent lines, not the whole history.
    assert run_cli(root, "logs", "--follow", "map").returncode == 0
    assert recorded(calls)[-1]["args"][3:] == ["logs", "--follow", "--tail", "100", "map"]
    assert run_cli(root, "shell", "autoware-map", "true").returncode == 0
    assert recorded(calls)[-1]["args"][3:6] == ["exec", "-T", "map"]
    # Compose prints nothing for a name it does not know; the CLI says so.
    for operation in (("logs", "nope"), ("shell", "nope", "true")):
        result = run_cli(root, *operation)
        assert result.returncode == 1 and "error: no service named nope\nservices: app, map, planning" in result.stderr
    result = run_cli(root, "status")
    assert [line.split() for line in result.stdout.splitlines()[:2]] == [
        ["SERVICE", "CONTAINER", "STATUS"], ["app", "autoware-app", "Up", "1", "minute"]]
    assert run_cli(root, "run", "example").returncode == 0
    assert run_cli(root, "restart", "autoware-planning", directory=tmp_path).returncode == 0
    assert next(row["args"] for row in reversed(recorded(calls)) if "up" in row["args"])[-1] == "planning"
    result = run_cli(root, "restart", "nope")
    assert result.returncode == 1 and "error: no service named nope" in result.stderr
    assert run_cli(root, "restart", "planning", directory=tmp_path).returncode == 0
    up = next(row["args"] for row in reversed(recorded(calls)) if "up" in row["args"])
    assert up[-3:] == ["--no-deps", "--force-recreate", "planning"]
    assert run_cli(root, "shell", "planning", "ros2", "topic", "list", "--include-hidden-topics").returncode == 0
    shell = recorded(calls)[-1]["args"]
    assert shell[3:6] == ["exec", "-T", "planning"] and shell[-4:] == ["ros2", "topic", "list", "--include-hidden-topics"]
    # A command's exit status is shell's own, with no error of the CLI's.
    result = run_cli(root, "shell", "planning", "false", FAKE_EXEC_EXIT="3")
    assert result.returncode == 3 and "error:" not in result.stderr
    for arguments in ((), ("/tf", "--all")):
        result = run_cli(root, "record", *arguments)
        assert result.returncode != 0 and "or pass --all" in result.stderr
    fake_docker(tmp_path)
    for operation in ("logs", "restart", "shell"):
        result = run_cli(root, operation)
        assert result.returncode != 0 and "nothing is running" in result.stderr
    result = run_cli(root, "status")
    assert result.returncode == 0 and "nothing is running" in result.stdout


def test_a_stopped_stack_is_shown_and_removed_and_blocks_another_deployment(tmp_path):
    root, _ = runtime_tree(tmp_path)
    edit_manifest(root, lambda kit: kit["deployments"].update(other={"path": "deployments/other"}))
    shutil.copytree(root / "deployments/example", root / "deployments/other")
    calls = fake_docker(tmp_path, stopped=["openadkit-other"], services=("app", "map"))
    result = run_cli(root, "status")
    assert result.returncode == 0 and "== other (stopped)" in result.stdout
    assert "remove the stopped containers with: openadkit stop" in result.stdout
    # Its containers keep their fixed names: another deployment cannot start over them.
    result = run_cli(root, "run", "example")
    assert result.returncode != 0 and "error: other left stopped containers" in result.stderr
    assert not any("up" in row["args"] for row in recorded(calls))
    # The same deployment starts again in place.
    assert run_cli(root, "run", "other").returncode == 0
    fake_docker(tmp_path, stopped=["openadkit-other"], services=("app", "map"))
    calls.write_text("")
    # Its logs stay readable until stop removes it.
    assert run_cli(root, "logs", "map", directory=tmp_path).returncode == 0
    assert recorded(calls)[-1]["args"] == ["compose", "--project-name", "openadkit-other", "logs", "map"]
    assert run_cli(root, "stop", directory=tmp_path).returncode == 0
    assert ["compose", "--project-name", "openadkit-other", "down", "--remove-orphans"] in [
        row["args"] for row in recorded(calls)]


def test_status_keeps_a_service_that_exited(tmp_path):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path, projects=["openadkit-example"], services=("map", "scenario-simulator"))
    result = run_cli(root, "status", FAKE_EXITED="scenario-simulator")
    assert result.returncode == 0, result.stderr
    assert "map" in result.stdout
    assert "scenario-simulator" in result.stdout and "Exited (1)" in result.stdout


def test_status_gives_the_visualizer_address_only_when_it_runs(tmp_path):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path, projects=["openadkit-example"], services=("map", "visualizer"))
    result = run_cli(root, "status")
    assert result.returncode == 0 and "visualizer: http://localhost:6080/vnc.html" in result.stdout
    assert "password: REMOTE_PASSWORD" in result.stdout
    fake_docker(tmp_path, projects=["openadkit-example"], services=("map",))
    result = run_cli(root, "status")
    assert result.returncode == 0 and "visualizer:" not in result.stdout


def test_status_names_what_an_unhealthy_service_reported(tmp_path):
    root, _ = runtime_tree(tmp_path)
    label = "com.docker.compose.service"
    containers = [
        {"Id": "a", "Config": {"Labels": {label: "perception"}}, "State": {"Health": {
            "Status": "unhealthy", "Log": [{"Output": ""}, {"Output": "tracker-4 died with exit code -9\n"}]}}},
        {"Id": "b", "Config": {"Labels": {label: "planning"}}, "State": {"Health": {"Status": "healthy", "Log": []}}},
        {"Id": "c", "Config": {"Labels": {label: "carla"}}, "State": {}},
    ]
    fake_docker(tmp_path, projects=["openadkit-example"], containers=containers, services=("carla", "perception", "planning"))
    result = run_cli(root, "status")
    assert result.returncode == 0
    assert "perception is unhealthy: tracker-4 died with exit code -9" in result.stdout
    assert "planning is" not in result.stdout and "carla is" not in result.stdout


def test_restart_recreates_what_run_started_with_the_current_settings(tmp_path):
    root, directory = runtime_tree(tmp_path)
    containers = [
        {"Id": "a", "Config": {"Labels": {"com.docker.compose.service": "planning"}},
         "Mounts": [{"Destination": "/openadkit/config/base"}]},
        {"Id": "b", "Config": {"Labels": {"com.docker.compose.service": "acme"}},
         "Mounts": [{"Destination": "/openadkit/overlay_ws"}]},
        {"Id": "c", "Config": {"Labels": {"com.docker.compose.service": "carla"}}, "Mounts": []},
        # In planning's process namespace, which ends when planning is recreated.
        {"Id": "d", "Config": {"Labels": {"com.docker.compose.service": "bridge"}}, "Mounts": [],
         "HostConfig": {"PidMode": "container:a"}},
    ]
    calls = fake_docker(tmp_path, projects=["openadkit-example"], containers=containers,
                        services=("acme", "bridge", "carla", "planning"))
    # A stack this CLI did not start cannot be recreated as it was.
    result = run_cli(root, "restart")
    assert result.returncode != 0 and "start it again with openadkit run" in result.stderr
    assert run_cli(root, "run", "example", "--no-visualizer").returncode == 0

    def recreated(**env):
        calls.write_text("")
        result = run_cli(root, "restart", directory=tmp_path, **env)
        assert result.returncode == 0, result.stderr
        rows = [row["args"] for row in recorded(calls)]
        up = next(args for args in rows if "up" in args)
        assert {"--no-deps", "--force-recreate", "--wait"} <= set(up)
        # As run does, it creates the writable mounts the settings name before recreating.
        assert any("config --format json" in " ".join(args) for args in rows[:rows.index(up)])
        return up[up.index("--force-recreate") + 1:], result.stdout

    # From any directory: the services that take config overrides, as run started them.
    # A service in the process namespace of a recreated one is recreated with it.
    services, output = recreated()
    assert services == ["acme", "bridge", "planning"] and "kept running: carla" in output
    # A settings change recreates the services it changes, here one without config.
    services, output = recreated(FAKE_CHANGED="carla")
    assert services == ["acme", "bridge", "carla", "planning"] and "kept running" not in output
    calls.write_text("")
    assert run_cli(root, "restart", "acme", directory=tmp_path).returncode == 0
    up = next(row["args"] for row in recorded(calls) if "up" in row["args"])
    assert up[up.index("--force-recreate") + 1:] == ["acme"]
    calls.write_text("")
    assert run_cli(root, "restart", "--all").returncode == 0
    up = next(row["args"] for row in recorded(calls) if "up" in row["args"])
    assert up[up.index("--force-recreate") + 1:] == ["acme", "bridge", "carla", "planning"]
    result = run_cli(root, "restart", "planning", "--all")
    assert result.returncode != 0 and "or pass --all" in result.stderr
    # A workspace built for another distro stops it before anything is recreated.
    (directory / "overlay_ws/install").mkdir(parents=True)
    (directory / "overlay_ws/install/.openadkit-overlay.json").write_text('{"image": "x", "rosDistro": "jazzy"}')
    calls.write_text("")
    result = run_cli(root, "restart")
    assert result.returncode == 1 and "rebuild it: openadkit build" in result.stderr
    assert not any("up" in row["args"] for row in recorded(calls))
    # stop forgets how the stack was started.
    assert run_cli(root, "stop").returncode == 0
    assert not list((root.parent / "home/.local/state/openadkit/runs").iterdir())


def test_restart_all_includes_a_stopped_visualizer_once_it_has_been_started(tmp_path):
    root, _ = runtime_tree(tmp_path)
    calls = fake_docker(tmp_path, services=("app", "visualizer"))
    assert run_cli(root, "run", "example", "--no-visualizer", FAKE_MISSING="visualizer").returncode == 0
    for args, state, expected in [
        (("--all",), {"FAKE_MISSING": "visualizer"}, ["app"]),
        (("visualizer",), {"FAKE_MISSING": "visualizer"}, ["visualizer"]),
        (("--all",), {"FAKE_EXITED": "visualizer"}, ["app", "visualizer"]),
    ]:
        calls.write_text("")
        result = run_cli(root, "restart", *args, **state)
        assert result.returncode == 0, result.stderr
        up = next(row["args"] for row in recorded(calls) if "up" in row["args"])
        assert up[up.index("--force-recreate") + 1:] == expected


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


@pytest.mark.parametrize("race", ["appeared", "replaced", "unmarked"])
def test_forced_fetch_preserves_targets_changed_during_publication(tmp_path, monkeypatch, race):
    resource = files_resource(tmp_path)
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
    download = cli_data.download
    def download_with_race(*args):
        download(*args)
        change_target()
    monkeypatch.setattr(cli_data, "download", download_with_race)
    selection = cli_settings.Selection("humble", False, None, {}, {"MAP_PATH": str(target)})
    with pytest.raises(cli_manifest.OpenADKitError, match="changed during download"):
        cli_data.install_resource(resource, selection, True)
    assert (target / "user-file").read_text() == ("original" if race == "unmarked" else "new user data")
    assert not list(tmp_path.glob(".dataset.stage.*"))


def test_forced_fetch_replaces_managed_data_and_removes_the_old(tmp_path):
    resource = files_resource(tmp_path)
    target = tmp_path / "installed"
    target.mkdir()
    (target / cli_data.MARKER).write_text("{}")
    (target / "old-file").write_text("old")
    selection = cli_settings.Selection("humble", False, None, {}, {"MAP_PATH": str(target)})
    cli_data.install_resource(resource, selection, True)
    assert cli_data.is_managed(target) and not (target / "old-file").exists()
    assert not list(tmp_path.glob(".dataset.stage.*"))


class SettingsDeployment:
    """The parts of a Deployment that settings resolution reads."""

    def __init__(self, directory, files, gpu_files, data):
        self.name, self.directory, self.data, self.roles = "example", directory, data, {}
        self.working_directory, self.base = directory, None
        self.files, self.gpu_files = files, gpu_files
        self.output_directory, self.kit_environment, self.overlay_paths = directory / "output", {}, {}
        self.requirements = {"rosDistros": ["humble", "jazzy"]}

    def env_files(self, gpu=False):
        return self.files + (self.gpu_files if gpu else [])


@NEEDS_COMPOSE
def test_data_destinations_resolve_as_compose_resolves_them(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MAP_ROOT", "/srv/maps")
    (tmp_path / "settings.env").write_text(
        "DATA_PATH=$HOME/data\nMODEL_PATH=${DATA_PATH}/models\n"
        "MAP_PATH=${MAP_ROOT:-/tmp/openadkit-map}\nROSBAG_PATH=${ROSBAG_ROOT:-/tmp/rosbag}\n")
    (tmp_path / "settings.gpu.env").write_text("ROSBAG_PATH=/srv/gpu-rosbag\n")
    data = [{"name": "rosbag", "destinationEnv": "ROSBAG_PATH", "gpu": True}]
    deployment = SettingsDeployment(tmp_path, [tmp_path / "settings.env"], [tmp_path / "settings.gpu.env"], data)
    kit = cli_catalog.Catalog("source", "humble", None, "registry.example/x", {}, {}, {}, {}, {})
    resolved = cli_settings.resolve(deployment, kit, data_only=True)
    destination = lambda name, gpu=False: cli_data.resolve_destination(  # noqa: E731
        {"name": name, "destinationEnv": name, "gpu": gpu}, resolved)
    assert destination("MODEL_PATH") == tmp_path / "data/models"
    assert destination("MAP_PATH") == Path("/srv/maps")
    assert destination("ROSBAG_PATH") == Path("/tmp/rosbag")
    # GPU-only data goes where a GPU run mounts it.
    assert destination("ROSBAG_PATH", gpu=True) == Path("/srv/gpu-rosbag")
    # Without GPU-only data there is no GPU variant to resolve.
    deployment.data = []
    assert cli_settings.resolve(deployment, kit, data_only=True).gpu_environment is None


@NEEDS_COMPOSE
def test_a_source_checkout_image_setting_resolves_as_compose_resolves_it(tmp_path, monkeypatch):
    for variable in ISOLATED_ENV:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("REGISTRY", "registry.example/mine")
    root, directory = runtime_tree(tmp_path, config="VEHICLE_SYSTEM_IMAGE=${REGISTRY}/api:dev\n")
    kit = cli_catalog.load_catalog(root)
    deployment = cli_catalog.get_deployment(root, kit, "example")
    selection = cli_settings.resolve(deployment, kit, "humble")
    assert "VEHICLE_SYSTEM_IMAGE" not in selection.injections
    assert selection.environment["VEHICLE_SYSTEM_IMAGE"] == "registry.example/mine/api:dev"
    # Images the env files leave out still come from the source checkout's prefix.
    assert selection.injections["PLANNING_IMAGE"].startswith("registry.example/openadkit:")


@NEEDS_COMPOSE
def test_a_run_without_gpu_resolves_its_settings_once(tmp_path, monkeypatch):
    for variable in ISOLATED_ENV:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root, _ = runtime_tree(tmp_path, document=manifest(gpu=True))
    kit = cli_catalog.load_catalog(root)
    deployment = cli_catalog.get_deployment(root, kit, "example")
    passes = []
    real = cli_settings.compose_environment
    monkeypatch.setattr(cli_settings, "compose_environment", lambda *args: passes.append(args) or real(*args))
    cli_settings._env_file_settings.cache_clear()
    selection = cli_settings.resolve(deployment, kit, "humble")
    # One clean pass for what the files set, one with the real environment.
    assert len(passes) == 2 and selection.gpu_environment is None


def test_data_paths_trust_the_users_own_symlinks_and_host_layout(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
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
    result = run_cli(root, "clean", "example", "--yes")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home/data/map").exists()


def test_clean_lists_what_it_deletes_and_needs_yes_without_a_terminal(tmp_path):
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    kit = extending_kit(tmp_path, root)
    target = tmp_path / "home/data/map"
    target.mkdir(parents=True)
    (target / cli_data.MARKER).write_text("{}")
    fake_docker(tmp_path)
    result = run_cli(root, "clean", "custom", directory=kit)
    assert result.returncode != 0 and "--yes" in result.stderr and target.exists()
    assert f"{target} (also used by example)" in result.stdout
    result = run_cli(root, "clean", "custom", "--yes", directory=kit)
    assert result.returncode == 0, result.stderr
    assert not target.exists()
    assert "no data of custom is installed" in run_cli(root, "clean", "custom", directory=kit).stdout


@pytest.mark.parametrize("unsafe", ["file", "running"])
def test_clean_checks_all_targets_before_deleting_anything(tmp_path, unsafe):
    resources = [files_resource(tmp_path), files_resource(tmp_path, env="SECOND_PATH", name="second")]
    root, _ = runtime_tree(tmp_path, document=manifest(data=resources),
                           config="MAP_PATH=$HOME/data/map\nSECOND_PATH=$HOME/data/second\n")
    first, second = tmp_path / "home/data/map", tmp_path / "home/data/second"
    for target in (first, second):
        target.mkdir(parents=True)
        (target / cli_data.MARKER).write_text("{}")
        (target / "required.txt").write_text("keep")
    if unsafe == "file":
        shutil.rmtree(second)
        second.write_text("keep")
    fake_docker(tmp_path, projects=["openadkit-example"] if unsafe == "running" else [])
    result = run_cli(root, "clean", "example", "--yes")
    assert result.returncode != 0
    assert ("example is running" if unsafe == "running" else "not installed by openadkit") in result.stderr
    assert (first / "required.txt").read_text() == "keep"
    assert second.exists()


def test_data_behind_the_users_own_link_is_their_own(tmp_path):
    # Data moved to a bigger disk and linked back: used as it is, never replaced or removed.
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]),
                           config="MAP_PATH=$HOME/data/map\n")
    moved = tmp_path / "ssd/map"
    moved.mkdir(parents=True)
    (moved / cli_data.MARKER).write_text("{}")
    (moved / "required.txt").write_text("keep")
    link = tmp_path / "home/data/map"
    link.parent.mkdir(parents=True)
    link.symlink_to(moved)
    fake_docker(tmp_path)
    assert "data dataset: your own directory, not checked" in run_cli(root, "validate", "example", "--data").stdout
    result = run_cli(root, "fetch", "example")
    assert result.returncode == 0 and f"using your own data: {link}" in result.stdout, result.stderr
    result = run_cli(root, "clean", "example", "--yes")
    assert result.returncode == 0, result.stderr
    assert link.is_symlink() and (moved / "required.txt").read_text() == "keep"


@pytest.mark.parametrize("marker", ["none", "symlink"])
def test_a_directory_the_cli_did_not_install_is_the_users_own(tmp_path, marker):
    # Their own map, with their own file names: used as it is, never checked, replaced or removed.
    resources = [files_resource(tmp_path), files_resource(tmp_path, env="SECOND_PATH", name="second")]
    root, _ = runtime_tree(tmp_path, document=manifest(data=resources),
                           config="MAP_PATH=$HOME/data/map\nSECOND_PATH=$HOME/data/second\n")
    installed, own = tmp_path / "home/data/map", tmp_path / "home/data/second"
    for target in (installed, own):
        target.mkdir(parents=True)
        (target / cli_data.MARKER).write_text("{}")
    (installed / "required.txt").write_text("installed")
    (installed / cli_data.MARKER).write_text(json.dumps({"source": cli_data.source_digest(resources[0])}))
    (own / cli_data.MARKER).unlink()
    (own / "my-own-name.osm").write_text("mine")
    if marker == "symlink":
        # A marker that only links to one vouches for nothing.
        (own / cli_data.MARKER).symlink_to(installed / cli_data.MARKER)
    fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", "--data", "--json")
    document = json.loads(result.stdout)
    assert document["dataValid"] is True, result.stderr
    assert {"name": "second", "status": "own"} in document["data"]
    assert "data second: your own directory, not checked" in run_cli(root, "validate", "example", "--data").stdout
    result = run_cli(root, "fetch", "example", "--force")
    assert result.returncode == 0 and f"using your own data: {own}" in result.stdout, result.stderr
    result = run_cli(root, "clean", "example", "--yes")
    assert result.returncode == 0, result.stderr
    assert str(own) not in result.stdout and not installed.exists()
    assert (own / "my-own-name.osm").read_text() == "mine"
    # An empty directory holds nothing to use and nothing to lose: it counts as missing.
    (own / "my-own-name.osm").unlink()
    if marker == "symlink":
        (own / cli_data.MARKER).unlink()
    result = run_cli(root, "validate", "example", "--data")
    assert result.returncode == 1 and "installed data is missing; run: openadkit fetch example" in result.stderr
    # fetch says what goes into a path outside the data directory, which may be a typo.
    result = run_cli(root, "fetch", "example")
    assert result.returncode == 0, result.stderr
    assert f"SECOND_PATH names {own}, which holds nothing: installing second there" in result.stdout
    assert cli_data.is_managed(own) and (own / "required.txt").is_file()
    # clean deletes what the CLI installed, and nothing else it only lists.
    (own / cli_data.MARKER).unlink()
    result = run_cli(root, "clean", "example", "--yes")
    assert result.returncode == 0 and str(own) not in result.stdout and (own / "required.txt").is_file()


@pytest.mark.parametrize(("name", "status", "shared"), [("custom", "running", True), ("example", "paused", True),
                                                        ("custom", "restarting", True), ("custom", "running", False),
                                                        ("custom", "exited", True)])
def test_clean_protects_shared_data_across_kit_catalogs(tmp_path, name, status, shared):
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    kit = extending_kit(tmp_path, root)
    target = tmp_path / "home/data/map"
    target.mkdir(parents=True)
    (target / cli_data.MARKER).write_text("{}")
    (target / "required.txt").write_text("keep")
    other = "example" if name == "custom" else "custom"
    container = {"Id": "abc", "Name": f"/{other}", "State": {"Status": status},
                 "Mounts": [{"Type": "bind", "Source": str(target if shared else tmp_path / "unrelated")}]}
    fake_docker(tmp_path, projects=[f"openadkit-{other}"], containers=[container])
    result = run_cli(root, "clean", name, "--yes", directory=kit if name == "custom" else root)
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
    monkeypatch.setattr(cli_compose, "docker", capture)
    with pytest.raises(cli_manifest.OpenADKitError, match="refusing cleanup"):
        cli_compose.require_data_unused([tmp_path / "data"])


def test_fetch_checks_every_destination_before_download(tmp_path):
    resources = [files_resource(tmp_path), files_resource(tmp_path, env="SECOND_PATH", name="second")]
    root, _ = runtime_tree(tmp_path, document=manifest(data=resources),
                           config="MAP_PATH=$HOME/data/map\nSECOND_PATH=relative\n")
    result = run_cli(root, "fetch", "example")
    assert result.returncode != 0 and "SECOND_PATH must be an absolute path, not relative" in result.stderr
    assert not (tmp_path / "home/data").exists()


@pytest.mark.parametrize("base_refs", [{"ref": PIN}, {"distros": {"humble": PIN, "jazzy": PIN}}])
def test_kit_external_image_fallback_and_wildcard_override(tmp_path, base_refs):
    root, _ = runtime_tree(tmp_path)
    edit_manifest(root, lambda doc: doc.update(externalImages={"EXTERNAL_IMAGE": {**base_refs}}))
    kit = extending_kit(tmp_path, root, external_images={"EXTERNAL_IMAGE": {"distros": {"humble": OTHER_PIN}}})
    context = cli_catalog.load_catalog(kit)
    assert context.external_image_environment("humble")["EXTERNAL_IMAGE"] == OTHER_PIN
    assert context.external_image_environment("jazzy")["EXTERNAL_IMAGE"] == PIN
    edit_manifest(kit, lambda doc: doc.update(externalImages={"EXTERNAL_IMAGE": {"ref": OTHER_PIN}}))
    assert cli_catalog.load_catalog(kit).external_image_environment("jazzy")["EXTERNAL_IMAGE"] == OTHER_PIN
    # Every distro is `ref`, never a "*" distro.
    edit_manifest(kit, lambda doc: doc.update(externalImages={"EXTERNAL_IMAGE": {"distros": {"*": OTHER_PIN}}}))
    with pytest.raises(cli_manifest.OpenADKitError, match="invalid ROS distro"):
        cli_catalog.load_catalog(kit)


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
    edit_manifest(root, lambda doc: doc.update(externalImages={"INHERITED_IMAGE": {"ref": PIN}}))
    kit = extending_kit(tmp_path, root, external_images={"VEHICLE_SYSTEM_IMAGE": {"ref": OTHER_PIN}})
    directory = kit / "deployments/custom"
    (directory / "settings.gpu.env").write_text("VALUE=kit-gpu\n")
    for path in (base / "config", directory / "config", kit / "overlay_ws"):
        path.mkdir()
    host_settings(root, "VALUE=site\n", name="custom")
    context = cli_catalog.load_catalog(kit)
    deployment = cli_catalog.get_deployment(kit, context, "custom")
    assert deployment.requirements["gpu"] == "optional" and deployment.data[0]["name"] == "dataset"
    selection = cli_settings.resolve(deployment, context, "humble", True)
    assert deployment.compose_files(True) == [directory / "compose.yaml", base / "compose.gpu.yaml"]
    assert selection.environment["VALUE"] == "site" and selection.environment["BASE_GPU"] == "1"
    assert selection.injections["VEHICLE_SYSTEM_IMAGE"] == OTHER_PIN
    assert selection.injections["OPENADKIT_BASE_DEPLOYMENT"] == str(base)
    calls = fake_docker(tmp_path)
    result = run_cli(root, "validate", "custom", "--gpu", directory=kit)
    assert result.returncode == 0, result.stderr
    env = recorded(calls)[0]["env"]
    assert [env[name] for name in (
        "OPENADKIT_CONFIG_BASE", "OPENADKIT_CONFIG_DEPLOYMENT", "OPENADKIT_OVERLAY_WS",
    )] == [str(base / "config"), str(directory / "config"), str(kit / "overlay_ws")]
    bom = json.loads(run_cli(root, "version", "--json", directory=kit).stdout)["bom"]
    assert bom["externalImages"]["INHERITED_IMAGE"]["ref"] == PIN
    assert (bom["images"] is not None) is release


def test_one_shot_services_are_those_compose_does_not_restart(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    calls = fake_docker(tmp_path, services=("app", "loader", "acme"))
    # A run starts each one-shot service afresh, the base's and the kit's alike.
    assert run_cli(root, "run", "custom", directory=kit, FAKE_ONE_SHOT="loader,acme").returncode == 0
    removed = [row["args"][-1] for row in recorded(calls) if "rm" in row["args"]]
    assert removed == ["acme", "loader"]
    # Without restart: "no" there is none.
    calls.write_text("")
    assert run_cli(root, "run", "custom", directory=kit).returncode == 0
    assert not any("rm" in row["args"] for row in recorded(calls))


def test_a_manifest_holds_only_what_the_files_do_not_say(tmp_path):
    for field, value in (("schemaVersion", 2), ("shared", ["shared"]), ("compose", {"files": ["compose.yaml"]})):
        document = manifest() | {field: value}
        root, _ = runtime_tree(tmp_path / field, document=document)
        with pytest.raises(cli_manifest.OpenADKitError, match=f"unknown manifest field\\(s\\): {field}"):
            cli_catalog.get_deployment(root, cli_catalog.load_catalog(root), "example")


@pytest.mark.parametrize("installed", [False, True])
def test_new_makes_a_kit_that_extends_this_open_ad_kit(tmp_path, installed):
    root, _ = runtime_tree(tmp_path, release=True)
    install = tmp_path / "oak/releases"
    if installed:
        install.mkdir(parents=True)
        (install / "openadkit-v1.2.3").symlink_to(root)
    work = tmp_path / "work"
    work.mkdir()
    result = run_cli(root, "new", "my-kit", "--base", "example", directory=work, OPENADKIT_HOME=str(tmp_path / "oak"))
    assert result.returncode == 0, result.stderr
    kit = work / "my-kit"
    manifest = json.loads((kit / "openadkit.json").read_text())
    # An installed release is followed by its version; anything else by its path.
    assert manifest["extends"] == ("v1.2.3" if installed else str(root.resolve()))
    # One manifest: the deployment is named after the kit and its base, and says its base.
    assert manifest["deployments"] == {"my-kit-example": {"base": "example"}} and manifest["externalImages"] == {}
    assert "my-kit-example, which runs example with the kit's files on top" in result.stdout
    # The kit's files are at its root; the deployment's own have their directory.
    assert sorted(str(path.relative_to(kit)) for path in kit.rglob("*") if path.is_file()) == [
        ".gitignore", "README.md", "config/autoware/README.md", "deployments/my-kit-example/settings.env",
        "openadkit.json", "overlay_ws/src/README.md", "settings.env",
    ]
    assert "{{" not in "".join(str(path) + path.read_text() for path in kit.rglob("*") if path.is_file())
    if not installed:
        loaded = cli_catalog.load_catalog(kit)
        assert loaded.kind == "kit" and set(loaded.deployments) == {"my-kit-example"}
        deployment = cli_catalog.get_deployment(kit, loaded, "my-kit-example")
        # Without a Compose file of its own it runs its base's.
        assert deployment.base.name == "example" and deployment.compose_files(False) == deployment.base.compose_files(False)


def test_new_makes_a_kit_inside_a_checkout_relative_to_it(tmp_path):
    root, _ = runtime_tree(tmp_path)
    (root / "kits").mkdir()
    result = run_cli(root, "new", "inner", "--base", "example", directory=root / "kits")
    assert result.returncode == 0, result.stderr
    assert json.loads((root / "kits/inner/openadkit.json").read_text())["extends"] == "../.."


@pytest.mark.parametrize(("name", "base", "message"), [
    ("Bad_Name", "example", "invalid kit name"),
    ("my-kit", "missing", "missing is not a deployment"),
    ("taken", "example", "already exists"),
])
def test_new_refuses_what_cannot_be_a_kit(tmp_path, name, base, message):
    root, _ = runtime_tree(tmp_path)
    work = tmp_path / "work"
    (work / "taken").mkdir(parents=True)
    result = run_cli(root, "new", name, "--base", base, directory=work)
    assert result.returncode != 0 and message in result.stderr


def test_a_kit_with_one_deployment_needs_no_name(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    fake_docker(tmp_path)
    result = run_cli(root, "validate", directory=kit)
    assert result.returncode == 0 and "custom is valid" in result.stdout, result.stderr
    assert json.loads(run_cli(root, "validate", "--json", directory=kit).stdout)["deployment"] == "custom"
    # Outside a kit the name is still asked for.
    assert run_cli(root, "validate").returncode == 2
    # With several, validate and fetch cover each of them; the others take a name.
    edit_manifest(kit, lambda document: document["deployments"].update(second={"base": "example"}))
    result = run_cli(root, "validate", directory=kit)
    assert result.returncode == 0 and "custom is valid" in result.stdout and "second is valid" in result.stdout
    assert run_cli(root, "fetch", directory=kit).returncode == 0
    for arguments in (["run"], ["config"], ["validate", "--json"]):
        result = run_cli(root, *arguments, directory=kit)
        assert result.returncode != 0 and "deployment name required" in result.stderr, arguments
    # One that does not validate fails the whole check.
    edit_kit_deployment(kit, "second", base="missing")
    result = run_cli(root, "validate", directory=kit)
    assert result.returncode != 0 and "unknown base deployment: missing" in result.stderr


def test_usage_errors_exit_2_and_help_keeps_its_capitals(tmp_path):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path, projects=("openadkit-example",))
    for args in (["restart", "app", "--all"], ["record"], ["record", "/tf", "--all"], ["build"]):
        result = run_cli(root, *args)
        assert result.returncode == 2 and result.stderr.startswith("error: "), args
    assert "in a running service with ROS sourced." in " ".join(run_cli(root, "shell", "--help").stdout.split())
    assert "resolved Compose model as JSON." in " ".join(run_cli(root, "config", "--help").stdout.split())
    # A kit on a source checkout names it once; one on a release names the version too.
    kit = extending_kit(tmp_path, root)
    assert f"extends: Open AD Kit at {root}" in run_cli(root, "version", directory=kit).stdout.splitlines()


def test_new_refuses_inside_a_kit(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    result = run_cli(root, "new", "nested", "--base", "example", directory=kit)
    assert result.returncode != 0 and "outside a kit" in result.stderr


def test_build_builds_one_workspace_in_the_pinned_devel_image(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    kit = extending_kit(tmp_path, root)
    workspace = kit / "overlay_ws"
    (workspace / "src").mkdir(parents=True)
    calls = fake_docker(tmp_path)
    # Without packages there is nothing to build: no image is pulled and no stamp written.
    result = run_cli(root, "build", directory=kit)
    assert result.returncode == 0 and "nothing to build" in result.stdout, result.stderr
    assert not recorded(calls) and not (workspace / "install").exists()
    (workspace / "src/my_pkg").mkdir()
    (workspace / "src/my_pkg/package.xml").write_text("<package/>")
    # A release from before the devel pin has nothing to build in.
    result = run_cli(root, "build", directory=kit)
    assert result.returncode != 0 and "pins no humble devel image" in result.stderr

    devel = "ghcr.io/example/openadkit:universe-common-devel-humble@sha256:" + "d" * 64
    edit_manifest(root, lambda doc: doc["images"]["humble"].update({"universe-common-devel": devel}))
    # In a kit, build takes its workspace; it builds where the services mount it.
    result = run_cli(root, "build", directory=kit)
    assert result.returncode == 0, result.stderr
    builds = [row["args"] for row in recorded(calls) if row["args"][:1] == ["run"]]
    assert len(builds) == 1 and devel in builds[0]
    assert f"{workspace}:/openadkit/overlay_ws" in builds[0]
    stamp = json.loads((workspace / "install/.openadkit-overlay.json").read_text())
    assert stamp == {"image": devel, "rosDistro": "humble", "complete": True}
    assert "overlay workspace" not in run_cli(root, "validate", "custom", directory=kit).stderr
    # A failed build leaves its stamp without "complete": the services may lack packages.
    del stamp["complete"]
    (workspace / "install/.openadkit-overlay.json").write_text(json.dumps(stamp))
    assert "the last build of" in run_cli(root, "validate", "custom", directory=kit).stderr

    # After a base upgrade the install is stale: validate stops until it is rebuilt.
    edit_manifest(root, lambda doc: doc["images"]["humble"].update({"universe-common-devel": devel[:-1] + "e"}))
    result = run_cli(root, "validate", "custom", directory=kit)
    assert result.returncode == 1 and f"rebuild it: openadkit build {workspace}" in result.stderr

    # A build for another image starts clean; the same image builds incrementally.
    (workspace / "build").mkdir(exist_ok=True)
    (workspace / "build/CMakeCache.txt").write_text("old")
    assert run_cli(root, "build", directory=kit).returncode == 0
    assert devel[:-1] + "e" in recorded(calls)[-1]["args"]
    assert not (workspace / "build/CMakeCache.txt").exists()
    (workspace / "build").mkdir(exist_ok=True)
    (workspace / "build/CMakeCache.txt").write_text("current")
    assert run_cli(root, "build", directory=kit).returncode == 0
    assert (workspace / "build/CMakeCache.txt").read_text() == "current"
    # A failed first build in an image: its retry continues from what it built.
    edit_manifest(root, lambda doc: doc["images"]["humble"].update({"universe-common-devel": devel[:-1] + "f"}))
    assert run_cli(root, "build", directory=kit, FAKE_RUN_EXIT="1").returncode != 0
    assert not (workspace / "build/CMakeCache.txt").exists()
    (workspace / "build").mkdir()
    (workspace / "build/CMakeCache.txt").write_text("partial")
    assert run_cli(root, "build", directory=kit).returncode == 0
    assert (workspace / "build/CMakeCache.txt").read_text() == "partial"

    # A build/ and install/ that openadkit build did not make stay as they are.
    host = tmp_path / "host_ws"
    for directory in ("src/pkg", "build/pkg", "install/pkg"):
        (host / directory).mkdir(parents=True)
    (host / "src/pkg/package.xml").write_text("<package/>")
    calls.write_text("")
    result = run_cli(root, "build", str(host), directory=kit)
    assert result.returncode != 0 and "did not come from openadkit build" in result.stderr
    assert (host / "build/pkg").is_dir() and (host / "install/pkg").is_dir()
    assert not any(row["args"][:1] == ["run"] for row in recorded(calls))

    # A path builds that workspace, with the pins of the kit around it.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = run_cli(root, "build", str(workspace), directory=elsewhere)
    assert result.returncode == 0, result.stderr
    assert devel[:-1] + "f" in recorded(calls)[-1]["args"]
    # Outside a kit, build needs a path; a path needs a src/.
    result = run_cli(root, "build", directory=elsewhere)
    assert result.returncode != 0 and "openadkit build PATH" in result.stderr
    result = run_cli(root, "build", str(elsewhere), directory=elsewhere)
    assert result.returncode != 0 and "has no src/" in result.stderr


def test_build_hands_the_arguments_after_dashes_to_colcon(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    devel = "ghcr.io/example/openadkit:universe-common-devel-humble@sha256:" + "d" * 64
    edit_manifest(root, lambda doc: doc["images"]["humble"].update({"universe-common-devel": devel}))
    kit = extending_kit(tmp_path, root)
    (kit / "overlay_ws/src/my_pkg").mkdir(parents=True)
    (kit / "overlay_ws/src/my_pkg/package.xml").write_text("<package/>")
    calls = fake_docker(tmp_path)
    colcon = ["--packages-select", "my_pkg", "--cmake-args", "-DCMAKE_BUILD_TYPE=Debug"]
    result = run_cli(root, "build", "--ros-distro", "humble", "--", *colcon, directory=kit)
    assert result.returncode == 0, result.stderr
    build = next(row["args"] for row in recorded(calls) if row["args"][:1] == ["run"])
    # The script gets them as its arguments; Release is only CMake's default.
    assert build[build.index(devel) + 3:] == ["build", *colcon]
    assert 'colcon build --install-base install "$@"' in build[build.index(devel) + 2]
    assert "CMAKE_BUILD_TYPE=Release" in build and "-DCMAKE_BUILD_TYPE=Release" not in " ".join(build)
    # The services source install/ where they mount the workspace.
    for option in ("--install-base", "--build-base=other"):
        result = run_cli(root, "build", "--", option, "x", directory=kit)
        assert result.returncode != 0 and "cannot change" in result.stderr


def test_a_source_checkout_runs_its_local_build_or_one_ci_build(tmp_path, monkeypatch):
    root, _ = runtime_tree(tmp_path)
    context = cli_catalog.load_catalog(root)
    arch = cli_catalog.host_architecture()
    monkeypatch.delenv("OPENADKIT_BUILD", raising=False)
    assert context.component_environment("humble", arch, False)["PLANNING_IMAGE"] == f"registry.example/openadkit:planning-{arch}-humble"
    assert context.devel_image("jazzy") == f"registry.example/openadkit:universe-common-devel-{arch}-jazzy"
    # One setting points every image, the devel image included, at one CI build.
    monkeypatch.setenv("OPENADKIT_BUILD", "ghcr.io/me/openadkit:123-1")
    assert context.component_environment("humble", arch, False)["PLANNING_IMAGE"] == "ghcr.io/me/openadkit:planning-humble-123-1"
    assert context.devel_image("jazzy") == "ghcr.io/me/openadkit:universe-common-devel-jazzy-123-1"
    monkeypatch.setenv("OPENADKIT_BUILD", "123-1")
    with pytest.raises(cli_manifest.OpenADKitError, match="<image repository>:<build tag>"):
        context.devel_image("humble")


def test_a_source_checkout_without_a_local_build_names_both_ways_out(tmp_path):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path, services=("app",))
    local = f"registry.example/openadkit:planning-{cli_catalog.host_architecture()}-humble"
    result = run_cli(root, "run", "example", FAKE_IMAGE=local, FAKE_NO_IMAGES="1")
    assert result.returncode != 0 and "no local build of planning" in result.stderr
    assert "docker buildx bake" in result.stderr and "OPENADKIT_BUILD" in result.stderr
    assert run_cli(root, "run", "example", FAKE_IMAGE=local).returncode == 0
    # A CI build's images are pulled as usual.
    ci = "ghcr.io/me/openadkit:planning-humble-123-1"
    assert run_cli(root, "run", "example", FAKE_IMAGE=ci, FAKE_NO_IMAGES="1",
                   OPENADKIT_BUILD="ghcr.io/me/openadkit:123-1").returncode == 0


def test_build_removes_its_container_when_interrupted(tmp_path, monkeypatch):
    commands = []

    def docker(command, **_):
        commands.append(command)
        if command[:2] == ["docker", "run"]:
            raise KeyboardInterrupt
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli_compose, "docker", docker)
    monkeypatch.setattr(cli_compose, "require_docker", lambda: None)
    (tmp_path / "src").mkdir()
    with pytest.raises(KeyboardInterrupt):
        cli_compose.build_overlay(tmp_path, "local/devel:test", "humble")
    name = commands[0][commands[0].index("--name") + 1]
    assert commands[1] == ["docker", "rm", "--force", name]


def test_a_kit_defaults_to_a_distro_it_runs_on(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    devel = {distro: f"ghcr.io/example/openadkit:universe-common-devel-{distro}@sha256:" + "d" * 64
             for distro in ("humble", "jazzy")}
    edit_manifest(root, lambda doc: [doc["images"][distro].update({"universe-common-devel": image})
                                     for distro, image in devel.items()])
    kit = extending_kit(tmp_path, root)
    edit_kit_deployment(kit, requirements={"rosDistros": ["jazzy"]})
    (kit / "overlay_ws/src/my_pkg").mkdir(parents=True)
    (kit / "overlay_ws/src/my_pkg/package.xml").write_text("<package/>")
    calls = fake_docker(tmp_path)
    # The release defaults to humble, which this kit leaves out.
    result = run_cli(root, "validate", "custom", directory=kit)
    assert result.returncode == 0, result.stderr
    assert run_cli(root, "build", directory=kit).returncode == 0
    assert devel["jazzy"] in recorded(calls)[-1]["args"]


def test_restart_ignores_a_one_shot_service_that_failed_before_it(monkeypatch):
    rows = {"old": "scenario-simulator", "new": "loader"}

    def docker(command, **_):
        lines = [f"{container} {service} 0 exited 1 none" for container, service in rows.items()]
        return subprocess.CompletedProcess(command, 0, "\n".join(lines), "")

    monkeypatch.setattr(cli_compose, "docker", docker)

    class Deployment:
        one_shots = {(None, False): {"scenario-simulator", "loader"}}

    class Selection:
        role = None
        gpu = False

    # "old" existed before this up, which left it as it was; "new" failed after it.
    assert cli_compose.failed_services(Deployment(), Selection(), list(rows), {"old": 0}) == ["loader"]


def overlay_workspace(root, name, monkeypatch, tmp_path, workspace=None):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for variable in ISOLATED_ENV:
        monkeypatch.delenv(variable, raising=False)
    context = cli_catalog.load_catalog(root)
    deployment = cli_catalog.get_deployment(root, context, name)
    if workspace is not None:
        deployment.use_workspace(workspace)
    return cli_settings.resolve(deployment, context, "humble", False).injections["OPENADKIT_OVERLAY_WS"]


def test_a_kit_has_one_workspace_at_its_root(tmp_path, monkeypatch):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    (kit / "overlay_ws").mkdir()
    # A deployment's own overlay_ws is no second layer.
    (kit / "deployments/custom/overlay_ws").mkdir()
    assert overlay_workspace(kit, "custom", monkeypatch, tmp_path) == str(kit / "overlay_ws")


def test_a_kits_root_applies_to_each_deployment_before_the_deployments_own_files(tmp_path, monkeypatch):
    for name in ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root, base = runtime_tree(tmp_path, config="VALUE=base\nBASE_ONLY=base\n")
    kit = extending_kit(tmp_path, root)
    edit_manifest(kit, lambda document: document["deployments"].update(plain={"base": "example"}))
    (kit / "settings.env").write_text("VALUE=kit\nKIT_ONLY=kit\n")
    (kit / "deployments/custom/settings.env").write_text("VALUE=deployment\n")
    for path in (kit / "config", kit / "deployments/custom/config"):
        path.mkdir()
    context = cli_catalog.load_catalog(kit)

    custom = cli_catalog.get_deployment(kit, context, "custom")
    selection = cli_settings.resolve(custom, context, "humble", False)
    # Later wins: the base, the kit, then the deployment.
    assert [selection.environment[name] for name in ("BASE_ONLY", "KIT_ONLY", "VALUE")] == ["base", "kit", "deployment"]
    assert selection.injections["OPENADKIT_CONFIG_KIT"] == str(kit / "config")
    assert selection.injections["OPENADKIT_CONFIG_DEPLOYMENT"] == str(kit / "deployments/custom/config")
    assert custom.compose_files(False) == [kit / "deployments/custom/compose.yaml"]

    # A deployment with no directory of its own is the base with the kit's files.
    plain = cli_catalog.get_deployment(kit, context, "plain")
    selection = cli_settings.resolve(plain, context, "humble", False)
    assert selection.environment["VALUE"] == "kit" and plain.compose_files(False) == [base / "compose.yaml"]
    assert selection.injections["OPENADKIT_CONFIG_KIT"] == str(kit / "config")
    assert selection.injections["OPENADKIT_CONFIG_DEPLOYMENT"].endswith("/empty")
    assert plain.working_directory == kit and plain.manifest["description"] == "example with this kit's files on top"


def test_a_kit_has_one_manifest_and_names_no_paths(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    for change, message in (
        ({"path": "."}, "unknown deployments.custom field\\(s\\): path"),
        ({"base": ""}, "deployments.custom.base must be a nonempty string"),
    ):
        edit_manifest(kit, lambda document, change=change: document["deployments"].update(
            custom={"description": "Kit deployment", "base": "example"} | change))
        with pytest.raises(cli_manifest.OpenADKitError, match=message):
            cli_catalog.load_catalog(kit)


def test_only_a_kit_deployment_names_a_base(tmp_path):
    root, _ = runtime_tree(tmp_path)
    directory = root / "deployments/on-top"
    directory.mkdir()
    (directory / "deployment.json").write_text(json.dumps({
        "description": "On top", "base": "example",
    }))
    (directory / "compose.yaml").write_text("services:\n  extra:\n    image: busybox:1.36.1\n")
    edit_manifest(root, lambda document: document["deployments"].update({"on-top": {"path": "deployments/on-top"}}))
    with pytest.raises(cli_manifest.OpenADKitError, match="unknown manifest field\\(s\\): base"):
        cli_catalog.get_deployment(root, cli_catalog.load_catalog(root), "on-top")


def test_a_kits_data_replaces_its_bases_at_the_same_destination(tmp_path):
    base_data = [files_resource(tmp_path), files_resource(tmp_path, env="ROSBAG_PATH", name="sample-recording")]
    root, _ = runtime_tree(tmp_path, document=manifest(data=base_data))
    kit = extending_kit(tmp_path, root)

    def data_with(*resources):
        edit_kit_deployment(kit, data=list(resources))
        deployment = cli_catalog.get_deployment(kit, cli_catalog.load_catalog(kit), "custom")
        return [(item["name"], item["destinationEnv"]) for item in deployment.data]

    # Its own recording instead of the sample; the map stays the base's.
    own = files_resource(tmp_path, env="ROSBAG_PATH", name="my-drive")
    assert data_with(own) == [("dataset", "MAP_PATH"), ("my-drive", "ROSBAG_PATH")]
    # Another destination adds to the base's data.
    extra = files_resource(tmp_path, env="MODEL_PATH", name="model")
    assert data_with(extra) == [("dataset", "MAP_PATH"), ("sample-recording", "ROSBAG_PATH"), ("model", "MODEL_PATH")]
    # A name stays one resource: the staging directory of its download.
    with pytest.raises(cli_manifest.OpenADKitError, match="reuses the name of a resource of the base deployment that it keeps: dataset"):
        data_with(files_resource(tmp_path, env="ROSBAG_PATH", name="dataset"))


def test_a_kits_replacement_data_needs_a_directory_of_its_own(tmp_path):
    # Left in the base's directory, the two would replace each other's files.
    root, _ = runtime_tree(tmp_path, document=manifest(data=[files_resource(tmp_path)]))
    kit = extending_kit(tmp_path, root)
    edit_kit_deployment(kit, data=[files_resource(tmp_path, name="my-map")])
    fake_docker(tmp_path)
    result = run_cli(root, "validate", "custom", directory=kit)
    assert result.returncode == 1
    assert ("data my-map replaces dataset of example, but MAP_PATH still names that deployment's directory; "
            "set MAP_PATH in deployments/custom/settings.env") in result.stderr
    with (kit / "deployments/custom/settings.env").open("a") as settings:
        settings.write("MAP_PATH=$HOME/data/my-map\n")
    result = run_cli(root, "validate", "custom", directory=kit)
    assert result.returncode == 0, result.stderr


def test_a_deployment_on_a_base_narrows_its_requirements_but_never_widens_them(tmp_path):
    gpu_data = files_resource(tmp_path, env="MODEL_PATH", name="model", gpu=True)
    document = manifest(gpu=True, data=[files_resource(tmp_path), gpu_data])
    document["requirements"]["gpuArchitectures"] = ["amd64"]
    root, _ = runtime_tree(tmp_path, document=document)
    kit_root = extending_kit(tmp_path, root)

    def on_top_with(requirements):
        edit_kit_deployment(kit_root, requirements=requirements)
        return cli_catalog.get_deployment(kit_root, cli_catalog.load_catalog(kit_root), "custom")

    # Only what it names changes; without a GPU mode the GPU-only data goes too.
    deployment = on_top_with({"architectures": ["amd64"], "gpu": "none"})
    assert deployment.requirements == {"architectures": ["amd64"], "rosDistros": ["humble", "jazzy"], "gpu": "none"}
    assert [item["name"] for item in deployment.data] == ["dataset"]
    assert on_top_with({"gpu": "required"}).requirements["gpu"] == "required"
    assert [item["name"] for item in on_top_with({"rosDistros": ["jazzy"]}).data] == ["dataset", "model"]
    for requirements, message in (
        ({"architectures": ["amd64", "riscv64"]}, "adds riscv64, which the base deployment does not support"),
        ({"rosDistros": ["rolling"]}, "adds rolling"),
        ({"gpuArchitectures": ["arm64"]}, "adds arm64"),
        ({"architectures": ["arm64"]}, "leave no architecture for the GPU mode"),
        ({"gpu": "sometimes"}, "must be none, optional, or required"),
        ({"cpus": 8}, "unknown requirements field"),
    ):
        with pytest.raises(cli_manifest.OpenADKitError, match=message):
            on_top_with(requirements)
    # A base that settled its GPU mode leaves nothing to choose.
    assert cli_manifest.narrow_requirements({"architectures": ["amd64"], "rosDistros": ["humble"], "gpu": "none"},
                                            {"gpu": "none"})["gpu"] == "none"
    with pytest.raises(cli_manifest.OpenADKitError, match="cannot change the base deployment's none"):
        cli_manifest.narrow_requirements({"architectures": ["amd64"], "rosDistros": ["humble"], "gpu": "none"},
                                         {"gpu": "optional"})


def test_safety_island_simulation_runs_where_its_release_does():
    kit = cli_catalog.load_catalog(ROOT)
    deployment = cli_catalog.get_deployment(ROOT, kit, "safety-island-simulation")
    assert deployment.requirements == {"architectures": ["amd64"], "rosDistros": ["humble", "jazzy"], "gpu": "none"}
    assert not any(item.get("gpu") for item in deployment.data)


def test_base_deployment_keeps_its_own_overlay(tmp_path, monkeypatch):
    root, directory = runtime_tree(tmp_path)
    assert overlay_workspace(root, "example", monkeypatch, tmp_path) == str(cli_catalog.state_root() / "empty")
    (directory / "overlay_ws").mkdir()
    assert overlay_workspace(root, "example", monkeypatch, tmp_path) == str(directory / "overlay_ws")


def test_ws_mounts_a_built_workspace_for_a_deployment_without_one(tmp_path, monkeypatch):
    root, directory = runtime_tree(tmp_path)
    workspace = tmp_path / "my_ws"
    (workspace / "src").mkdir(parents=True)
    with pytest.raises(cli_manifest.OpenADKitError, match="is not built; run: openadkit build"):
        overlay_workspace(root, "example", monkeypatch, tmp_path, workspace)
    (workspace / "install").mkdir()
    (workspace / "install/local_setup.bash").write_text("")
    assert overlay_workspace(root, "example", monkeypatch, tmp_path, workspace) == str(workspace)
    calls = fake_docker(tmp_path)
    result = run_cli(root, "run", "example", "--ws", str(workspace))
    assert result.returncode == 0, result.stderr
    up = next(row for row in recorded(calls) if "up" in row["args"])
    assert up["env"]["OPENADKIT_OVERLAY_WS"] == str(workspace)
    # An empty workspace of its own, as `openadkit new` makes one, gives way.
    (directory / "overlay_ws/src").mkdir(parents=True)
    (directory / "overlay_ws/src/README.md").write_text("")
    assert overlay_workspace(root, "example", monkeypatch, tmp_path, workspace) == str(workspace)
    # One with packages keeps them: --ws would hide them.
    (directory / "overlay_ws/src/my_pkg").mkdir()
    (directory / "overlay_ws/src/my_pkg/package.xml").write_text("")
    with pytest.raises(cli_manifest.OpenADKitError, match="has packages of its own"):
        overlay_workspace(root, "example", monkeypatch, tmp_path, workspace)


def test_a_deployment_can_be_named_by_its_directory(tmp_path):
    root, directory = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    fake_docker(tmp_path)
    # The kit around the directory is the one used, wherever the command runs.
    result = run_cli(root, "validate", str(kit / "deployments/custom"), directory=elsewhere)
    assert result.returncode == 0 and "custom is valid" in result.stdout, result.stderr
    result = run_cli(root, "validate", "./deployments/example", directory=root)
    assert result.returncode == 0 and "example is valid" in result.stdout, result.stderr
    # A kit's directory names its deployment while it has one.
    result = run_cli(root, "validate", str(kit), directory=elsewhere)
    assert result.returncode == 0 and "custom is valid" in result.stdout, result.stderr
    edit_manifest(kit, lambda document: document["deployments"].update(second={"base": "example"}))
    # With several, it is the kit, as inside it: validate checks each, and run needs one of them.
    result = run_cli(root, "validate", str(kit), directory=elsewhere)
    assert result.returncode == 0 and "custom is valid" in result.stdout and "second is valid" in result.stdout, result.stderr
    result = run_cli(root, "run", str(kit), directory=elsewhere)
    assert result.returncode == 2, result.stderr
    assert (f"{kit} has several deployments; name one by its directory: "
            f"{kit}/deployments/custom, {kit}/deployments/second") in result.stderr
    result = run_cli(root, "validate", str(kit), "--json", directory=elsewhere)
    assert result.returncode == 2 and "name one by its directory" in json.loads(result.stdout)["error"]
    # A deployment's directory names it, even while it holds no file.
    result = run_cli(root, "validate", str(kit / "deployments/second"), directory=elsewhere)
    assert result.returncode == 0 and "second is valid" in result.stdout, result.stderr


@pytest.mark.parametrize("available", [False, True])
def test_pinned_kit_uses_its_release_cli_or_fails_with_install_guidance(tmp_path, available):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root, extends="v1.2.3")
    record = tmp_path / "delegated"
    if available:
        pinned = tmp_path / "home/.local/share/openadkit/openadkit-v1.2.3"
        pinned.mkdir(parents=True)
        (pinned / "openadkit.json").write_text('{"schemaVersion":2,"kind":"release"}')
        executable(pinned / "openadkit", "#!/usr/bin/env bash\n"
                   f'printf "%s|%s|%s\\n" "$OPENADKIT_KIT" "$OPENADKIT_DELEGATED" "$*" > "{record}"\n')
    else:
        # Offline: the download of the pinned release fails.
        executable(tmp_path / "bin/curl", "#!/usr/bin/env bash\nexit 22\n")
    result = run_cli(root, "run", "custom", directory=kit)
    assert (result.returncode == 0) is available, result.stderr
    if available:
        assert record.read_text().strip() == f"{kit}|1|run custom"
    else:
        assert "could not install Open AD Kit v1.2.3, which this kit extends" in result.stderr


def test_a_kit_downloads_its_pinned_release_without_activating_it(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root, extends="v1.2.3")
    release = release_bin(tmp_path)
    result = run_cli(root, "validate", "custom", "--json", directory=kit,
                     PATH=f"{release}:{tmp_path / 'bin'}:{os.environ['PATH']}")
    assert result.returncode == 0, result.stderr
    # The release's own CLI ran the command; its stdout is untouched.
    assert result.stdout == "ok\n"
    assert "this kit uses Open AD Kit v1.2.3" in result.stderr
    assert (tmp_path / "home/.local/share/openadkit/openadkit-v1.2.3/openadkit").is_file()
    assert not (tmp_path / "home/.local/bin/openadkit").exists()
    assert not (tmp_path / "home/.local/bin/adkit").exists()


def test_a_kit_hands_over_options_only_its_pinned_release_knows(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root, extends="v1.2.3")
    record = tmp_path / "delegated"
    pinned = tmp_path / "home/.local/share/openadkit/openadkit-v1.2.3"
    pinned.mkdir(parents=True)
    (pinned / "openadkit.json").write_text('{"schemaVersion":2,"kind":"release"}')
    executable(pinned / "openadkit", f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" > "{record}"\n')
    workspace = tmp_path / "ws"
    for args, directory in (
        (["run", "custom", "--option-from-a-newer-release"], kit),
        # An option's value that looks like a path is not the deployment.
        (["run", "--ws", str(workspace), "custom", "--option-from-a-newer-release"], kit),
        # A kit named by its directory, from anywhere.
        (["validate", str(kit / "deployments/custom"), "--option-from-a-newer-release"], tmp_path),
    ):
        result = run_cli(root, *args, directory=directory)
        assert result.returncode == 0, result.stderr
        assert record.read_text().strip() == " ".join(args)


@pytest.mark.parametrize("pinned", ["path", "version"])
def test_reading_a_kit_neither_runs_nor_downloads_what_it_pins(tmp_path, pinned):
    root, _ = runtime_tree(tmp_path)
    acted = tmp_path / "acted"
    if pinned == "path":
        # Another Open AD Kit, whose launcher a command that acts runs.
        other = tmp_path / "other"
        shutil.copytree(root, other)
        executable(other / "openadkit", f'#!/usr/bin/env bash\ntouch "{acted}"\n')
        kit = extending_kit(tmp_path, root, extends=str(other))
    else:
        kit = extending_kit(tmp_path, root, extends="v1.2.3")
        executable(tmp_path / "bin/curl", f'#!/usr/bin/env bash\ntouch "{acted}"\nexit 22\n')
    fake_docker(tmp_path)
    for args in (["list"], ["list", "--json"], ["version"], ["run", "--help"], ["validate", "custom", "--help"]):
        result = run_cli(root, *args, directory=kit)
        assert not acted.exists(), args
        assert pinned == "version" or result.returncode == 0, result.stderr
    # Tab asks list for the names; a release that is not installed offers none.
    names = complete(root, ["openadkit", "run", ""], directory=kit)
    assert names == ({"custom"} if pinned == "path" else set())
    assert not acted.exists()
    missing = run_cli(root, "list", directory=kit)
    assert pinned == "path" or "openadkit validate, downloads it" in missing.stdout + missing.stderr
    # A command that acts hands over to the pinned launcher, or downloads the release.
    run_cli(root, "validate", "custom", directory=kit)
    assert acted.exists()


def test_reading_a_kit_runs_with_its_pinned_release_once_that_is_installed(tmp_path):
    # An older openadkit never has to read the manifests of a newer release.
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root, extends="v1.2.3")
    record = tmp_path / "delegated"
    pinned = tmp_path / "home/.local/share/openadkit/openadkit-v1.2.3"
    pinned.mkdir(parents=True)
    (pinned / "openadkit.json").write_text('{"schemaVersion":2,"kind":"release","fieldOfANewerRelease":1}')
    executable(pinned / "openadkit", f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{record}"\necho custom\n')
    for args in (["list"], ["list", "--json"], ["version"]):
        result = run_cli(root, *args, directory=kit)
        assert result.returncode == 0, result.stderr
    assert record.read_text().splitlines() == ["list", "list --json", "version"]
    # Help is this CLI's own, also the deployment list that the top-level help ends with.
    for args in (["list", "--help"], ["run", "--help"], ["--help"]):
        assert run_cli(root, *args, directory=kit).returncode == 0
    assert len(record.read_text().splitlines()) == 3


def test_a_failed_start_names_the_unhealthy_service_and_its_reason(monkeypatch):
    # Compose only says "container autoware-map is unhealthy".
    def container(service, status, output=""):
        return {"Config": {"Labels": {"com.docker.compose.service": service}},
                "State": {"Health": {"Status": status, "Log": [{"Output": "old\n"}, {"Output": output}]}}}

    inspected = [container("map", "unhealthy", "pointcloud_map_loader-1 died with exit code -6\n"),
                 container("planning", "healthy"), {"Config": {"Labels": {"com.docker.compose.service": "rosbag"}}, "State": {}}]

    def run_compose(deployment, selection, arguments, **options):
        if arguments[0] == "up":
            raise cli_manifest.OpenADKitError("command failed with exit code 1: docker")
        return types.SimpleNamespace(stdout="a b c\n" if arguments[0] == "ps" else "")

    monkeypatch.setattr(cli_compose, "run_compose", run_compose)
    monkeypatch.setattr(cli_compose, "restart_counts", lambda *_: {})
    monkeypatch.setattr(cli_compose, "docker", lambda *_, **__: types.SimpleNamespace(stdout=json.dumps(inspected)))
    deployment = types.SimpleNamespace(compose={"waitTimeout": 5})
    with pytest.raises(cli_manifest.OpenADKitError) as error:
        cli_compose.up(deployment, None, [])
    assert str(error.value) == ("map is unhealthy: pointcloud_map_loader-1 died with exit code -6\n"
                                "see: openadkit logs map")
    # Without an unhealthy service, the failure stays Compose's own.
    inspected[0] = container("map", "healthy")
    with pytest.raises(cli_manifest.OpenADKitError, match="command failed with exit code 1"):
        cli_compose.up(deployment, None, [])
    # A command that fails at once, such as a package that is not built, never reaches a healthcheck.
    inspected[1] = container("planning", "starting") | {"RestartCount": 3}
    inspected[1]["State"]["ExitCode"] = 1
    inspected[2]["State"] = {"Status": "exited", "ExitCode": 2}
    with pytest.raises(cli_manifest.OpenADKitError) as error:
        cli_compose.up(deployment, None, [])
    assert str(error.value) == ("planning keeps crashing (exit code 1)\nrosbag exited with code 2\n"
                                "see: openadkit logs planning rosbag")


def test_a_kit_names_the_files_it_does_not_read(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    fake_docker(tmp_path)
    assert "warning" not in run_cli(root, "validate", directory=kit).stderr
    (kit / "compose.yaml").write_text("services: {}\n")
    misspelled = kit / "deployments/custmo"
    misspelled.mkdir()
    (misspelled / "settings.env").write_text("VALUE=lost\n")
    (kit / "deployments/custom/compose.gpu.yaml").write_text("services: {}\n")
    (kit / "deployments/custom/compose.yml").write_text("services: {}\n")
    (kit / "deployments/custom/overlay_ws").mkdir()
    # A directory of fragments that several deployments include is the kit's own business.
    (kit / "deployments/fragments").mkdir()
    (kit / "deployments/fragments/ota-agent.yaml").write_text("services: {}\n")
    result = run_cli(root, "validate", directory=kit)
    assert result.returncode == 0, result.stderr
    warnings = [line for line in result.stderr.splitlines() if line.startswith("warning: this kit does not read ")]
    assert [line.removeprefix("warning: this kit does not read ").split(":")[0] for line in warnings] == [
        "compose.yaml at its root", "deployments/custmo/", "deployments/custom/compose.gpu.yaml",
        "deployments/custom/compose.yml", "deployments/custom/overlay_ws",
    ]


def test_the_kit_variable_in_the_shell_redirects_nothing(tmp_path):
    # A kit's files read OPENADKIT_KIT; exported by hand, it must not choose the kit of every command.
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    fake_docker(tmp_path)
    result = run_cli(root, "validate", "example", directory=tmp_path, OPENADKIT_KIT=str(kit))
    assert result.returncode == 0 and "example is valid" in result.stdout, result.stderr
    result = run_cli(root, "validate", directory=kit, OPENADKIT_KIT=str(tmp_path / "nowhere"))
    assert result.returncode == 0 and "custom is valid" in result.stdout, result.stderr


def test_a_kit_reports_the_open_ad_kit_it_extends_as_its_version(tmp_path):
    root, _ = runtime_tree(tmp_path, release=True)
    kit = extending_kit(tmp_path, root)
    subprocess.run(["git", "init", "-q", str(kit)], check=True)
    version = json.loads(run_cli(root, "version", "--json", directory=kit).stdout)
    # The release it runs, as run.json says; never the commit of the kit's own repository.
    assert (version["kind"], version["version"], version["commit"]) == ("kit", "v1.2.3", None)


def test_validate_checks_every_deployment_of_a_kit_past_a_broken_one(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    edit_manifest(kit, lambda document: document["deployments"].update(
        {"a-broken": {"base": "nowhere"}, "second": {"base": "example"}}))
    fake_docker(tmp_path)
    result = run_cli(root, "validate", directory=kit)
    assert result.returncode == 1
    assert "error: a-broken: unknown base deployment: nowhere" in result.stderr
    assert "custom is valid" in result.stdout and "second is valid" in result.stdout


@NEEDS_COMPOSE
def test_a_kit_names_its_own_files_by_its_root(tmp_path):
    # A relative path in a setting would resolve inside the base, where its Compose file is.
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    (kit / "settings.env").write_text("MAP_PATH=${OPENADKIT_KIT}/maps/mine\n")
    deployment = cli_catalog.get_deployment(kit, cli_catalog.load_catalog(kit), "custom")
    selection = cli_settings.resolve(deployment, cli_catalog.load_catalog(kit), data_only=True)
    assert selection.environment["MAP_PATH"] == f"{kit}/maps/mine"


def test_a_workspace_with_packages_but_no_build_is_named(tmp_path, capsys):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    deployment = cli_catalog.get_deployment(kit, cli_catalog.load_catalog(kit), "custom")
    selection = types.SimpleNamespace(ros_distro="humble")
    package = kit / "overlay_ws/src/my_vehicle_description"
    package.mkdir(parents=True)
    cli_compose.check_overlay_build(deployment, selection, None)
    assert capsys.readouterr().err == ""
    (package / "package.xml").write_text("<package/>")
    cli_compose.check_overlay_build(deployment, selection, None)
    warning = capsys.readouterr().err
    assert "holds packages that are not built" in warning and f"openadkit build {kit / 'overlay_ws'}" in warning
    # A build made by hand, without the CLI's stamp, is the user's to keep right.
    (kit / "overlay_ws/install").mkdir()
    cli_compose.check_overlay_build(deployment, selection, None)
    assert capsys.readouterr().err == ""


def test_an_overlay_built_for_another_distro_or_image_stops(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    deployment = cli_catalog.get_deployment(kit, cli_catalog.load_catalog(kit), "custom")
    selection = types.SimpleNamespace(ros_distro="humble")
    stamp = kit / "overlay_ws/install/.openadkit-overlay.json"
    stamp.parent.mkdir(parents=True)
    stamp.write_text(json.dumps({"image": "devel:2", "rosDistro": "humble"}))
    cli_compose.check_overlay_build(deployment, selection, "devel:2")
    rebuild = re.escape(f"rebuild it: openadkit build {kit / 'overlay_ws'} --ros-distro humble")
    for built in ({"image": "devel:2", "rosDistro": "jazzy"}, {"image": "devel:1", "rosDistro": "humble"}):
        stamp.write_text(json.dumps(built))
        with pytest.raises(cli_manifest.OpenADKitError, match=rebuild):
            cli_compose.check_overlay_build(deployment, selection, "devel:2")


def test_validate_json_reports_a_broken_kit_as_json(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root, extends=str(tmp_path / "nowhere"))
    result = run_cli(root, "validate", "custom", "--json", directory=kit)
    assert result.returncode == 1
    document = json.loads(result.stdout)
    assert document["valid"] is False and document["deployment"] == "custom"
    assert "extends does not point to an Open AD Kit" in document["error"]


@pytest.mark.parametrize("gpu", [False, True])
def test_only_a_gpu_run_uses_the_gpu_component_images(gpu):
    # The CUDA builds are amd64-only: a CPU run, also on arm64, must not need them.
    kit = cli_catalog.load_catalog(ROOT)
    environment = kit.component_environment("humble", "arm64", gpu)
    gpu_images = {name for name in COMPONENT_IMAGES if name.endswith("_GPU_IMAGE")}
    assert gpu_images >= {"SENSING_PERCEPTION_GPU_IMAGE", "PLANNING_GPU_IMAGE"}
    assert (gpu_images <= set(environment)) is gpu
    assert set(environment) - gpu_images == set(COMPONENT_IMAGES) - gpu_images


def test_a_deployment_is_named_by_its_kit_manifest_key_alone(tmp_path):
    root, directory = runtime_tree(tmp_path)
    document = json.loads((directory / "deployment.json").read_text())
    # A renamed directory keeps working: only the kit manifest's key names it.
    renamed = directory.rename(directory.parent / "elsewhere")
    edit_manifest(root, lambda kit: kit["deployments"].update(example={"path": "deployments/elsewhere"}))
    assert cli_catalog.get_deployment(root, cli_catalog.load_catalog(root), "example").name == "example"
    # The file does not repeat the name.
    (renamed / "deployment.json").write_text(json.dumps(document | {"name": "example"}))
    with pytest.raises(cli_manifest.OpenADKitError, match="name"):
        cli_catalog.get_deployment(root, cli_catalog.load_catalog(root), "example")


def test_a_missing_directory_and_a_missing_devel_image_say_so(tmp_path):
    root, _ = runtime_tree(tmp_path)
    fake_docker(tmp_path)
    result = run_cli(root, "validate", "./nope")
    assert result.returncode == 1 and result.stderr == "error: ./nope: no such directory\n"
    # A source checkout builds in its own local devel image and pulls none.
    kit = extending_kit(tmp_path, root)
    (kit / "overlay_ws/src/my_pkg").mkdir(parents=True)
    (kit / "overlay_ws/src/my_pkg/package.xml").write_text("<package/>")
    result = run_cli(root, "build", directory=kit, FAKE_NO_IMAGES="1")
    assert result.returncode == 1 and "has no local build of universe-common-devel; build it with" in result.stderr
    assert "docker: Error" not in result.stderr


def test_a_docker_permission_error_names_the_group_step():
    denied = "permission denied while trying to connect to the Docker daemon socket"
    assert "newgrp docker" in str(cli_compose.docker_error("could not access the Docker daemon", denied + "\n"))
    other = str(cli_compose.docker_error("could not access the Docker daemon", "Cannot connect to the Docker daemon"))
    assert other == "could not access the Docker daemon: Cannot connect to the Docker daemon"


@pytest.mark.skipif(os.geteuid() == 0, reason="setup refuses root")
def test_setup_gpu_needs_a_working_driver_before_it_asks_for_sudo(tmp_path):
    try:
        distribution = platform.freedesktop_os_release().get("ID")
    except OSError:
        distribution = None
    if distribution != "ubuntu":
        pytest.skip("setup runs on Ubuntu only")
    executable(tmp_path / "bin/nvidia-smi", "#!/usr/bin/env bash\nexit 9\n")
    executable(tmp_path / "bin/sudo", f"#!/usr/bin/env bash\ntouch {tmp_path / 'sudo-called'}\nexit 1\n")
    result = subprocess.run(["bash", str(ROOT / "cli/setup.sh"), "setup", "--gpu"], text=True, capture_output=True,
                            timeout=30, env=os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"})
    assert result.returncode == 1 and "install the NVIDIA driver first" in result.stderr
    assert not (tmp_path / "sudo-called").exists()


def test_inline_python_ignores_the_current_directory():
    # `python3 -c` and `python3 -` put the current directory first on sys.path.
    for path in ("openadkit", "cli/setup.sh", "cli/completion.bash"):
        text = (ROOT / path).read_text()
        assert not re.search(r"python3 (-c|-)\s", text), path


def test_run_leaves_another_kits_stack_of_the_same_name_alone(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    other = tmp_path / "other-kit"
    shutil.copytree(kit, other)
    calls = fake_docker(tmp_path, projects=["openadkit-custom"])
    state = root.parent / "home/.local/state/openadkit/runs/openadkit-custom.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"schemaVersion": 1, "kit": str(kit), "deployment": "custom"}))
    result = run_cli(root, "run", "custom", directory=other)
    assert result.returncode != 0 and "error: custom is already running" in result.stderr
    assert not any("up" in row["args"] for row in recorded(calls))
    # The kit that started it is not refused.
    result = run_cli(root, "run", "custom", directory=kit)
    assert "is already running" not in result.stderr


def test_a_kit_deployment_cannot_take_a_release_deployments_name(tmp_path):
    root, _ = runtime_tree(tmp_path)
    kit = extending_kit(tmp_path, root)
    edit = json.loads((kit / "openadkit.json").read_text())
    edit["deployments"] = {"example": edit["deployments"]["custom"]}
    (kit / "openadkit.json").write_text(json.dumps(edit))
    (kit / "deployments/custom").rename(kit / "deployments/example")
    result = run_cli(root, "validate", directory=kit)
    assert result.returncode != 0 and "kit deployment example has the name of a deployment of" in result.stderr
