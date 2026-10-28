"""Process execution and Docker Compose lifecycle handling."""

from __future__ import annotations

import dataclasses
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
    deployment: Deployment,
    selection: Selection,
    *,
    environment_from: Deployment | None = None,
    files: list[Path] | None = None,
) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        deployment.project_name(selection.node),
    ]
    for env_file in (environment_from or deployment).env_files(selection.gpu):
        command.extend(("--env-file", str(env_file)))
    for compose_file in files or deployment.compose_files(selection.gpu, selection.node):
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


def _resolved_settings(deployment: Deployment, selection: Selection) -> dict[str, str]:
    command = ["docker", "compose", "--project-name", "openadkit-settings", "--file", "-"]
    for env_file in deployment.env_files(selection.gpu):
        command.extend(("--env-file", str(env_file)))
    try:
        result = subprocess.run(
            command + ["config", "--environment"],
            input="services: {}\n",
            capture_output=True,
            text=True,
            cwd=deployment.directory,
            env=compose_process_environment(deployment, selection),
        )
    except OSError as error:
        raise OpenADKitError(f"could not run Docker Compose: {error}") from error
    if result.returncode != 0:
        raise OpenADKitError(
            f"could not resolve {deployment.name} settings: {result.stderr.strip()}"
        )
    resolved = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    return {name: resolved.get(name, value) for name, value in selection.environment.items()}


