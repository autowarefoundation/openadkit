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

from catalog import (
    Catalog,
    Deployment,
    ci_build,
    deployment_checksum,
    holds_packages,
    host_architecture,
    state_root,
)
from manifest import DEVEL_IMAGE_TARGET, OpenADKitError
from settings import Selection, compose_process_environment, docker_environment

PROJECT_PREFIX = "openadkit-"
LIVE_PROJECT_STATES = {"running", "restarting", "paused", "removing"}
# runtime.env's ROS_DOMAIN_ID when the CLI sets none.
DEFAULT_ROS_DOMAIN_ID = 1

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


def docker(
    command: list[str],
    *,
    show: bool = False,
    check: bool = True,
    trace: bool = True,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a docker command: captured, or shown on the terminal with `show`.

    env defaults to the process environment without Compose's own settings.
    """
    if trace or show:
        print_command(command)
    try:
        return subprocess.run(
            command, cwd=cwd, env=docker_environment() if env is None else env,
            capture_output=not show, text=True, check=check,
        )
    except FileNotFoundError as error:
        raise OpenADKitError(f"required command is not installed: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = " ".join((error.stderr or "").split())
        suffix = f": {detail}" if detail else ""
        raise OpenADKitError(f"command failed with exit code {error.returncode}: {command[0]}{suffix}") from error


def compose_command(deployment: Deployment, selection: Selection) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        deployment.project_name(selection.role, selection.instance),
    ]
    for env_file in deployment.env_files(selection.gpu):
        command.extend(("--env-file", str(env_file)))
    for compose_file in deployment.compose_files(selection.gpu, selection.role):
        command.extend(("--file", str(compose_file)))
    return command


def run_compose(
    deployment: Deployment, selection: Selection, arguments: list[str], **options: Any
) -> subprocess.CompletedProcess[str]:
    """A Compose command on the deployment, with its files and settings; options as docker()."""
    return docker(
        compose_command(deployment, selection) + arguments,
        cwd=deployment.working_directory, env=compose_process_environment(deployment, selection), **options,
    )


def require_docker() -> None:
    if not shutil.which("docker"):
        raise OpenADKitError("Docker is unavailable. Run: openadkit setup")



def live_projects() -> set[str]:
    """Names of the Open AD Kit Compose projects that are live on this host."""
    return set(live_project_files())


def docker_error(message: str, stderr: str) -> OpenADKitError:
    """Docker's own reason, and the next step when the user cannot reach the daemon yet."""
    detail = stderr.strip()
    if detail:
        message = f"{message}: {detail}"
    if "permission denied" in detail.lower():
        message += "\nyour user is not in the docker group yet: log out and back in, or run: newgrp docker"
    return OpenADKitError(message)


def _project_files(*, stopped: bool) -> dict[str, list[str]]:
    """Open AD Kit Compose projects, with the Compose files each started from:
    the live ones, or with `stopped` every one that still has containers."""
    require_docker()
    result = docker(
        ["docker", "compose", "ls", *(["--all"] if stopped else []), "--format", "json"],
        check=False,
        trace=False,
    )
    if result.returncode != 0:
        raise docker_error("could not list Compose projects", result.stderr)
    try:
        projects = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError as error:
        raise OpenADKitError("could not parse Compose project list") from error
    if not isinstance(projects, list):
        raise OpenADKitError("could not parse Compose project list")
    found: dict[str, list[str]] = {}
    for project in projects:
        if not isinstance(project, dict):
            continue
        name = project.get("Name")
        status = project.get("Status") or ""
        if not isinstance(name, str) or not isinstance(status, str):
            continue
        state = status.lower().split("(", 1)[0].strip()
        if name.startswith(PROJECT_PREFIX) and (stopped or state in LIVE_PROJECT_STATES):
            files = project.get("ConfigFiles")
            found[name] = [item for item in files.split(",") if item] if isinstance(files, str) else []
    return found


def live_project_files() -> dict[str, list[str]]:
    """Live Open AD Kit Compose projects, with the Compose files each started from."""
    return _project_files(stopped=False)


def stopped_project_files() -> dict[str, list[str]]:
    """Open AD Kit Compose projects with containers but none running: a start
    that failed, or a Docker that restarted under the stack. Their containers
    keep their fixed names, which another deployment's would collide with."""
    live = live_project_files()
    return {name: files for name, files in _project_files(stopped=True).items() if name not in live}


def _started_here(
    deployment: Deployment, role: str | None, projects: dict[str, list[str]], instance: int | None = None
) -> bool:
    """Whether the project of this role or instance started from the deployment's own
    entry Compose file. Compose that reports no files keeps the name as the
    only evidence."""
    project = deployment.project_name(role, instance)
    files = projects.get(project)
    if files is None:
        return False
    # Two kits' deployments of one name can start from the same base Compose
    # file; the run record names the kit that started the project.
    state = read_run_state(project)
    if state is not None and "kit" in state:
        kit = deployment.root.resolve() if deployment.base is not None else None
        if (Path(state["kit"]).resolve() if state["kit"] else None) != kit:
            return False
        # An instance's project has the name another deployment's may have:
        # instance 2 of foo, and foo-2.
        if state.get("deployment") != deployment.name:
            return False
    return not files or Path(files[0]).resolve() == deployment.compose_files(False, role)[0].resolve()


def other_projects(deployment: Deployment) -> list[str]:
    """Include foreign kits; only this deployment's own projects may coexist.

    A project is named after its deployment only, so another kit's deployment
    of the same name has the same project name as one of these. A project is this deployment's only
    when it started from its own entry Compose file; otherwise `run`
    would replace another stack in place. stop, status and logs still go by name, so
    a stack started from an older release stays reachable after an upgrade.
    An instance in another ROS domain shares neither names nor topics, so it may coexist too.
    """
    live = live_project_files()
    names = {deployment.project_name(role) for role in (None, *deployment.roles)}
    own = {deployment.project_name(role) for role in (None, *deployment.roles) if _started_here(deployment, role, live)}
    # An instance under one of this deployment's names would be replaced in place.
    return sorted(project for project in set(live) - own if project in names or not _copy_elsewhere(project))


def stopped_other_projects(deployment: Deployment, role: str | None) -> list[str]:
    """Stopped projects other than the one this run starts again in place."""
    stopped = stopped_project_files()
    name = deployment.project_name(role)
    own = {name} if _started_here(deployment, role, stopped) else set()
    return sorted(project for project in set(stopped) - own if project == name or not _copy_elsewhere(project))


def _copy_elsewhere(project: str) -> bool:
    """An instance outside the default ROS domain; instance N runs in domain N."""
    domain = (read_run_state(project) or {}).get("instance")
    return domain is not None and domain != DEFAULT_ROS_DOMAIN_ID


def same_domain_projects(deployment: Deployment, selection: Selection) -> list[str]:
    """Projects, live or left stopped, that an instance cannot start beside.

    Every project shares the host network, so only one in the same domain
    would see the instance's topics. A project whose run record names no
    instance runs single-host in the default domain, or in its role's. A project
    of the instance's name that another kit or deployment started is never
    replaced in place.
    """
    own = deployment.project_name(None, selection.instance)
    clashing = []
    for project, files in {**stopped_project_files(), **live_project_files()}.items():
        if project == own:
            if not _started_here(deployment, None, {project: files}, selection.instance):
                clashing.append(project)
            continue
        state = read_run_state(project) or {}
        domain = state.get("instance")
        if domain is None and not (state.get("role") or "_" in project):
            domain = DEFAULT_ROS_DOMAIN_ID
        if domain == selection.instance:
            clashing.append(project)
    return sorted(clashing)


def live_roles(deployment: Deployment) -> list[str | None]:
    """The live projects of one deployment, by role: None is the single-host project."""
    live = live_projects()
    roles: list[str | None] = []
    if deployment.project_name() in live:
        roles.append(None)
    roles.extend(
        role for role in sorted(deployment.roles) if deployment.project_name(role) in live
    )
    return roles


def role_label(role: str | None) -> str:
    return "single-host" if role is None else f"role {role}"


def live_state_conflict(deployment: Deployment, selection: Selection) -> str | None:
    """Roles of one deployment may share a host; single-host and roles may not."""
    live = live_roles(deployment)
    clashing: list[str | None]
    if selection.role is None:
        clashing = [role for role in live if role is not None]
    else:
        clashing = [None] if None in live else []
    if not clashing:
        return None
    running = ", ".join(role_label(role) for role in clashing)
    return (
        f"{deployment.name} is already running as {running}; "
        "stop it with openadkit stop "
        f"before starting {role_label(selection.role)}"
    )


def require_stopped(deployment: Deployment) -> None:
    """Refuse destructive cleanup while any project of this deployment is live."""
    if live_roles(deployment):
        raise OpenADKitError(f"{deployment.name} is running; stop it before deleting data: openadkit stop")


def require_data_unused(paths: Iterable[Path]) -> None:
    """Protect data shared with any live container, including another kit."""
    targets = [path.resolve() for path in paths]
    if not targets:
        return
    ids = docker(["docker", "ps", "-aq"], trace=False).stdout.split()
    if not ids:
        return
    result = docker(["docker", "inspect", *ids], trace=False)
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
                            "stop that container before replacing or deleting data"
                        )
    except (ValueError, KeyError, TypeError) as error:
        raise OpenADKitError("could not inspect data usage; refusing cleanup") from error


