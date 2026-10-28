#!/usr/bin/env python3
"""Upgrade and uninstall the installed Open AD Kit release.

`openadkit install` stays in the launcher, because it runs before any release
is on disk. Upgrade asks that installer to resolve the latest release and then
hands the install back to it, so downloading and verifying a release has one
implementation. Only the installation's kind and version are read here, so an
installation with outdated manifests can still be upgraded or removed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import compose
from manifest import OpenADKitError, expand_home, root_path

_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
# Strict SemVer release tag; must agree with the launcher (test_release_versions.py).
VERSION_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    rf"(?:-({_IDENTIFIER}(?:\.{_IDENTIFIER})*))?$"
)
KEPT_RELEASE_RE = re.compile(r"^openadkit-v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$")

UPGRADE_USAGE = """\
Usage: openadkit upgrade [--check]

Upgrades an installed release to the latest stable Open AD Kit release. The
previous version is kept under the install destination for rollback with
`openadkit install --version vX.Y.Z --force`; the kept directory must be
replaced. Source checkouts update with git pull or git checkout instead.

  --check  report whether an upgrade is available without installing it
"""

UNINSTALL_USAGE = """\
Usage: openadkit uninstall [--all]

Removes the active Open AD Kit release installation, its launcher, the adkit
short name and Tab completion.
Downloaded data is not touched. Refuses while an openadkit-* Compose project
is still running, because uninstall removes the launcher `openadkit stop` needs.

  --all  also remove previously kept releases in the install destination

Stop running deployments first (`openadkit stop <deployment>`). Run
`openadkit clean <deployment> --data` before uninstalling if you also want to
delete downloaded data such as maps and perception models.
"""


class UsageError(Exception):
    """A command-line mistake; exits 2 like the launcher's other usage errors."""


def log(message: str) -> None:
    print(f"[openadkit] {message}", flush=True)


def _parse_version(value: str) -> tuple[tuple[int, ...], str | None]:
    match = VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid version: {value}")
    return tuple(int(part) for part in match.group(1, 2, 3)), match.group(4)


def compare_versions(current: str, latest: str) -> str:
    """Whether latest is "newer", "older" or the "same" SemVer precedence as current."""
    current_core, current_pre = _parse_version(current)
    latest_core, latest_pre = _parse_version(latest)
    if current_core != latest_core:
        return "newer" if latest_core > current_core else "older"
    if current_pre == latest_pre:
        return "same"
    if current_pre is None:
        return "older"
    if latest_pre is None:
        return "newer"
    current_parts = current_pre.split(".")
    latest_parts = latest_pre.split(".")
    for current_part, latest_part in zip(current_parts, latest_parts, strict=False):
        if current_part == latest_part:
            continue
        current_numeric = current_part.isdigit()
        latest_numeric = latest_part.isdigit()
        if current_numeric and latest_numeric:
            return "newer" if int(latest_part) > int(current_part) else "older"
        if current_numeric != latest_numeric:
            # Numeric identifiers have lower precedence than alphanumeric ones.
            return "newer" if current_numeric else "older"
        return "newer" if latest_part > current_part else "older"
    if len(current_parts) == len(latest_parts):
        return "same"
    # A larger set of identifiers has higher precedence when all shared ones match.
    return "newer" if len(latest_parts) > len(current_parts) else "older"


def launcher_path() -> Path:
    return Path(expand_home("$HOME")) / ".local/bin/openadkit"


def shortcut_paths() -> list[Path]:
    """The short name and the completion links the installer puts beside the launcher."""
    home = Path(expand_home("$HOME"))
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    completions = data / "bash-completion/completions"
    return [home / ".local/bin/adkit", completions / "openadkit", completions / "adkit"]


def active_release(root: Path, command: str) -> str:
    """The version of the release at root, which must be the active installation.

    Only the active installation may repoint or remove the launcher; an
    extracted bundle or a stale copy must not take over ~/.local/bin/openadkit.
    """
    metadata = root / "openadkit.json"
    if not metadata.is_file():
        raise OpenADKitError("Open AD Kit is not installed. Run: openadkit install")
    try:
        kit = json.loads(metadata.read_text(encoding="utf-8"))
        if not isinstance(kit, dict):
            raise ValueError("JSON root must be an object")
    except (OSError, ValueError) as error:
        raise OpenADKitError(f"could not read the installed release metadata: {error}") from error
    kind, version = kit.get("kind", "unknown"), kit.get("version", "")
    if kind == "repository":
        raise OpenADKitError({
            "upgrade": "upgrade is for release installs; update a source checkout with git pull or git checkout",
            "uninstall": "uninstall is for release installs; remove a source checkout with git",
        }[command])
    if kind != "release":
        raise OpenADKitError(f"unrecognized Open AD Kit installation: {root}")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise OpenADKitError(f"could not read the installed release version: {version or 'unknown'}")
    if root.name != f"openadkit-{version}":
        raise OpenADKitError(
            f"installed release is not in a versioned directory: {root}; "
            "use openadkit install --destination"
        )
    launcher = launcher_path()
    if launcher.exists() and not launcher.is_symlink():
        action = "replace" if command == "upgrade" else "remove"
        raise OpenADKitError(f"refusing to {action} non-symlink launcher: {launcher}")
    if not launcher.is_symlink():
        raise OpenADKitError("Open AD Kit is not installed. Run: openadkit install")
    if os.path.realpath(launcher) != str(root / "openadkit"):
        raise OpenADKitError(
            f"the active installation is not {root}; "
            f"run openadkit {command} through the installed launcher"
        )
    return version


