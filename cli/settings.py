"""A deployment's settings: its env files, the host and what the CLI sets."""

from __future__ import annotations

import functools
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from catalog import (
    Catalog,
    Deployment,
    data_root,
    default_ros_distro,
    host_architecture,
    state_root,
)
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
    # here; resolve resolves those.
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


@dataclass(frozen=True)
class Selection:
    """How a command runs a deployment, with its settings resolved as Compose resolves them."""

    ros_distro: str
    gpu: bool
    role: str | None
    # What the CLI sets: distro, host user, mounts, images, role network.
    injections: dict[str, str]
    # Every env-file setting and injection, as Compose interpolates them.
    environment: dict[str, str]
    # Data-only selections: the settings a GPU run sees, so GPU-only data
    # goes where a GPU run mounts it. None when no GPU-only data is selected.
    gpu_environment: dict[str, str] | None = None


def configuration_environment(deployment: Deployment, gpu: bool = False) -> dict[str, str]:
    """Deployment env files only. The shell must not override these.

    Compose interpolation uses the same file order. A shell export of
    MAP_PATH would otherwise install data somewhere other than the mount.
    Host overrides belong in the host settings file, which is loaded last.
    """
    return dict(_env_file_settings(tuple(deployment.env_files(gpu))))


def docker_environment() -> dict[str, str]:
    """The process environment for a docker command, without Compose's own settings."""
    environment = dict(os.environ)
    for name in COMPOSE_CONTROL_ENV:
        environment.pop(name, None)
    return environment


def _compose_environment(deployment: Deployment, gpu: bool, injections: dict[str, str]) -> dict[str, str]:
    """Environment Compose uses to interpolate the deployment.

    Compose prefers the process environment over ``--env-file``, so a shell
    export would otherwise hide ``settings.gpu.env`` and the host settings file.
    Drop shell values for names the env files define and let Compose read
    the files itself, so quoting and ``$VAR`` expansion follow Compose rules.
    CLI injections (distro and component images) still win.
    """
    environment = docker_environment()
    for name in configuration_environment(deployment, gpu):
        environment.pop(name, None)
    environment.update(injections)
    return environment


def compose_process_environment(deployment: Deployment, selection: Selection) -> dict[str, str]:
    return _compose_environment(deployment, selection.gpu, selection.injections)


def _require_host_support(deployment: Deployment, distro: str, architecture: str, gpu: bool) -> bool:
    """Whether the run uses the GPU, once the host and distro are supported."""
    requirements = deployment.requirements
    if architecture not in requirements["architectures"]:
        raise OpenADKitError(
            f"{deployment.name} does not support {architecture}; expected "
            f"{', '.join(requirements['architectures'])}"
        )
    if distro not in requirements["rosDistros"]:
        raise OpenADKitError(
            f"{deployment.name} does not support ROS distro {distro}; expected "
            f"{', '.join(requirements['rosDistros'])}"
        )
    # A deployment that only runs on a GPU needs no --gpu flag.
    if requirements["gpu"] == "required":
        gpu = True
    if requirements["gpu"] == "none" and gpu:
        raise OpenADKitError(f"{deployment.name} does not provide a GPU mode")
    if gpu and requirements["gpu"] == "optional" and not deployment.has_gpu_files:
        raise OpenADKitError(f"{deployment.name} declares optional GPU but has no GPU Compose file")
    gpu_architectures = requirements.get("gpuArchitectures")
    if gpu and gpu_architectures is not None and architecture not in gpu_architectures:
        raise OpenADKitError(
            f"{deployment.name} GPU mode does not support {architecture}; expected "
            f"{', '.join(gpu_architectures)}"
        )
    return gpu


def _injections(deployment: Deployment, distro: str, role: str | None) -> dict[str, str]:
    """What the CLI sets for every command, images aside."""
    # settings.env defaults OUTPUT_HOST_PATH to this directory.
    injections = {
        "ROS_DISTRO": distro,
        "OPENADKIT_RESULTS_DIR": str(deployment.output_directory / "results"),
        # The deployments' data paths build on it (settings.env).
        "OPENADKIT_DATA_DIR": str(data_root()),
        **host_user_environment(),
        **deployment.kit_environment,
        **_overlay_mounts(deployment),
    }
    if role is not None:
        # runtime.env reads this, so each role joins its own DDS domain and
        # two roles on one host stay apart.
        injections["OPENADKIT_ROS_DOMAIN_ID"] = str(deployment.roles[role]["rosDomainId"])
        # A role's DDS stays on loopback even when the host settings name a
        # LAN interface: roles reach each other only through a service that
        # their own Compose files start.
        injections["CYCLONEDDS_NETWORK_INTERFACE"] = "lo"
    return injections


