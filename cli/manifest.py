"""Open AD Kit bundle and deployment manifest handling."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Compose also reads env file keys with dots and dashes; only interpolation
# names are limited to ENV_NAME_RE.
ENV_FILE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_REFERENCE_RE = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
GPU_COMPONENT_IMAGE = "SENSING_PERCEPTION_GPU_IMAGE"
# The image a release builds integrator overlays in, pinned with its runtime images.
DEVEL_IMAGE_TARGET = "universe-common-devel"
# Manifests from before v2.0.0 never shipped in a stable release; they are
# rejected rather than translated.
SCHEMA_VERSION = 2

ALLOWED_KIT_KEYS = {
    "schemaVersion",
    "kind",
    "version",
    "defaultRosDistro",
    "imagePrefixComponent",
    "componentImages",
    "images",
    "deployments",
    "shared",
    "artifacts",
    "autoware",
}
ALLOWED_ARTIFACT_KEYS = {"workload", "ref", "distros"}
# An integrator kit: its own deployments on top of one pinned Open AD Kit.
ALLOWED_INTEGRATOR_KIT_KEYS = {"schemaVersion", "kind", "extends", "deployments", "artifacts"}
ALLOWED_INTEGRATOR_DEPLOYMENT_KEYS = {
    "schemaVersion", "name", "description", "base", "compose", "data",
}
ALLOWED_INTEGRATOR_COMPOSE_KEYS = {"files", "resetServices", "waitTimeout"}
# The include variable for the pinned kit, named per kit so a later layer
# (a Tier-1 kit extended by an OEM kit) can add its own.
BASE_KIT_ENV = "KIT_openadkit"
RELEASE_TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$")
ALLOWED_DEPLOYMENT_REF_KEYS = {"path", "checksum"}
ALLOWED_DEPLOYMENT_KEYS = {
    "schemaVersion",
    "name",
    "description",
    "compose",
    "requirements",
    "data",
    "shared",
    "nodes",
    "evidence",
}
ALLOWED_COMPOSE_KEYS = {
    "files",
    "gpuFiles",
    "profiles",
    "resetServices",
    "waitTimeout",
}
ALLOWED_NODE_KEYS = {
    "backend",
    "files",
    "resetServices",
    "requiredEnv",
    "requiredFiles",
    "rosDomainId",
}
NODE_BACKENDS = {"compose"}
# Linux keeps DDS ports for domains 0-101 clear of the ephemeral port range.
MAX_ROS_DOMAIN_ID = 101
ALLOWED_REQUIREMENT_KEYS = {
    "architectures",
    "rosDistros",
    "gpu",
    "gpuArchitectures",
}
ALLOWED_DATA_KEYS = {
    "name",
    "kind",
    "destinationEnv",
    "expectedRoot",
    "url",
    "sha256",
    "files",
    "generatedFiles",
    "requiredFiles",
    "gpu",
    "nodes",
}
ALLOWED_DATA_FILE_KEYS = {"path", "url", "source", "sha256"}


class OpenADKitError(Exception):
    """A user-facing failure."""


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as source:
            value = json.load(source, object_pairs_hook=unique_object)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise OpenADKitError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise OpenADKitError(f"JSON root must be an object: {path}")
    return value


def reject_unknown(mapping: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise OpenADKitError(f"unknown {where} field(s): {', '.join(unknown)}")


def require_string(value: Any, where: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        qualifier = " nonempty" if nonempty else ""
        raise OpenADKitError(f"{where} must be a{qualifier} string")
    return value


def require_string_list(
    value: Any,
    where: str,
    *,
    nonempty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise OpenADKitError(f"{where} must be an array of nonempty strings")
    if nonempty and not value:
        raise OpenADKitError(f"{where} must not be empty")
    if len(value) != len(set(value)):
        raise OpenADKitError(f"{where} contains duplicate values")
    return value


def safe_relative(value: str, where: str) -> PurePosixPath:
    path = PurePosixPath(require_string(value, where))
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise OpenADKitError(f"{where} must be a safe relative path: {value}")
    return path


def ensure_safe_existing(
    base: Path,
    relative: str,
    where: str,
) -> Path:
    rel = safe_relative(relative, where)
    current = base
    for part in rel.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError as error:
            raise OpenADKitError(f"missing {where}: {current}") from error
        if stat.S_ISLNK(info.st_mode):
            raise OpenADKitError(f"symlinked {where} is not allowed: {current}")
    if not current.is_file():
        raise OpenADKitError(f"{where} is not a regular file: {current}")
    return current


# The escapes Compose applies inside a double-quoted value.
DOTENV_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "$": "$"}


def _dotenv_unescape(value: str) -> str:
    result, index = [], 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            following = value[index + 1]
            if following in DOTENV_ESCAPES:
                result.append(DOTENV_ESCAPES[following])
                index += 2
                continue
        result.append(char)
        index += 1
    return "".join(result)


def parse_dotenv(path: Path) -> dict[str, str]:
    """Read a Compose env file the way Compose does.

    A name is followed by "=" or ":". A name alone takes its value from the
    shell, so the file does not set it. Quoted values may span lines and keep
    comments; a double-quoted value unescapes \\n, \\r, \\t, \\", \\\\ and
    \\$; an unquoted one ends at " #".
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise OpenADKitError(f"could not read environment file {path}: {error}") from error
    values: dict[str, str] = {}
    index, line = 0, 1
    length = len(text)
    while index < length:
        start_of_line = index
        line_end = text.find("\n", index)
        line_end = length if line_end == -1 else line_end
        raw = text[start_of_line:line_end]
        index = line_end + 1
        where = f"{path}:{line}"
        stripped = raw.strip()
        line += 1
        if not stripped or stripped.startswith("#"):
            continue
        separators = [position for position in (raw.find("="), raw.find(":")) if position != -1]
        separator = min(separators, default=len(raw))
        name, value_start = raw[:separator].strip(), raw[separator + 1 :]
        words = name.split(None, 1)
        if len(words) == 2 and words[0] == "export":
            name = words[1]
        if not ENV_FILE_NAME_RE.fullmatch(name):
            raise OpenADKitError(f"invalid environment name at {where}: {name}")
        if not separators:
            continue
        # Position of the value in the whole text, for multi-line values.
        offset = start_of_line + separator + 1
        while offset < length and text[offset] in " \t":
            offset += 1
        if offset < length and text[offset] in ("'", '"'):
            quote = text[offset]
            cursor = offset + 1
            while cursor < length:
                if quote == '"' and text[cursor] == "\\":
                    cursor += 2
                    continue
                if text[cursor] == quote:
                    break
                cursor += 1
            if cursor >= length:
                raise OpenADKitError(f"unterminated quoted value at {where}")
            content = text[offset + 1 : cursor]
            line += content.count("\n")
            rest_end = text.find("\n", cursor + 1)
            rest_end = length if rest_end == -1 else rest_end
            rest = text[cursor + 1 : rest_end].strip()
            if rest and not rest.startswith("#"):
                raise OpenADKitError(f"unexpected text after quoted value at {where}")
            values[name] = _dotenv_unescape(content) if quote == '"' else content
            index = rest_end + 1
            continue
        value = value_start
        comment = value.find(" #")
        values[name] = (value if comment == -1 else value[:comment]).strip()
    return values