def resolve_settings(deployment: Deployment, selection: Selection) -> Selection:
    """The selection with its env-file settings resolved as Compose resolves them.

    Data paths must match the mounts, so Compose itself interpolates the env
    files (${VAR:-default}, values built on other settings, quoting). The
    empty project leaves out the deployment's own required variables. GPU-only
    data resolves with the GPU env files, as a GPU run would.
    """
    require_docker()
    environment = _resolved_settings(deployment, selection)
    gpu_environment = environment
    if not selection.gpu and deployment.has_gpu_files:
        gpu = dataclasses.replace(
            selection,
            gpu=True,
            environment={
                **deployment.configuration_environment(True),
                **selection.injections,
            },
        )
        gpu_environment = _resolved_settings(deployment, gpu)
    return dataclasses.replace(
        selection, environment=environment, gpu_environment=gpu_environment
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


def other_projects(deployment: Deployment) -> list[str]:
    """Include foreign kits; only this deployment's exact views may coexist."""
    own = {deployment.project_name(), *(deployment.project_name(node) for node in deployment.nodes)}
    return sorted(live_projects() - own)


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


def require_data_unused(paths: Iterable[Path]) -> None:
    """Protect data shared with any live container, including another kit."""
    targets = [path.resolve() for path in paths]
    if not targets or not shutil.which("docker"):
        return
    ids = capture_process(["docker", "ps", "-aq"], trace=False).stdout.split()
    if not ids:
        return
    result = capture_process(["docker", "inspect", *ids], trace=False)
    try:
        containers = json.loads(result.stdout)
        if not isinstance(containers, list) or len(containers) != len(ids):
            raise ValueError("incomplete container inspection")
        for container in containers:
            if container["State"]["Status"] not in LIVE_PROJECT_STATES:
                continue
            for mount in container["Mounts"]:
                if mount["Type"] not in ("bind", "volume"):
                    continue
                source = Path(mount["Source"]).resolve()
                for target in targets:
                    if source == target or source in target.parents or target in source.parents:
                        raise OpenADKitError(
                            f"data at {target} is in use by {container['Name']}; "
                            "stop that container before deleting data"
                        )
    except (ValueError, KeyError, TypeError) as error:
        raise OpenADKitError("could not inspect data usage; refusing cleanup") from error


def render(deployment: Deployment, selection: Selection) -> set[str]:
    require_docker()
    compose_run(deployment, selection, ["config", "--quiet"])
    configured = set(
        compose_capture(deployment, selection, ["config", "--services"])
        .stdout.splitlines()
    )
    # The Compose project is the deployment: every configured service is meant
    # to run. Only the oneshot services are cross-checked, so a typo in a
    # resetServices entry still fails fast. A kit inherits its base's oneshots
    # but may leave their side of the base out (one service layer of it).
    inherited = set(deployment.base.reset_services()) if deployment.base else set()
    unknown = sorted(set(deployment.reset_services(selection.node)) - configured - inherited)
    if unknown:
        raise OpenADKitError(
            "manifest references unknown Compose service(s): " + ", ".join(unknown)
        )
    return configured


def compose_model(
    deployment: Deployment,
    selection: Selection,
    *,
    environment_from: Deployment | None = None,
    files: list[Path] | None = None,
) -> dict[str, Any]:
    result = capture_process(
        compose_command(deployment, selection, environment_from=environment_from, files=files)
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


def baseline_injections(
    deployment: Deployment, selection: Selection, kit: RuntimeContext, base_selection: Selection
) -> dict[str, str]:
    """The kit's injections with the base's images, as the base runs on this host.

    The kit's config/state mounts and public env values stay, so only what the
    kit replaces differs. An image override in the host's site file applies to
    the base as well: a source checkout reads it there (a pinned one ignores
    image overrides), and it is the host's choice, not the kit's replacement.
    """
    injections = dict(selection.injections)
    image_names = set(kit.base.component_images) | set(kit.base.artifacts) if kit.base else set()
    images = {name: value for name, value in base_selection.injections.items() if name in image_names}
    if not kit.pinned and deployment.site_config.is_file():
        site = parse_dotenv(deployment.site_config)
        images.update({name: value for name, value in site.items() if name in image_names and value})
    injections.update(images)
    return injections


# A list item naming a relative Compose file, as in a kit's include: list.
LOCAL_INCLUDE_RE = re.compile(r"^\s*-\s*(?:path:\s*)?['\"]?([^\s'\"$][^\s'\"]*\.ya?ml)['\"]?\s*$", re.MULTILINE)
BASE_REFERENCE_RE = re.compile(r"\$\{(OPENADKIT_BASE_DEPLOYMENT|KIT_openadkit)\}/([^\s'\"]+\.ya?ml)")
COMPOSE_DOCUMENT_RE = re.compile(r"^(services|include):", re.MULTILINE)
# ${NAME:-default}, ${NAME:?message} and their unset-only forms: a value the
# file means to take from the host or the site file, not a typo.
DELIBERATE_READ_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):?[-?]")


def is_compose_document(path: Path) -> bool:
    return path.is_file() and COMPOSE_DOCUMENT_RE.search(path.read_text(encoding="utf-8")) is not None


def kit_compose_files(deployment: Deployment, gpu: bool) -> list[Path]:
    """The kit's own Compose files: its entry files and the kit files they include."""
    root = deployment.root.resolve()
    pending = [path.resolve() for path in deployment.compose_files(gpu)]
    found: list[Path] = []
    while pending:
        path = pending.pop(0)
        if path in found:
            continue
        found.append(path)
        for relative in LOCAL_INCLUDE_RE.findall(path.read_text(encoding="utf-8")):
            candidate = (path.parent / relative).resolve()
            if candidate.is_relative_to(root) and is_compose_document(candidate):
                pending.append(candidate)
    return found


def kit_variables(deployment: Deployment, gpu: bool) -> set[str]:
    """Variables the kit sets or reads that only one side of the kit knows.

    A variable the kit sets in its env files and reads in its own Compose
    files is the kit's own setting, such as one of its services' options, and
    one read with a default or a required message (${NAME:-x}, ${NAME:?x})
    is meant to come from the host or the site file. One only set, or only
    read plainly, and that the base does not declare, is a likely typo. The
    host's site file is not part of the kit: what it sets, such as the
    documented *_IMAGE overrides, belongs to this host.
    """
    set_by_kit: set[str] = set()
    for path in deployment.env_layers[-1].files(gpu):
        set_by_kit.update(parse_dotenv(path))
    read_by_kit: set[str] = set()
    deliberate: set[str] = set()
    for path in kit_compose_files(deployment, gpu):
        text = path.read_text(encoding="utf-8")
        read_by_kit.update(INTERPOLATION_RE.findall(text))
        deliberate.update(DELIBERATE_READ_RE.findall(text))
    return (set_by_kit - read_by_kit) | (read_by_kit - deliberate - set_by_kit)


def included_base_files(deployment: Deployment, gpu: bool) -> list[Path] | None:
    """The base Compose files the kit includes; None means all of them.

    A kit that includes the base's entry file inherits every base service.
    One that includes only a service layer (services.autoware.yaml) inherits
    that layer's services, and one that includes no base file inherits none;
    a service of the same name elsewhere in the kit is its own, not a
    replacement of the base's. A kit reaches the base only through
    OPENADKIT_BASE_DEPLOYMENT or KIT_openadkit, since it cannot know where
    the base is installed.
    """
    base = deployment.base
    assert base is not None
    roots = {"OPENADKIT_BASE_DEPLOYMENT": base.directory, "KIT_openadkit": base.root}
    entry = {path.resolve() for path in base.compose_files(gpu)}
    found: list[Path] = []
    for path in kit_compose_files(deployment, gpu):
        for variable, relative in BASE_REFERENCE_RE.findall(path.read_text(encoding="utf-8")):
            candidate = (roots[variable] / relative).resolve()
            if candidate in entry:
                return None
            if candidate not in found and is_compose_document(candidate):
                found.append(candidate)
    return found


def check_overlay(
    deployment: Deployment, selection: Selection, kit: RuntimeContext
) -> list[dict[str, str]]:
    if deployment.base is None:
        return []
    assert kit.base is not None
    base = deployment.base
    base_selection = base.select(kit.base, selection.ros_distro, selection.gpu)
    injections = baseline_injections(deployment, selection, kit, base_selection)
    baseline = Selection(selection.ros_distro, selection.gpu, None, injections, selection.environment)
    layers = included_base_files(deployment, selection.gpu)
    original = (
        compose_model(base, baseline, environment_from=deployment, files=layers)
        if layers != []
        else {}
    )
    current = compose_model(deployment, selection)
    declared = set(selection.injections)
    for layer in base.env_layers:
        for path in layer.files(selection.gpu):
            declared.update(parse_dotenv(path))
    declared.update(item["destinationEnv"] for item in deployment.data)
    # Include variables used by shared services and their env files, including
    # host values such as HOME. This remains static: no image pull or inspection
    # is needed.
    for directory in [base.directory, *(base.root / "deployments" / name for name in base.shared)]:
        for path in directory.rglob("*"):
            if path.suffix not in (".yaml", ".yml", ".env") or not path.is_file():
                continue
            declared.update(INTERPOLATION_RE.findall(path.read_text(encoding="utf-8")))
    used = kit_variables(deployment, selection.gpu)
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


def restart_counts(deployment: Deployment, selection: Selection) -> dict[str, int]:
    """Restarts each container of the project has had so far, by container id."""
    ids = compose_capture(deployment, selection, ["ps", "--all", "--quiet"]).stdout.split()
    if not ids:
        return {}
    result = capture_process(
        ["docker", "inspect", "--format", "{{.Id}} {{.RestartCount}}", *ids],
        env=process_environment(selection),
        trace=False,
    )
    return {
        container: int(restarts)
        for container, restarts in (line.split() for line in result.stdout.splitlines())
    }


def failed_services(
    deployment: Deployment,
    selection: Selection,
    ids: list[str],
    baseline: dict[str, int],
) -> list[str]:
    """Long-running services that restarted since `up` or exited with an error."""
    result = capture_process(
        [
            "docker",
            "inspect",
            "--format",
            '{{.Id}} {{index .Config.Labels "com.docker.compose.service"}} '
            "{{.RestartCount}} {{.State.Status}} {{.State.ExitCode}}",
            *ids,
        ],
        env=process_environment(selection),
        trace=False,
    )
    failed = set()
    for line in result.stdout.splitlines():
        container, service, restarts, state, exit_code = line.split()
        # Reset services may finish, as map-check does, but not fail.
        if service in deployment.reset_services(selection.node):
            if state == "exited" and exit_code != "0":
                failed.add(service)
            continue
        # `up` keeps unchanged containers, and with them earlier restarts.
        restarted = int(restarts) > baseline.get(container, 0)
        if restarted or state == "restarting" or exit_code != "0":
            failed.add(service)
    return sorted(failed)


def check_services_stay_up(
    deployment: Deployment, selection: Selection, baseline: dict[str, int]
) -> None:
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
        failed = failed_services(deployment, selection, ids, baseline)
        if failed:
            raise OpenADKitError(
                f"{', '.join(failed)} failed after start; "
                f"see: openadkit logs {deployment.name}"
            )
        time.sleep(1)


def start(
    deployment: Deployment,
    selection: Selection,
    pull_policy: str,
    services: set[str],
    skipped: set[str] | None = None,
) -> None:
    """Start `services` of the rendered set; `skipped` ones get no container."""
    skipped = skipped or set()
    if pull_policy != "never":
        pull = ["pull", "--policy", pull_policy]
        compose_run(deployment, selection, pull + (sorted(services - skipped) if skipped else []))

    for service in deployment.reset_services(selection.node):
        if service not in services:
            continue
        compose_run(
            deployment,
            selection,
            ["rm", "--stop", "--force", service],
        )

    baseline = restart_counts(deployment, selection)
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
            *(f"--scale={service}=0" for service in sorted(skipped)),
        ],
    )
    check_services_stay_up(deployment, selection, baseline)
    report_overrides(deployment, selection)


