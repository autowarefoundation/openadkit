#!/usr/bin/env python3
"""Turn a resolved Compose model into what an AutoSD image runs.

    openadkit config planning-simulation | platforms/autosd/quadlet.py --output out

Compose stays the single source: `openadkit config` resolves a deployment, with
the image digests when it runs from a release, and this writes the result:

    out/rootfs/etc/containers/systemd/  a Quadlet unit per service
    out/rootfs/usr/share/openadkit/     the bind-mounted files, by mount target
    out/image.aib.yml                   an Automotive Image Builder manifest, with
                                        --root-password-hash; run it from the
                                        directory this ran in

A field this does not translate stops it, so a change to the Compose files can
not silently drop behaviour.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

UNIT_DIRECTORY = Path("etc/containers/systemd")
MOUNT_ROOT = Path("usr/share/openadkit")
TRANSLATED = {
    "command", "container_name", "depends_on", "entrypoint", "environment", "healthcheck",
    "image", "init", "ipc", "network_mode", "pid", "restart", "volumes",
}
# Compose healthcheck timings and the Quadlet keys that take them as they are.
HEALTH_KEYS = {
    "interval": "HealthInterval", "timeout": "HealthTimeout",
    "retries": "HealthRetries", "start_period": "HealthStartPeriod",
}
# The CLI's mapping of the container user to the host user; AutoSD has no such user.
DROPPED_ENVIRONMENT = {"HOST_UID", "HOST_GID"}
# AIB embeds a local file in one message that a large file does not fit; it
# fetches a URL instead. Its runner mounts the working directory at /host.
EMBEDDED_LIMIT = 1024 * 1024
BUILDER_ROOT = "/host"
MANIFEST_DEFAULTS: dict[str, Any] = {
    "name": "openadkit",
    "image": {
        "hostname": "openadkit",
        "selinux_booleans": {"domain_can_mmap_files": True},
        "image_size": "40 GiB",
        "partitions": {"boot": {"size": "300 MiB"}},
    },
}


class TranslationError(Exception):
    """The model has something a Quadlet unit cannot express here."""


def quote(word: str) -> str:
    """One systemd word. The model already writes a literal $ as $$, as systemd does."""
    escaped = word.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("%", "%%")
    return word if word and escaped == word and not set(word) & set(" \t'") else f'"{escaped}"'


def words(items: list[str]) -> str:
    return " ".join(quote(item) for item in items)


def unit_name(services: dict[str, Any], service: str) -> str:
    if service not in services:
        raise TranslationError(f"{service} is needed by another service but left out")
    return str(services[service]["container_name"])


def translate(name: str, service: dict[str, Any], services: dict[str, Any], oneshots: set[str]) -> str:
    """The Quadlet unit of one service."""
    unknown = sorted(set(service) - TRANSLATED)
    if unknown:
        raise TranslationError(f"{name}: {', '.join(unknown)} has no translation")
    if service.get("network_mode") != "host":
        raise TranslationError(f"{name}: only network_mode: host has a translation")
    if service.get("ipc", "host") != "host":
        raise TranslationError(f"{name}: only ipc: host has a translation")

    unit = [f"Description=Open AD Kit {name}"]
    for dependency, condition in sorted(service.get("depends_on", {}).items()):
        if condition["condition"] not in ("service_started", "service_completed_successfully"):
            raise TranslationError(f"{name}: depends_on condition {condition['condition']} has no translation")
        target = unit_name(services, dependency)
        unit += [f"Requires={target}.service", f"After={target}.service"]

    # Podman has the flags for these, and they work on every Quadlet version.
    podman_arguments = []
    if "ipc" in service:
        podman_arguments.append("--ipc=host")
    pid = service.get("pid")
    if pid:
        if not pid.startswith("service:"):
            raise TranslationError(f"{name}: only pid: service:<name> has a translation")
        podman_arguments.append(f"--pid=container:{unit_name(services, pid.removeprefix('service:'))}")
    arguments = list(service.get("command") or [])
    entrypoint = service.get("entrypoint")
    if entrypoint:
        podman_arguments.append(f"--entrypoint={entrypoint[0]}")
        arguments = [*entrypoint[1:], *arguments]

    container = [
        f"Image={service['image']}",
        f"ContainerName={service['container_name']}",
        "Network=host",
        # A mount source under the read-only /usr can not be relabeled.
        "SecurityLabelDisable=true",
    ]
    # Podman refuses an init in a joined PID namespace; the owner's init is PID 1 there.
    if service.get("init") and not pid:
        container.append("RunInit=true")
    for key, value in sorted((service.get("environment") or {}).items()):
        if key not in DROPPED_ENVIRONMENT:
            container.append(f"Environment={quote(f'{key}={value}')}")
    for volume in service.get("volumes", []):
        container.append(f"Volume=/{MOUNT_ROOT}{volume['target']}:{volume['target']}:ro")
    container += healthcheck(name, service.get("healthcheck"))
    if podman_arguments:
        container.append(f"PodmanArgs={' '.join(podman_arguments)}")
    if arguments:
        container.append(f"Exec={words(arguments)}")

    # Pulling on a host without the embedded images can outlast the default timeout.
    system = ["TimeoutStartSec=0"]
    if name in oneshots:
        system += ["Type=oneshot", "RemainAfterExit=yes"]
    elif service.get("restart") not in (None, "no"):
        system.append(f"Restart={service['restart']}")

    sections = {
        "Unit": unit,
        "Container": container,
        "Service": system,
        "Install": ["WantedBy=multi-user.target"],
    }
    return "\n\n".join(f"[{title}]\n" + "\n".join(lines) for title, lines in sections.items()) + "\n"


def healthcheck(name: str, health: dict[str, Any] | None) -> list[str]:
    """Quadlet health keys of a Compose healthcheck.

    Podman runs a string command with /bin/sh -c, as Compose runs CMD-SHELL.
    Its startup check stands in for start_interval: it runs that often until
    it first passes, and the regular check then runs every interval.
    """
    if not health:
        return []
    test = health.get("test") or []
    if health.get("disable") or len(test) != 2 or test[0] != "CMD-SHELL":
        raise TranslationError(f"{name}: only a CMD-SHELL healthcheck has a translation")
    command = test[1].replace("%", "%%")
    keys = [f"HealthCmd={command}"]
    keys += [f"{key}={health[option]}" for option, key in HEALTH_KEYS.items() if option in health]
    if "start_interval" in health:
        keys += [
            f"HealthStartupCmd={command}",
            f"HealthStartupInterval={health['start_interval']}",
            f"HealthStartupTimeout={health.get('timeout', '30s')}",
            "HealthStartupSuccess=1",
        ]
    return keys


def mounts(services: dict[str, Any]) -> dict[str, Path]:
    """Each mount target and the one source every service gives it."""
    found: dict[str, Path] = {}
    for name, service in services.items():
        for volume in service.get("volumes", []):
            if volume["type"] != "bind":
                raise TranslationError(f"{name}: only bind volumes have a translation")
            if not volume.get("read_only"):
                raise TranslationError(f"{name}: writable {volume['target']} has no translation")
            source = Path(volume["source"])
            if found.setdefault(volume["target"], source) != source:
                raise TranslationError(f"{volume['target']} has two sources")
            if not source.exists():
                raise TranslationError(f"{name}: {source} does not exist; run openadkit fetch first")
    return found


def container_image(reference: str) -> dict[str, str]:
    source, separator, digest = reference.partition("@")
    if separator:
        return {"source": source.rsplit(":", 1)[0] if ":" in source.rsplit("/", 1)[-1] else source, "digest": digest}
    repository, _, tag = reference.rpartition(":")
    return {"source": repository, "tag": tag}


def added_file(path: Path, rootfs: Path, output: Path) -> dict[str, str]:
    target = f"/{path.relative_to(rootfs)}"
    if path.stat().st_size <= EMBEDDED_LIMIT:
        return {"path": target, "source_path": str(path.relative_to(output))}
    built = os.path.normpath(os.path.join(BUILDER_ROOT, os.path.relpath(path)))
    return {"path": target, "url": f"file://{built}"}


def manifest(services: dict[str, Any], output: Path, root_password_hash: str) -> dict[str, Any]:
    images = sorted({service["image"] for service in services.values()})
    rootfs = output / "rootfs"
    paths = sorted(rootfs.rglob("*"))
    return {
        **MANIFEST_DEFAULTS,
        "auth": {"root_password": root_password_hash},
        "content": {
            "rpms": ["podman"],
            "container_images": [container_image(image) for image in images],
            "make_dirs": [
                {"path": f"/{path.relative_to(rootfs)}", "parents": True, "exist_ok": True}
                for path in paths if path.is_dir() and path.parent != rootfs
            ],
            "add_files": [added_file(path, rootfs, output) for path in paths if path.is_file()],
        },
    }


def write(model: dict[str, Any], output: Path, without: list[str], root_password_hash: str | None = None) -> None:
    services = {name: service for name, service in model["services"].items() if name not in without}
    missing = sorted(set(without) - set(model["services"]))
    if missing:
        raise TranslationError(f"no such service to leave out: {', '.join(missing)}")
    oneshots = {
        dependency
        for service in services.values()
        for dependency, condition in service.get("depends_on", {}).items()
        if condition["condition"] == "service_completed_successfully"
    }
    # Translate first, so a refusal leaves no partial tree behind.
    units = {service["container_name"]: translate(name, service, services, oneshots) for name, service in services.items()}
    sources = mounts(services)
    rootfs = output / "rootfs"
    if output.exists():
        raise TranslationError(f"{output} already exists")
    (rootfs / UNIT_DIRECTORY).mkdir(parents=True)
    for name, text in units.items():
        (rootfs / UNIT_DIRECTORY / f"{name}.container").write_text(text, encoding="utf-8")
    for target, source in sources.items():
        destination = rootfs / MOUNT_ROOT / target.lstrip("/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    # An image has no default password; the units alone need none.
    if root_password_hash:
        # JSON is YAML, and this keeps the script free of dependencies.
        text = json.dumps(manifest(services, output, root_password_hash), indent=2)
        (output / "image.aib.yml").write_text(text + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="directory to create")
    parser.add_argument("--without", action="append", default=[], metavar="SERVICE", help="leave a service out; repeatable")
    parser.add_argument(
        "--root-password-hash", metavar="HASH",
        help="the image's root password, from openssl passwd -6; without it no image manifest is written",
    )
    args = parser.parse_args()
    try:
        write(json.load(sys.stdin), args.output, args.without, args.root_password_hash)
    except TranslationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
