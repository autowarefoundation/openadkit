"""Process execution and Docker Compose lifecycle handling."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

from manifest import (
    Deployment,
    OpenADKitError,
    RuntimeContext,
    Selection,
    parse_dotenv,
)

PROJECT_PREFIX = "openadkit-"
LIVE_PROJECT_STATES = {"running", "restarting", "paused", "removing"}
# Launch failures show up within seconds; watch this long after `up`.
SETTLE_SECONDS = 10
INTERNAL_IMAGE_ROOTS = {"opt", "usr", "etc", "bin", "sbin", "lib", "lib64", "home", "root"}
OVERLAY_RUNTIME_ROOT = PurePosixPath("/tmp/openadkit")


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
    export would otherwise hide ``config.gpu.env`` and the site configuration.
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


def compose_command(
    deployment: Deployment, selection: Selection, *, environment_from: Deployment | None = None
) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        deployment.project_name(selection.node),
    ]
    for env_file in (environment_from or deployment).env_files(selection.gpu):
        command.extend(("--env-file", str(env_file)))
    for compose_file in deployment.compose_files(selection.gpu, selection.node):
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


def live_projects() -> set[str]:
    """Names of the Open AD Kit Compose projects that are live on this host."""
    require_docker()
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
    live: set[str] = set()
    for project in projects:
        if not isinstance(project, dict):
            continue
        name = project.get("Name")
        status = project.get("Status") or ""
        if not isinstance(name, str) or not isinstance(status, str):
            continue
        state = status.lower().split("(", 1)[0].strip()
        if name.startswith(PROJECT_PREFIX) and state in LIVE_PROJECT_STATES:
            live.add(name)
    return live


def owner(project: str, deployment_names: Iterable[str]) -> str | None:
    """Deployment that owns a project: openadkit-<name> or openadkit-<name>-<node>.

    The longest matching name wins, so planning-simulation is never read as
    node "simulation" of a deployment called planning.
    """
    key = project[len(PROJECT_PREFIX) :]
    matches = [
        name
        for name in deployment_names
        if key == name or key.startswith(f"{name}-")
    ]
    return max(matches, key=len) if matches else None


def running_names(deployment_names: Iterable[str]) -> list[str]:
    wanted = list(deployment_names)
    found = {owner(project, wanted) for project in live_projects()}
    return [name for name in wanted if name in found]


def live_nodes(deployment: Deployment) -> list[str | None]:
    """Live views of one deployment: None is the single-host project."""
    live = live_projects()
    views: list[str | None] = []
    if deployment.project_name() in live:
        views.append(None)
    views.extend(
        node for node in sorted(deployment.nodes) if deployment.project_name(node) in live
    )
    return views


def view_label(node: str | None) -> str:
    return "single-host" if node is None else f"node {node}"


def live_state_conflict(deployment: Deployment, selection: Selection) -> str | None:
    """Nodes of one deployment may share a host; single-host and nodes may not."""
    live = live_nodes(deployment)
    clashing: list[str | None]
    if selection.node is None:
        clashing = [node for node in live if node is not None]
    else:
        clashing = [None] if None in live else []
    if not clashing:
        return None
    running = ", ".join(view_label(node) for node in clashing)
    return (
        f"{deployment.name} is already running as {running}; "
        f"stop it with openadkit stop {deployment.name} "
        f"before starting {view_label(selection.node)}"
    )


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
    unknown = sorted(set(deployment.reset_services(selection.node)) - configured)
    if unknown:
        raise OpenADKitError(
            "manifest references unknown Compose service(s): " + ", ".join(unknown)
        )
    return configured


def compose_model(
    deployment: Deployment, selection: Selection, *, environment_from: Deployment | None = None
) -> dict[str, Any]:
    result = capture_process(
        compose_command(deployment, selection, environment_from=environment_from)
        + ["config", "--format", "json"],
        cwd=deployment.directory,
        env=compose_process_environment(environment_from or deployment, selection),
    )
    try:
        services = json.loads(result.stdout)["services"]
        if not isinstance(services, dict):
            raise ValueError("services must be an object")
    except (ValueError, KeyError, TypeError) as error:
        raise OpenADKitError("could not parse the Compose configuration") from error
    return services


def overlay_warnings(
    base: dict[str, Any], services: dict[str, Any], unknown_variables: set[str]
) -> list[dict[str, str]]:
    """Compare resolved services, not YAML text; inherited mounts are allowed.

    Both models use the kit's values, so changing a public value is not mistaken
    for replacing a command or an internal mount. New services have no base
    command/image contract.
    """
    warnings = []
    for name in sorted(base.keys() & services.keys()):
        original, current = base[name], services[name]
        for field in ("command", "image"):
            if current.get(field) != original.get(field):
                warnings.append({
                    "rule": field, "service": name,
                    "message": f"{name}: replaces the base {field}",
                })
        original_mounts = {item["target"]: item for item in original.get("volumes", [])}
        for mount in current.get("volumes", []):
            target = PurePosixPath(mount["target"])
            internal = (
                target == PurePosixPath("/")
                or (len(target.parts) > 1 and target.parts[1] in INTERNAL_IMAGE_ROOTS)
                or target == OVERLAY_RUNTIME_ROOT
                or OVERLAY_RUNTIME_ROOT in target.parents
                or target in OVERLAY_RUNTIME_ROOT.parents
            )
            if internal and mount != original_mounts.get(mount["target"]):
                warnings.append({
                    "rule": "internal-mount", "service": name,
                    "message": f"{name}: mounts over an image-internal path: {target}",
                })
    for name in sorted(unknown_variables):
        warnings.append({
            "rule": "variable", "variable": name,
            "message": f"{name}: variable is not declared by the base, kit artifacts or data",
        })
    return warnings


INTERPOLATION_RE = re.compile(r"(?<!\$)\$(?:\{)?([A-Za-z_][A-Za-z0-9_]*)")


def check_overlay(
    deployment: Deployment, selection: Selection, kit: RuntimeContext
) -> list[dict[str, str]]:
    if deployment.base is None:
        return []
    assert kit.base is not None
    base = deployment.base
    base_selection = base.select(kit.base, selection.ros_distro, selection.gpu)
    # Keep the kit's config/state mounts and public env values in the baseline,
    # but not its replacement images.
    injections = dict(selection.injections)
    image_names = set(kit.base.component_images) | set(kit.base.artifacts)
    injections.update({name: value for name, value in base_selection.injections.items() if name in image_names})
    baseline = Selection(selection.ros_distro, selection.gpu, None, injections, selection.environment)
    original = compose_model(base, baseline, environment_from=deployment)
    current = compose_model(deployment, selection)
    declared = set(selection.injections)
    for path in base._own_env_files(selection.gpu):
        declared.update(parse_dotenv(path))
    declared.update(item["destinationEnv"] for item in deployment.data)
    # Include variables used by shared services, including host values such as
    # HOME. This remains static: no image pull or inspection is needed.
    for directory in [base.directory, *(base.root / "deployments" / name for name in base.shared)]:
        for path in directory.rglob("*"):
            if path.suffix not in (".yaml", ".yml") or not path.is_file():
                continue
            declared.update(INTERPOLATION_RE.findall(path.read_text(encoding="utf-8")))
    used = set(deployment.configuration_environment(selection.gpu))
    for path in deployment.compose_files(selection.gpu):
        used.update(INTERPOLATION_RE.findall(path.read_text(encoding="utf-8")))
    warnings = overlay_warnings(original, current, used - declared)
    for warning in warnings:
        print(f"warning: overlay contract: {warning['message']}", file=sys.stderr)
    return warnings


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
        if service in deployment.reset_services(selection.node):
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

    for service in deployment.reset_services(selection.node):
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