def render(deployment: Deployment, selection: Selection) -> set[str]:
    require_docker()
    run_compose(deployment, selection, ["config", "--quiet"], show=True)
    configured = set(
        run_compose(deployment, selection, ["config", "--services"])
        .stdout.splitlines()
    )
    # The Compose project is the deployment: every configured service is meant
    # to run, and the manifest names one only for its verify step.
    if deployment.verify and deployment.verify["service"] not in configured:
        if deployment.verify_inherited:
            # A kit that leaves out the service of its base's verify step has no verify step.
            deployment.verify = None
        elif selection.role is None:
            # A role may leave the verify service to another role; the whole graph must have it.
            raise OpenADKitError(
                f"manifest references unknown Compose service(s): {deployment.verify['service']}"
            )
    return configured


def one_shot_services(deployment: Deployment, selection: Selection) -> set[str]:
    """Services that do their work and exit: those with restart: "no" in the
    Compose model, which other services wait on with service_completed_successfully.
    Read once per command."""
    key = (selection.role, selection.gpu)
    if key not in deployment.one_shots:
        model = json.loads(run_compose(deployment, selection, ["config", "--format", "json"]).stdout or "{}")
        deployment.one_shots[key] = {
            name for name, service in (model.get("services") or {}).items() if service.get("restart") == "no"
        }
    return deployment.one_shots[key]


