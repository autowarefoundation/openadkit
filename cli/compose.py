"""Process execution and Docker Compose lifecycle handling."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from manifest import Deployment, OpenADKitError, Selection

PROJECT_PREFIX = "openadkit-"
LIVE_PROJECT_STATES = {"running", "restarting", "paused", "removing"}


COMPOSE_CONTROL_ENV = {
    "COMPOSE_ENV_FILES",
    "COMPOSE_FILE",
    "COMPOSE_PROFILES",
    "COMPOSE_PROJECT_NAME",
}


def ensure_runtime_user() -> None:
    if os.geteuid() == 0:
        raise OpenADKitError("runtime commands must run as a normal user, not root")


def print_command(command: list[str]) -> None:
    print("+ " + shlex.join(command), file=sys.stderr, flush=True)


def run_process(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    print_command(command)
    try:
        subprocess.run(command, cwd=cwd, env=env, text=True, check=True)
    except FileNotFoundError as error:
        raise OpenADKitError(
            f"required command is not installed: {command[0]}"
        ) from error
    except subprocess.CalledProcessError as error:
        raise OpenADKitError(
            f"command failed with exit code {error.returncode}: {command[0]}"
        ) from error


def capture_process(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    trace: bool = True,
) -> subprocess.CompletedProcess[str]:
    if trace:
        print_command(command)
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=check,
        )
    except FileNotFoundError as error:
        raise OpenADKitError(
            f"required command is not installed: {command[0]}"
        ) from error
    except subprocess.CalledProcessError as error:
        raise OpenADKitError(
            f"command failed with exit code {error.returncode}: {command[0]}"
        ) from error


def process_environment(selection: Selection) -> dict[str, str]:
    environment = dict(os.environ)
    for name in COMPOSE_CONTROL_ENV:
        environment.pop(name, None)
    environment.update(selection.injections)
    return environment


def compose_command(deployment: Deployment, selection: Selection) -> list[str]:
    command = ["docker", "compose", "--project-name", deployment.project]
    for env_file in deployment.env_files:
        command.extend(("--env-file", str(env_file)))
    for compose_file in deployment.compose_files(selection.gpu):
        command.extend(("--file", str(compose_file)))
    for profile in deployment.compose["profiles"]:
        command.extend(("--profile", profile))
    return command


def compose_run(
    deployment: Deployment,
    selection: Selection,
    arguments: list[str],
) -> None:
    run_process(
        compose_command(deployment, selection) + arguments,
        cwd=deployment.directory,
        env=process_environment(selection),
    )


def compose_capture(
    deployment: Deployment,
    selection: Selection,
    arguments: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return capture_process(
        compose_command(deployment, selection) + arguments,
        cwd=deployment.directory,
        env=process_environment(selection),
        check=check,
    )


def require_docker() -> None:
    if not shutil.which("docker"):
        raise OpenADKitError("Docker is unavailable. Run: ./openadkit setup")


def _compose_ls_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in COMPOSE_CONTROL_ENV:
        environment.pop(name, None)
    return environment


def running_names(deployment_names: Iterable[str]) -> list[str]:
    require_docker()
    wanted = list(deployment_names)
    result = capture_process(
        ["docker", "compose", "ls", "--format", "json"],
        env=_compose_ls_environment(),
        check=False,
        trace=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise OpenADKitError(f"could not list Compose projects{suffix}")
    try:
        projects = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError as error:
        raise OpenADKitError("could not parse Compose project list") from error
    if not isinstance(projects, list):
        raise OpenADKitError("could not parse Compose project list")
    found: set[str] = set()
    for project in projects:
        if not isinstance(project, dict):
            continue
        name = project.get("Name")
        status = project.get("Status") or ""
        if not isinstance(name, str) or not isinstance(status, str):
            continue
        if not name.startswith(PROJECT_PREFIX):
            continue
        key = name[len(PROJECT_PREFIX) :]
        state = status.lower().split("(", 1)[0].strip()
        if key in wanted and state in LIVE_PROJECT_STATES:
            found.add(key)
    return [name for name in wanted if name in found]


def _runtime_state_path(deployment: Deployment) -> Path:
    return deployment.directory / ".cache" / "runtime.json"


def save_runtime(deployment: Deployment, selection: Selection) -> None:
    cache = deployment.directory / ".cache"
    if cache.is_symlink() or (cache.exists() and not cache.is_dir()):
        raise OpenADKitError(f"unsafe runtime cache path: {cache}")
    cache.mkdir(exist_ok=True)
    path = _runtime_state_path(deployment)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise OpenADKitError(f"unsafe runtime state path: {path}")
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "rosDistro": selection.ros_distro,
                "gpu": selection.gpu,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def load_runtime(deployment: Deployment) -> tuple[str, bool] | None:
    path = _runtime_state_path(deployment)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        return None
    ros_distro = value.get("rosDistro")
    gpu = value.get("gpu")
    if not isinstance(ros_distro, str) or not ros_distro or not isinstance(gpu, bool):
        return None
    return ros_distro, gpu


def render(deployment: Deployment, selection: Selection) -> set[str]:
    require_docker()
    compose_run(deployment, selection, ["config", "--quiet"])
    configured = set(
        compose_capture(deployment, selection, ["config", "--services"])
        .stdout.splitlines()
    )
    declared = set(selection.services)
    declared.update(deployment.compose["resetServices"])
    unknown = sorted(declared - configured)
    if unknown:
        raise OpenADKitError(
            "manifest references unknown Compose service(s): " + ", ".join(unknown)
        )
    return configured


def check_daemon(selection: Selection) -> None:
    result = capture_process(
        ["docker", "info"], env=process_environment(selection), check=False
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise OpenADKitError(f"could not access the Docker daemon{suffix}")
    if not selection.gpu:
        return
    runtimes = capture_process(
        ["docker", "info", "--format", "{{json .Runtimes}}"],
        env=process_environment(selection),
        check=False,
    )
    try:
        available = json.loads(runtimes.stdout) if runtimes.returncode == 0 else {}
    except json.JSONDecodeError:
        available = {}
    if "nvidia" not in available:
        raise OpenADKitError(
            "NVIDIA Container Toolkit is unavailable for the selected GPU mode"
        )


def start(
    deployment: Deployment,
    selection: Selection,
    pull_policy: str,
    configured_services: set[str],
) -> None:
    services = list(selection.services)
    if pull_policy != "never":
        compose_run(
            deployment,
            selection,
            ["pull", "--policy", pull_policy, *services],
        )

    excluded = sorted(configured_services - set(services))
    if excluded:
        compose_run(deployment, selection, ["stop", *excluded])
        compose_run(deployment, selection, ["rm", "--force", *excluded])

    for service in deployment.compose["resetServices"]:
        compose_run(
            deployment,
            selection,
            ["rm", "--stop", "--force", service],
        )

    compose_run(
        deployment,
        selection,
        [
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            str(deployment.compose["waitTimeout"]),
            "--pull",
            "never",
            "--remove-orphans",
            *services,
        ],
    )


def status(deployment: Deployment, selection: Selection) -> None:
    compose_run(deployment, selection, ["ps"])


def logs(deployment: Deployment, selection: Selection, follow: bool) -> None:
    arguments = ["logs"]
    if follow:
        arguments.append("--follow")
    compose_run(deployment, selection, arguments)


def stop(deployment: Deployment, selection: Selection) -> None:
    compose_run(deployment, selection, ["down", "--remove-orphans"])
