"""Validated download, extraction, and atomic data publication."""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
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


def download(url: str, destination: Path, checksum: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "OpenADKit/1"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                request, timeout=60
            ) as response, destination.open("wb") as output:
                shutil.copyfileobj(response, output)
            if sha256_file(destination) != checksum:
                raise OpenADKitError(f"checksum mismatch for {url}")
            return
        except (OSError, urllib.error.URLError, OpenADKitError) as error:
            last_error = error
            destination.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(1 + attempt)
    raise OpenADKitError(f"failed to download {url}: {last_error}")


def ensure_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
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


def atomic_publish(candidate: Path, target: Path, force: bool) -> None:
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
    flags = 2 if target.exists() else 1
    if target.exists() and not force:
        raise OpenADKitError(f"data target already exists: {target}")
    if renameat2(-100, os.fsencode(candidate), -100, os.fsencode(target), flags) != 0:
        error = ctypes.get_errno()
        raise OpenADKitError(
            f"atomic data publication failed for {target}: {os.strerror(error)}"
        )


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
) -> list[dict[str, Any]]:
    return [
        resource
        for resource in deployment.data
        if (not resource.get("gpu", False) or selection.gpu)
        and (not resource["groups"] or selection.group in resource["groups"])
    ]


def resolve_destination(resource: dict[str, Any], selection: Selection) -> Path:
    variable = resource["destinationEnv"]
    value = selection.environment.get(variable)
    if not value:
        raise OpenADKitError(
            f"{variable} is required for data resource {resource['name']}"
        )
    destination = Path(expand_home(value))
    if not destination.is_absolute():
        raise OpenADKitError(
            f"data destination must be absolute after HOME expansion: {destination}"
        )
    ensure_no_symlink_components(destination.parent)
    return destination


def validate_destinations(deployment: Deployment, selection: Selection) -> None:
    for resource in selected_resources(deployment, selection):
        resolve_destination(resource, selection)


def validate_install_targets(
    deployment: Deployment,
    selection: Selection,
    force: bool,
) -> None:
    destinations: set[Path] = set()
    for resource in selected_resources(deployment, selection):
        target = resolve_destination(resource, selection)
        if target in destinations:
            raise OpenADKitError(f"multiple data resources target the same path: {target}")
        destinations.add(target)
        if not (target.exists() or target.is_symlink()):
            continue
        if force:
            if target.is_symlink() or not target.is_dir():
                raise OpenADKitError(f"unsafe data target: {target}")
        elif not validate_dataset(target, resource["requiredFiles"]):
            raise OpenADKitError(f"incomplete data at {target}; rerun with --force")


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
    required = resource["requiredFiles"]
    if target.exists() or target.is_symlink():
        if not force:
            if validate_dataset(target, required):
                print(f"data already present: {target}")
                return
            raise OpenADKitError(f"incomplete data at {target}; rerun with --force")
        if target.is_symlink() or not target.is_dir():
            raise OpenADKitError(f"unsafe data target: {target}")

    with tempfile.TemporaryDirectory(
        prefix=f".{resource['name']}.stage.", dir=target.parent
    ) as temporary:
        stage = Path(temporary)
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
                download(item["url"], destination, item["sha256"])
        for relative, content in resource["generatedFiles"].items():
            generated = candidate / safe_relative(relative, "generated data file")
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_text(content, encoding="utf-8")
        if not validate_dataset(candidate, required):
            raise OpenADKitError(
                f"downloaded data failed validation: {resource['name']}"
            )
        atomic_publish(candidate, target, force)
        print(f"installed data: {target}")


def install_data(
    deployment: Deployment,
    selection: Selection,
    force: bool,
) -> None:
    validate_install_targets(deployment, selection, force)
    for resource in selected_resources(deployment, selection):
        install_resource(resource, selection, force)