def create_writable_mounts(deployment: Deployment, selection: Selection) -> str:
    """Create missing writable bind sources as the user; return the resolved model.

    Docker creates a missing bind source as root, which the services, running
    as the user, then cannot write to (for example ~/autoware_data).
    """
    result = run_compose(deployment, selection, ["config", "--format", "json"])
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


def require_local_devel_image(catalog: Catalog, image: str) -> None:
    """As require_local_images, for the devel image a workspace builds in."""
    if catalog.pinned or ci_build() is not None:
        return
    if docker(["docker", "image", "inspect", "--format", "{{.Id}}", image], check=False, trace=False).returncode:
        raise OpenADKitError(
            f"this source checkout has no local build of {DEVEL_IMAGE_TARGET}; build it with "
            f"`docker buildx bake -f components/docker-bake.hcl --load {DEVEL_IMAGE_TARGET}`, "
            "or set OPENADKIT_BUILD=<image repository>:<build tag> to build in a CI build's image"
        )


def require_local_images(
    catalog: Catalog, selection: Selection, model: str, services: set[str]
) -> None:
    """A source checkout runs its own local build, so it pulls none of those
    images: a missing one would come from a registry, built from other code.
    OPENADKIT_BUILD names a CI build to pull instead."""
    if catalog.pinned or ci_build() is not None:
        return
    targets = {
        catalog.source_image(target, selection.ros_distro, host_architecture()): target
        for target in catalog.component_images.values()
    }
    used = {
        service.get("image")
        for name, service in (json.loads(model).get("services") or {}).items()
        if name in services
    }
    missing = sorted(
        targets[image] for image in used & set(targets)
        if docker(["docker", "image", "inspect", "--format", "{{.Id}}", image], check=False, trace=False).returncode
    )
    if missing:
        raise OpenADKitError(
            f"this source checkout has no local build of {', '.join(missing)}; build them with "
            f"`docker buildx bake -f components/docker-bake.hcl --load {' '.join(missing)}`, "
            "or set OPENADKIT_BUILD=<image repository>:<build tag> to run a CI build's images"
        )