def _overlay_mounts(deployment: Deployment) -> dict[str, str]:
    """Host directories the entrypoint hook layers over Autoware's files.

    Config overrides apply in order: the base a kit builds on, the kit
    (what every deployment of it shares), then this deployment.
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


def _resolved(deployment: Deployment, gpu: bool, injections: dict[str, str]) -> dict[str, str]:
    """The env-file settings and injections as Compose interpolates them.

    Data paths must match the mounts, so Compose itself interpolates the env
    files (${VAR:-default}, values built on other settings, quoting).
    """
    files = deployment.env_files(gpu)
    resolved = compose_environment(files, _compose_environment(deployment, gpu, injections), deployment.working_directory)
    settings = {**configuration_environment(deployment, gpu), **injections}
    return {name: resolved.get(name, value) for name, value in settings.items()}


def require_own_destinations(deployment: Deployment) -> None:
    """A kit's data that replaces its base's needs a directory of its own.

    Left where the base keeps its data, the two would replace each other's
    files on every run of the other.
    """
    base = deployment.base
    if base is None:
        return
    for replaced in deployment.replaced_data:
        variable, gpu = replaced["destinationEnv"], bool(replaced.get("gpu"))
        inherited = _env_file_settings(tuple(path for layer in base.env_layers for path in layer.files(gpu)))
        if configuration_environment(deployment, gpu).get(variable) == inherited.get(variable):
            own = next(item["name"] for item in deployment.data if item["destinationEnv"] == variable)
            raise OpenADKitError(
                f"data {own} replaces {replaced['name']} of {base.name}, but {variable} still names "
                f"that deployment's directory; set {variable} in deployments/{deployment.name}/settings.env"
            )


def resolve(
    deployment: Deployment,
    catalog: Catalog,
    ros_distro: str | None = None,
    gpu: bool = False,
    *,
    role: str | None = None,
    data_only: bool = False,
) -> Selection:
    """How to run the deployment on this host, with every setting resolved.

    data_only (fetch, clean) needs only where the data goes, GPU-only data
    included: it skips the host requirements and the images, so a host or
    distro the deployment does not run on can still fetch or clean its data.
    """
    if role is not None and role not in deployment.roles:
        valid = ", ".join(sorted(deployment.roles)) if deployment.roles else "none"
        raise OpenADKitError(f"{deployment.name} has no role {role}\navailable roles: {valid}")
    require_own_destinations(deployment)
    distro = ros_distro or default_ros_distro(catalog, deployment.requirements["rosDistros"])
    injections = _injections(deployment, distro, role)
    if data_only:
        environment = _resolved(deployment, False, injections)
        gpu_environment = None
        if any(resource.get("gpu") for resource in deployment.data):
            same_files = deployment.env_files(True) == deployment.env_files(False)
            gpu_environment = environment if same_files else _resolved(deployment, True, injections)
        return Selection(distro, False, role, injections, environment, gpu_environment)

    architecture = host_architecture()
    gpu = _require_host_support(deployment, distro, architecture, gpu)
    images = catalog.component_environment(distro, architecture, gpu)
    images.update(catalog.external_image_environment(distro))
    file_settings = configuration_environment(deployment, gpu)
    if not catalog.pinned:
        # A source checkout may set its own images in the env files; Compose
        # reads those itself, ${VAR} and all.
        images = {name: image for name, image in images.items() if name not in file_settings}
    injections.update(images)

    environment = _resolved(deployment, gpu, injections)
    # Env files and injections stay authoritative for data paths and
    # Compose interpolation. Shell values only fill requiredEnv gaps, such
    # as an endpoint given for one command; they cannot hide MAP_PATH.
    present = {**os.environ, **environment}
    required = deployment.roles[role]["requiredEnv"] if role is not None else []
    missing = [name for name in required if not present.get(name)]
    if missing:
        raise OpenADKitError(
            f"required environment variable(s) are missing: {', '.join(missing)}\n"
            f"set them in {deployment.host_settings}"
        )
    return Selection(distro, gpu, role, injections, environment)
