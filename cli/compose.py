"""Process execution and Docker Compose lifecycle handling."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from manifest import Deployment, OpenADKitError, Selection, parse_dotenv

PROJECT_PREFIX = "openadkit-"
LIVE_PROJECT_STATES = {"running", "restarting", "paused", "removing"}
# Launch failures show up within seconds; watch this long after `up`.
SETTLE_SECONDS = 10


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
        detail = " ".join((error.stderr or "").split())
        suffix = f": {detail}" if detail else ""
        raise OpenADKitError(
            f"command failed with exit code {error.returncode}: "
            f"{command[0]}{suffix}"
        ) from error


def process_environment(selection: Selection) -> dict[str, str]:
    environment = dict(os.environ)
    for name in COMPOSE_CONTROL_ENV:
        environment.pop(name, None)
    environment.update(selection.injections)
    return environment


def compose_process_environment(
    deployment: Deployment, selection: Selection
) -> dict[str, str]:
    """Environment Compose uses to interpolate the deployment.

    Compose prefers the process environment over ``--env-file``, so a shell
    export would otherwise hide ``config.gpu.env`` and ``config.local.env``.
    Drop shell values for names the env files define and let Compose read
    the files itself, so quoting and ``$VAR`` expansion follow Compose rules.
    CLI injections (distro and component images) still win.
    """
    environment = dict(os.environ)
    for path in deployment.env_files(selection.gpu):
        for name in parse_dotenv(path):
            environment.pop(name, None)
    environment.update(selection.injections)
    for name in COMPOSE_CONTROL_ENV:
        environment.pop(name, None)
    return environment


def compose_command(deployment: Deployment, selection: Selection) -> list[str]:
    command = ["docker", "compose", "--project-name", deployment.project]
    for env_file in deployment.env_files(selection.gpu):
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
        env=compose_process_environment(deployment, selection),
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
        env=compose_process_environment(deployment, selection),
        check=check,
    )


def require_docker() -> None:
    if not shutil.which("docker"):
        raise OpenADKitError("Docker is unavailable. Run: openadkit setup")


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


def require_stopped(name: str) -> None:
    """Refuse destructive cleanup while this deployment's project is live."""
    if not shutil.which("docker"):
        return
    if name in running_names([name]):
        raise OpenADKitError(
            f"{name} is running; stop it before deleting data: "
            f"openadkit stop {name}"
        )


def render(deployment: Deployment, selection: Selection) -> set[str]:
    require_docker()
    compose_run(deployment, selection, ["config", "--quiet"])
    configured = set(
        compose_capture(deployment, selection, ["config", "--services"])
        .stdout.splitlines()
    )
    # The Compose project is the deployment: every configured service is meant
    # to run. Only the oneshot services are cross-checked, so a typo in a
    # resetServices entry still fails fast.
    unknown = sorted(set(deployment.compose["resetServices"]) - configured)
    if unknown:
        raise OpenADKitError(
            "manifest references unknown Compose service(s): " + ", ".join(unknown)
        )
    return configured


def create_writable_mounts(deployment: Deployment, selection: Selection) -> None:
    """Create missing writable bind sources as the user.

    Docker creates a missing bind source as root, which the services, running
    as the user, then cannot write to (for example ~/autoware_data).
    """
    result = compose_capture(deployment, selection, ["config", "--format", "json"])
    try:
        services = json.loads(result.stdout).get("services") or {}
    except (json.JSONDecodeError, AttributeError) as error:
        raise OpenADKitError("could not parse the Compose configuration") from error
    for service in services.values():
        for volume in service.get("volumes") or []:
            if volume.get("type") != "bind" or volume.get("read_only"):
                continue
            source = Path(volume["source"])
            if not source.exists():
                source.mkdir(parents=True)


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


def failed_services(
    deployment: Deployment, selection: Selection, ids: list[str]
) -> list[str]:
    """Long-running services that restarted or exited with an error."""
    result = capture_process(
        [
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "com.docker.compose.service"}} '
            "{{.RestartCount}} {{.State.Status}} {{.State.ExitCode}}",
            *ids,
        ],
        env=process_environment(selection),
        trace=False,
    )
    failed = set()
    for line in result.stdout.splitlines():
        service, restarts, state, exit_code = line.split()
        if service in deployment.compose["resetServices"]:
            continue
        if restarts != "0" or state == "restarting" or exit_code != "0":
            failed.add(service)
    return sorted(failed)


def check_services_stay_up(deployment: Deployment, selection: Selection) -> None:
    """Fail when a service crashes shortly after `up`.

    Without healthchecks `up --wait` only waits for the containers to start, so
    a service that fails during launch and restarts would still look running.
    """
    ids = compose_capture(deployment, selection, ["ps", "--all", "--quiet"]).stdout.split()
    if not ids:
        return
    print(
        f"checking that services stay up for {SETTLE_SECONDS}s...",
        file=sys.stderr,
        flush=True,
    )
    for _ in range(SETTLE_SECONDS):
        failed = failed_services(deployment, selection, ids)
        if failed:
            raise OpenADKitError(
                f"{', '.join(failed)} failed after start; "
                f"see: openadkit logs {deployment.name}"
            )
        time.sleep(1)


def start(deployment: Deployment, selection: Selection, pull_policy: str) -> None:
    if pull_policy != "never":
        compose_run(deployment, selection, ["pull", "--policy", pull_policy])

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
        ],
    )
    check_services_stay_up(deployment, selection)


def status(deployment: Deployment, selection: Selection) -> None:
    compose_run(deployment, selection, ["ps"])


def logs(deployment: Deployment, selection: Selection, follow: bool) -> None:
    arguments = ["logs"]
    if follow:
        arguments.append("--follow")
    compose_run(deployment, selection, arguments)


def stop(deployment: Deployment, selection: Selection) -> None:
    compose_run(deployment, selection, ["down", "--remove-orphans"])
