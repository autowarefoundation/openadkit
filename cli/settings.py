"""A deployment's settings: its env files, the host and what the CLI sets."""

from __future__ import annotations

import dataclasses
import functools
import os
import platform
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from catalog import Deployment, RuntimeContext, state_root
from manifest import OpenADKitError

# Compose settings the CLI passes itself; a shell export must not change them.
COMPOSE_CONTROL_ENV = {
    "COMPOSE_ENV_FILES",
    "COMPOSE_FILE",
    "COMPOSE_PROFILES",
    "COMPOSE_PROJECT_NAME",
}

# What Compose adds to `config --environment` on its own.
COMPOSE_OWN_SETTINGS = {"COMPOSE_PROJECT_NAME", "PWD"}


def compose_environment(files: Iterable[Path], environment: dict[str, str], cwd: Path) -> dict[str, str]:
    """The settings of env files as Compose reads them.

    The empty project leaves out the deployment's own required variables.
    """
    command = ["docker", "compose", "--project-name", "openadkit-settings", "--file", "-"]
    for path in files:
        command.extend(("--env-file", str(path)))
    try:
        result = subprocess.run(
            [*command, "config", "--environment"],
            input="services: {}\n", capture_output=True, text=True, cwd=cwd, env=environment,
        )
    except OSError as error:
        raise OpenADKitError("Docker is unavailable. Run: openadkit setup") from error
    if result.returncode != 0:
        raise OpenADKitError(f"could not read the settings: {result.stderr.strip()}")
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


@functools.cache
def _env_file_settings(files: tuple[Path, ...]) -> dict[str, str]:
    # The process environment beats an env file in Compose, so only a clean
    # one shows what the files set. A value built on the shell stays blank
    # here; resolve_settings resolves those.
    clean = {
        name: value for name, value in os.environ.items()
        if name in ("HOME", "PATH") or name.startswith("DOCKER_")
    }
    return {
        name: value
        for name, value in compose_environment(files, clean, Path("/")).items()
        if name not in clean and name not in COMPOSE_OWN_SETTINGS and not name.startswith("DOCKER_CLI_")
    }


def host_user_environment() -> dict[str, str]:
    """Host user ids, so files written to host mounts belong to the user.

    ``shared/runtime.env`` passes them to the Open AD Kit images as
    ``HOST_UID``/``HOST_GID``; the upstream scenario runner uses them as ``user:``.
    """
    return {"OPENADKIT_UID": str(os.getuid()), "OPENADKIT_GID": str(os.getgid())}


def host_architecture() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


@dataclass(frozen=True)
class Selection:
    ros_distro: str
    gpu: bool
    node: str | None
    injections: dict[str, str]
    environment: dict[str, str]
    # Settings a GPU run sees, for GPU-only data (resolve_settings).
    gpu_environment: dict[str, str] | None = None


def configuration_environment(deployment: Deployment, gpu: bool = False) -> dict[str, str]:
    """Deployment env files only. The shell must not override these.

    Compose interpolation uses the same file order. A shell export of
    MAP_PATH would otherwise install data somewhere other than the mount.
    Host overrides belong in the site configuration, which is loaded last.
    """
    return dict(_env_file_settings(tuple(deployment.env_files(gpu))))


def _base_injections(deployment: Deployment, distro: str) -> dict[str, str]:
    # config.env defaults OUTPUT_HOST_PATH to this directory.
    injections = {
        "ROS_DISTRO": distro,
        "OPENADKIT_RESULTS_DIR": str(deployment.output_directory / "results"),
        **host_user_environment(),
    }
    injections.update(deployment.kit_environment)
    injections.update(_overlay_mounts(deployment))
    return injections


def _overlay_mounts(deployment: Deployment) -> dict[str, str]:
    """Host directories the entrypoint hook layers over Autoware's files.

    Config overrides apply in order: shared (every deployment that uses
    the shared services), the base a kit builds on, then this deployment.
    The overlay workspace is sourced on top of Autoware. A missing layer
    mounts an empty directory, so Docker never creates a root-owned one
    in its place.
    """
    empty = state_root() / "empty"

    def layer(path: Path | None) -> str:
        if path is not None and path.is_dir():
            return str(path)
        empty.mkdir(parents=True, exist_ok=True)
        return str(empty)

    return {name: layer(path) for name, path in deployment.overlay_paths.items()}


def _node_injections(deployment: Deployment, node: str | None, injections: dict[str, str]) -> dict[str, str]:
    if node is None:
        return injections
    # runtime.env reads this, so each node joins its own DDS domain and
    # two nodes on one host stay isolated until the Zenoh bridge links them.
    injections["OPENADKIT_ROS_DOMAIN_ID"] = str(deployment.nodes[node]["rosDomainId"])
    # Only the Zenoh bridge and its allowlist link nodes: DDS stays on
    # loopback even when the host settings name a LAN interface.
    injections["CYCLONEDDS_NETWORK_INTERFACE"] = "lo"
    return injections


