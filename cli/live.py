"""The running system, by Compose project name: status, logs, restart, shell, record, stop."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from catalog import output_root
from compose import (
    HOOK_MOUNTS,
    PROJECT_PREFIX,
    ROS_SHELL,
    SHELL_SETUP,
    _compose_ls_environment,
    capture_process,
    live_projects,
    print_command,
    report_container_overrides,
    run_process,
)
from manifest import OpenADKitError, load_json


def autoware_state(project: str) -> dict[str, Any] | None:
    """The AD API state from the running api service, or None without one."""
    if "api" not in running_services(project):
        return None
    script = (Path(__file__).parent / "autoware_state.py").read_text(encoding="utf-8")
    result = project_capture(
        project, ["exec", "-T", "api", "bash", "-c", ROS_SHELL + 'exec python3 -c "$0"', script]
    )
    try:
        state = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def format_autoware_state(state: dict[str, Any]) -> list[str]:
    lines = []
    for name in ("localization", "routing", "mode", "mrm"):
        item = state.get(name)
        if not isinstance(item, dict):
            lines.append(f"{name:<13}no data")
            continue
        text = item["state"]
        if name == "mode":
            notes = [] if item.get("autowareControl", True) else ["manual control"]
            if item.get("autonomousAvailable"):
                notes.append("autonomous available")
            text += f" ({', '.join(notes)})" if notes else ""
        elif name == "mrm" and item.get("behavior"):
            text += f": {item['behavior']}"
        lines.append(f"{name:<13}{text}")
    return lines


# The running stack is found from Docker, not from a kit: any directory and
# any release's CLI reach it. run allows one deployment per host, so the live
# projects are its views, its single-host project or the nodes of it that
# run here.
def live_views(node: str | None = None) -> list[str]:
    projects = sorted(live_projects())
    if node is not None:
        projects = [name for name in projects if name.endswith(f"-{node}")]
    return projects


def view_name(project: str) -> str:
    return project[len(PROJECT_PREFIX):]


def live_view(node: str | None) -> str:
    """The one live project a command acts on."""
    projects = live_views(node)
    if not projects:
        raise OpenADKitError(f"node {node} is not running here" if node else "nothing is running")
    if len(projects) > 1:
        names = ", ".join(view_name(project) for project in projects)
        raise OpenADKitError(f"{names} run here; choose one with --node")
    return projects[0]


def project_command(project: str, arguments: list[str]) -> list[str]:
    return ["docker", "compose", "--project-name", project, *arguments]


# Compose finds a running project by its labels. From / it reads no Compose
# file of the current directory, so none of the deployment's settings are needed.
def project_run(project: str, arguments: list[str]) -> None:
    run_process(project_command(project, arguments), cwd=Path("/"), env=_compose_ls_environment())


def project_capture(project: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return capture_process(
        project_command(project, arguments), cwd=Path("/"), env=_compose_ls_environment(),
        check=False, trace=False,
    )


def running_services(project: str) -> list[str]:
    return project_capture(project, ["ps", "--services", "--status", "running"]).stdout.split()


def visualizer_address(tls: bool) -> str:
    """Plain HTTP unless the site gives noVNC its own certificate."""
    return f"visualizer: {'https' if tls else 'http'}://localhost:6080/vnc.html"


def status(project: str) -> None:
    project_run(project, ["ps"])
    state = autoware_state(project)
    if state is not None:
        print()
        print("\n".join(format_autoware_state(state)))
    if "visualizer" in running_services(project):
        certificate = project_capture(project, ["exec", "-T", "visualizer", "printenv", "NOVNC_CERT"])
        print()
        print(visualizer_address(bool(certificate.stdout.strip())))
        print("password: REMOTE_PASSWORD (default openadkit)")


def logs(project: str, follow: bool, services: list[str]) -> None:
    project_run(project, ["logs", *(["--follow"] if follow else []), *services])


def hooked_services(project: str) -> list[str]:
    """Services that take the integrator's layer: config overrides or overlay workspaces."""
    ids = project_capture(project, ["ps", "--quiet"]).stdout.split()
    inspected = capture_process(
        ["docker", "inspect", *ids], env=_compose_ls_environment(), check=False, trace=False
    ) if ids else None
    try:
        containers = json.loads(inspected.stdout) if inspected else []
    except json.JSONDecodeError as error:
        raise OpenADKitError("could not inspect the running services") from error
    return sorted(
        container["Config"]["Labels"]["com.docker.compose.service"]
        for container in containers
        if any(mount.get("Destination", "").startswith(HOOK_MOUNTS) for mount in container.get("Mounts", []))
    )


def restart(project: str, services: list[str], everything: bool) -> tuple[list[str], list[str]]:
    """Restart services in place, with the settings they run with.

    The default is every service that takes Open AD Kit config or an overlay
    workspace, so a change to either applies without restarting a simulator
    such as CARLA. Everything also reruns the one-shot services, as run did.
    Returns the restarted services and the running ones left alone.
    """
    running = running_services(project)
    if everything:
        project_run(project, ["restart"])
        return sorted(running), []
    services = services or hooked_services(project)
    if not services:
        raise OpenADKitError(f"{view_name(project)} has no service with Open AD Kit config to restart")
    project_run(project, ["restart", *services])
    return services, sorted(set(running) - set(services))


