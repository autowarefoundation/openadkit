"""Open AD Kit manifest files: reading and validating them."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import urllib.parse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
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
ALLOWED_ARTIFACT_KEYS = {"ref", "distros"}
# An integrator kit: its own deployments on top of one pinned Open AD Kit.
ALLOWED_INTEGRATOR_KIT_KEYS = {"schemaVersion", "kind", "extends", "deployments", "artifacts"}
ALLOWED_INTEGRATOR_DEPLOYMENT_KEYS = {
    "schemaVersion", "name", "description", "base", "compose", "data", "verify",
}
ALLOWED_INTEGRATOR_COMPOSE_KEYS = {"files", "resetServices", "waitTimeout"}
_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
# Strict SemVer release tag; must agree with the launcher (test_release_versions.py).
VERSION_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    rf"(?:-({_IDENTIFIER}(?:\.{_IDENTIFIER})*))?$"
)
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
    "verify",
}
# What `run --verify` runs once the deployment is ready: a command in a running
# service, or, without one, that service's own exit.
ALLOWED_VERIFY_KEYS = {"service", "command"}
ALLOWED_COMPOSE_KEYS = {
    "files",
    "gpuFiles",
    "profiles",
    "resetServices",
    "waitTimeout",
}
ALLOWED_NODE_KEYS = {
    "files",
    "resetServices",
    "requiredEnv",
    "requiredFiles",
    "rosDomainId",
}
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


def require_url(value: Any, where: str) -> str:
    url = require_string(value, where)
    parsed = urllib.parse.urlsplit(url)
    # file: serves a local mirror; anything else would fail only at fetch.
    if parsed.scheme not in ("http", "https", "file") or (parsed.scheme != "file" and not parsed.netloc):
        raise OpenADKitError(f"{where} must be an http, https or file URL: {url}")
    return url


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_data(data: Any, nodes: dict[str, Any], directory: Path) -> list[dict[str, Any]]:
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
            require_url(resource.get("url"), f"{where}.url")
            checksum = require_string(resource.get("sha256"), f"{where}.sha256")
            if not SHA256_RE.fullmatch(checksum):
                raise OpenADKitError(f"{where}.sha256 is invalid")
            # The archive's single top-level directory, which data.py extracts.
            expected_root = safe_relative(
                require_string(resource.get("expectedRoot"), f"{where}.expectedRoot"),
                f"{where}.expectedRoot",
            )
            if len(expected_root.parts) != 1:
                raise OpenADKitError(f"{where}.expectedRoot must be one directory name")
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
                    require_url(item["url"], f"{file_where}.url")
                else:
                    item["sourcePath"] = ensure_safe_existing(
                        directory, item["source"], f"{file_where}.source"
                    )
                checksum = require_string(item.get("sha256"), f"{file_where}.sha256")
                if not SHA256_RE.fullmatch(checksum):
                    raise OpenADKitError(f"{file_where}.sha256 is invalid")
                # A shipped file is part of the deployment: check it with the
                # manifest, so validate and release packaging catch a mismatch
                # before any user fetches it.
                if "sourcePath" in item and sha256_file(item["sourcePath"]) != checksum:
                    raise OpenADKitError(
                        f"{file_where}.source {item['source']} does not match its sha256"
                    )
    return data


def read_deployment_manifest(directory: Path, allowed_keys: set[str]) -> dict[str, Any]:
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


def validate_verify(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise OpenADKitError("verify must be an object")
    reject_unknown(value, ALLOWED_VERIFY_KEYS, "verify")
    verify: dict[str, Any] = {"service": require_string(value.get("service"), "verify.service")}
    if "command" in value:
        verify["command"] = require_string_list(value["command"], "verify.command", nonempty=True)
    return verify


def validate_wait_timeout(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise OpenADKitError("compose.waitTimeout must be a positive integer")
    return value


def validate_deployment_manifest(root: Path, directory: Path) -> dict[str, Any]:
    """A base deployment.json, checked and with its defaults filled in."""
    manifest = read_deployment_manifest(directory, ALLOWED_DEPLOYMENT_KEYS)

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
    compose["waitTimeout"] = validate_wait_timeout(compose.get("waitTimeout", 300))

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
    manifest["verify"] = validate_verify(manifest.get("verify"))

    data = validate_data(manifest.get("data", []), nodes, directory)
    manifest["data"] = data
    return manifest


@dataclass(frozen=True)
class DeploymentRef:
    path: str
    checksum: str | None


def parse_component_images(value: Any) -> dict[str, str]:
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


def parse_deployment_refs(value: Any, kind: str) -> dict[str, DeploymentRef]:
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


def parse_artifacts(value: Any, component_images: dict[str, str]) -> dict[str, dict[str, Any]]:
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


def parse_autoware(value: Any, kind: str) -> dict[str, str] | None:
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


def require_checksum_map(value: Any, where: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(name, str)
        or not isinstance(checksum, str)
        or not SHA256_RE.fullmatch(checksum)
        for name, checksum in value.items()
    ):
        raise OpenADKitError(f"{where} must map names to SHA-256 checksums")
    return value