def installer(root: Path, *arguments: str, capture: bool = False) -> str:
    """Run this release's launcher installer; its errors already reach stderr."""
    sys.stdout.flush()  # Keep our output ahead of the installer's own.
    result = subprocess.run(
        [str(root / "openadkit"), "install", *arguments],
        stdout=subprocess.PIPE if capture else None,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout or "", end="")
        raise SystemExit(result.returncode)
    return result.stdout or ""


def upgrade(root: Path, arguments: Sequence[str]) -> int:
    check_only = False
    for argument in arguments:
        if argument == "--check":
            check_only = True
        elif argument in ("-h", "--help"):
            print(UPGRADE_USAGE, end="")
            return 0
        else:
            raise UsageError(f"unknown upgrade option: {argument}")

    if shutil.which("curl") is None:
        raise OpenADKitError("curl is required")
    current = active_release(root, "upgrade")

    # The installer prints its progress, then the resolved version last.
    *progress, latest = installer(root, "--resolve", capture=True).splitlines() or [""]
    for line in progress:
        print(line)
    try:
        relationship = compare_versions(current, latest)
    except ValueError as error:
        raise OpenADKitError("could not compare release versions") from error
    if relationship == "same":
        print(f"Open AD Kit is up to date: {current}")
        return 0
    if relationship == "older":
        print(
            f"Open AD Kit {current} is newer than the latest stable release {latest}; "
            "nothing to upgrade"
        )
        return 0
    if check_only:
        print(f"Upgrade available: {current} -> {latest}")
        return 0

    # Force replacement so a version directory left behind by a rollback or a
    # previous install is re-verified and reinstalled instead of failing.
    destination = root.parent
    installer(root, "--version", latest, "--destination", str(destination), "--force", "--no-next-steps")
    print(
        f"Upgraded {current} -> {latest} "
        f"(previous version kept at {destination / f'openadkit-{current}'})"
    )
    return 0


def require_no_running_deployments() -> None:
    """Uninstall removes the only launcher that can stop these projects."""
    if shutil.which("docker") is None:
        return
    try:
        live = compose.live_projects()
    except OpenADKitError as error:
        # Fail closed: an unreadable project list is not an empty one.
        print(error, file=sys.stderr)
        raise OpenADKitError(
            "could not confirm deployments are stopped; stop them before uninstall"
        ) from error
    running = sorted(name[len(compose.PROJECT_PREFIX) :] for name in live)
    if running:
        raise OpenADKitError(
            f"stop running deployments before uninstall: {', '.join(running)}. "
            "Run: openadkit stop <deployment>"
        )


def uninstall(root: Path, arguments: Sequence[str]) -> int:
    remove_kept = False
    for argument in arguments:
        if argument == "--all":
            remove_kept = True
        elif argument in ("-h", "--help"):
            print(UNINSTALL_USAGE, end="")
            return 0
        else:
            raise UsageError(f"unknown uninstall option: {argument}")

    version = active_release(root, "uninstall")
    destination = root.parent
    require_no_running_deployments()

    log(f"removing {root}")
    # Only links into this release; a file of the user's at those paths stays.
    # Compare where the links lead, not their text: the installer writes the
    # destination as given, which may end in "/" or pass through a linked HOME.
    shortcuts = [
        path for path in shortcut_paths()
        if path.is_symlink() and path.resolve().is_relative_to(root.resolve())
    ]
    shutil.rmtree(root)
    launcher_path().unlink()
    for path in shortcuts:
        path.unlink()

    if remove_kept:
        for candidate in sorted(destination.glob("openadkit-v*")):
            if candidate.is_dir() and not candidate.is_symlink() and KEPT_RELEASE_RE.fullmatch(candidate.name):
                log(f"removing {candidate}")
                shutil.rmtree(candidate)
        for pattern in (".openadkit-old.*", ".openadkit-stage.*"):
            for candidate in sorted(destination.glob(pattern)):
                if candidate.is_dir() and not candidate.is_symlink():
                    shutil.rmtree(candidate)

    if destination.is_dir() and not any(destination.iterdir()):
        try:
            destination.rmdir()
        except OSError:
            pass

    log(
        f"uninstalled {version}; downloaded data under ~/autoware_map and "
        "~/autoware_data was kept"
    )
    return 0


def main(arguments: Sequence[str]) -> int:
    command, *options = arguments
    try:
        root = root_path()
        return {"upgrade": upgrade, "uninstall": uninstall}[command](root, options)
    except UsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (OpenADKitError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
