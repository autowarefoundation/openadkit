"""Validated download, extraction, and atomic data publication."""

from __future__ import annotations

import ctypes
import hashlib
import http.client
import json
import os
import shutil
import stat
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from manifest import (
    Deployment,
    OpenADKitError,
    Selection,
    expand_home,
    safe_relative,
    sha256_file,
)

# Marks a directory the CLI installed. Only marked data is replaced or deleted,
# so a data variable pointing at, say, $HOME can never lose user files.
MARKER = ".openadkit-resource.json"


class PublicationConflict(OpenADKitError):
    """The exchanged directory must not be removed by staging cleanup."""


@contextmanager
def resource_stage(parent: Path, name: str) -> Iterator[Path]:
    stage = Path(tempfile.mkdtemp(prefix=f".{name}.stage.", dir=parent))
    cleanup = True
    try:
        yield stage
    except PublicationConflict as error:
        cleanup = False
        raise OpenADKitError(f"{error}; staging preserved at {stage}") from error
    finally:
        if cleanup:
            shutil.rmtree(stage)


def is_managed(target: Path) -> bool:
    marker = target / MARKER
    return target.is_dir() and not marker.is_symlink() and marker.is_file()


def source_digest(resource: dict[str, Any]) -> str:
    """Identify the content a resource declares, so a changed declaration shows.

    Only checksums and generated content count: a mirror URL for the same bytes
    is the same data.
    """
    source = {
        "kind": resource["kind"],
        "sha256": resource.get("sha256"),
        "expectedRoot": resource.get("expectedRoot"),
        "files": sorted((item["path"], item["sha256"]) for item in resource.get("files", [])),
        "generatedFiles": resource.get("generatedFiles", {}),
    }
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()


def is_outdated(target: Path, resource: dict[str, Any]) -> bool:
    """Managed data installed from a different declaration than the current one."""
    if not is_managed(target):
        return False
    try:
        marker = json.loads((target / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # The CLI writes valid JSON: an unreadable marker says nothing about
        # what was installed, so the data cannot count as current.
        return True
    recorded = marker.get("source") if isinstance(marker, dict) else None
    if isinstance(recorded, str):
        return recorded != source_digest(resource)
    # Markers written before the source was recorded: plain files can still be
    # compared with their checksums; an extracted archive cannot.
    if resource["kind"] != "files":
        return False
    for item in resource["files"]:
        installed = target / safe_relative(item["path"], "data file path")
        if not installed.is_file() or sha256_file(installed) != item["sha256"]:
            return True
    return any(
        (target / relative).read_text(encoding="utf-8") != content
        for relative, content in resource.get("generatedFiles", {}).items()
        if (target / relative).is_file()
    )


def refuse_unmanaged(target: Path, action: str) -> None:
    if (target.exists() or target.is_symlink()) and not is_managed(target):
        raise OpenADKitError(
            f"refusing to {action} {target}: it was not installed by openadkit "
            f"(no {MARKER}); move or remove it yourself"
        )


def download(url: str, destination: Path, checksum: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "OpenADKit/1"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                request, timeout=60
            ) as response, destination.open("wb") as output:
                size = response.headers.get("Content-Length")
                expected = int(size) if size and size.isdigit() else None
                if expected is not None:
                    print(f"downloading {url} ({expected} bytes)", flush=True)
                else:
                    print(f"downloading {url}", flush=True)
                shutil.copyfileobj(response, output)
            # urllib ends a cut-off body without an error; retry a short file.
            received = destination.stat().st_size
            if expected is not None and received != expected:
                raise OSError(f"received {received} of {expected} bytes")
        except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
            last_error = error
            destination.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(1 + attempt)
            continue
        # A complete file with the wrong content does not improve on retry.
        if sha256_file(destination) != checksum:
            destination.unlink(missing_ok=True)
            raise OpenADKitError(f"checksum mismatch for {url}")
        return
    raise OpenADKitError(f"failed to download {url}: {last_error}")


def copy_verified(source: Path, destination: Path, checksum: str) -> None:
    """Install a file the deployment ships, if it is the one its manifest pins."""
    if sha256_file(source) != checksum:
        raise OpenADKitError(f"checksum mismatch for {source}")
    shutil.copyfile(source, destination)


def ensure_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        # Root-owned links are host layout (a relocated /home); a link anyone
        # else made could redirect data writes and removals.
        if current.is_symlink() and current.lstat().st_uid != 0:
            raise OpenADKitError(f"symlinked data path is not allowed: {current}")
        if current.exists() and not current.is_dir():
            raise OpenADKitError(f"data path component is not a directory: {current}")


def validate_dataset(path: Path, required: list[str]) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    for relative in required:
        candidate = path / safe_relative(relative, "required data file")
        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or candidate.stat().st_size == 0
        ):
            return False
    return True


def rename_atomic(candidate: Path, target: Path, flags: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as error:
        raise OpenADKitError("atomic data publication is unsupported on this host") from error
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(candidate), -100, os.fsencode(target), flags) != 0:
        errno = ctypes.get_errno()
        raise OpenADKitError(
            f"atomic data publication failed for {target}: {os.strerror(errno)}"
        )


def target_identity(path: Path) -> tuple[int, int, int] | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    return info.st_dev, info.st_ino, info.st_ctime_ns


def atomic_publish(candidate: Path, target: Path, expected: tuple[int, int, int] | None) -> None:
    # Absence at download start always means NOREPLACE, even for fetch --force.
    if expected is None:
        rename_atomic(candidate, target, 1)
        return
    if target_identity(target) != expected or not is_managed(target):
        raise OpenADKitError(f"data target changed during download: {target}")
    published = candidate.stat()
    rename_atomic(candidate, target, 2)
    try:
        displaced = candidate.lstat()
        # rename changes ctime itself: compare device/inode after the exchange.
        if (displaced.st_dev, displaced.st_ino) == expected[:2] and is_managed(candidate):
            return
        current = target.lstat()
        if (current.st_dev, current.st_ino) == (published.st_dev, published.st_ino):
            rename_atomic(candidate, target, 2)
    except (OSError, OpenADKitError) as error:
        raise PublicationConflict(f"could not verify/restore data publication: {target}") from error
    raise PublicationConflict(f"data target changed during publication: {target}")


def validate_zip(archive: Path, expected_root: str) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    seen: set[str] = set()
    total_size = 0
    try:
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                name = member.filename
                if not name or "\\" in name or name.startswith("/"):
                    raise OpenADKitError(f"unsafe ZIP member: {name!r}")
                normalized = name[:-1] if name.endswith("/") else name
                parts = normalized.split("/")
                if (
                    any(part in ("", ".", "..") for part in parts)
                    or parts[0] != expected_root
                ):
                    raise OpenADKitError(f"unsafe ZIP member: {name!r}")
                key = PurePosixPath(*parts).as_posix()
                if key in seen:
                    raise OpenADKitError(f"duplicate ZIP member: {name!r}")
                seen.add(key)
                if member.flag_bits & 0x1:
                    raise OpenADKitError(f"encrypted ZIP member: {name!r}")
                file_type = (member.external_attr >> 16) & 0o170000
                if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise OpenADKitError(f"special ZIP member: {name!r}")
                total_size += member.file_size
                if total_size > 50 * 1024 * 1024 * 1024:
                    raise OpenADKitError(
                        "ZIP expands beyond the 50 GiB safety limit"
                    )
                members.append(member)
    except (OSError, zipfile.BadZipFile) as error:
        raise OpenADKitError(f"invalid ZIP archive: {error}") from error
    return members


def extract_zip(archive: Path, stage: Path, expected_root: str) -> Path:
    members = validate_zip(archive, expected_root)
    with zipfile.ZipFile(archive) as source:
        for member in members:
            relative = PurePosixPath(member.filename.rstrip("/"))
            destination = stage.joinpath(*relative.parts)
            if member.is_dir() or member.filename.endswith("/"):
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member) as input_file, destination.open("wb") as output:
                shutil.copyfileobj(input_file, output)
    return stage / expected_root


