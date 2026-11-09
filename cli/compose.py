"""Starting a deployment with Docker Compose."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from catalog import Deployment, RuntimeContext, deployment_checksum
from manifest import OpenADKitError
from settings import (
    COMPOSE_CONTROL_ENV,
    Selection,
    compose_process_environment,
    process_environment,
)

PROJECT_PREFIX = "openadkit-"
LIVE_PROJECT_STATES = {"running", "restarting", "paused", "removing"}

# Launch failures show up within seconds; watch this long after `up`.
SETTLE_SECONDS = 10

# Workspaces build where the services mount them, so the paths CMake records
# resolve at runtime too.
OVERLAY_TARGET = "/openadkit/overlay_ws"

# What the entrypoint hook layers over Autoware.
HOOK_MOUNTS = ("/openadkit/config/", OVERLAY_TARGET)


def ensure_runtime_user() -> None:
    if os.geteuid() == 0:
        raise OpenADKitError("runtime commands must run as a normal user, not root")


def print_command(command: list[str]) -> None:
    """Show a docker command the CLI runs, with --verbose or OPENADKIT_VERBOSE=1."""
    if os.environ.get("OPENADKIT_VERBOSE", "") not in ("", "0"):
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


def compose_command(deployment: Deployment, selection: Selection) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        deployment.project_name(selection.node),
    ]
    for env_file in deployment.env_files(selection.gpu):
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
    return set(live_project_files())


def live_project_files() -> dict[str, list[str]]:
    """Live Open AD Kit Compose projects, with the Compose files each started from."""
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
    live: dict[str, list[str]] = {}
    for project in projects:
        if not isinstance(project, dict):
            continue
        name = project.get("Name")
        status = project.get("Status") or ""
        if not isinstance(name, str) or not isinstance(status, str):
            continue
        state = status.lower().split("(", 1)[0].strip()
        if name.startswith(PROJECT_PREFIX) and state in LIVE_PROJECT_STATES:
            files = project.get("ConfigFiles")
            live[name] = [item for item in files.split(",") if item] if isinstance(files, str) else []
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
    """Include foreign kits; only this deployment's exact views may coexist.

    A project is named after its deployment only, so another kit's deployment
    of the same name, or a deployment named like this one plus a node, has the
    same project name as one of these views. A view is this deployment's only
    when it started from the view's own entry Compose file; otherwise `run`
    would replace another stack in place. Compose that reports no files keeps
    the name as the only evidence. stop, status and logs still go by name, so
    a stack started from an older release stays reachable after an upgrade.
    """
    live = live_project_files()
    own = set()
    for node in (None, *deployment.nodes):
        name = deployment.project_name(node)
        if name not in live:
            continue
        entry = deployment.compose_files(False, node)[0].resolve()
        if not live[name] or Path(live[name][0]).resolve() == entry:
            own.add(name)
    return sorted(set(live) - own)


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
        "stop it with openadkit stop "
        f"before starting {view_label(selection.node)}"
    )


def require_stopped(name: str) -> None:
    """Refuse destructive cleanup while this deployment's project is live."""
    if not shutil.which("docker"):
        return
    if name in running_names([name]):
        raise OpenADKitError(
            f"{name} is running; stop it before deleting data: "
            "openadkit stop"
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
    # A node may leave the verify service to another node; the whole graph must have it.
    if deployment.verify and selection.node is None and deployment.verify["service"] not in configured:
        unknown.append(deployment.verify["service"])
    if unknown:
        raise OpenADKitError(
            "manifest references unknown Compose service(s): " + ", ".join(unknown)
        )
    return configured


def create_writable_mounts(deployment: Deployment, selection: Selection) -> str:
    """Create missing writable bind sources as the user; return the resolved model.

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
    return result.stdout


def run_record(
    deployment: Deployment, selection: Selection, kit: RuntimeContext, model: str, started: float,
) -> dict[str, Any]:
    """What this run started: the version, the images, the resolved model's
    digest, and the content digests of what the services mount from the host.

    The model holds every image, setting and mount path; the config layers and
    the overlay workspace are hashed for their content, so two runs with the
    same digests started the same thing. Written to the results as run.json.
    """
    services = json.loads(model).get("services") or {}
    mounted = selection.injections
    return {
        "schemaVersion": 1,
        "deployment": deployment.name,
        "node": selection.node,
        "rosDistro": selection.ros_distro,
        "gpu": selection.gpu,
        "version": kit.version or (kit.base.version if kit.base else None),
        "extends": kit.extends,
        "images": {name: service.get("image") for name, service in sorted(services.items())},
        "modelSha256": hashlib.sha256(model.encode("utf-8")).hexdigest(),
        "configSha256": {
            layer: deployment_checksum(Path(mounted[f"OPENADKIT_CONFIG_{layer.upper()}"]))
            for layer in ("shared", "base", "deployment")
        },
        # What the services source; build products and logs are not.
        "overlaySha256": deployment_checksum(Path(mounted["OPENADKIT_OVERLAY_WS"]), exclude_dirs=("build", "log")),
        "readySeconds": round(time.monotonic() - started, 1),
    }


def write_run_record(deployment: Deployment, record: dict[str, Any]) -> Path:
    results = deployment.output_directory / "results"
    results.mkdir(parents=True, exist_ok=True)
    path = results / "run.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


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
    """Long-running services that restarted since `up` or exited."""
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
        # on-failure does not restart a clean exit, which leaves the service gone.
        restarted = int(restarts) > baseline.get(container, 0)
        if restarted or state in ("restarting", "exited") or exit_code != "0":
            failed.add(service)
    return sorted(failed)


def check_services_stay_up(
    deployment: Deployment, selection: Selection, baseline: dict[str, int]
) -> None:
    """Fail when a service crashes shortly after `up`.

    `up --wait` waits for the services with a healthcheck to be healthy and
    only for the others to start, so one of those that fails during launch and
    restarts would still look running.
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
                f"see: openadkit logs {' '.join(failed)}"
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


def verify(deployment: Deployment, selection: Selection, services: set[str], record: dict[str, Any]) -> int:
    """Run the deployment's verify step on the ready stack and return its exit code.

    A command runs in its service with ROS, Autoware and the overlays sourced;
    without one, the step is the service's own exit, as a scenario run's. The
    result joins the run's record.
    """
    spec = deployment.verify
    assert spec is not None
    service = spec["service"]
    if service not in services:
        print(f"verify: {service} does not run on this node; nothing to verify here")
        return 0
    # The step's own output follows on the same terminal.
    print(f"verify: {' '.join(spec['command']) if 'command' in spec else f'waiting for {service} to finish'}", flush=True)
    begin = time.monotonic()
    if "command" in spec:
        command = compose_command(deployment, selection) + [
            "exec", "-T", service, "bash", "-c", SHELL_SETUP + 'exec "$@"', "bash", *spec["command"],
        ]
        print_command(command)
        code = subprocess.run(
            command, cwd=deployment.directory, env=compose_process_environment(deployment, selection), check=False,
        ).returncode
    else:
        ids = compose_capture(deployment, selection, ["ps", "--all", "--quiet", service]).stdout.split()
        if not ids:
            raise OpenADKitError(f"{service} has no container to wait for")
        code = int(capture_process(["docker", "wait", ids[0]], env=process_environment(selection)).stdout.strip())
    record["verify"] = {
        "service": service,
        "seconds": round(time.monotonic() - begin, 1),
        "exitCode": code,
        "result": "PASSED" if code == 0 else "FAILED",
    }
    path = write_run_record(deployment, record)
    print(f"verify: {'passed' if code == 0 else f'failed (exit {code})'}; record: {path}")
    return code


def report_overrides(deployment: Deployment, selection: Selection) -> list[str]:
    """Warn about config overrides with no counterpart in the started services.

    Each hooked service writes /tmp/openadkit/overlay-report.json on start.
    Every service gets the same layers, so an overridden package is missing
    from most images; it is a mistake only when no service has it. After a
    base version change these usually are renamed packages, files or keys.
    """
    ids = compose_capture(deployment, selection, ["ps", "--quiet"], check=False).stdout.split()
    return report_container_overrides(ids, process_environment(selection))


def report_container_overrides(ids: list[str], environment: dict[str, str]) -> list[str]:
    """report_overrides for these containers."""
    if not ids:
        return []
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
        if not any(path.startswith(HOOK_MOUNTS) for path in mounts):
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
    # The hook applies nothing for an unknown package; it adds unknown files and keys.
    warnings = [
        f"override changed nothing: package {package} is in no service"
        for package in sorted(set.intersection(*(set(item.get("unknownPackages", [])) for item in reports)))
    ]
    for kind, label, owner in (("unknownFiles", "file", "package"), ("unknownKeys", "parameter", "file")):
        found = {entry for item in reports for entry in item.get(kind, [])}
        warnings += [f"override adds {label} {entry}, which its {owner} does not have" for entry in sorted(found)]
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if warnings:
        print(
            "warning: after a base version change, look for renamed packages, "
            "files or parameters (config/autoware/<package>/...)",
            file=sys.stderr,
        )
    return warnings


# Written into install/ by build: the image and distro it built with.
OVERLAY_STAMP = ".openadkit-overlay.json"

# The arguments after `openadkit build ... --` follow; CMAKE_BUILD_TYPE in the
# environment is CMake's default, so --cmake-args of their own keep Release.
OVERLAY_BUILD = """set -eo pipefail
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source /opt/autoware/setup.bash
colcon build --install-base install "$@"
"""

# The services mount the workspace and source install/ at fixed paths.
FIXED_COLCON_OPTIONS = ("--install-base", "--build-base")


def read_overlay_stamp(workspace: Path) -> dict[str, Any] | None:
    try:
        stamp = json.loads((workspace / "install" / OVERLAY_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stamp if isinstance(stamp, dict) else None


def build_overlay(workspace: Path, image: str, ros_distro: str, colcon: Sequence[str] = ()) -> None:
    """Build a workspace in the devel image, passing `colcon` on to colcon build.

    It builds incrementally only on its own last build in this image and
    distro. Anything else (another image or distro, a build by hand at another
    path) starts from a clean build and install: CMake caches record the
    image's paths and the path they were configured at.
    """
    fixed = sorted({option for option in FIXED_COLCON_OPTIONS for argument in colcon
                    if argument == option or argument.startswith(f"{option}=")})
    if fixed:
        raise OpenADKitError(f"{', '.join(fixed)} cannot change: the services use {OVERLAY_TARGET}/install")
    require_docker()
    if read_overlay_stamp(workspace) != {"image": image, "rosDistro": ros_distro}:
        for products in (workspace / "build", workspace / "install"):
            if products.is_dir() and not products.is_symlink():
                shutil.rmtree(products)
    # The image compiles through ccache in the aw home, which only uid
    # 1000 can write; keep HOME and the cache in the container's /tmp.
    run_process(
        [
            "docker", "run", "--rm",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", "HOME=/tmp",
            "--env", "CCACHE_DIR=/tmp/ccache",
            "--env", "CMAKE_BUILD_TYPE=Release",
            "--volume", f"{workspace}:{OVERLAY_TARGET}",
            "--workdir", OVERLAY_TARGET,
            "--entrypoint", "bash",
            image, "-c", OVERLAY_BUILD, "build", *colcon,
        ],
        env=_compose_ls_environment(),
    )
    (workspace / "install").mkdir(exist_ok=True)
    (workspace / "install" / OVERLAY_STAMP).write_text(
        json.dumps({"image": image, "rosDistro": ros_distro}) + "\n",
        encoding="utf-8",
    )
    print(f"built: {workspace}")


def check_overlay_build(deployment: Deployment, selection: Selection, image: str | None) -> str | None:
    """Warn about an overlay install that build made for another image."""
    stamp = read_overlay_stamp(deployment.workspace)
    if stamp is None:
        return None
    if stamp.get("rosDistro") == selection.ros_distro and (not image or stamp.get("image") == image):
        return None
    warning = (
        f"{deployment.workspace} was built for {stamp.get('rosDistro')} in {stamp.get('image')}; "
        f"rebuild it: openadkit build {deployment.workspace} --ros-distro {selection.ros_distro}"
    )
    print(f"warning: overlay workspace: {warning}", file=sys.stderr)
    return warning


# Sourced before a ROS command runs in a service container: docker exec skips
# the entrypoint that sources them for the service itself.
ROS_SHELL = 'source "/opt/ros/${ROS_DISTRO}/setup.bash"; source /opt/autoware/setup.bash; '

# As the entrypoint hook layers them, for an interactive shell or command.
SHELL_SETUP = ROS_SHELL + (
    f'[ -f {OVERLAY_TARGET}/install/local_setup.bash ] && source {OVERLAY_TARGET}/install/local_setup.bash; '
)