def expand_home(value: str) -> str:
    home = os.environ.get("HOME")
    if not home:
        raise OpenADKitError("HOME is required")
    if value in ("$HOME", "${HOME}"):
        return home
    if value.startswith("$HOME/"):
        return str(Path(home) / value[6:])
    if value.startswith("${HOME}/"):
        return str(Path(home) / value[8:])
    return value


def _user_root(override: str, xdg: str, fallback: str) -> Path:
    """An Open AD Kit root outside the release, so upgrades keep it."""
    explicit = os.environ.get(override)
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get(xdg) or str(Path(expand_home("$HOME")) / fallback)
    return Path(base) / "openadkit"


def config_root() -> Path:
    """Site settings: one ``<deployment>.env`` per deployment."""
    return _user_root("OPENADKIT_CONFIG_DIR", "XDG_CONFIG_HOME", ".config")


def state_root() -> Path:
    """Run results: ``<deployment>/output``."""
    return _user_root("OPENADKIT_STATE_DIR", "XDG_STATE_HOME", ".local/state")


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
class DeploymentRef:
    path: str
    checksum: str | None


@dataclass(frozen=True)
class RuntimeContext:
    kind: str
    default_ros_distro: str
    version: str | None
    image_prefix_component: str | None
    component_images: dict[str, str]
    images: dict[str, dict[str, str]]
    deployments: dict[str, DeploymentRef]
    shared: dict[str, str]
    # Pinned images we consume rather than build: name -> {workload, refs}.
    artifacts: dict[str, dict[str, Any]]
    # Release only: the Autoware version, commit and lock file it was built from.
    autoware: dict[str, str] | None = None
    # Integrator kit only: the pinned Open AD Kit it extends.
    extends: str | None = None
    base: RuntimeContext | None = None
    base_root: Path | None = None

    @property
    def pinned(self) -> bool:
        """Release images cannot be overridden from env files; source images can."""
        return self.image_prefix_component is None

    def devel_image(self, ros_distro: str) -> str | None:
        """The devel image of the build the runtime images come from, if pinned."""
        return self.images.get(ros_distro, {}).get(DEVEL_IMAGE_TARGET)

    def bom(self) -> dict[str, Any]:
        """What this kit runs: Autoware, component images and artifacts."""
        return {
            "autoware": self.autoware,
            "images": self.images or None,
            "artifacts": self.artifacts,
        }

    def artifact_environment(self, ros_distro: str) -> dict[str, str]:
        """Artifact references for one distro; Compose requires them by name.

        In an integrator kit its own artifacts come last, so one named like a
        component image replaces that component.
        """
        environment = {}
        for name, artifact in self.artifacts.items():
            # A resolved kit can have per-distro overrides and a base fallback.
            reference = artifact.get("distros", {}).get(ros_distro) or artifact.get("ref")
            if reference:
                environment[name] = reference
        return environment

    def component_environment(
        self, ros_distro: str, architecture: str, gpu: bool
    ) -> dict[str, str]:
        applicable = {
            name: target
            for name, target in self.component_images.items()
            if gpu or name != GPU_COMPONENT_IMAGE
        }
        if self.image_prefix_component is not None:
            return {
                name: (
                    f"{self.image_prefix_component}:{target}-{architecture}-{ros_distro}"
                )
                for name, target in applicable.items()
            }

        distro_images = self.images.get(ros_distro)
        if distro_images is None:
            raise OpenADKitError(
                f"release has no component images for ROS distro {ros_distro}"
            )
        missing = sorted(set(applicable.values()) - set(distro_images))
        if missing:
            raise OpenADKitError(
                "release is missing component image target(s) for "
                f"{ros_distro}: {', '.join(missing)}"
            )
        return {
            name: distro_images[target]
            for name, target in applicable.items()
            if target in distro_images
        }


@dataclass(frozen=True)
class Selection:
    ros_distro: str
    gpu: bool
    node: str | None
    injections: dict[str, str]
    environment: dict[str, str]
    # Settings a GPU run sees, for GPU-only data (compose.resolve_settings).
    gpu_environment: dict[str, str] | None = None