def selected_resources(
    deployment: Deployment,
    selection: Selection,
    *,
    include_gpu: bool | None = None,
) -> list[dict[str, Any]]:
    want_gpu = selection.gpu if include_gpu is None else include_gpu
    resources = [
        resource
        for resource in deployment.data
        if want_gpu or not resource.get("gpu", False)
    ]
    if selection.node is not None:
        resources = [
            resource
            for resource in resources
            if not resource.get("nodes") or selection.node in resource["nodes"]
        ]
    return resources


def resolve_destination(resource: dict[str, Any], selection: Selection) -> Path:
    """Where a resource goes, from settings compose.resolve_settings resolved."""
    variable = resource["destinationEnv"]
    environment = selection.environment
    if resource.get("gpu") and selection.gpu_environment is not None:
        environment = selection.gpu_environment
    value = environment.get(variable)
    if not value:
        raise OpenADKitError(
            f"{variable} is required for data resource {resource['name']}"
        )
    destination = Path(expand_home(value))
    if not destination.is_absolute():
        raise OpenADKitError(
            f"data destination must be absolute after variable expansion: {destination}"
        )
    ensure_no_symlink_components(destination.parent)
    return destination


def validate_destinations(
    deployment: Deployment,
    selection: Selection,
    *,
    include_gpu: bool | None = None,
) -> None:
    for resource in selected_resources(
        deployment, selection, include_gpu=include_gpu
    ):
        resolve_destination(resource, selection)


