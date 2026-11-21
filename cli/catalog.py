"""Which deployments a kit has, where they come from and where they keep files."""

from __future__ import annotations

import hashlib
import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manifest import (
    ALLOWED_BASE_KEYS,
    ALLOWED_KIT_DEPLOYMENT_KEYS,
    ALLOWED_KIT_KEYS,
    DEVEL_IMAGE_TARGET,
    ENTRY_COMPOSE_FILE,
    GPU_COMPONENT_IMAGE_SUFFIX,
    IMAGE_REFERENCE_RE,
    NAME_RE,
    SCHEMA_VERSION,
    VERSION_RE,
    DeploymentRef,
    OpenADKitError,
    compose_layout,
    ensure_safe_existing,
    load_json,
    narrow_requirements,
    parse_autoware,
    parse_component_images,
    parse_deployment_refs,
    parse_external_images,
    reject_unknown,
    require_checksum_map,
    require_string,
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


def openadkit_home() -> Path | None:
    """OPENADKIT_HOME, when set: one directory for everything Open AD Kit keeps,
    such as for a run isolated from the user's own files."""
    raw = os.environ.get("OPENADKIT_HOME")
    if not raw:
        return None
    home = Path(expand_home(raw)).expanduser()
    if not home.is_absolute():
        raise OpenADKitError(f"OPENADKIT_HOME must be an absolute path: {raw}")
    return home


def _user_root(part: str, xdg: str, fallback: str) -> Path:
    """An Open AD Kit root outside the release, so upgrades keep it."""
    home = openadkit_home()
    if home is not None:
        return home / part
    base = os.environ.get(xdg) or str(Path(expand_home("$HOME")) / fallback)
    return Path(base) / "openadkit"


def _home_root(part: str, default: str) -> Path:
    """A root the user looks into, under the home directory by default."""
    home = openadkit_home()
    return home / part if home is not None else Path(expand_home("$HOME")) / default


def settings_root() -> Path:
    """Host settings: one ``<deployment>.env`` per deployment."""
    return _user_root("settings", "XDG_CONFIG_HOME", ".config")


def state_root() -> Path:
    """The CLI's own files, such as the empty directory for an absent layer."""
    return _user_root("state", "XDG_STATE_HOME", ".local/state")


def output_root() -> Path:
    """What runs produce, where the user looks: ``<deployment>/{results,recordings}``."""
    return _home_root("output", "openadkit-output")


def data_root() -> Path:
    """Downloaded data, which the deployments' data paths build on."""
    return _home_root("data", "autoware_data")


def root_path() -> Path:
    raw = os.environ.get("OPENADKIT_ROOT")
    if not raw:
        raise OpenADKitError(
            "OPENADKIT_ROOT is not set; run the ./openadkit launcher"
        )
    root = Path(raw)
    if root.is_symlink() or not root.is_dir():
        raise OpenADKitError(f"unsafe Open AD Kit root: {root}")
    return root.resolve()


def host_architecture() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


# A tag of a CI build (<run id>-<attempt>) or of a release (vX.Y.Z).
BUILD_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def ci_build() -> tuple[str, str] | None:
    """OPENADKIT_BUILD=<image repository>:<build tag>: the one build a source
    checkout takes every image from, instead of a local build's."""
    raw = os.environ.get("OPENADKIT_BUILD")
    if not raw:
        return None
    repository, separator, tag = raw.rpartition(":")
    if not separator or not repository or "/" in tag or not BUILD_TAG_RE.fullmatch(tag):
        raise OpenADKitError(
            "OPENADKIT_BUILD must be <image repository>:<build tag>, such as "
            f"ghcr.io/autowarefoundation/openadkit:123456789-1; got {raw}"
        )
    return repository, tag


def install_root() -> Path:
    """Where `openadkit install` puts versioned releases; the launcher computes the same."""
    return _user_root("releases", "XDG_DATA_HOME", ".local/share")


@dataclass(frozen=True)
class Catalog:
    """A loaded openadkit.json: Open AD Kit itself (kind "source" or "release"),
    or a kit that extends it (kind "kit")."""

    kind: str
    default_ros_distro: str
    version: str | None
    image_repository: str | None
    component_images: dict[str, str]
    images: dict[str, dict[str, str]]
    deployments: dict[str, DeploymentRef]
    shared: dict[str, str]
    # Pinned images we consume rather than build: name -> {ref or distros}.
    external_images: dict[str, dict[str, Any]]
    # Release only: the Autoware version, commit and lock file it was built from.
    autoware: dict[str, str] | None = None
    # A kit only: the Open AD Kit it extends, as written in the manifest and loaded.
    extends: str | None = None
    extended: Catalog | None = None
    extended_root: Path | None = None

    @property
    def pinned(self) -> bool:
        """Release images cannot be overridden from env files; source images can."""
        return self.image_repository is None

    def devel_image(self, ros_distro: str) -> str | None:
        """The devel image of the build the runtime images come from: the one
        a release pins, or in a source checkout the local build's, or that of
        the CI build OPENADKIT_BUILD names."""
        if self.image_repository is None:
            return self.images.get(ros_distro, {}).get(DEVEL_IMAGE_TARGET)
        return self.source_image(DEVEL_IMAGE_TARGET, ros_distro, host_architecture())

    def source_image(self, target: str, ros_distro: str, architecture: str) -> str:
        """A source checkout's image of target: its local build's tag, or the
        one of the CI build OPENADKIT_BUILD names."""
        build = ci_build()
        if build is not None:
            repository, tag = build
            return f"{repository}:{target}-{ros_distro}-{tag}"
        return f"{self.image_repository}:{target}-{architecture}-{ros_distro}"

    def bom(self) -> dict[str, Any]:
        """What this catalog runs: Autoware, component images and external images."""
        return {
            "autoware": self.autoware,
            "images": self.images or None,
            "externalImages": self.external_images,
        }

    def external_image_environment(self, ros_distro: str) -> dict[str, str]:
        """External image references for one distro; Compose requires them by name.

        In a kit its own external images come last, so one named like a
        component image replaces that component.
        """
        environment = {}
        for name, image in self.external_images.items():
            # A kit can have per-distro overrides and a fallback from what it extends.
            reference = image.get("distros", {}).get(ros_distro) or image.get("ref")
            if reference:
                environment[name] = reference
        return environment

    def component_environment(
        self, ros_distro: str, architecture: str, gpu: bool
    ) -> dict[str, str]:
        applicable = {
            name: target
            for name, target in self.component_images.items()
            if gpu or not name.endswith(GPU_COMPONENT_IMAGE_SUFFIX)
        }
        if self.image_repository is not None:
            return {
                name: self.source_image(target, ros_distro, architecture)
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
        names = [("settings.env", self.required)]
        if gpu:
            names.append(("settings.gpu.env", self.gpu_required))
        for name, required in names:
            candidate = self.directory / name
            if required or candidate.exists() or candidate.is_symlink():
                result.append(ensure_safe_existing(self.directory, name, "environment file"))
        return result


def holds_packages(workspace: Path) -> bool:
    """Whether a workspace's src/ holds a ROS package."""
    return next((workspace / "src").rglob("package.xml"), None) is not None


class Deployment:
    def __init__(
        self,
        root: Path,
        directory: Path,
        manifest: dict[str, Any],
        base: Deployment | None = None,
    ) -> None:
        self.root = root
        # Kept for provenance. Runtime layers below are resolved once; they
        # never delegate to base.
        self.base = base
        self.directory = directory
        self.manifest = manifest
        self.name: str = manifest["name"]
        self.compose: dict[str, Any] = manifest["compose"]
        self.roles: dict[str, dict[str, Any]] = manifest["roles"]
        self.requirements: dict[str, Any] = manifest["requirements"]
        self.data: list[dict[str, Any]] = manifest["data"]
        self.shared: list[str] = manifest["shared"]
        self.verify: dict[str, Any] | None = manifest["verify"]
        # A kit deployment that names no verify step runs its base's.
        self.verify_inherited = False
        # A kit only: the base's data resources that its own data replaces.
        self.replaced_data: list[dict[str, Any]] = []
        # Services that run once and exit, read from each Compose model (compose.one_shot_services).
        self.one_shots: dict[tuple[str | None, bool], set[str]] = {}
        # Why CI cannot produce evidence for this deployment, if it cannot.
        self.evidence_exemption: str | None = manifest["evidence"].get("exempt")
        self.project = f"openadkit-{self.name}"
        own_layer = EnvironmentLayer(directory, base is None, bool(self.compose["gpuFiles"]))
        # A kit's root holds what every deployment of it shares, between its
        # base and its own directory.
        kit_layers = (*base.env_layers, EnvironmentLayer(root, False, False)) if base else ()
        self.env_layers: tuple[EnvironmentLayer, ...] = (*kit_layers, own_layer)
        # A kit deployment that has no Compose file of its own runs its base's.
        own_compose = directory / ENTRY_COMPOSE_FILE
        self.compose_directory = (
            directory if base is None or own_compose.exists() or own_compose.is_symlink() else base.directory
        )
        # A kit's GPU files follow its entry Compose file.
        self.gpu_files: list[tuple[Path, str]] = [
            (directory, name) for name in self.compose["gpuFiles"]
        ] + (base.gpu_files if base else [])
        # A kit's ROS packages serve all of its deployments, so its one
        # workspace lives at the kit root.
        self.overlay_paths: dict[str, Path | None] = {
            "OPENADKIT_CONFIG_BASE": base.directory / "config" if base else None,
            "OPENADKIT_CONFIG_KIT": root / "config" if base else None,
            "OPENADKIT_CONFIG_DEPLOYMENT": directory / "config",
            "OPENADKIT_OVERLAY_WS": (root if base else directory) / "overlay_ws",
        }
        # What a kit's Compose files and settings name their paths with.
        self.kit_environment = {
            "OPENADKIT_ROOT": str(base.root),
            "OPENADKIT_BASE_DEPLOYMENT": str(base.directory),
            "OPENADKIT_KIT": str(root),
        } if base else {}

    def project_name(self, role: str | None = None) -> str:
        """Each role is its own Compose project, so roles never share state.

        Names never contain "_", so it separates the role unambiguously.
        """
        return self.project if role is None else f"{self.project}_{role}"

    @property
    def working_directory(self) -> Path:
        """Where its commands run: its own directory, which a kit deployment
        without files of its own does not have."""
        return self.directory if self.directory.is_dir() else self.root

    @property
    def host_settings(self) -> Path:
        """Host settings for this deployment; loaded last, kept across upgrades."""
        return settings_root() / f"{self.name}.env"

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
        if holds_packages(self.workspace):
            raise OpenADKitError(
                f"{self.name} has packages of its own in {self.workspace / 'src'}; "
                "--ws is for a deployment without any"
            )
        if not (path / "install/local_setup.bash").is_file():
            raise OpenADKitError(f"{path} is not built; run: openadkit build {path}")
        self.overlay_paths["OPENADKIT_OVERLAY_WS"] = path

    @property
    def has_gpu_files(self) -> bool:
        return bool(self.gpu_files)

    def env_files(self, gpu: bool = False) -> list[Path]:
        """Base env files, then this deployment's, then the host settings file."""
        result = [path for layer in self.env_layers for path in layer.files(gpu)]
        host_file = self.host_settings
        if host_file.exists():
            if not host_file.is_file():
                raise OpenADKitError(f"host settings file is not a regular file: {host_file}")
            result.append(host_file)
        return result

    def compose_files(self, gpu: bool, role: str | None = None) -> list[Path]:
        """Only explicitly selected files; each entrypoint owns its whole graph."""
        names = self.compose["files"] if role is None else self.roles[role]["files"]
        files = [
            ensure_safe_existing(self.compose_directory, name, "Compose file") for name in names
        ]
        if gpu:
            files.extend(
                ensure_safe_existing(directory, name, "Compose file")
                for directory, name in self.gpu_files
            )
        return files


def _load_base_deployment(root: Path, directory: Path, name: str) -> Deployment:
    manifest = validate_deployment_manifest(root, directory, name)
    compose, roles = manifest["compose"], manifest["roles"]
    deployment = Deployment(root, directory, manifest)
    deployment.compose_files(False)
    if compose["gpuFiles"]:
        deployment.compose_files(True)
        ensure_safe_existing(
            directory, "settings.gpu.env", "GPU settings file"
        )
    for role_name in roles:
        deployment.compose_files(False, role_name)
        if compose["gpuFiles"]:
            deployment.compose_files(True, role_name)
    deployment.env_files()
    return deployment


def _load_kit_deployment(
    root: Path, directory: Path, extended: Catalog, extended_root: Path, manifest: dict[str, Any]
) -> Deployment:
    """A kit deployment: the kit's files and its own on top of a base
    deployment of the Open AD Kit the kit extends, whose requirements it keeps
    or narrows. Its directory, deployments/<name>/, holds only what it alone
    needs, so it may be missing."""
    reject_unknown(manifest, ALLOWED_KIT_DEPLOYMENT_KEYS | {"name"}, f"deployments.{manifest['name']}")
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise OpenADKitError(f"unsafe deployment directory: {directory}")
    base_name = require_string(manifest.get("base"), "base")
    if base_name not in extended.deployments:
        raise OpenADKitError(
            f"unknown base deployment: {base_name}; "
            f"available: {available_deployments(extended)}"
        )
    base = get_deployment(extended_root, extended, base_name)

    # A kit's GPU mode is its base's: it adds no GPU overlay of its own.
    compose = compose_layout(
        directory, validate_wait_timeout(manifest.get("waitTimeout", base.compose["waitTimeout"])), gpu=False
    )
    requirements = narrow_requirements(base.requirements, manifest.get("requirements"))
    # Without a GPU mode it never mounts the data only that mode uses.
    base_data = [item for item in base.data if requirements["gpu"] != "none" or not item.get("gpu")]

    own_verify = validate_verify(manifest.get("verify"))
    # A file the kit ships as data is named from the kit root, where the manifest is.
    own_data = validate_data(manifest.get("data", []), {}, root)
    # Its own data replaces the base's with the same destination, as its
    # settings replace the base's: its own recording instead of the sample.
    replaced = {item["destinationEnv"] for item in own_data}
    replaced_data = [item for item in base_data if item["destinationEnv"] in replaced]
    base_data = [item for item in base_data if item["destinationEnv"] not in replaced]
    repeated = sorted({item["name"] for item in base_data} & {item["name"] for item in own_data})
    if repeated:
        raise OpenADKitError(
            "data reuses the name of a resource of the base deployment that it keeps: " + ", ".join(repeated)
        )

    merged = {
        "name": manifest["name"],
        "description": require_string(
            manifest.get("description", f"{base_name} with this kit's files on top"), "description"
        ),
        "compose": compose,
        "roles": {},
        "requirements": requirements,
        "data": base_data + own_data,
        "shared": [],
        "evidence": dict(base.manifest["evidence"]),
        # The base's verify step runs on top of this layer unless it names its own.
        "verify": own_verify or base.verify,
    }
    deployment = Deployment(root, directory, merged, base=base)
    deployment.verify_inherited = own_verify is None
    deployment.replaced_data = replaced_data
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
                "a command that acts on the kit, such as openadkit validate, downloads it"
            )
        candidate = candidate.resolve()
    else:
        candidate = (kit_root / Path(extends).expanduser()).resolve()
        if not (candidate / "openadkit.json").is_file():
            raise OpenADKitError(
                f"extends does not point to an Open AD Kit: {extends}; "
                "name a release as vX.Y.Z, or give the path of an Open AD Kit"
            )
    if load_json(candidate / "openadkit.json").get("kind") == "kit":
        raise OpenADKitError(
            f"{candidate} is itself a kit; only one level of extends is supported"
        )
    return candidate


def _load_kit(root: Path, value: dict[str, Any]) -> Catalog:
    reject_unknown(value, ALLOWED_KIT_KEYS, "kit manifest")
    extends = require_string(value.get("extends"), "extends")
    extended_root = resolve_extends(root, extends)
    extended = load_catalog(extended_root)
    # A kit's external image may reuse a component image name to replace that component.
    own_images = parse_external_images(value.get("externalImages", {}), {})
    external_images = dict(extended.external_images)
    for name, image in own_images.items():
        if name in external_images and "distros" in image:
            inherited = external_images[name]
            external_images[name] = {
                **inherited, **image,
                "distros": {**inherited.get("distros", {}), **image["distros"]},
            }
        else:
            external_images[name] = image
    deployments = parse_deployment_refs(value.get("deployments"), "kit")
    # A deployment's name keys its host settings file, output directory and
    # Compose project, so a kit's must not be one of the release's.
    taken = sorted(set(deployments) & set(extended.deployments))
    if taken:
        raise OpenADKitError(
            f"kit deployment {', '.join(taken)} has the name of a deployment of {extends}; give it another name"
        )
    return Catalog(
        kind="kit",
        default_ros_distro=extended.default_ros_distro,
        version=None,
        image_repository=extended.image_repository,
        component_images=extended.component_images,
        images=extended.images,
        deployments=deployments,
        shared={},
        external_images=external_images,
        autoware=extended.autoware,
        extends=extends,
        extended=extended,
        extended_root=extended_root,
    )


def load_catalog(root: Path) -> Catalog:
    value = load_json(ensure_safe_existing(root, "openadkit.json", "manifest"))
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise OpenADKitError(
            f"unsupported openadkit.json schemaVersion {value.get('schemaVersion')!r} "
            f"(expected {SCHEMA_VERSION})"
        )
    if value.get("kind") == "kit":
        return _load_kit(root, value)
    reject_unknown(value, ALLOWED_BASE_KEYS, "release manifest")
    if value.get("kind") not in ("source", "release"):
        raise OpenADKitError("openadkit.json kind must be source, release or kit")
    default_ros_distro = require_string(
        value.get("defaultRosDistro", "humble"), "defaultRosDistro"
    )
    kind = value["kind"]
    component_images = parse_component_images(value.get("componentImages"))
    prefix: str | None = None
    images: dict[str, dict[str, str]] = {}
    if kind == "source":
        prefix = require_string(
            value.get("imageRepository"), "imageRepository"
        )
        if "images" in value:
            raise OpenADKitError("a source checkout's openadkit.json must not declare release images")
    else:
        if "imageRepository" in value:
            raise OpenADKitError("release bundles must not declare imageRepository")
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
    return Catalog(
        kind=kind,
        default_ros_distro=default_ros_distro,
        version=version,
        image_repository=prefix,
        component_images=component_images,
        images=images,
        deployments=parse_deployment_refs(value.get("deployments"), kind),
        shared=require_checksum_map(value.get("shared", {}), "shared"),
        external_images=parse_external_images(value.get("externalImages", {}), component_images),
        autoware=parse_autoware(value.get("autoware"), kind),
    )


def default_ros_distro(catalog: Catalog, distros: list[str]) -> str:
    """The Open AD Kit's default distro, or the first of `distros` when they leave it out."""
    if not distros or catalog.default_ros_distro in distros:
        return catalog.default_ros_distro
    return distros[0]


def available_deployments(catalog: Catalog) -> str:
    return ", ".join(catalog.deployments)


def get_deployment(root: Path, catalog: Catalog, name: str) -> Deployment:
    available = available_deployments(catalog)
    if not NAME_RE.fullmatch(name):
        raise OpenADKitError(
            f"invalid deployment name: {name}\navailable: {available}"
        )
    try:
        reference = catalog.deployments[name]
    except KeyError as error:
        raise OpenADKitError(
            f"unknown deployment: {name}\navailable: {available}"
        ) from error
    directory = root.joinpath(*safe_relative(reference.path, "deployment path").parts)
    if catalog.extended is not None:
        assert catalog.extended_root is not None
        assert reference.entry is not None
        deployment = _load_kit_deployment(
            root, directory, catalog.extended, catalog.extended_root, dict(reference.entry)
        )
    else:
        deployment = _load_base_deployment(root, directory, name)
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


def deployment_modified(
    root: Path,
    deployment: Deployment,
    catalog: Catalog,
) -> bool | None:
    """Whether a release's deployment differs from the files the release came
    with. None where nothing vouches for the files: a source checkout or a kit."""
    if catalog.kind != "release":
        return None
    if catalog.deployments[deployment.name].checksum != deployment_checksum(deployment.directory):
        return True
    return not all(
        catalog.shared.get(name) == deployment_checksum(root / "deployments" / name)
        for name in deployment.shared
    )
