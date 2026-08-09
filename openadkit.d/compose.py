"""Process execution and Docker Compose lifecycle handling."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from manifest import (
    Deployment,
    OpenADKitError,
    Selection,
    ensure_safe_existing,
)


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
    print("+ " + shlex.join(command))


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
) -> subprocess.CompletedProcess[str]:
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


def render(deployment: Deployment, selection: Selection) -> set[str]:
    require_docker()
    compose_run(deployment, selection, ["config", "--quiet"])
    configured = set(
        compose_capture(deployment, selection, ["config", "--services"])
        .stdout.splitlines()
    )
    declared = set(selection.services) | set(selection.verification_services)
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


def hook_environment(
    deployment: Deployment,
    selection: Selection,
) -> dict[str, str]:
    environment = dict(selection.environment)
    for name in COMPOSE_CONTROL_ENV:
        environment.pop(name, None)
    environment.update(
        {
            "OPENADKIT_ROOT": str(deployment.root),
            "OPENADKIT_DEPLOYMENT": deployment.name,
            "OPENADKIT_DEPLOYMENT_DIR": str(deployment.directory),
            "OPENADKIT_PROJECT": deployment.project,
            "OPENADKIT_GPU": "true" if selection.gpu else "false",
            "OPENADKIT_GROUP": selection.group or "",
            "OPENADKIT_FEATURES": ",".join(selection.features),
        }
    )
    return environment


def run_hook(
    deployment: Deployment,
    phase: str,
    selection: Selection,
) -> None:
    relative = deployment.hooks.get(phase)
    if not relative:
        return
    hook = ensure_safe_existing(
        deployment.directory, relative, f"{phase} hook", executable=True
    )
    run_process(
        [str(hook)],
        cwd=deployment.directory,
        env=hook_environment(deployment, selection),
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


def verify(deployment: Deployment, selection: Selection) -> None:
    running = compose_capture(
        deployment,
        selection,
        ["ps", "--status", "running", "--services"],
        check=False,
    )
    if running.returncode != 0:
        raise OpenADKitError("could not inspect running Compose services")
    actual = set(running.stdout.splitlines())
    missing = [
        service
        for service in selection.verification_services
        if service not in actual
    ]
    if missing:
        raise OpenADKitError(
            f"required service(s) are not running: {', '.join(missing)}"
        )
    run_hook(deployment, "verify", selection)


def status(deployment: Deployment, selection: Selection) -> None:
    compose_run(deployment, selection, ["ps"])


def logs(deployment: Deployment, selection: Selection, follow: bool) -> None:
    arguments = ["logs"]
    if follow:
        arguments.append("--follow")
    compose_run(deployment, selection, arguments)


def stop(deployment: Deployment, selection: Selection) -> None:
    compose_run(deployment, selection, ["stop"])


def down(deployment: Deployment, selection: Selection) -> None:
    compose_run(deployment, selection, ["down", "--remove-orphans"])