def run_report(
    deployment: Deployment, selection: Selection, catalog: Catalog, model: str, started: float,
) -> dict[str, Any]:
    """What this run started: the version, the images, the resolved model's
    digest, and the content digests of what the services mount from the host.

    The model holds every image, setting and mount path; the config layers and
    the overlay workspace are hashed for their content, so two runs with the
    same digests started the same thing. Written to the results as run.json.
    """
    ready_seconds = round(time.monotonic() - started, 1)
    services = json.loads(model).get("services") or {}
    mounted = selection.injections
    return {
        "schemaVersion": 1,
        "deployment": deployment.name,
        "role": selection.role,
        # run --instance N: the copy's number, which is also its ROS domain.
        "instance": selection.instance,
        "rosDistro": selection.ros_distro,
        "gpu": selection.gpu,
        "version": catalog.version or (catalog.extended.version if catalog.extended else None),
        "extends": catalog.extends,
        "images": {name: service.get("image") for name, service in sorted(services.items())},
        "modelSha256": hashlib.sha256(model.encode("utf-8")).hexdigest(),
        "configSha256": {
            layer: deployment_checksum(Path(mounted[f"OPENADKIT_CONFIG_{layer.upper()}"]))
            for layer in ("base", "kit", "deployment")
        },
        # What the services source; build products and logs are not.
        "overlaySha256": deployment_checksum(Path(mounted["OPENADKIT_OVERLAY_WS"]), exclude_dirs=("build", "log")),
        "readySeconds": ready_seconds,
    }


def write_run_report(deployment: Deployment, report: dict[str, Any], instance: int | None = None) -> Path:
    results = deployment.output_directory / "results"
    if instance is not None:
        results /= str(instance)
    results.mkdir(parents=True, exist_ok=True)
    path = results / "run.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def check_daemon(selection: Selection) -> None:
    result = docker(
        ["docker", "info"], check=False
    )
    if result.returncode != 0:
        raise docker_error("could not access the Docker daemon", result.stderr)
    if not selection.gpu:
        return
    runtimes = docker(
        ["docker", "info", "--format", "{{json .Runtimes}}"],
        check=False,
    )
    try:
        available = json.loads(runtimes.stdout) if runtimes.returncode == 0 else {}
    except json.JSONDecodeError:
        available = {}
    if "nvidia" not in available:
        raise OpenADKitError(
            "NVIDIA Container Toolkit is unavailable for the selected GPU mode; run: openadkit setup --gpu"
        )


def restart_counts(deployment: Deployment, selection: Selection) -> dict[str, int]:
    """Restarts each container of the project has had so far, by container id."""
    ids = run_compose(deployment, selection, ["ps", "--all", "--quiet"]).stdout.split()
    if not ids:
        return {}
    result = docker(
        ["docker", "inspect", "--format", "{{.Id}} {{.RestartCount}}", *ids],
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
    """Long-running services that restarted since `up`, exited, died or turned
    unhealthy."""
    result = docker(
        [
            "docker",
            "inspect",
            "--format",
            '{{.Id}} {{index .Config.Labels "com.docker.compose.service"}} '
            "{{.RestartCount}} {{.State.Status}} {{.State.ExitCode}} "
            # Docker fails on .State.Health for a container without a
            # healthcheck; index reads a missing key as empty.
            '{{with index .State "Health"}}{{.Status}}{{else}}none{{end}}',
            *ids,
        ],
        trace=False,
    )
    failed = set()
    for line in result.stdout.splitlines():
        container, service, restarts, state, exit_code, health = line.split()
        # One-shot services may finish, but not fail. One that failed before
        # this `up`, which left its container as it was, is no news.
        if service in one_shot_services(deployment, selection):
            if state == "exited" and exit_code != "0" and container not in baseline:
                failed.add(service)
            continue
        # `up` keeps unchanged containers, and with them earlier restarts.
        # on-failure does not restart a clean exit, which leaves the service gone.
        restarted = int(restarts) > baseline.get(container, 0)
        if restarted or state in ("restarting", "exited", "dead") or exit_code != "0" or health == "unhealthy":
            failed.add(service)
    return sorted(failed)


def check_services_stay_up(
    deployment: Deployment, selection: Selection, baseline: dict[str, int]
) -> None:
    """Fail when a service crashes shortly after `up`.

    `up --wait` waits for the services with a healthcheck to be healthy and
    only for the others to start, so one of those that fails during launch and
    restarts would still look running. A recreated service is a new container,
    whose restarts count from zero.
    """
    ids = run_compose(deployment, selection, ["ps", "--all", "--quiet"]).stdout.split()
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
    services: set[str],
    skipped: set[str] | None = None,
) -> None:
    """Start `services` of the rendered set, pulling the images they miss;
    `skipped` ones get no container."""
    skipped = skipped or set()
    pull = ["pull", "--policy", "missing"]
    run_compose(deployment, selection, pull + (sorted(services - skipped) if skipped else []), show=True)

    for service in sorted(one_shot_services(deployment, selection) & services):
        run_compose(deployment, selection, ["rm", "--stop", "--force", service], show=True)

    up(deployment, selection, ["--remove-orphans", *scale_to_zero(skipped)])


