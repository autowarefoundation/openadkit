"""The running system, by Compose project name: status, logs, restart, shell, record, stop."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from catalog import output_root
from compose import (
    HOOK_MOUNTS,
    PROJECT_PREFIX,
    ROS_SHELL,
    SHELL_SETUP,
    docker,
    live_projects,
    print_command,
    read_run_state,
    remove_run_state,
    stopped_project_files,
    unhealthy_reasons,
)
from manifest import OpenADKitError
from settings import docker_environment


def autoware_state(project: str) -> dict[str, Any] | None:
    """The AD API state from the running api service, or None without one."""
    if "api" not in running_services(project):
        return None
    script = (Path(__file__).parent / "autoware_state.py").read_text(encoding="utf-8")
    result = run_project(
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
# projects are all its own: its single-host project, or the roles of it that
# run here.
def running_projects(role: str | None = None) -> list[str]:
    projects = sorted(live_projects())
    if role is not None:
        projects = [name for name in projects if name.endswith(f"_{role}")]
    return projects


def stopped_projects(role: str | None = None) -> list[str]:
    """Projects whose containers are left but none runs; stop removes them."""
    projects = sorted(stopped_project_files())
    if role is not None:
        projects = [name for name in projects if name.endswith(f"_{role}")]
    return projects


def display_name(project: str) -> str:
    return project[len(PROJECT_PREFIX):]


def running_project(role: str | None, *, stopped: bool = False) -> str:
    """The one live project a command acts on; with `stopped`, a stack whose
    containers all stopped too, as after a failed start."""
    projects = running_projects(role) or (stopped_projects(role) if stopped else [])
    if not projects:
        raise OpenADKitError(f"role {role} is not running here" if role else "nothing is running")
    if len(projects) > 1:
        names = ", ".join(display_name(project) for project in projects)
        raise OpenADKitError(f"{names} run here; choose one with --role")
    return projects[0]


# Compose finds a running project by its labels. From / it reads no Compose
# file of the current directory, so none of the deployment's settings are needed.
def run_project(project: str, arguments: list[str], *, show: bool = False) -> subprocess.CompletedProcess[str]:
    """A Compose command on a running project: shown, or captured quietly and unchecked."""
    command = ["docker", "compose", "--project-name", project, *arguments]
    return docker(command, cwd=Path("/"), show=show, check=show, trace=show)


def running_services(project: str) -> list[str]:
    return run_project(project, ["ps", "--services", "--status", "running"]).stdout.split()


def visualizer_address(tls: bool) -> str:
    """Plain HTTP unless the host settings give noVNC its own certificate."""
    return f"visualizer: {'https' if tls else 'http'}://localhost:6080/vnc.html"


def unhealthy_services(project: str) -> dict[str, str]:
    """The project's unhealthy services, each with its reason."""
    return unhealthy_reasons(running_containers(project))


def containers(project: str) -> list[dict[str, str]]:
    """Each container of the project, stopped ones included: its service, its
    own name as docker ps shows it, its state and its status line."""
    output = run_project(project, ["ps", "--all", "--format", "json"]).stdout.strip()
    try:
        # One JSON document per line; older Compose printed one array.
        rows = json.loads(output) if output.startswith("[") else [json.loads(line) for line in output.splitlines()]
        found = [
            {"service": row["Service"], "container": row["Name"], "state": row["State"], "status": row["Status"]}
            for row in rows
        ]
    except (ValueError, LookupError, TypeError) as error:
        raise OpenADKitError("could not list the services") from error
    return sorted(found, key=lambda row: row["service"])


def print_services(rows: list[dict[str, str]]) -> None:
    """A service by the name the commands take, beside the container Docker shows."""
    table = [("SERVICE", "CONTAINER", "STATUS"), *((row["service"], row["container"], row["status"]) for row in rows)]
    widths = [max(len(line[column]) for line in table) for column in (0, 1)]
    for service, container, state in table:
        print(f"{service:<{widths[0]}}  {container:<{widths[1]}}  {state}")
    sys.stdout.flush()


def resolve_services(project: str, names: list[str], known: set[str] | None = None) -> list[str]:
    """The services the names stand for. A service goes by its own name, and
    also by its container's, which docker ps and the log lines show."""
    rows = containers(project)
    services = {row["service"] for row in rows} | (known or set())
    by_container = {row["container"]: row["service"] for row in rows}
    resolved = []
    for name in names:
        if name not in services and name not in by_container:
            raise OpenADKitError(f"no service named {name}\nservices: {', '.join(sorted(services))}")
        resolved.append(name if name in services else by_container[name])
    return list(dict.fromkeys(resolved))


def status(project: str) -> None:
    # Stopped containers stay listed: a crashed service and a one-shot service's
    # exit code show here.
    print_services(containers(project))
    unhealthy = unhealthy_services(project)
    if unhealthy:
        print()
    for service, reason in sorted(unhealthy.items()):
        print(f"{service} is unhealthy" + (f": {reason}" if reason else ""))
    state = autoware_state(project)
    if state is not None:
        print()
        print("\n".join(format_autoware_state(state)))
    if "visualizer" in running_services(project):
        certificate = run_project(project, ["exec", "-T", "visualizer", "printenv", "NOVNC_CERT"])
        print()
        print(visualizer_address(bool(certificate.stdout.strip())))
        print("password: REMOTE_PASSWORD (default openadkit)")


def status_stopped(project: str) -> None:
    """The containers a stopped project left, with how each ended."""
    print_services(containers(project))


# A stack up for hours holds tens of thousands of lines: following starts from
# each service's recent ones.
FOLLOW_TAIL = "100"