OVERLAY_MOUNTS = ("/openadkit/overlay_ws", "/openadkit/overlay_ws_deployment")


def report_overrides(deployment: Deployment, selection: Selection) -> list[str]:
    """Warn about config overrides that changed nothing in the started services.

    Each hooked service writes /tmp/openadkit/overlay-report.json on start.
    Every service gets the same layers, so an overridden package is missing
    from most images; it is a mistake only when no service has it. After a
    base version change these usually are renamed packages, files or keys.
    """
    ids = compose_capture(deployment, selection, ["ps", "--quiet"], check=False).stdout.split()
    if not ids:
        return []
    environment = process_environment(selection)
    inspected = capture_process(
        ["docker", "inspect", *ids], env=environment, check=False, trace=False
    )
    try:
        containers = json.loads(inspected.stdout) if inspected.returncode == 0 else []
    except json.JSONDecodeError:
        containers = []
    reports: list[dict[str, Any]] = []
    for container in containers:
        mounts = [mount.get("Destination", "") for mount in container.get("Mounts") or []]
        if not any(path.startswith("/openadkit/config/") or path in OVERLAY_MOUNTS for path in mounts):
            continue
        result = capture_process(
            ["docker", "exec", container["Id"], "cat", "/tmp/openadkit/overlay-report.json"],
            env=environment,
            check=False,
            trace=False,
        )
        try:
            report = json.loads(result.stdout) if result.returncode == 0 else None
        except json.JSONDecodeError:
            report = None
        if isinstance(report, dict):
            reports.append(report)
    if not reports:
        return []
    warnings = [
        f"package {package} is in no service"
        for package in sorted(set.intersection(*(set(item.get("unknownPackages", [])) for item in reports)))
    ]
    for kind, label in (("unknownFiles", "file"), ("unknownKeys", "parameter")):
        found = {entry for item in reports for entry in item.get(kind, [])}
        warnings += [f"{label} {entry} is not in its package" for entry in sorted(found)]
    for warning in warnings:
        print(f"warning: override changed nothing: {warning}", file=sys.stderr)
    if warnings:
        print(
            "warning: after a base version change, look for renamed packages, "
            "files or parameters (config/autoware/<package>/...)",
            file=sys.stderr,
        )
    return warnings


