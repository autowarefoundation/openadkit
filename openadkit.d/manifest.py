"""Open AD Kit manifest, context, discovery, and checksum handling."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_REFERENCE_RE = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")

COMPONENT_IMAGE_TARGETS = {
    "LOCALIZATION_MAPPING_IMAGE": "localization-mapping",
    "PLANNING_CONTROL_IMAGE": "planning-control",
    "VEHICLE_SYSTEM_IMAGE": "vehicle-system",
    "API_IMAGE": "api",
    "VISUALIZER_IMAGE": "visualizer",
    "SIMULATOR_IMAGE": "simulator",
    "SENSING_PERCEPTION_IMAGE": "sensing-perception",
    "SENSING_PERCEPTION_GPU_IMAGE": "sensing-perception-cuda",
}

ALLOWED_ROOT_KEYS = {
    "schemaVersion",
    "name",
    "description",
    "compose",
    "requirements",
    "distroEnvironment",
    "data",
    "hooks",
    "shared",
}
ALLOWED_COMPOSE_KEYS = {
    "files",
    "gpuFiles",
    "profiles",
    "services",
    "verifyServices",
    "resetServices",
    "waitTimeout",
    "groups",
    "features",
}
ALLOWED_REQUIREMENT_KEYS = {
    "architectures",
    "rosDistros",
    "gpu",
    "gpuArchitectures",
    "requiredEnv",
}
ALLOWED_HOOK_KEYS = {"preflight", "verify"}
ALLOWED_GROUP_KEYS = {
    "services",
    "verifyServices",
    "architectures",
    "rosDistros",
    "requiredEnv",
}
ALLOWED_FEATURE_KEYS = {
    "services",
    "excludeServices",
    "verifyServices",
    "environment",
    "architectures",
    "rosDistros",
    "requiredEnv",
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
    "groups",
    "gpu",
}
ALLOWED_DATA_FILE_KEYS = {"path", "url", "sha256"}
ALLOWED_CONTEXT_KEYS = {
    "schemaVersion",
    "kind",
    "version",
    "defaultRosDistro",
    "imagePrefixComponent",
    "images",
    "deployments",
    "shared",
}


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


def require_environment(value: Any, where: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise OpenADKitError(f"{where} must be an object")
    if any(not ENV_NAME_RE.fullmatch(name) or not isinstance(item, str) for name, item in value.items()):
        raise OpenADKitError(f"{where} must map environment names to strings")
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
    *,
    executable: bool = False,
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
    if executable and not os.access(current, os.X_OK):
        raise OpenADKitError(f"{where} is not executable: {current}")
    return current


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise OpenADKitError(f"could not read environment file {path}: {error}") from error
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise OpenADKitError(f"invalid dotenv assignment at {path}:{number}")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not ENV_NAME_RE.fullmatch(name):
            raise OpenADKitError(f"invalid environment name at {path}:{number}: {name}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
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


def host_architecture() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


@dataclass(frozen=True)
class RuntimeContext:
    kind: str
    default_ros_distro: str
    version: str | None
    image_prefix_component: str | None
    images: dict[str, dict[str, str]]
    deployments: dict[str, str]
    shared: dict[str, str]

    def component_environment(
        self,
        ros_distro: str,
        gpu: bool,
    ) -> dict[str, str]:
        applicable = {
            name: target
            for name, target in COMPONENT_IMAGE_TARGETS.items()
            if gpu or name != "SENSING_PERCEPTION_GPU_IMAGE"
        }
        if self.kind == "repository":
            assert self.image_prefix_component is not None
            return {
                name: f"{self.image_prefix_component}:{target}-{ros_distro}"
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
    group: str | None
    features: tuple[str, ...]
    services: tuple[str, ...]
    verification_services: tuple[str, ...]
    injections: dict[str, str]
    environment: dict[str, str]


class Deployment:
    def __init__(self, root: Path, directory: Path, manifest: dict[str, Any]) -> None:
        self.root = root
        self.directory = directory
        self.manifest_path = directory / "openadkit.json"
        self.manifest = manifest
        self.name: str = manifest["name"]
        self.compose: dict[str, Any] = manifest["compose"]
        self.requirements: dict[str, Any] = manifest["requirements"]
        self.distro_environment: dict[str, dict[str, str]] = manifest["distroEnvironment"]
        self.data: list[dict[str, Any]] = manifest["data"]
        self.hooks: dict[str, str] = manifest["hooks"]
        self.shared: list[str] = manifest["shared"]
        self.project = f"openadkit-{self.name}"

    @property
    def env_files(self) -> list[Path]:
        result = [
            ensure_safe_existing(self.directory, "config.env", "environment file")
        ]
        for name in ("config.release.env", "config.local.env"):
            candidate = self.directory / name
            if candidate.exists() or candidate.is_symlink():
                result.append(
                    ensure_safe_existing(self.directory, name, "environment file")
                )
        return result

    @property
    def configuration_environment(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for path in self.env_files:
            values.update(parse_dotenv(path))
        values.update(os.environ)
        return values

    def compose_files(self, gpu: bool) -> list[Path]:
        names = list(self.compose["files"])
        if gpu:
            names.extend(self.compose["gpuFiles"])
        return [
            ensure_safe_existing(self.directory, name, "Compose file") for name in names
        ]

    def select(
        self,
        current_context: RuntimeContext,
        ros_distro: str | None,
        gpu: bool,
        group: str | None,
        features: list[str],
        *,
        require_group: bool = True,
    ) -> Selection:
        distro = ros_distro or current_context.default_ros_distro
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
        if gpu_requirement == "required" and not gpu:
            raise OpenADKitError(f"{self.name} requires --gpu")
        if gpu_requirement == "none" and gpu:
            raise OpenADKitError(f"{self.name} does not provide a GPU mode")
        if gpu and gpu_requirement == "optional" and not self.compose["gpuFiles"]:
            raise OpenADKitError(
                f"{self.name} declares optional GPU but has no GPU Compose file"
            )
        gpu_architectures = self.requirements.get("gpuArchitectures")
        if gpu and gpu_architectures is not None and architecture not in gpu_architectures:
            raise OpenADKitError(
                f"{self.name} GPU mode does not support {architecture}; expected "
                f"{', '.join(gpu_architectures)}"
            )

        groups = self.compose["groups"]
        if groups and not group and require_group:
            raise OpenADKitError(
                f"{self.name} requires --group ({', '.join(sorted(groups))})"
            )
        if group and group not in groups:
            raise OpenADKitError(f"unknown group for {self.name}: {group}")
        if len(features) != len(set(features)):
            raise OpenADKitError(f"duplicate feature for {self.name}")
        unknown_features = sorted(set(features) - set(self.compose["features"]))
        if unknown_features:
            raise OpenADKitError(
                f"unknown feature for {self.name}: {', '.join(unknown_features)}"
            )

        definitions: list[tuple[str, dict[str, Any]]] = []
        if group:
            definitions.append((f"group {group}", groups[group]))
        definitions.extend(
            (f"feature {feature}", self.compose["features"][feature])
            for feature in features
        )
        for label, definition in definitions:
            architectures = definition.get("architectures")
            if architectures is not None and architecture not in architectures:
                raise OpenADKitError(
                    f"{self.name} {label} does not support {architecture}; expected "
                    f"{', '.join(architectures)}"
                )
            distros = definition.get("rosDistros")
            if distros is not None and distro not in distros:
                raise OpenADKitError(
                    f"{self.name} {label} does not support ROS distro {distro}; expected "
                    f"{', '.join(distros)}"
                )

        if groups and not group:
            services: list[str] = []
        else:
            services = list(groups[group]["services"] if group else self.compose["services"])
        for feature in features:
            definition = self.compose["features"][feature]
            services.extend(item for item in definition["services"] if item not in services)
            excluded = set(definition["excludeServices"])
            services = [item for item in services if item not in excluded]
        if require_group and not services:
            raise OpenADKitError(f"selection for {self.name} contains no services")

        if not require_group and groups and not group:
            verification: list[str] = []
        elif group and "verifyServices" in groups[group]:
            verification = list(groups[group]["verifyServices"])
        elif "verifyServices" in self.compose:
            verification = list(self.compose["verifyServices"])
        else:
            verification = list(services)
        for feature in features:
            verification.extend(
                service
                for service in self.compose["features"][feature]["verifyServices"]
                if service not in verification
            )
        unavailable = sorted(set(verification) - set(services))
        if unavailable:
            raise OpenADKitError(
                "verification service(s) are not selected: " + ", ".join(unavailable)
            )

        required_environment = list(self.requirements["requiredEnv"])
        for _, definition in definitions:
            required_environment.extend(
                name
                for name in definition["requiredEnv"]
                if name not in required_environment
            )

        environment = self.configuration_environment
        injections: dict[str, str] = {"ROS_DISTRO": distro}
        injections.update(self.distro_environment.get(distro, {}))
        for feature in features:
            injections.update(self.compose["features"][feature]["environment"])
        component_environment = current_context.component_environment(distro, gpu)
        if current_context.kind == "repository":
            injections.update(
                {
                    name: environment.get(name) or reference
                    for name, reference in component_environment.items()
                }
            )
        else:
            injections.update(component_environment)
        injections["ROS_DISTRO"] = distro

        environment.update(injections)
        missing_environment = [
            name for name in required_environment if not environment.get(name)
        ]
        if missing_environment:
            raise OpenADKitError(
                "required environment variable(s) are missing: "
                + ", ".join(missing_environment)
            )

        return Selection(
            ros_distro=distro,
            gpu=gpu,
            group=group,
            features=tuple(features),
            services=tuple(services),
            verification_services=tuple(verification),
            injections=injections,
            environment=environment,
        )


def _validate_constraints(
    definition: dict[str, Any],
    where: str,
    declared_distros: set[str],
) -> None:
    for field in ("architectures", "rosDistros"):
        if field in definition:
            definition[field] = require_string_list(
                definition[field], f"{where}.{field}", nonempty=True
            )
    if "rosDistros" in definition:
        unknown = sorted(set(definition["rosDistros"]) - declared_distros)
        if unknown:
            raise OpenADKitError(
                f"{where}.rosDistros contains undeclared distros: {', '.join(unknown)}"
            )
    definition["requiredEnv"] = require_string_list(
        definition.get("requiredEnv", []), f"{where}.requiredEnv"
    )
    invalid = [name for name in definition["requiredEnv"] if not ENV_NAME_RE.fullmatch(name)]
    if invalid:
        raise OpenADKitError(
            f"{where}.requiredEnv contains invalid environment names: {', '.join(invalid)}"
        )


def validate_manifest(root: Path, directory: Path) -> Deployment:
    if directory.is_symlink() or not directory.is_dir():
        raise OpenADKitError(f"unsafe deployment directory: {directory}")
    manifest_path = ensure_safe_existing(
        directory, "openadkit.json", "deployment manifest"
    )
    manifest = load_json(manifest_path)
    reject_unknown(manifest, ALLOWED_ROOT_KEYS, "manifest")
    if manifest.get("schemaVersion") != 1:
        raise OpenADKitError("unsupported deployment schemaVersion (expected 1)")
    name = require_string(manifest.get("name"), "name")
    if not NAME_RE.fullmatch(name) or name != directory.name:
        raise OpenADKitError(
            f"manifest name must match deployment directory: {directory.name}"
        )
    require_string(manifest.get("description"), "description")

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
            set(requirements["gpuArchitectures"])
            - set(requirements["architectures"])
        )
        if unknown:
            raise OpenADKitError(
                "requirements.gpuArchitectures contains undeclared architectures: "
                + ", ".join(unknown)
            )
    _validate_constraints(requirements, "requirements", set(requirements["rosDistros"]))
    manifest["requirements"] = requirements

    distro_environment = manifest.get("distroEnvironment", {})
    if not isinstance(distro_environment, dict):
        raise OpenADKitError("distroEnvironment must be an object")
    unknown_distros = sorted(
        set(distro_environment) - set(requirements["rosDistros"])
    )
    if unknown_distros:
        raise OpenADKitError(
            "distroEnvironment contains undeclared distros: "
            + ", ".join(unknown_distros)
        )
    for distro, environment in distro_environment.items():
        distro_environment[distro] = require_environment(
            environment, f"distroEnvironment.{distro}"
        )
    manifest["distroEnvironment"] = distro_environment

    compose = manifest.get("compose")
    if not isinstance(compose, dict):
        raise OpenADKitError("compose must be an object")
    reject_unknown(compose, ALLOWED_COMPOSE_KEYS, "compose")
    for field in ("files", "gpuFiles", "profiles", "services", "resetServices"):
        compose[field] = require_string_list(compose.get(field, []), f"compose.{field}")
    if not compose["files"]:
        raise OpenADKitError("compose.files must not be empty")
    if "verifyServices" in compose:
        compose["verifyServices"] = require_string_list(
            compose["verifyServices"], "compose.verifyServices"
        )
    wait_timeout = compose.get("waitTimeout", 300)
    if not isinstance(wait_timeout, int) or isinstance(wait_timeout, bool) or wait_timeout <= 0:
        raise OpenADKitError("compose.waitTimeout must be a positive integer")
    compose["waitTimeout"] = wait_timeout

    groups = compose.get("groups", {})
    if not isinstance(groups, dict):
        raise OpenADKitError("compose.groups must be an object")
    if not groups and not compose["services"]:
        raise OpenADKitError(
            "compose.services must not be empty when compose.groups is empty"
        )
    for group_name, group in groups.items():
        if not NAME_RE.fullmatch(group_name) or not isinstance(group, dict):
            raise OpenADKitError(f"invalid compose group: {group_name}")
        reject_unknown(group, ALLOWED_GROUP_KEYS, f"group {group_name}")
        group["services"] = require_string_list(
            group.get("services"), f"group {group_name}.services", nonempty=True
        )
        if "verifyServices" in group:
            group["verifyServices"] = require_string_list(
                group["verifyServices"], f"group {group_name}.verifyServices"
            )
        _validate_constraints(
            group, f"group {group_name}", set(requirements["rosDistros"])
        )
    compose["groups"] = groups

    features = compose.get("features", {})
    if not isinstance(features, dict):
        raise OpenADKitError("compose.features must be an object")
    for feature_name, feature in features.items():
        if not NAME_RE.fullmatch(feature_name) or not isinstance(feature, dict):
            raise OpenADKitError(f"invalid compose feature: {feature_name}")
        reject_unknown(feature, ALLOWED_FEATURE_KEYS, f"feature {feature_name}")
        feature["services"] = require_string_list(
            feature.get("services", []), f"feature {feature_name}.services"
        )
        feature["excludeServices"] = require_string_list(
            feature.get("excludeServices", []),
            f"feature {feature_name}.excludeServices",
        )
        feature["verifyServices"] = require_string_list(
            feature.get("verifyServices", []),
            f"feature {feature_name}.verifyServices",
        )
        feature["environment"] = require_environment(
            feature.get("environment", {}), f"feature {feature_name}.environment"
        )
        _validate_constraints(
            feature, f"feature {feature_name}", set(requirements["rosDistros"])
        )
    compose["features"] = features
    manifest["compose"] = compose

    hooks = manifest.get("hooks", {})
    if not isinstance(hooks, dict):
        raise OpenADKitError("hooks must be an object")
    reject_unknown(hooks, ALLOWED_HOOK_KEYS, "hooks")
    for phase, relative in hooks.items():
        hook = ensure_safe_existing(
            directory,
            require_string(relative, f"hooks.{phase}"),
            f"{phase} hook",
            executable=True,
        )
        try:
            if re.search(rb"(^|\s)sudo(\s|$)", hook.read_bytes()):
                raise OpenADKitError(
                    f"deployment hooks must not invoke sudo: {hook}"
                )
        except OSError as error:
            raise OpenADKitError(f"could not inspect hook {hook}: {error}") from error
    manifest["hooks"] = hooks

    data = manifest.get("data", [])
    if not isinstance(data, list):
        raise OpenADKitError("data must be an array")
    names: set[str] = set()
    for index, resource in enumerate(data):
        where = f"data[{index}]"
        if not isinstance(resource, dict):
            raise OpenADKitError(f"{where} must be an object")
        reject_unknown(resource, ALLOWED_DATA_KEYS, where)
        resource_name = require_string(resource.get("name"), f"{where}.name")
        if resource_name in names:
            raise OpenADKitError(f"duplicate data resource: {resource_name}")
        names.add(resource_name)
        if resource.get("kind") not in ("zip", "files"):
            raise OpenADKitError(f"{where}.kind must be zip or files")
        require_string(resource.get("destinationEnv"), f"{where}.destinationEnv")
        if not ENV_NAME_RE.fullmatch(resource["destinationEnv"]):
            raise OpenADKitError(f"{where}.destinationEnv must be an environment name")
        if "gpu" in resource and not isinstance(resource["gpu"], bool):
            raise OpenADKitError(f"{where}.gpu must be a boolean")
        resource["requiredFiles"] = require_string_list(
            resource.get("requiredFiles", []), f"{where}.requiredFiles"
        )
        resource["groups"] = require_string_list(
            resource.get("groups", []), f"{where}.groups"
        )
        unknown_groups = sorted(set(resource["groups"]) - set(groups))
        if unknown_groups:
            raise OpenADKitError(
                f"{where}.groups contains unknown groups: {', '.join(unknown_groups)}"
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
                require_string(item.get("url"), f"{file_where}.url")
                checksum = require_string(item.get("sha256"), f"{file_where}.sha256")
                if not SHA256_RE.fullmatch(checksum):
                    raise OpenADKitError(f"{file_where}.sha256 is invalid")
    manifest["data"] = data

    deployment = Deployment(root, directory, manifest)
    deployment.compose_files(False)
    if compose["gpuFiles"]:
        deployment.compose_files(True)
    deployment.env_files
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


def discover(root: Path) -> dict[str, Path]:
    deployments = root / "deployments"
    if deployments.is_symlink() or not deployments.is_dir():
        raise OpenADKitError(
            f"deployment directory is missing or unsafe: {deployments}"
        )
    found: dict[str, Path] = {}
    for candidate in sorted(deployments.iterdir()):
        if (
            candidate.is_symlink()
            or not candidate.is_dir()
            or not NAME_RE.fullmatch(candidate.name)
        ):
            continue
        manifest = candidate / "openadkit.json"
        if manifest.is_file() and not manifest.is_symlink():
            found[candidate.name] = candidate
    return found


def get_deployment(root: Path, name: str) -> Deployment:
    if not NAME_RE.fullmatch(name):
        raise OpenADKitError(f"invalid deployment name: {name}")
    try:
        directory = discover(root)[name]
    except KeyError as error:
        raise OpenADKitError(f"unknown deployment: {name}") from error
    return validate_manifest(root, directory)


def _require_checksum_map(value: Any, where: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(name, str)
        or not isinstance(checksum, str)
        or not SHA256_RE.fullmatch(checksum)
        for name, checksum in value.items()
    ):
        raise OpenADKitError(f"{where} must map names to SHA-256 checksums")
    return value


def load_context(root: Path) -> RuntimeContext:
    value = load_json(
        ensure_safe_existing(root / "openadkit.d", "context.json", "context manifest")
    )
    reject_unknown(value, ALLOWED_CONTEXT_KEYS, "context")
    if value.get("schemaVersion") != 1 or value.get("kind") not in (
        "repository",
        "release",
    ):
        raise OpenADKitError("invalid Open AD Kit context manifest")
    default_ros_distro = require_string(
        value.get("defaultRosDistro", "humble"), "context.defaultRosDistro"
    )
    kind = value["kind"]
    prefix: str | None = None
    images: dict[str, dict[str, str]] = {}
    if kind == "repository":
        prefix = require_string(
            value.get("imagePrefixComponent"), "context.imagePrefixComponent"
        )
    else:
        raw_images = value.get("images")
        if not isinstance(raw_images, dict):
            raise OpenADKitError("context.images must be an object")
        for distro, distro_images in raw_images.items():
            if not isinstance(distro, str) or not NAME_RE.fullmatch(distro):
                raise OpenADKitError(f"invalid ROS distro in context.images: {distro}")
            if not isinstance(distro_images, dict) or any(
                not isinstance(target, str)
                or not target
                or not isinstance(reference, str)
                or not IMAGE_REFERENCE_RE.fullmatch(reference)
                for target, reference in distro_images.items()
            ):
                raise OpenADKitError(
                    f"context.images.{distro} must map targets to digest-pinned image references"
                )
            images[distro] = distro_images
    version = value.get("version")
    if version is not None:
        version = require_string(version, "context.version")
    return RuntimeContext(
        kind=kind,
        default_ros_distro=default_ros_distro,
        version=version,
        image_prefix_component=prefix,
        images=images,
        deployments=_require_checksum_map(
            value.get("deployments", {}), "context.deployments"
        ),
        shared=_require_checksum_map(value.get("shared", {}), "context.shared"),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deployment_checksum(directory: Path) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(
        directory.rglob("*"),
        key=lambda path: path.relative_to(directory).as_posix(),
    ):
        relative = candidate.relative_to(directory)
        if (
            relative.name == "config.local.env"
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


def is_verified(
    root: Path,
    deployment: Deployment,
    current_context: RuntimeContext,
) -> bool:
    if current_context.kind == "release":
        expected = current_context.deployments.get(deployment.name)
        actual = deployment_checksum(deployment.directory)
        if expected != actual:
            return False
        return all(
            current_context.shared.get(name)
            == deployment_checksum(root / "deployments" / name)
            for name in deployment.shared
        )
    try:
        relative = deployment.manifest_path.relative_to(root)
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", str(relative)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if tracked.returncode != 0:
            return False
        paths = [deployment.directory.relative_to(root)]
        paths.extend(
            (root / "deployments" / name).relative_to(root)
            for name in deployment.shared
        )
        status = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                *(str(path) for path in paths),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return status.returncode == 0 and not status.stdout
    except (OSError, ValueError):
        return False