def wait_after_restart(project: str, services: list[str]) -> None:
    """Return once the restarted services are ready, as run does: their
    healthchecks pass, and none crashed. A restart starts each healthcheck's
    start period over, so Docker bounds the wait."""
    ids = project_capture(project, ["ps", "--all", "--quiet", *services]).stdout.split()
    if not ids:
        return
    print("waiting for the restarted services to be ready...", file=sys.stderr, flush=True)
    while True:
        result = capture_process(
            [
                "docker", "inspect", "--format",
                '{{index .Config.Labels "com.docker.compose.service"}} {{.State.Status}} {{.State.ExitCode}} '
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                *ids,
            ],
            env=_compose_ls_environment(), check=False, trace=False,
        )
        rows = [row for row in (line.split() for line in result.stdout.splitlines()) if len(row) == 4]
        # A one-shot service may finish, as map-check does, but not fail.
        failed = sorted({
            service for service, state, code, health in rows
            if state in ("restarting", "dead") or (state == "exited" and code != "0") or health == "unhealthy"
        })
        if failed:
            raise OpenADKitError(f"{', '.join(failed)} failed after restart; see: openadkit logs {' '.join(failed)}")
        if not any(health == "starting" for *_, health in rows):
            report_container_overrides(project_capture(project, ["ps", "--quiet"]).stdout.split(), _compose_ls_environment())
            return
        time.sleep(2)


def shell(project: str, service: str, command: list[str]) -> None:
    """A shell, or one command, in a running service with ROS, Autoware and the overlays sourced."""
    arguments = ["exec"] if sys.stdin.isatty() else ["exec", "-T"]
    arguments += [service, "bash", "-c", SHELL_SETUP + 'exec "$@"', "bash", *(command or ["bash"])]
    project_run(project, arguments)


def record(project: str, topics: list[str], output: Path | None) -> Path:
    """Record topics into a bag on the host until interrupted.

    The recorder runs as a copy of the running api container: its image,
    environment, user and mounts, so it joins the same ROS domain and
    middleware, and its entrypoint sources the overlay workspaces for
    integrator message types. The bag is written to a host directory, so it
    survives the deployment's containers.
    """
    ids = project_capture(project, ["ps", "--quiet", "api"]).stdout.split()
    if not ids:
        raise OpenADKitError(f"{view_name(project)} has no running api service to record from")
    environment = _compose_ls_environment()
    inspected = capture_process(
        ["docker", "inspect", ids[0]], env=environment, check=False, trace=False
    )
    try:
        config = json.loads(inspected.stdout)[0]["Config"]
    except (ValueError, LookupError, TypeError) as error:
        raise OpenADKitError("could not inspect the api container") from error
    output = output or output_root() / deployment_of(config, view_name(project)) / "recordings"
    bag = output / f"{view_name(project)}-{time.strftime('%Y%m%d-%H%M%S')}"
    output.mkdir(parents=True, exist_ok=True)
    # The container's own entrypoint, which a service may have overridden.
    entrypoint = config.get("Entrypoint") or []
    command = [
        "docker", "run", "--rm", "--init",
        *(["--entrypoint", entrypoint[0]] if entrypoint else []),
        "--network", "host", "--ipc", "host",
        "--volumes-from", f"{ids[0]}:ro",
        "--volume", f"{output}:/openadkit/recordings",
        *(["--user", config["User"]] if config.get("User") else []),
        *(argument for variable in config.get("Env") or [] for argument in ("--env", variable)),
        config["Image"], *entrypoint[1:],
        "bash", "-c", 'exec ros2 bag record --output "$0" "$@"',
        f"/openadkit/recordings/{bag.name}", *(topics or ["--all"]),
    ]
    print_command(command)
    process = subprocess.Popen(command, env=environment)
    interrupted = False
    while True:
        try:
            returncode = process.wait()
            break
        except KeyboardInterrupt:
            # Ctrl+C reached the recorder too; killing the client would leave
            # it recording, so wait while it closes the bag.
            interrupted = True
    # Ctrl+C ends ros2 bag record with a nonzero status; a bag is a result.
    # Without it the recorder stopped on its own, and the bag may be partial.
    if returncode != 0 and not (interrupted and bag.is_dir()):
        raise OpenADKitError(
            f"recording failed with exit status {returncode}"
            + (f"; partial bag: {bag}" if bag.is_dir() else "")
        )
    return bag


def deployment_of(config: dict[str, Any], fallback: str) -> str:
    """The deployment a container runs: its project's directory holds deployment.json."""
    directory = (config.get("Labels") or {}).get("com.docker.compose.project.working_dir", "")
    try:
        name = load_json(Path(directory) / "deployment.json")["name"]
    except (OpenADKitError, KeyError, TypeError):
        name = None
    return name if isinstance(name, str) and name else fallback


def stop(project: str) -> None:
    project_run(project, ["down", "--remove-orphans"])