def check_installed_data(
    deployment: Deployment,
    selection: Selection,
    *,
    include_gpu: bool | None = None,
) -> list[dict[str, Any]]:
    """Report presence and completeness for each selected data resource."""
    results: list[dict[str, Any]] = []
    for resource in selected_resources(
        deployment, selection, include_gpu=include_gpu
    ):
        target = resolve_destination(resource, selection)
        if validate_dataset(target, resource["requiredFiles"]):
            if is_outdated(target, resource):
                status = "outdated"
                recovery = "fetch-force"
            else:
                status = "ok"
                recovery = None
        elif target.is_symlink() or (target.exists() and not is_managed(target)):
            # fetch --force refuses these; the operator has to remove them first.
            status = "incomplete"
            recovery = "remove"
        elif target.is_dir():
            status = "incomplete"
            recovery = "fetch-force"
        else:
            status = "missing"
            recovery = "fetch"
        results.append(
            {
                "name": resource["name"],
                "destination": target,
                "status": status,
                "recovery": recovery,
            }
        )
    return results


def remove_installed_data(
    deployment: Deployment,
    selection: Selection,
    *,
    include_gpu: bool | None = None,
) -> list[dict[str, Any]]:
    """Delete installed data targets and report what was removed."""
    targets: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for resource in selected_resources(
        deployment, selection, include_gpu=include_gpu
    ):
        target = resolve_destination(resource, selection)
        if target in seen:
            continue
        seen.add(target)
        if target.is_symlink():
            raise OpenADKitError(f"refusing to remove symlinked data: {target}")
        refuse_unmanaged(target, "remove")
        targets.append((resource["name"], target))

    removed: list[dict[str, Any]] = []
    for name, target in targets:
        if not target.is_dir():
            continue
        shutil.rmtree(target)
        print(f"removed data: {target}")
        removed.append({"name": name, "destination": target})
    return removed


def validate_install_targets(
    deployment: Deployment,
    selection: Selection,
    force: bool,
    *,
    include_gpu: bool | None = None,
) -> None:
    destinations: set[Path] = set()
    for resource in selected_resources(
        deployment, selection, include_gpu=include_gpu
    ):
        target = resolve_destination(resource, selection)
        if target in destinations:
            raise OpenADKitError(f"multiple data resources target the same path: {target}")
        destinations.add(target)
        if not (target.exists() or target.is_symlink()):
            continue
        if force:
            if target.is_symlink() or not target.is_dir():
                raise OpenADKitError(f"unsafe data target: {target}")
            refuse_unmanaged(target, "replace")
        elif is_outdated(target, resource):
            raise OpenADKitError(
                f"data at {target} is from an older {resource['name']}; "
                f"run: openadkit fetch {deployment.name} --force"
            )
        elif not validate_dataset(target, resource["requiredFiles"]):
            if target.is_symlink() or not is_managed(target):
                # fetch --force refuses these; the operator has to remove them first.
                raise OpenADKitError(
                    f"incomplete data at {target} cannot be replaced in place; "
                    f"remove it and run: openadkit fetch {deployment.name}"
                )
            raise OpenADKitError(
                f"incomplete data at {target}; run: openadkit fetch {deployment.name} --force"
            )


def resource_destination(resource: dict[str, Any], selection: Selection) -> Path:
    destination = resolve_destination(resource, selection)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_components(destination.parent)
    return destination


def install_resource(
    resource: dict[str, Any],
    selection: Selection,
    force: bool,
) -> None:
    target = resource_destination(resource, selection)
    expected = target_identity(target)
    required = resource["requiredFiles"]
    if target.exists() or target.is_symlink():
        if not force:
            if validate_dataset(target, required):
                print(f"data already present: {target}")
                return
            raise OpenADKitError(
                f"incomplete data at {target}; run: openadkit fetch <deployment> --force"
            )
        if target.is_symlink() or not target.is_dir():
            raise OpenADKitError(f"unsafe data target: {target}")
        refuse_unmanaged(target, "replace")

    with resource_stage(target.parent, resource["name"]) as stage:
        if resource["kind"] == "zip":
            archive = stage / "download.zip"
            download(resource["url"], archive, resource["sha256"])
            candidate = extract_zip(
                archive, stage / "extract", resource["expectedRoot"]
            )
        else:
            candidate = stage / resource["name"]
            candidate.mkdir()
            for item in resource["files"]:
                destination = candidate / safe_relative(
                    item["path"], "data file path"
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                if "sourcePath" in item:
                    copy_verified(item["sourcePath"], destination, item["sha256"])
                else:
                    download(item["url"], destination, item["sha256"])
        for relative, content in resource.get("generatedFiles", {}).items():
            generated = candidate / safe_relative(relative, "generated data file")
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_text(content, encoding="utf-8")
        if not validate_dataset(candidate, required):
            raise OpenADKitError(
                f"downloaded data failed validation: {resource['name']}"
            )
        # Written before publication, so the data and its marker appear together.
        (candidate / MARKER).write_text(
            json.dumps({"resource": resource["name"], "source": source_digest(resource)}) + "\n",
            encoding="utf-8",
        )
        atomic_publish(candidate, target, expected)
        print(f"installed data: {target}")


def install_data(
    deployment: Deployment,
    selection: Selection,
    force: bool,
    *,
    include_gpu: bool | None = None,
) -> None:
    validate_install_targets(
        deployment, selection, force, include_gpu=include_gpu
    )
    for resource in selected_resources(
        deployment, selection, include_gpu=include_gpu
    ):
        install_resource(resource, selection, force)