def select(
    deployment: Deployment,
    current_context: RuntimeContext,
    ros_distro: str | None,
    gpu: bool,
    *,
    node: str | None = None,
    operational: bool = False,
    require_gpu: bool = True,
) -> Selection:
    if node is not None and node not in deployment.nodes:
        valid = ", ".join(sorted(deployment.nodes)) if deployment.nodes else "none"
        raise OpenADKitError(
            f"{deployment.name} has no node {node}\navailable nodes: {valid}"
        )
    distro = ros_distro or current_context.default_ros_distro

    # clean selects no images; it only needs the data paths of the env
    # files. Skip requirement validation and component image injection so
    # a missing default-distro image map can never block it.
    injections: dict[str, str]
    if operational:
        injections = _base_injections(deployment, distro)
        injections.update(current_context.artifact_environment(distro))
        injections = _node_injections(deployment, node, injections)
        environment = configuration_environment(deployment)
        environment.update(injections)
        return Selection(
            ros_distro=distro,
            gpu=False,
            node=node,
            injections=injections,
            environment=environment,
        )

    architecture = host_architecture()
    if architecture not in deployment.requirements["architectures"]:
        raise OpenADKitError(
            f"{deployment.name} does not support {architecture}; expected "
            f"{', '.join(deployment.requirements['architectures'])}"
        )
    if distro not in deployment.requirements["rosDistros"]:
        raise OpenADKitError(
            f"{deployment.name} does not support ROS distro {distro}; expected "
            f"{', '.join(deployment.requirements['rosDistros'])}"
        )

    gpu_requirement = deployment.requirements["gpu"]
    if require_gpu:
        # A deployment that only runs on a GPU needs no --gpu flag.
        if gpu_requirement == "required":
            gpu = True
        if gpu_requirement == "none" and gpu:
            raise OpenADKitError(f"{deployment.name} does not provide a GPU mode")
        if gpu and gpu_requirement == "optional" and not deployment.has_gpu_files:
            raise OpenADKitError(
                f"{deployment.name} declares optional GPU but has no GPU Compose file"
            )
        gpu_architectures = deployment.requirements.get("gpuArchitectures")
        if (
            gpu
            and gpu_architectures is not None
            and architecture not in gpu_architectures
        ):
            raise OpenADKitError(
                f"{deployment.name} GPU mode does not support {architecture}; expected "
                f"{', '.join(gpu_architectures)}"
            )

    view = deployment.nodes.get(node) if node is not None else None
    required_environment = list(view["requiredEnv"]) if view else []
    environment = configuration_environment(deployment, gpu)
    injections = _base_injections(deployment, distro)
    component_environment = current_context.component_environment(
        distro, architecture, gpu
    )
    component_environment.update(current_context.artifact_environment(distro))
    if not current_context.pinned:
        injections.update(
            {
                name: environment.get(name) or reference
                for name, reference in component_environment.items()
            }
        )
    else:
        injections.update(component_environment)
    injections["ROS_DISTRO"] = distro
    injections = _node_injections(deployment, node, injections)

    environment.update(injections)
    # Env files and injections stay authoritative for data paths and
    # Compose interpolation. Shell values only fill requiredEnv gaps such
    # as CI dummy ZENOH_LISTEN exports; they cannot hide MAP_PATH.
    present = dict(os.environ)
    present.update(environment)
    missing_environment = [
        name for name in required_environment if not present.get(name)
    ]
    if missing_environment:
        raise OpenADKitError(
            "required environment variable(s) are missing: "
            + ", ".join(missing_environment)
        )

    return Selection(
        ros_distro=distro,
        gpu=gpu,
        node=node,
        injections=injections,
        environment=environment,
    )


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
    for name in configuration_environment(deployment, selection.gpu):
        environment.pop(name, None)
    environment.update(selection.injections)
    for name in COMPOSE_CONTROL_ENV:
        environment.pop(name, None)
    return environment


def _resolved_settings(deployment: Deployment, selection: Selection) -> dict[str, str]:
    resolved = compose_environment(
        deployment.env_files(selection.gpu), compose_process_environment(deployment, selection), deployment.directory
    )
    return {name: resolved.get(name, value) for name, value in selection.environment.items()}


def resolve_settings(deployment: Deployment, selection: Selection) -> Selection:
    """The selection with its env-file settings resolved as Compose resolves them.

    Data paths must match the mounts, so Compose itself interpolates the env
    files (${VAR:-default}, values built on other settings, quoting). GPU-only
    data resolves with the GPU env files, as a GPU run would.
    """
    environment = _resolved_settings(deployment, selection)
    gpu_environment = environment
    if not selection.gpu and deployment.has_gpu_files:
        gpu = dataclasses.replace(
            selection,
            gpu=True,
            environment={
                **configuration_environment(deployment, True),
                **selection.injections,
            },
        )
        gpu_environment = _resolved_settings(deployment, gpu)
    return dataclasses.replace(
        selection, environment=environment, gpu_environment=gpu_environment
    )
