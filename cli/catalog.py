"""Which deployments a kit has, where they come from and where they keep files."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manifest import (
    ALLOWED_INTEGRATOR_COMPOSE_KEYS,
    ALLOWED_INTEGRATOR_DEPLOYMENT_KEYS,
    ALLOWED_INTEGRATOR_KIT_KEYS,
    ALLOWED_KIT_KEYS,
    DEVEL_IMAGE_TARGET,
    GPU_COMPONENT_IMAGE,
    IMAGE_REFERENCE_RE,
    NAME_RE,
    SCHEMA_VERSION,
    VERSION_RE,
    DeploymentRef,
    OpenADKitError,
    ensure_safe_existing,
    load_json,
    parse_artifacts,
    parse_autoware,
    parse_component_images,
    parse_deployment_refs,
    read_deployment_manifest,
    reject_unknown,
    require_checksum_map,
    require_string,
    require_string_list,
    safe_relative,
    sha256_file,
    validate_data,
    validate_deployment_manifest,
    validate_verify,
    validate_wait_timeout,
)


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
    """The CLI's own files, such as the empty directory for an absent layer."""
    return _user_root("OPENADKIT_STATE_DIR", "XDG_STATE_HOME", ".local/state")


def output_root() -> Path:
    """What runs produce, where the user looks: ``<deployment>/{results,recordings}``."""
    explicit = os.environ.get("OPENADKIT_OUTPUT_DIR")
    return Path(explicit).expanduser() if explicit else Path(expand_home("$HOME")) / "openadkit-output"


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


def install_root() -> Path:
    """Where `openadkit install` puts versioned releases."""
    explicit = os.environ.get("OPENADKIT_INSTALL_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path(expand_home("$HOME")) / ".local/share/openadkit"


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
    # Pinned images we consume rather than build: name -> {ref or distros}.
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
        # Kept for provenance and the inherited reset services.
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
        self.verify: dict[str, Any] | None = manifest["verify"]
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
        # A kit's ROS packages serve all of its deployments, so its one
        # workspace lives at the kit root.
        self.overlay_paths: dict[str, Path | None] = {
            "OPENADKIT_CONFIG_SHARED": (
                owner.root / "deployments/shared/config" if "shared" in owner.shared else None
            ),
            "OPENADKIT_CONFIG_BASE": base.directory / "config" if base else None,
            "OPENADKIT_CONFIG_DEPLOYMENT": directory / "config",
            "OPENADKIT_OVERLAY_WS": (root if base and base.root != root else directory) / "overlay_ws",
        }
        self.kit_environment = {
            "OPENADKIT_BASE_ROOT": str(base.root),
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
        return output_root() / self.name

    @property
    def workspace(self) -> Path:
        workspace = self.overlay_paths["OPENADKIT_OVERLAY_WS"]
        assert workspace is not None
        return workspace

    def use_workspace(self, path: Path) -> None:
        """Mount a workspace built elsewhere (run --ws) as the overlay workspace."""
        if (self.workspace / "src").is_dir():
            raise OpenADKitError(
                f"{self.name} has its own overlay workspace ({self.workspace}); "
                "--ws is for a deployment without one"
            )
        if not (path / "install/local_setup.bash").is_file():
            raise OpenADKitError(f"{path} is not built; run: openadkit build {path}")
        self.overlay_paths["OPENADKIT_OVERLAY_WS"] = path

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


def _load_deployment(root: Path, directory: Path) -> Deployment:
    manifest = validate_deployment_manifest(root, directory)
    compose, nodes = manifest["compose"], manifest["nodes"]
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


def _load_kit_deployment(
    root: Path, directory: Path, base_kit: RuntimeContext, base_root: Path
) -> Deployment:
    """An integrator deployment: its own Compose file and values on top of a
    base deployment from the pinned kit, whose requirements it keeps as is."""
    manifest = read_deployment_manifest(directory, ALLOWED_INTEGRATOR_DEPLOYMENT_KEYS)
    base_name = require_string(manifest.get("base"), "base")
    if base_name not in base_kit.deployments:
        raise OpenADKitError(
            f"base deployment {base_name} is not in the pinned kit; "
            f"available: {available_deployments(base_kit)}"
        )
    if declares_base(base_root, base_kit, base_name):
        raise OpenADKitError(f"base deployment {base_name} has a base of its own")
    base = get_deployment(base_root, base_kit, base_name)

    compose = manifest.get("compose")
    if not isinstance(compose, dict):
        raise OpenADKitError("compose must be an object")
    reject_unknown(compose, ALLOWED_INTEGRATOR_COMPOSE_KEYS, "compose")
    files = require_string_list(compose.get("files"), "compose.files", nonempty=True)
    extra_resets = require_string_list(compose.get("resetServices", []), "compose.resetServices")
    wait_timeout = validate_wait_timeout(compose.get("waitTimeout", base.compose["waitTimeout"]))

    own_data = validate_data(manifest.get("data", []), {}, directory)
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
        # The base's verify step runs on top of this layer unless it names its own.
        "verify": validate_verify(manifest.get("verify")) or base.verify,
    }
    deployment = Deployment(root, directory, merged, base=base)
    deployment.compose_files(False)
    deployment.env_files()
    return deployment


def resolve_extends(kit_root: Path, extends: str) -> Path:
    """The Open AD Kit a kit pins: an installed release tag or, while
    developing, a path to a source checkout."""
    if VERSION_RE.fullmatch(extends):
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
    own_artifacts = parse_artifacts(value.get("artifacts", {}), {})
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
        deployments=parse_deployment_refs(value.get("deployments"), "kit"),
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
    component_images = parse_component_images(value.get("componentImages"))
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
        deployments=parse_deployment_refs(value.get("deployments"), kind),
        shared=require_checksum_map(value.get("shared", {}), "shared"),
        artifacts=parse_artifacts(value.get("artifacts", {}), component_images),
        autoware=parse_autoware(value.get("autoware"), kind),
    )


def available_deployments(kit: RuntimeContext) -> str:
    return ", ".join(kit.deployments)


def declares_base(root: Path, kit: RuntimeContext, name: str) -> bool:
    directory = root.joinpath(*safe_relative(kit.deployments[name].path, "deployment path").parts)
    manifest = directory / "deployment.json"
    return manifest.is_file() and not manifest.is_symlink() and "base" in load_json(manifest)


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
        deployment = _load_kit_deployment(root, directory, kit.base, kit.base_root)
    elif declares_base(root, kit, name):
        # A deployment on another of the same catalog, as a kit's is on its pinned kit.
        deployment = _load_kit_deployment(root, directory, kit, root)
    else:
        deployment = _load_deployment(root, directory)
    if deployment.name != name:
        raise OpenADKitError(
            f"deployment {name} path does not match manifest name {deployment.name}"
        )
    return deployment


def deployment_checksum(directory: Path, *, exclude_dirs: tuple[str, ...] = ()) -> str:
    digest = hashlib.sha256()
    for candidate in sorted(
        directory.rglob("*"),
        key=lambda path: path.relative_to(directory).as_posix(),
    ):
        relative = candidate.relative_to(directory)
        if (
            any(part in exclude_dirs for part in relative.parts)
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
    if deployment.base is not None and deployment.base.root == root:
        return deployment_integrity(root, deployment.base, kit)
    return "intact"