@dataclass(frozen=True)
class EnvironmentLayer:
    directory: Path
    required: bool
    gpu_required: bool

    def files(self, gpu: bool) -> list[Path]:
        result = []
        names = [("config.env", self.required)]
        if gpu:
            names.append(("config.gpu.env", self.gpu_required))
        for name, required in names:
            candidate = self.directory / name
            if required or candidate.exists() or candidate.is_symlink():
                result.append(ensure_safe_existing(self.directory, name, "environment file"))
        return result


class Deployment:
    def __init__(
        self,
        root: Path,
        directory: Path,
        manifest: dict[str, Any],
        base: Deployment | None = None,
    ) -> None:
        self.root = root
        # Retained only as provenance and the static overlay-contract baseline.
        # Runtime layers below are resolved once; they never delegate to base.
        self.base = base
        self.directory = directory
        self.manifest = manifest
        self.name: str = manifest["name"]
        self.compose: dict[str, Any] = manifest["compose"]
        self.nodes: dict[str, dict[str, Any]] = manifest["nodes"]
        self.requirements: dict[str, Any] = manifest["requirements"]
        self.data: list[dict[str, Any]] = manifest["data"]
        self.shared: list[str] = manifest["shared"]
        # Why CI cannot produce evidence for this deployment, if it cannot.
        self.evidence_exemption: str | None = manifest["evidence"].get("exempt")
        self.project = f"openadkit-{self.name}"
        own_layer = EnvironmentLayer(directory, base is None, bool(self.compose["gpuFiles"]))
        self.env_layers: tuple[EnvironmentLayer, ...] = (*(base.env_layers if base else ()), own_layer)
        # Kit GPU patches follow its Compose entrypoint, as before.
        self.gpu_files: list[tuple[Path, str]] = [
            (directory, name) for name in self.compose["gpuFiles"]
        ] + (base.gpu_files if base else [])
        owner = base if base else self
        # A kit's ROS packages serve all of its deployments, so its workspace
        # lives at the kit root; a deployment may layer its own on top. A kit
        # whose deployment is the root itself has the one workspace.
        own_workspace = base is not None and directory.resolve() != root.resolve()
        self.overlay_paths = {
            "OPENADKIT_CONFIG_SHARED": (
                owner.root / "deployments/shared/config" if "shared" in owner.shared else None
            ),
            "OPENADKIT_CONFIG_BASE": base.directory / "config" if base else None,
            "OPENADKIT_CONFIG_DEPLOYMENT": directory / "config",
            "OPENADKIT_OVERLAY_WS": (root if base else directory) / "overlay_ws",
            "OPENADKIT_OVERLAY_WS_DEPLOYMENT": directory / "overlay_ws" if own_workspace else None,
        }
        self.kit_environment = {
            BASE_KIT_ENV: str(base.root),
            "OPENADKIT_BASE_DEPLOYMENT": str(base.directory),
        } if base else {}

    def project_name(self, node: str | None = None) -> str:
        """Each node is its own Compose project, so nodes never share state."""
        return self.project if node is None else f"{self.project}-{node}"

    @property
    def site_config(self) -> Path:
        """Host settings for this deployment; loaded last, kept across upgrades."""
        return config_root() / f"{self.name}.env"

    @property
    def output_directory(self) -> Path:
        return state_root() / self.name / "output"

    @property
    def has_gpu_files(self) -> bool:
        return bool(self.gpu_files)

    def env_files(self, gpu: bool = False) -> list[Path]:
        """Base env files, then this deployment's, then the host's site file."""
        result = [path for layer in self.env_layers for path in layer.files(gpu)]
        site = self.site_config
        if site.exists():
            if not site.is_file():
                raise OpenADKitError(f"site configuration is not a regular file: {site}")
            result.append(site)
        return result

    def configuration_environment(self, gpu: bool = False) -> dict[str, str]:
        """Deployment env files only. The shell must not override these.

        Compose interpolation uses the same file order. A shell export of
        MAP_PATH would otherwise install data somewhere other than the mount.
        Host overrides belong in the site configuration, which is loaded last.
        """
        values: dict[str, str] = {}
        for path in self.env_files(gpu):
            values.update(parse_dotenv(path))
        return values

    def compose_files(self, gpu: bool, node: str | None = None) -> list[Path]:
        """Only explicitly selected files; each entrypoint owns its whole graph."""
        names = self.compose["files"] if node is None else self.nodes[node]["files"]
        files = [
            ensure_safe_existing(self.directory, name, "Compose file") for name in names
        ]
        if gpu:
            files.extend(
                ensure_safe_existing(directory, name, "Compose file")
                for directory, name in self.gpu_files
            )
        return files

    def reset_services(self, node: str | None = None) -> list[str]:
        if node is None:
            return list(self.compose["resetServices"])
        return list(self.nodes[node]["resetServices"])

    def _base_injections(self, distro: str) -> dict[str, str]:
        # config.env defaults OUTPUT_HOST_PATH to this directory.
        injections = {
            "ROS_DISTRO": distro,
            "OPENADKIT_OUTPUT_DIR": str(self.output_directory),
            **host_user_environment(),
        }
        injections.update(self.kit_environment)
        injections.update(self._overlay_mounts())
        return injections

    def _overlay_mounts(self) -> dict[str, str]:
        """Host directories the entrypoint hook layers over Autoware's files.

        Config overrides apply in order: shared (every deployment that uses
        the shared services), the base a kit builds on, then this deployment.
        Overlay workspaces are sourced in order: the kit's, then this
        deployment's. A missing layer mounts an empty directory, so Docker
        never creates a root-owned one in its place.
        """
        empty = state_root() / "empty"

        def layer(path: Path | None) -> str:
            if path is not None and path.is_dir():
                return str(path)
            empty.mkdir(parents=True, exist_ok=True)
            return str(empty)

        return {name: layer(path) for name, path in self.overlay_paths.items()}

    def _node_injections(self, node: str | None, injections: dict[str, str]) -> dict[str, str]:
        if node is None:
            return injections
        # runtime.env reads this, so each node joins its own DDS domain and
        # two nodes on one host stay isolated until the Zenoh bridge links them.
        injections["OPENADKIT_ROS_DOMAIN_ID"] = str(self.nodes[node]["rosDomainId"])
        # Only the Zenoh bridge and its allowlist link nodes: DDS stays on
        # loopback even when the host settings name a LAN interface.
        injections["CYCLONEDDS_NETWORK_INTERFACE"] = "lo"
        return injections

    def select(
        self,
        current_context: RuntimeContext,
        ros_distro: str | None,
        gpu: bool,
        *,
        node: str | None = None,
        operational: bool = False,
        require_gpu: bool = True,
    ) -> Selection:
        if node is not None and node not in self.nodes:
            valid = ", ".join(sorted(self.nodes)) if self.nodes else "none"
            raise OpenADKitError(
                f"{self.name} has no node {node}\navailable nodes: {valid}"
            )
        distro = ros_distro or current_context.default_ros_distro

        # Operational commands (status/logs/stop) do not select images or
        # profiles; they only need the deployment's Compose and env files.
        # Skip requirement validation and component image injection so a
        # missing default-distro image map can never block a stop.
        injections: dict[str, str]
        if operational:
            injections = self._base_injections(distro)
            injections.update(current_context.artifact_environment(distro))
            injections = self._node_injections(node, injections)
            environment = self.configuration_environment()
            environment.update(injections)
            return Selection(
                ros_distro=distro,
                gpu=False,
                node=node,
                injections=injections,
                environment=environment,
            )

        architecture = host_architecture()
        if architecture not in self.requirements["architectures"]:
            raise OpenADKitError(
                f"{self.name} does not support {architecture}; expected "
                f"{', '.join(self.requirements['architectures'])}"
            )
        if distro not in self.requirements["rosDistros"]:
            raise OpenADKitError(
                f"{self.name} does not support ROS distro {distro}; expected "
                f"{', '.join(self.requirements['rosDistros'])}"
            )

        gpu_requirement = self.requirements["gpu"]
        if require_gpu:
            # A deployment that only runs on a GPU needs no --gpu flag.
            if gpu_requirement == "required":
                gpu = True
            if gpu_requirement == "none" and gpu:
                raise OpenADKitError(f"{self.name} does not provide a GPU mode")
            if gpu and gpu_requirement == "optional" and not self.has_gpu_files:
                raise OpenADKitError(
                    f"{self.name} declares optional GPU but has no GPU Compose file"
                )
            gpu_architectures = self.requirements.get("gpuArchitectures")
            if (
                gpu
                and gpu_architectures is not None
                and architecture not in gpu_architectures
            ):
                raise OpenADKitError(
                    f"{self.name} GPU mode does not support {architecture}; expected "
                    f"{', '.join(gpu_architectures)}"
                )

        view = self.nodes.get(node) if node is not None else None
        required_environment = list(view["requiredEnv"]) if view else []
        environment = self.configuration_environment(gpu)
        injections = self._base_injections(distro)
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
        injections = self._node_injections(node, injections)

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