def logs(project: str, follow: bool, services: list[str]) -> None:
    services = resolve_services(project, services)
    run_project(project, ["logs", *(["--follow", "--tail", FOLLOW_TAIL] if follow else []), *services], show=True)


def running_containers(project: str) -> list[dict[str, Any]]:
    """What Docker reports of the project's running containers."""
    ids = run_project(project, ["ps", "--quiet"]).stdout.split()
    inspected = docker(["docker", "inspect", *ids], check=False, trace=False) if ids else None
    try:
        containers = json.loads(inspected.stdout) if inspected else []
    except json.JSONDecodeError as error:
        raise OpenADKitError("could not inspect the running services") from error
    return containers if isinstance(containers, list) else []


def service_of(container: dict[str, Any]) -> str:
    return container["Config"]["Labels"]["com.docker.compose.service"]


def hooked_services(project: str) -> list[str]:
    """Services that mount config overrides or overlay workspaces."""
    return sorted(
        service_of(container)
        for container in running_containers(project)
        if any(mount.get("Destination", "").startswith(HOOK_MOUNTS) for mount in container.get("Mounts", []))
    )


def pid_followers(project: str, services: set[str]) -> set[str]:
    """Running services in the process namespace of one of `services`.

    Recreating the owner (pid: service:map) ends every process in its
    namespace, and Docker cannot restart a container into a namespace that is
    gone: whoever joins a recreated service is recreated with it.
    """
    containers = running_containers(project)
    owners = {container["Id"]: service_of(container) for container in containers}
    followers = set()
    for container in containers:
        mode = (container.get("HostConfig") or {}).get("PidMode") or ""
        if mode.startswith("container:") and owners.get(mode.removeprefix("container:")) in services:
            followers.add(service_of(container))
    return followers - services


def shell(project: str, service: str, command: list[str]) -> int:
    """A shell, or one command, in a running service with ROS, Autoware and
    the overlays sourced. Returns the shell's or the command's exit status."""
    service = resolve_services(project, [service])[0]
    arguments = ["exec"] if sys.stdin.isatty() else ["exec", "-T"]
    arguments += [service, "bash", "-c", SHELL_SETUP + 'exec "$@"', "bash", *(command or ["bash"])]
    command_line = ["docker", "compose", "--project-name", project, *arguments]
    return docker(command_line, cwd=Path("/"), show=True, check=False).returncode


def record(project: str, topics: list[str], output: Path | None) -> Path:
    """Record topics into a bag on the host until interrupted.

    The recorder runs as a copy of the running api container: its image,
    environment, user and mounts, so it joins the same ROS domain and
    middleware, and its entrypoint sources the overlay workspaces for
    a kit's message types. The bag is written to a host directory, so it
    survives the deployment's containers.
    """
    ids = run_project(project, ["ps", "--quiet", "api"]).stdout.split()
    if not ids:
        raise OpenADKitError(f"{display_name(project)} has no running api service to record from")
    inspected = docker(["docker", "inspect", ids[0]], check=False, trace=False)
    try:
        config = json.loads(inspected.stdout)[0]["Config"]
    except (ValueError, LookupError, TypeError) as error:
        raise OpenADKitError("could not inspect the api container") from error
    output = output or output_root() / deployment_name(project) / "recordings"
    bag = output / f"{display_name(project)}-{time.strftime('%Y%m%d-%H%M%S')}"
    output.mkdir(parents=True, exist_ok=True)
    # The container's own entrypoint, which a service may have overridden.
    entrypoint = config.get("Entrypoint") or []
    # Its environment holds settings such as REMOTE_PASSWORD; an env file
    # only the user can read keeps them off the command line.
    variables = config.get("Env") or []
    descriptor, env_file = tempfile.mkstemp(prefix="openadkit-record-", suffix=".env")
    with os.fdopen(descriptor, "w", encoding="utf-8") as output_file:
        output_file.writelines(f"{variable}\n" for variable in variables if "\n" not in variable)
    command = [
        "docker", "run", "--rm", "--init",
        *(["--entrypoint", entrypoint[0]] if entrypoint else []),
        "--network", "host", "--ipc", "host",
        "--volumes-from", f"{ids[0]}:ro",
        "--volume", f"{output}:/openadkit/recordings",
        *(["--user", config["User"]] if config.get("User") else []),
        "--env-file", env_file,
        *(argument for variable in variables if "\n" in variable for argument in ("--env", variable)),
        config["Image"], *entrypoint[1:],
        "bash", "-c", 'exec ros2 bag record --output "$0" "$@"',
        f"/openadkit/recordings/{bag.name}", *(topics or ["--all"]),
    ]
    print_command(command)
    try:
        process = subprocess.Popen(command, env=docker_environment())
        interrupted = False
        while True:
            try:
                returncode = process.wait()
                break
            except KeyboardInterrupt:
                # Ctrl+C reached the recorder too; killing the client would leave
                # it recording, so wait while it closes the bag.
                interrupted = True
    finally:
        os.unlink(env_file)
    # Ctrl+C ends ros2 bag record with a nonzero status; a bag is a result.
    # Without it the recorder stopped on its own, and the bag may be partial.
    if returncode != 0 and not (interrupted and bag.is_dir()):
        raise OpenADKitError(
            f"recording failed with exit status {returncode}"
            + (f"; partial bag: {bag}" if bag.is_dir() else "")
        )
    return bag


def deployment_name(project: str) -> str:
    """The deployment a project runs: names never contain "_", which separates a role."""
    state = read_run_state(project)
    return state["deployment"] if state else display_name(project).split("_", 1)[0]


def stop(project: str) -> None:
    run_project(project, ["down", "--remove-orphans"], show=True)
    remove_run_state(project)