# Overlay workspaces build where the services mount them, so CMake paths
# recorded against the kit's layer resolve in the deployment's layer too.
OVERLAY_TARGETS = {
    "OPENADKIT_OVERLAY_WS": "/openadkit/overlay_ws",
    "OPENADKIT_OVERLAY_WS_DEPLOYMENT": "/openadkit/overlay_ws_deployment",
}
# Written into install/ by build-overlay: the image and distro it built with.
OVERLAY_STAMP = ".openadkit-overlay.json"
OVERLAY_BUILD = """set -eo pipefail
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source /opt/autoware/setup.bash
for layer in "$@"; do source "${layer}/install/local_setup.bash"; done
colcon build --install-base install --cmake-args -DCMAKE_BUILD_TYPE=Release
"""


def overlay_workspaces(deployment: Deployment) -> list[tuple[Path, str]]:
    """The deployment's overlay workspaces with sources, the kit's first."""
    return [
        (path, OVERLAY_TARGETS[name])
        for name, path in deployment.overlay_paths.items()
        if name in OVERLAY_TARGETS and path is not None and (path / "src").is_dir()
    ]


def read_overlay_stamp(workspace: Path) -> dict[str, Any] | None:
    try:
        stamp = json.loads((workspace / "install" / OVERLAY_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stamp if isinstance(stamp, dict) else None


def build_overlay(workspaces: list[tuple[Path, str]], image: str, ros_distro: str) -> None:
    """Build each overlay layer in the devel image, on top of the ones before it.

    A layer builds incrementally only on its own last build in this image and
    distro. Anything else (another image or distro, a build by hand at another
    path, a layer below that was rebuilt) starts from a clean build and
    install: CMake caches record the image's paths and the path they were
    configured at, and links record the layers below.
    """
    require_docker()
    environment = _compose_ls_environment()
    below: list[tuple[Path, str]] = []
    clean = False
    for host, target in workspaces:
        clean = clean or read_overlay_stamp(host) != {"image": image, "rosDistro": ros_distro}
        if clean:
            for products in (host / "build", host / "install"):
                if products.is_dir() and not products.is_symlink():
                    shutil.rmtree(products)
        mounts = [arg for path, mount in below for arg in ("--volume", f"{path}:{mount}:ro")]
        # The image compiles through ccache in the aw home, which only uid
        # 1000 can write; keep HOME and the cache in the container's /tmp.
        run_process(
            [
                "docker", "run", "--rm",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--env", "HOME=/tmp",
                "--env", "CCACHE_DIR=/tmp/ccache",
                *mounts,
                "--volume", f"{host}:{target}",
                "--workdir", target,
                "--entrypoint", "bash",
                image, "-c", OVERLAY_BUILD, "bash", *(mount for _, mount in below),
            ],
            env=environment,
        )
        (host / "install").mkdir(exist_ok=True)
        (host / "install" / OVERLAY_STAMP).write_text(
            json.dumps({"image": image, "rosDistro": ros_distro}) + "\n",
            encoding="utf-8",
        )
        print(f"built overlay: {host}")
        below.append((host, target))


def check_overlay_builds(deployment: Deployment, selection: Selection, image: str | None) -> list[str]:
    """Warn about overlay installs that build-overlay made for another image."""
    warnings: list[str] = []
    for host, _ in overlay_workspaces(deployment):
        stamp = read_overlay_stamp(host)
        if stamp is None:
            continue
        if stamp.get("rosDistro") != selection.ros_distro or (image and stamp.get("image") != image):
            warnings.append(
                f"{host} was built for {stamp.get('rosDistro')} in {stamp.get('image')}; "
                f"rebuild it: openadkit build-overlay {deployment.name}"
            )
    for warning in warnings:
        print(f"warning: overlay workspace: {warning}", file=sys.stderr)
    return warnings


# Sourced before a ROS command runs in a service container: docker exec skips
# the entrypoint that sources them for the service itself.
ROS_SHELL = 'source "/opt/ros/${ROS_DISTRO}/setup.bash"; source /opt/autoware/setup.bash; '


def autoware_state(deployment: Deployment, selection: Selection) -> dict[str, Any] | None:
    """The AD API state from the running api service, or None without one."""
    command = compose_command(deployment, selection)
    environment = compose_process_environment(deployment, selection)
    running = capture_process(
        command + ["ps", "--services", "--status", "running"],
        cwd=deployment.directory, env=environment, check=False, trace=False,
    )
    if "api" not in running.stdout.split():
        return None
    script = (Path(__file__).parent / "autoware_state.py").read_text(encoding="utf-8")
    result = capture_process(
        command + ["exec", "-T", "api", "bash", "-c", ROS_SHELL + 'exec python3 -c "$0"', script],
        cwd=deployment.directory, env=environment, check=False, trace=False,
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


def status(deployment: Deployment, selection: Selection) -> None:
    compose_run(deployment, selection, ["ps"])
    state = autoware_state(deployment, selection)
    if state is not None:
        print()
        print("\n".join(format_autoware_state(state)))


def logs(
    deployment: Deployment, selection: Selection, follow: bool, services: list[str] | None = None
) -> None:
    arguments = ["logs"]
    if follow:
        arguments.append("--follow")
    compose_run(deployment, selection, arguments + list(services or []))


def record(
    deployment: Deployment, selection: Selection, topics: list[str], output: Path
) -> Path:
    """Record topics into a bag on the host until interrupted.

    The recorder runs as a copy of the running api container: its image,
    environment, user and mounts, so it joins the same ROS domain and
    middleware, and its entrypoint sources the overlay workspaces for
    integrator message types. The bag is written to a host directory, so it
    survives the deployment's containers.
    """
    ids = compose_capture(deployment, selection, ["ps", "--quiet", "api"], check=False).stdout.split()
    if not ids:
        raise OpenADKitError(f"{deployment.name} has no running api service to record from")
    environment = process_environment(selection)
    inspected = capture_process(
        ["docker", "inspect", ids[0]], env=environment, check=False, trace=False
    )
    try:
        config = json.loads(inspected.stdout)[0]["Config"]
    except (ValueError, LookupError, TypeError) as error:
        raise OpenADKitError("could not inspect the api container") from error
    label = deployment.name if selection.node is None else f"{deployment.name}-{selection.node}"
    bag = output / f"{label}-{time.strftime('%Y%m%d-%H%M%S')}"
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
    while True:
        try:
            returncode = process.wait()
            break
        except KeyboardInterrupt:
            # Ctrl+C reached the recorder too; killing the client would leave
            # it recording, so wait while it closes the bag.
            continue
    # Ctrl+C ends ros2 bag record with a nonzero status; a bag is a result.
    if returncode != 0 and not bag.is_dir():
        raise OpenADKitError(f"recording failed with exit status {returncode}")
    return bag


def stop(deployment: Deployment, selection: Selection) -> None:
    compose_run(deployment, selection, ["down", "--remove-orphans"])