def _validate_data(data: Any, nodes: dict[str, Any], directory: Path) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise OpenADKitError("data must be an array")
    names: set[str] = set()
    destinations: set[str] = set()
    for index, resource in enumerate(data):
        where = f"data[{index}]"
        if not isinstance(resource, dict):
            raise OpenADKitError(f"{where} must be an object")
        reject_unknown(resource, ALLOWED_DATA_KEYS, where)
        resource_name = require_string(resource.get("name"), f"{where}.name")
        # The name also names the staging directory of its download.
        if not NAME_RE.fullmatch(resource_name):
            raise OpenADKitError(f"invalid {where}.name: {resource_name}")
        if resource_name in names:
            raise OpenADKitError(f"duplicate data resource: {resource_name}")
        names.add(resource_name)
        if resource.get("kind") not in ("zip", "files"):
            raise OpenADKitError(f"{where}.kind must be zip or files")
        require_string(resource.get("destinationEnv"), f"{where}.destinationEnv")
        if not ENV_NAME_RE.fullmatch(resource["destinationEnv"]):
            raise OpenADKitError(f"{where}.destinationEnv must be an environment name")
        if resource["destinationEnv"] in destinations:
            raise OpenADKitError(
                f"duplicate data destination environment: {resource['destinationEnv']}"
            )
        destinations.add(resource["destinationEnv"])
        if "gpu" in resource and not isinstance(resource["gpu"], bool):
            raise OpenADKitError(f"{where}.gpu must be a boolean")
        if "nodes" in resource:
            resource["nodes"] = require_string_list(
                resource["nodes"], f"{where}.nodes", nonempty=True
            )
            unknown_nodes = sorted(set(resource["nodes"]) - set(nodes))
            if unknown_nodes:
                raise OpenADKitError(
                    f"{where}.nodes contains undeclared node(s): "
                    + ", ".join(unknown_nodes)
                )
        resource["requiredFiles"] = require_string_list(
            resource.get("requiredFiles", []), f"{where}.requiredFiles"
        )
        for required in resource["requiredFiles"]:
            safe_relative(required, f"{where}.requiredFiles")
        generated = resource.get("generatedFiles", {})
        if not isinstance(generated, dict) or any(
            not isinstance(value, str) for value in generated.values()
        ):
            raise OpenADKitError(f"{where}.generatedFiles must map paths to strings")
        for relative in generated:
            safe_relative(relative, f"{where}.generatedFiles")
        resource["generatedFiles"] = generated
        if resource["kind"] == "zip":
            require_string(resource.get("url"), f"{where}.url")
            checksum = require_string(resource.get("sha256"), f"{where}.sha256")
            if not SHA256_RE.fullmatch(checksum):
                raise OpenADKitError(f"{where}.sha256 is invalid")
            safe_relative(
                require_string(resource.get("expectedRoot"), f"{where}.expectedRoot"),
                f"{where}.expectedRoot",
            )
            if resource.get("files") not in (None, []):
                raise OpenADKitError(f"{where}.files is invalid for zip data")
            resource["files"] = []
        else:
            files = resource.get("files")
            if not isinstance(files, list) or not files:
                raise OpenADKitError(f"{where}.files must be a nonempty array")
            seen_paths: set[str] = set()
            for file_index, item in enumerate(files):
                file_where = f"{where}.files[{file_index}]"
                if not isinstance(item, dict):
                    raise OpenADKitError(f"{file_where} must be an object")
                reject_unknown(item, ALLOWED_DATA_FILE_KEYS, file_where)
                relative = require_string(item.get("path"), f"{file_where}.path")
                safe_relative(relative, f"{file_where}.path")
                if relative in seen_paths:
                    raise OpenADKitError(f"duplicate data file path: {relative}")
                seen_paths.add(relative)
                # A file the deployment ships (source, relative to its directory)
                # or one to download (url); the checksum is checked either way.
                if ("url" in item) == ("source" in item):
                    raise OpenADKitError(f"{file_where} needs exactly one of url and source")
                if "url" in item:
                    require_string(item["url"], f"{file_where}.url")
                else:
                    item["sourcePath"] = ensure_safe_existing(
                        directory, item["source"], f"{file_where}.source"
                    )
                checksum = require_string(item.get("sha256"), f"{file_where}.sha256")
                if not SHA256_RE.fullmatch(checksum):
                    raise OpenADKitError(f"{file_where}.sha256 is invalid")
    return data