def recreate(deployment: Deployment, selection: Selection, services: set[str]) -> None:
    """Recreate `services` with the deployment's current settings, config and
    workspace, leaving the others as they are. Compose refuses a scale for a
    service it does not start, so services run skipped are left out instead."""
    up(deployment, selection, ["--no-deps", "--force-recreate", *sorted(services)])


def scale_to_zero(services: set[str]) -> list[str]:
    return [f"--scale={service}=0" for service in sorted(services)]


def unhealthy_reasons(containers: list[dict[str, Any]]) -> dict[str, str]:
    """The unhealthy services among inspected containers, each with what its
    last healthcheck printed, such as the node that died."""
    reasons = {}
    for container in containers:
        health = (container.get("State") or {}).get("Health") or {}
        if health.get("Status") == "unhealthy":
            output = (health.get("Log") or [{}])[-1].get("Output") or ""
            service = container["Config"]["Labels"]["com.docker.compose.service"]
            reasons[service] = "; ".join(output.split("\n")[:-1] or [output]).strip()
    return reasons


def explain_failed_start(deployment: Deployment, selection: Selection) -> str | None:
    """Why `up --wait` failed, where a healthcheck or a container's state says
    so: Compose only names the unhealthy container."""
    ids = run_compose(deployment, selection, ["ps", "--all", "--quiet"], check=False).stdout.split()
    inspected = docker(["docker", "inspect", *ids], check=False, trace=False) if ids else None
    try:
        containers = json.loads(inspected.stdout) if inspected else []
    except ValueError:
        return None
    containers = containers if isinstance(containers, list) else []
    failed = {
        service: f"{service} is unhealthy" + (f": {reason}" if reason else "")
        for service, reason in unhealthy_reasons(containers).items()
    }
    for container in containers:
        state = container.get("State") or {}
        service = container["Config"]["Labels"]["com.docker.compose.service"]
        # A command that fails at once never reaches a healthcheck.
        if state.get("Restarting") or container.get("RestartCount"):
            failed[service] = f"{service} keeps crashing (exit code {state.get('ExitCode')})"
        elif state.get("Status") == "exited" and state.get("ExitCode"):
            failed[service] = f"{service} exited with code {state['ExitCode']}"
    if not failed:
        return None
    return "\n".join([*(failed[service] for service in sorted(failed)), f"see: openadkit logs {' '.join(sorted(failed))}"])


def up(deployment: Deployment, selection: Selection, arguments: list[str]) -> None:
    """`compose up`, held to one readiness policy for run and restart:
    healthchecks pass within the deployment's waitTimeout, then no service
    crashes, restarts or exits while the stack settles. One-shot services
    may finish, but not fail."""
    baseline = restart_counts(deployment, selection)
    try:
        run_compose(
            deployment,
            selection,
            ["up", "--detach", "--wait", "--wait-timeout", str(deployment.compose["waitTimeout"]),
             "--pull", "never", *arguments],
            show=True,
        )
    except OpenADKitError as error:
        reason = explain_failed_start(deployment, selection)
        if reason is None:
            raise
        raise OpenADKitError(reason) from error
    check_services_stay_up(deployment, selection, baseline)
    report_overrides(deployment, selection)


def changed_services(deployment: Deployment, selection: Selection) -> set[str]:
    """Running services whose Compose model differs from the current one, as
    after a settings change: Compose labels each container with its hash."""
    current = dict(
        line.split(maxsplit=1)
        for line in run_compose(deployment, selection, ["config", "--hash", "*"]).stdout.splitlines()
        if len(line.split()) == 2
    )
    ids = run_compose(deployment, selection, ["ps", "--quiet"]).stdout.split()
    if not ids:
        return set()
    result = docker(
        ["docker", "inspect", "--format",
         '{{index .Config.Labels "com.docker.compose.service"}} '
         '{{index .Config.Labels "com.docker.compose.config-hash"}}', *ids],
        trace=False,
    )
    running = dict(line.split(maxsplit=1) for line in result.stdout.splitlines() if len(line.split()) == 2)
    return {service for service, digest in running.items() if current.get(service) != digest}


# What run started, by Compose project, so restart can recreate it from any
# directory with the same choices and the current settings.
def run_state_path(project: str) -> Path:
    return state_root() / "runs" / f"{project}.json"


def write_run_state(project: str, state: dict[str, Any]) -> None:
    path = run_state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def read_run_state(project: str) -> dict[str, Any] | None:
    try:
        state = json.loads(run_state_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("schemaVersion") == 1 else None


def remove_run_state(project: str) -> None:
    run_state_path(project).unlink(missing_ok=True)


def verify(deployment: Deployment, selection: Selection, services: set[str], report: dict[str, Any]) -> int:
    """Run the deployment's verify step on the ready stack and return its exit code.

    A command runs in its service with ROS, Autoware and the overlays sourced;
    without one, the step is the service's own exit, as a scenario run's. The
    result joins the run's report.
    """
    spec = deployment.verify
    assert spec is not None
    service = spec["service"]
    if service not in services:
        print(f"verify: {service} does not run on this role; nothing to verify here")
        return 0
    # The step's own output follows on the same terminal.
    print(f"verify: {' '.join(spec['command']) if 'command' in spec else f'waiting for {service} to finish'}", flush=True)
    begin = time.monotonic()
    if "command" in spec:
        command = ["exec", "-T", service, "bash", "-c", SHELL_SETUP + 'exec "$@"', "bash", *spec["command"]]
        code = run_compose(deployment, selection, command, show=True, check=False).returncode
    else:
        ids = run_compose(deployment, selection, ["ps", "--all", "--quiet", service]).stdout.split()
        if not ids:
            raise OpenADKitError(f"{service} has no container to wait for")
        code = int(docker(["docker", "wait", ids[0]]).stdout.strip())
    report["verify"] = {
        "service": service,
        "seconds": round(time.monotonic() - begin, 1),
        "exitCode": code,
        "result": "PASSED" if code == 0 else "FAILED",
    }
    path = write_run_report(deployment, report, selection.instance)
    print(f"verify: {'passed' if code == 0 else f'failed (exit {code})'}; report: {path}")
    return code


def report_overrides(deployment: Deployment, selection: Selection) -> list[str]:
    """Warn about config overrides with no counterpart in the started services.

    Each hooked service writes /tmp/openadkit/overlay-report.json on start.
    Every service gets the same layers, so an overridden package is missing
    from most images; it is a mistake only when no service has it. After a
    base version change these usually are renamed packages, files or keys.
    """
    ids = run_compose(deployment, selection, ["ps", "--quiet"], check=False).stdout.split()
    return report_container_overrides(ids)


def report_container_overrides(ids: list[str]) -> list[str]:
    """report_overrides for these containers."""
    if not ids:
        return []
    inspected = docker(["docker", "inspect", *ids], check=False, trace=False)
    try:
        containers = json.loads(inspected.stdout) if inspected.returncode == 0 else []
    except json.JSONDecodeError:
        containers = []
    reports: list[dict[str, Any]] = []
    for container in containers:
        mounts = [mount.get("Destination", "") for mount in container.get("Mounts") or []]
        if not any(path.startswith(HOOK_MOUNTS) for path in mounts):
            continue
        result = docker(
            ["docker", "exec", container["Id"], "cat", "/tmp/openadkit/overlay-report.json"], check=False, trace=False
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
    distro; its build for another image or distro starts from a clean build
    and install, since CMake caches record the image's paths. A build/ or
    install/ it did not make, such as a colcon build on the host, is left
    alone: the build stops and names them.
    """
    fixed = sorted({option for option in FIXED_COLCON_OPTIONS for argument in colcon
                    if argument == option or argument.startswith(f"{option}=")})
    if fixed:
        raise OpenADKitError(f"{', '.join(fixed)} cannot change: the services use {OVERLAY_TARGET}/install")
    require_docker()
    stamp = {"image": image, "rosDistro": ros_distro}
    built = read_overlay_stamp(workspace)
    if built is None or {key: built.get(key) for key in stamp} != stamp:
        products = [path for path in (workspace / "build", workspace / "install")
                    if path.is_dir() and not path.is_symlink()]
        if built is None and any(any(path.iterdir()) for path in products):
            raise OpenADKitError(
                f"{' and '.join(str(path) for path in products)} did not come from openadkit build; "
                "remove them to build this workspace"
            )
        for path in products:
            shutil.rmtree(path)
        (workspace / "install").mkdir()
    # The stamp names the image the products belong to, so a failed build's
    # retry continues from what it built; "complete" waits for the build to pass.
    write_overlay_stamp(workspace, stamp)
    # Ctrl+C ends the docker client but not the build in the container, so
    # the container is named and removed with it.
    name = f"openadkit-build-{os.getpid()}"
    try:
        build_container(name, workspace, image, colcon)
    except KeyboardInterrupt:
        docker(["docker", "rm", "--force", name], check=False, trace=False)
        raise
    write_overlay_stamp(workspace, {**stamp, "complete": True})
    print(f"built: {workspace}")


def write_overlay_stamp(workspace: Path, stamp: dict[str, Any]) -> None:
    (workspace / "install" / OVERLAY_STAMP).write_text(json.dumps(stamp) + "\n", encoding="utf-8")


def build_container(name: str, workspace: Path, image: str, colcon: Sequence[str]) -> None:
    # The image compiles through ccache in the aw home, which only uid
    # 1000 can write; keep HOME and the cache in the container's /tmp.
    docker(
        [
            "docker", "run", "--rm", "--name", name,
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", "HOME=/tmp",
            "--env", "CCACHE_DIR=/tmp/ccache",
            "--env", "CMAKE_BUILD_TYPE=Release",
            "--volume", f"{workspace}:{OVERLAY_TARGET}",
            "--workdir", OVERLAY_TARGET,
            "--entrypoint", "bash",
            image, "-c", OVERLAY_BUILD, "build", *colcon,
        ],
        show=True,
    )


def check_overlay_build(deployment: Deployment, selection: Selection, image: str | None) -> None:
    """Warn about an overlay workspace that holds packages but no build, and
    stop on an install that build made for another image or ROS distro."""
    workspace = deployment.workspace
    stamp = read_overlay_stamp(workspace)
    if stamp is None:
        if not (workspace / "install").exists() and holds_packages(workspace):
            print(f"warning: overlay workspace: {workspace} holds packages that are not built; "
                  f"build it: openadkit build {workspace}", file=sys.stderr)
        return
    if stamp.get("rosDistro") == selection.ros_distro and (not image or stamp.get("image") == image):
        if not stamp.get("complete"):
            print(f"warning: overlay workspace: the last build of {workspace} failed, so some packages may "
                  f"be missing; build it: openadkit build {workspace}", file=sys.stderr)
        return
    raise OpenADKitError(
        f"overlay workspace {workspace} was built for {stamp.get('rosDistro')} in {stamp.get('image')}; "
        f"rebuild it: openadkit build {workspace} --ros-distro {selection.ros_distro}"
    )


# Sourced before a ROS command runs in a service container: docker exec skips
# the entrypoint that sources them for the service itself.
ROS_SHELL = 'source "/opt/ros/${ROS_DISTRO}/setup.bash"; source /opt/autoware/setup.bash; '

# As the entrypoint hook layers them, for an interactive shell or command.
SHELL_SETUP = ROS_SHELL + (
    f'[ -f {OVERLAY_TARGET}/install/local_setup.bash ] && source {OVERLAY_TARGET}/install/local_setup.bash; '
)