def _load_deployment_manifest(directory: Path, allowed_keys: set[str]) -> dict[str, Any]:
    """The part every deployment manifest shares: location, schema and identity."""
    if directory.is_symlink() or not directory.is_dir():
        raise OpenADKitError(f"unsafe deployment directory: {directory}")
    manifest = load_json(
        ensure_safe_existing(directory, "deployment.json", "deployment manifest")
    )
    reject_unknown(manifest, allowed_keys, "manifest")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise OpenADKitError(
            f"unsupported deployment schemaVersion {manifest.get('schemaVersion')!r} "
            f"(expected {SCHEMA_VERSION})"
        )
    name = require_string(manifest.get("name"), "name")
    if not NAME_RE.fullmatch(name) or name != directory.name:
        raise OpenADKitError(
            f"manifest name must match deployment directory: {directory.name}"
        )
    require_string(manifest.get("description"), "description")
    return manifest


def _wait_timeout(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise OpenADKitError("compose.waitTimeout must be a positive integer")
    return value


def validate_manifest(root: Path, directory: Path) -> Deployment:
    manifest = _load_deployment_manifest(directory, ALLOWED_DEPLOYMENT_KEYS)

    shared = require_string_list(manifest.get("shared", []), "shared")
    for shared_name in shared:
        if not NAME_RE.fullmatch(shared_name):
            raise OpenADKitError(f"invalid shared deployment asset name: {shared_name}")
        shared_directory = root / "deployments" / shared_name
        if shared_directory.is_symlink() or not shared_directory.is_dir():
            raise OpenADKitError(
                f"missing or unsafe shared deployment assets: {shared_name}"
            )
    manifest["shared"] = shared

    requirements = manifest.get("requirements")
    if not isinstance(requirements, dict):
        raise OpenADKitError("requirements must be an object")
    reject_unknown(requirements, ALLOWED_REQUIREMENT_KEYS, "requirements")
    requirements["architectures"] = require_string_list(
        requirements.get("architectures"),
        "requirements.architectures",
        nonempty=True,
    )
    requirements["rosDistros"] = require_string_list(
        requirements.get("rosDistros"),
        "requirements.rosDistros",
        nonempty=True,
    )
    if any(not NAME_RE.fullmatch(item) for item in requirements["rosDistros"]):
        raise OpenADKitError("requirements.rosDistros contains invalid distro names")
    if requirements.get("gpu") not in ("none", "optional", "required"):
        raise OpenADKitError("requirements.gpu must be none, optional, or required")
    if "gpuArchitectures" in requirements:
        requirements["gpuArchitectures"] = require_string_list(
            requirements["gpuArchitectures"],
            "requirements.gpuArchitectures",
            nonempty=True,
        )
        unknown = sorted(
            set(requirements["gpuArchitectures"]) - set(requirements["architectures"])
        )
        if unknown:
            raise OpenADKitError(
                "requirements.gpuArchitectures contains undeclared architectures: "
                + ", ".join(unknown)
            )
    manifest["requirements"] = requirements

    compose = manifest.get("compose")
    if not isinstance(compose, dict):
        raise OpenADKitError("compose must be an object")
    reject_unknown(compose, ALLOWED_COMPOSE_KEYS, "compose")
    for field in ("files", "gpuFiles", "profiles", "resetServices"):
        compose[field] = require_string_list(compose.get(field, []), f"compose.{field}")
    if not compose["files"]:
        raise OpenADKitError("compose.files must not be empty")
    compose["waitTimeout"] = _wait_timeout(compose.get("waitTimeout", 300))

    manifest["compose"] = compose

    nodes = manifest.get("nodes", {})
    if not isinstance(nodes, dict):
        raise OpenADKitError("nodes must be an object")
    domain_ids: set[int] = set()
    for node_name, node in nodes.items():
        where = f"nodes.{node_name}"
        if not NAME_RE.fullmatch(node_name):
            raise OpenADKitError(f"invalid node name: {node_name}")
        if not isinstance(node, dict):
            raise OpenADKitError(f"{where} must be an object")
        reject_unknown(node, ALLOWED_NODE_KEYS, where)
        node["backend"] = node.get("backend", "compose")
        if node["backend"] not in NODE_BACKENDS:
            raise OpenADKitError(
                f"{where}.backend must be one of: {', '.join(sorted(NODE_BACKENDS))}"
            )
        node["files"] = require_string_list(
            node.get("files"), f"{where}.files", nonempty=True
        )
        node["resetServices"] = require_string_list(
            node.get("resetServices", []), f"{where}.resetServices"
        )
        node["requiredEnv"] = require_string_list(
            node.get("requiredEnv", []), f"{where}.requiredEnv"
        )
        node["requiredFiles"] = require_string_list(
            node.get("requiredFiles", []), f"{where}.requiredFiles"
        )
        for file_name in node["requiredFiles"]:
            ensure_safe_existing(directory, file_name, "required node file")
        invalid_node_env = [
            item for item in node["requiredEnv"] if not ENV_NAME_RE.fullmatch(item)
        ]
        if invalid_node_env:
            raise OpenADKitError(
                f"{where}.requiredEnv contains invalid environment names: "
                + ", ".join(invalid_node_env)
            )
        domain_id = node.get("rosDomainId")
        if (
            not isinstance(domain_id, int)
            or isinstance(domain_id, bool)
            or not 0 <= domain_id <= MAX_ROS_DOMAIN_ID
        ):
            raise OpenADKitError(
                f"{where}.rosDomainId must be an integer from 0 to {MAX_ROS_DOMAIN_ID}"
            )
        if domain_id in domain_ids:
            raise OpenADKitError(f"{where}.rosDomainId {domain_id} is used by another node")
        domain_ids.add(domain_id)
        for file_name in node["files"]:
            ensure_safe_existing(directory, file_name, "Compose file")
    manifest["nodes"] = nodes

    evidence = manifest.get("evidence", {})
    if not isinstance(evidence, dict):
        raise OpenADKitError("evidence must be an object")
    reject_unknown(evidence, {"exempt"}, "evidence")
    if "exempt" in evidence:
        require_string(evidence["exempt"], "evidence.exempt")
    manifest["evidence"] = evidence

    data = _validate_data(manifest.get("data", []), nodes, directory)
    manifest["data"] = data

    deployment = Deployment(root, directory, manifest)
    deployment.compose_files(False)
    if compose["gpuFiles"]:
        deployment.compose_files(True)
        ensure_safe_existing(
            directory, "config.gpu.env", "GPU environment file"
        )
    for node_name in nodes:
        deployment.compose_files(False, node_name)
        if compose["gpuFiles"]:
            deployment.compose_files(True, node_name)
    deployment.env_files()
    return deployment


def validate_kit_deployment(
    root: Path, directory: Path, base_kit: RuntimeContext, base_root: Path
) -> Deployment:
    """An integrator deployment: its own Compose file and values on top of a
    base deployment from the pinned kit, whose requirements it keeps as is."""
    manifest = _load_deployment_manifest(directory, ALLOWED_INTEGRATOR_DEPLOYMENT_KEYS)
    base_name = require_string(manifest.get("base"), "base")
    if base_name not in base_kit.deployments:
        raise OpenADKitError(
            f"base deployment {base_name} is not in the pinned kit; "
            f"available: {available_deployments(base_kit)}"
        )
    base = get_deployment(base_root, base_kit, base_name)

    compose = manifest.get("compose")
    if not isinstance(compose, dict):
        raise OpenADKitError("compose must be an object")
    reject_unknown(compose, ALLOWED_INTEGRATOR_COMPOSE_KEYS, "compose")
    files = require_string_list(compose.get("files"), "compose.files", nonempty=True)
    extra_resets = require_string_list(compose.get("resetServices", []), "compose.resetServices")
    wait_timeout = _wait_timeout(compose.get("waitTimeout", base.compose["waitTimeout"]))

    own_data = _validate_data(manifest.get("data", []), {}, directory)
    destinations = {item["destinationEnv"] for item in base.data}
    clashing = sorted(destinations & {item["destinationEnv"] for item in own_data})
    if clashing:
        raise OpenADKitError(
            "data reuses a destination of the base deployment: " + ", ".join(clashing)
        )

    merged = {
        "name": manifest["name"],
        "description": manifest["description"],
        "compose": {
            "files": files,
            "gpuFiles": [],
            "profiles": list(base.compose["profiles"]),
            "resetServices": list(dict.fromkeys(base.compose["resetServices"] + extra_resets)),
            "waitTimeout": wait_timeout,
        },
        "nodes": {},
        "requirements": base.requirements,
        "data": base.data + own_data,
        "shared": [],
        "evidence": dict(base.manifest["evidence"]),
    }
    deployment = Deployment(root, directory, merged, base=base)
    deployment.compose_files(False)
    deployment.env_files()
    return deployment


def root_path() -> Path:
    raw = os.environ.get("OPENADKIT_ROOT")
    if not raw:
        raise OpenADKitError(
            "OPENADKIT_ROOT is not set; invoke the root ./openadkit entrypoint"
        )
    root = Path(raw)
    if root.is_symlink() or not root.is_dir():
        raise OpenADKitError(f"unsafe Open AD Kit root: {root}")
    return root.resolve()


def _parse_component_images(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise OpenADKitError("componentImages must be a nonempty object")
    images: dict[str, str] = {}
    for name, target in value.items():
        if not ENV_NAME_RE.fullmatch(name) or not isinstance(target, str) or not target:
            raise OpenADKitError(
                "componentImages must map environment names to bake targets"
            )
        if not NAME_RE.fullmatch(target):
            raise OpenADKitError(f"invalid component image target: {target}")
        images[name] = target
    return images


def _parse_deployment_refs(value: Any, kind: str) -> dict[str, DeploymentRef]:
    if not isinstance(value, dict) or not value:
        raise OpenADKitError("deployments must be a nonempty object")
    refs: dict[str, DeploymentRef] = {}
    for name, entry in value.items():
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise OpenADKitError(f"invalid deployment name: {name}")
        if not isinstance(entry, dict):
            raise OpenADKitError(f"deployments.{name} must be an object")
        reject_unknown(entry, ALLOWED_DEPLOYMENT_REF_KEYS, f"deployments.{name}")
        path = require_string(entry.get("path"), f"deployments.{name}.path")
        safe_relative(path, f"deployments.{name}.path")
        checksum = entry.get("checksum")
        if kind == "release":
            checksum = require_string(checksum, f"deployments.{name}.checksum")
            if not SHA256_RE.fullmatch(checksum):
                raise OpenADKitError(f"deployments.{name}.checksum is invalid")
        elif checksum is not None:
            raise OpenADKitError("repository deployments must not declare checksums")
        refs[name] = DeploymentRef(path=path, checksum=checksum)
    return refs


def _parse_artifacts(value: Any, component_images: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Images we pin but do not build: one ref, or one ref per ROS distro."""
    if not isinstance(value, dict):
        raise OpenADKitError("artifacts must be an object")
    for name, artifact in value.items():
        where = f"artifacts.{name}"
        if not ENV_NAME_RE.fullmatch(name):
            raise OpenADKitError(f"invalid artifact name: {name}")
        if name in component_images:
            raise OpenADKitError(f"{where} is already a component image")
        if not isinstance(artifact, dict):
            raise OpenADKitError(f"{where} must be an object")
        reject_unknown(artifact, ALLOWED_ARTIFACT_KEYS, where)
        workload = require_string(artifact.get("workload"), f"{where}.workload")
        if not NAME_RE.fullmatch(workload):
            raise OpenADKitError(f"invalid {where}.workload: {workload}")
        if ("ref" in artifact) == ("distros" in artifact):
            raise OpenADKitError(f"{where} needs exactly one of ref or distros")
        # `ref` serves every distro; `distros` names each one.
        references = (
            {"*": artifact["ref"]} if "ref" in artifact else artifact["distros"]
        )
        if not isinstance(references, dict) or not references:
            raise OpenADKitError(f"{where}.distros must be a nonempty object")
        for distro, reference in references.items():
            if "ref" not in artifact and not NAME_RE.fullmatch(distro):
                raise OpenADKitError(f"invalid ROS distro in {where}: {distro}")
            if not isinstance(reference, str) or not IMAGE_REFERENCE_RE.fullmatch(reference):
                raise OpenADKitError(f"{where} must use digest-pinned image references")
    return value


def _parse_autoware(value: Any, kind: str) -> dict[str, str] | None:
    if value is None:
        if kind == "release":
            raise OpenADKitError("release bundles must declare autoware")
        return None
    if kind != "release":
        raise OpenADKitError("repository bundles must not declare autoware")
    if not isinstance(value, dict):
        raise OpenADKitError("autoware must be an object")
    reject_unknown(value, {"version", "ref", "lockSha256", "backports"}, "autoware")
    for field in ("version", "ref", "lockSha256"):
        require_string(value.get(field), f"autoware.{field}")
    backports = value.get("backports", [])
    if not isinstance(backports, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("upstream"), str) for item in backports
    ):
        raise OpenADKitError("autoware.backports must list fixes with their upstream URL")
    return value


def _require_checksum_map(value: Any, where: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(name, str)
        or not isinstance(checksum, str)
        or not SHA256_RE.fullmatch(checksum)
        for name, checksum in value.items()
    ):
        raise OpenADKitError(f"{where} must map names to SHA-256 checksums")
    return value


def install_root() -> Path:
    """Where `openadkit install` puts versioned releases."""
    explicit = os.environ.get("OPENADKIT_INSTALL_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path(expand_home("$HOME")) / ".local/share/openadkit"


def resolve_extends(kit_root: Path, extends: str) -> Path:
    """The Open AD Kit a kit pins: an installed release tag or, while
    developing, a path to a source checkout."""
    if RELEASE_TAG_RE.fullmatch(extends):
        candidate = install_root() / f"openadkit-{extends}"
        if not (candidate / "openadkit.json").is_file():
            raise OpenADKitError(
                f"this kit extends Open AD Kit {extends}, which is not installed; "
                f"run: openadkit install --version {extends}"
            )
        candidate = candidate.resolve()
    else:
        candidate = (kit_root / Path(extends).expanduser()).resolve()
        if not (candidate / "openadkit.json").is_file():
            raise OpenADKitError(f"extends does not point to an Open AD Kit: {extends}")
    if load_json(candidate / "openadkit.json").get("kind") == "kit":
        raise OpenADKitError(
            f"{candidate} is itself a kit; only one level of extends is supported"
        )
    return candidate


def _load_integrator_kit(root: Path, value: dict[str, Any]) -> RuntimeContext:
    reject_unknown(value, ALLOWED_INTEGRATOR_KIT_KEYS, "kit")
    extends = require_string(value.get("extends"), "extends")
    base_root = resolve_extends(root, extends)
    base = load_kit(base_root)
    # A kit artifact may reuse a component image name to replace that component.
    own_artifacts = _parse_artifacts(value.get("artifacts", {}), {})
    artifacts = dict(base.artifacts)
    for name, artifact in own_artifacts.items():
        if name in artifacts and "distros" in artifact:
            inherited = artifacts[name]
            artifacts[name] = {
                **inherited, **artifact,
                "distros": {**inherited.get("distros", {}), **artifact["distros"]},
            }
        else:
            artifacts[name] = artifact
    return RuntimeContext(
        kind="kit",
        default_ros_distro=base.default_ros_distro,
        version=None,
        image_prefix_component=base.image_prefix_component,
        component_images=base.component_images,
        images=base.images,
        deployments=_parse_deployment_refs(value.get("deployments"), "kit"),
        shared={},
        artifacts=artifacts,
        autoware=base.autoware,
        extends=extends,
        base=base,
        base_root=base_root,
    )


def load_kit(root: Path) -> RuntimeContext:
    value = load_json(ensure_safe_existing(root, "openadkit.json", "bundle manifest"))
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise OpenADKitError(
            f"unsupported openadkit.json schemaVersion {value.get('schemaVersion')!r} "
            f"(expected {SCHEMA_VERSION})"
        )
    if value.get("kind") == "kit":
        return _load_integrator_kit(root, value)
    reject_unknown(value, ALLOWED_KIT_KEYS, "bundle")
    if value.get("kind") not in ("repository", "release"):
        raise OpenADKitError("invalid Open AD Kit bundle manifest")
    default_ros_distro = require_string(
        value.get("defaultRosDistro", "humble"), "defaultRosDistro"
    )
    kind = value["kind"]
    component_images = _parse_component_images(value.get("componentImages"))
    prefix: str | None = None
    images: dict[str, dict[str, str]] = {}
    if kind == "repository":
        prefix = require_string(
            value.get("imagePrefixComponent"), "imagePrefixComponent"
        )
        if "images" in value:
            raise OpenADKitError("repository bundles must not declare release images")
    else:
        if "imagePrefixComponent" in value:
            raise OpenADKitError("release bundles must not declare imagePrefixComponent")
        raw_images = value.get("images")
        if not isinstance(raw_images, dict):
            raise OpenADKitError("images must be an object")
        for distro, distro_images in raw_images.items():
            if not isinstance(distro, str) or not NAME_RE.fullmatch(distro):
                raise OpenADKitError(f"invalid ROS distro in images: {distro}")
            if not isinstance(distro_images, dict) or any(
                not isinstance(target, str)
                or not target
                or not isinstance(reference, str)
                or not IMAGE_REFERENCE_RE.fullmatch(reference)
                for target, reference in distro_images.items()
            ):
                raise OpenADKitError(
                    f"images.{distro} must map targets to digest-pinned image references"
                )
            images[distro] = distro_images
    version = value.get("version")
    if version is not None:
        version = require_string(version, "version")
    elif kind == "release":
        raise OpenADKitError("release bundles must declare version")
    return RuntimeContext(
        kind=kind,
        default_ros_distro=default_ros_distro,
        version=version,
        image_prefix_component=prefix,
        component_images=component_images,
        images=images,
        deployments=_parse_deployment_refs(value.get("deployments"), kind),
        shared=_require_checksum_map(value.get("shared", {}), "shared"),
        artifacts=_parse_artifacts(value.get("artifacts", {}), component_images),
        autoware=_parse_autoware(value.get("autoware"), kind),
    )


def available_deployments(kit: RuntimeContext) -> str:
    return ", ".join(kit.deployments)


def get_deployment(root: Path, kit: RuntimeContext, name: str) -> Deployment:
    available = available_deployments(kit)
    if not NAME_RE.fullmatch(name):
        raise OpenADKitError(
            f"invalid deployment name: {name}\navailable: {available}"
        )
    try:
        reference = kit.deployments[name]
    except KeyError as error:
        raise OpenADKitError(
            f"unknown deployment: {name}\navailable: {available}"
        ) from error
    directory = root.joinpath(*safe_relative(reference.path, "deployment path").parts)
    if kit.base is not None:
        assert kit.base_root is not None
        deployment = validate_kit_deployment(root, directory, kit.base, kit.base_root)
    else:
        deployment = validate_manifest(root, directory)
    if deployment.name != name:
        raise OpenADKitError(
            f"deployment {name} path does not match manifest name {deployment.name}"
        )
    return deployment


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deployment_checksum(directory: Path, *, exclude_dirs: tuple[str, ...] = ()) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(
        directory.rglob("*"),
        key=lambda path: path.relative_to(directory).as_posix(),
    ):
        relative = candidate.relative_to(directory)
        if (
            relative.name == "config.local.env"
            or any(part in exclude_dirs for part in relative.parts)
            or "__pycache__" in relative.parts
            or relative.suffix == ".pyc"
        ):
            continue
        if candidate.is_symlink():
            digest.update(
                f"000 symlink:{os.readlink(candidate)}  {relative.as_posix()}\n".encode()
            )
            continue
        if not candidate.is_file():
            continue
        mode = "755" if os.access(candidate, os.X_OK) else "644"
        digest.update(
            f"{mode} {sha256_file(candidate)}  {relative.as_posix()}\n".encode()
        )
    return digest.hexdigest()


def deployment_integrity(
    root: Path,
    deployment: Deployment,
    kit: RuntimeContext,
) -> str:
    if kit.kind != "release":
        return "source"
    expected = kit.deployments[deployment.name].checksum
    if expected != deployment_checksum(deployment.directory):
        return "modified"
    if not all(
        kit.shared.get(name) == deployment_checksum(root / "deployments" / name)
        for name in deployment.shared
    ):
        return "modified"
    return "intact"
