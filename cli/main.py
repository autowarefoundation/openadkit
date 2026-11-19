#!/usr/bin/env python3
"""Open AD Kit command-line parser and runtime orchestrator."""

from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import compose
import data
import live
import settings
from catalog import (
    Catalog,
    Deployment,
    available_deployments,
    default_ros_distro,
    deployment_modified,
    get_deployment,
    holds_packages,
    install_root,
    load_catalog,
    resolve_extends,
    root_path,
)
from manifest import (
    KIT_DEPLOYMENTS_DIRECTORY,
    NAME_RE,
    VERSION_RE,
    OpenADKitError,
    UsageError,
    load_json,
    require_string,
)
from settings import Selection

KIT_TEMPLATE = Path(__file__).resolve().parent / "templates/kit"


def find_kit(start: Path) -> Path | None:
    """The extending kit (kind "kit") around the working directory, if any.

    Like git, the nearest openadkit.json wins; it is a kit only when its kind
    is "kit". A CLI that took the command over from another one is told the
    kit: the variable alone, which a kit's own files also read, names nothing.
    """
    explicit = os.environ.get("OPENADKIT_KIT")
    if explicit and os.environ.get("OPENADKIT_DELEGATED"):
        return Path(explicit).resolve()
    for directory in (start, *start.parents):
        manifest = directory / "openadkit.json"
        if manifest.is_file():
            try:
                kind = json.loads(manifest.read_text(encoding="utf-8")).get("kind")
            except (OSError, ValueError, AttributeError) as error:
                raise OpenADKitError(f"invalid manifest {manifest}: {error}") from error
            return directory if kind == "kit" else None
    return None


def read_extends(kit_root: Path) -> str:
    return require_string(load_json(kit_root / "openadkit.json").get("extends"), "extends")


def create_kit(root: Path, catalog: Catalog, name: str, base: str, destination: Path) -> Path:
    """A kit named name in destination, on top of base, from cli/templates/kit.

    An installed release is extended by its version, so the kit follows that
    install; anything else by its path, relative when the kit is inside it.
    """
    if catalog.kind == "kit":
        raise OpenADKitError("run openadkit new outside a kit: a kit extends an Open AD Kit, not another kit")
    if not NAME_RE.fullmatch(name):
        raise OpenADKitError(f"invalid kit name {name}: use lowercase letters, digits and -")
    if base not in catalog.deployments:
        raise OpenADKitError(f"{base} is not a deployment of this Open AD Kit; available: {available_deployments(catalog)}")
    target = destination.resolve() / name
    if target.exists() or target.is_symlink():
        raise OpenADKitError(f"{target} already exists")
    if catalog.kind == "release" and (install_root() / f"openadkit-{catalog.version}").resolve() == root.resolve():
        extends = str(catalog.version)
    elif target.is_relative_to(root.resolve()):
        extends = os.path.relpath(root.resolve(), target)
    else:
        extends = str(root.resolve())
    values = {"name": name, "base": base, "extends": extends, "version": catalog.version or "(a source checkout)"}

    def fill(text: str) -> str:
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        return text

    # The template names the first deployment's directory after the kit and its base.
    for source in sorted(KIT_TEMPLATE.rglob("*")):
        output = target / fill(str(source.relative_to(KIT_TEMPLATE)))
        if source.is_dir():
            output.mkdir(parents=True, exist_ok=True)
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(fill(source.read_text(encoding="utf-8")), encoding="utf-8")
    return target


def hand_over(start: Path, *, act: bool = True) -> Path | None:
    """The kit around start, if any, once this is the CLI of the Open AD Kit it pins.

    Otherwise the pinned release's own launcher takes over the command: only
    its CLI is guaranteed to understand that release's manifests and options.
    A command that acts downloads a pinned release that is missing. One that
    only reads the kit (act=False) hands over to a pinned release that is
    installed and otherwise reads with this CLI: it downloads nothing and
    never starts a program that a path in the kit names.
    """
    kit_root = find_kit(start)
    if kit_root is None:
        return None
    extends = read_extends(kit_root)
    pinned = VERSION_RE.fullmatch(extends) is not None
    if act and pinned:
        install_pinned_release(extends)
    if act or (pinned and (install_root() / f"openadkit-{extends}" / "openadkit.json").is_file()):
        run_with(resolve_extends(kit_root, extends), {"OPENADKIT_KIT": str(kit_root)})
    return kit_root


def run_with(cli_root: Path, environment: dict[str, str] | None = None) -> None:
    """Hand this command to the CLI at cli_root, unless this is that CLI."""
    if cli_root == root_path():
        return
    if os.environ.get("OPENADKIT_DELEGATED"):
        raise OpenADKitError(f"{cli_root}/openadkit did not run this command as its own CLI")
    launcher = cli_root / "openadkit"
    if not launcher.is_file():
        raise OpenADKitError(f"{cli_root} has no openadkit launcher")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(launcher, [str(launcher), *sys.argv[1:]], os.environ | (environment or {}) | {"OPENADKIT_DELEGATED": "1"})


def install_pinned_release(version: str) -> None:
    """Download the release a kit pins if it is missing, as a build tool's
    wrapper does; the active openadkit stays as it is."""
    if (install_root() / f"openadkit-{version}" / "openadkit.json").is_file():
        return
    print(f"[openadkit] this kit uses Open AD Kit {version}; installing it "
          "(your openadkit stays as it is)", file=sys.stderr, flush=True)
    # stdout stays the command's own, for --json.
    result = subprocess.run(
        [str(root_path() / "openadkit"), "install", "--version", version, "--no-activate", "--no-next-steps"],
        stdout=sys.stderr, check=False,
    )
    if result.returncode != 0:
        raise OpenADKitError(f"could not install Open AD Kit {version}, which this kit extends")


def load_catalog_around(start: Path, *, act: bool = True) -> tuple[Path, Catalog]:
    """The kit around start, or this CLI's own Open AD Kit.

    A command that acts on a kit runs with the CLI of the release the kit pins.
    Reading one (act=False) does too when that release is installed; it
    downloads nothing (hand_over).
    """
    root = hand_over(start, act=act) or root_path()
    return root, load_catalog(root)


class OpenADKitParser(argparse.ArgumentParser):
    help_inventory: str | None = None
    # The top-level parser's command parsers, by name.
    commands: dict[str, OpenADKitParser]

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(2)

    def print_help(self, file=None) -> None:
        super().print_help(file)
        if self.help_inventory != "catalog":
            return
        try:
            # Help is this CLI's own: it never hands over to print a list.
            root = find_kit(Path.cwd()) or root_path()
            catalog = load_catalog(root)
        except OpenADKitError:
            return
        print(file=file)
        list_deployments(root, catalog)


def _print_table(headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    print(
        "  ".join(
            header.ljust(widths[index]) for index, header in enumerate(headers)
        ).rstrip()
    )
    for row in rows:
        print(
            "  ".join(
                row[index].ljust(widths[index]) for index in range(len(headers))
            ).rstrip()
        )


def list_deployments(
    root, catalog, names: list[str] | None = None, *, json_output: bool = False
) -> int:
    selected = list(catalog.deployments if names is None else names)
    if not selected:
        if json_output:
            print(json.dumps({"schemaVersion": 1, "deployments": []}))
        else:
            print("No deployments found.")
        return 0
    entries: list[dict[str, object]] = []
    for name in selected:
        try:
            deployment = get_deployment(root, catalog, name)
            entries.append(
                {
                    "name": name,
                    "modified": deployment_modified(root, deployment, catalog),
                    "requirements": deployment.requirements,
                    "description": deployment.manifest["description"],
                }
            )
        except OpenADKitError as error:
            entries.append(
                {
                    "name": name,
                    "modified": None,
                    "requirements": None,
                    "description": None,
                    "error": str(error).replace("\n", " "),
                }
            )
    if json_output:
        print(json.dumps({"schemaVersion": 1, "deployments": entries}))
        return 0
    gpu = {"none": "no", "optional": "optional", "required": "required"}
    rows = [
        (
            str(entry["name"]),
            "" if entry["requirements"] is None else gpu[entry["requirements"]["gpu"]],  # type: ignore[index]
            str(entry.get("error") or entry.get("description") or ""),
        )
        for entry in entries
    ]
    _print_table(("NAME", "GPU", "DESCRIPTION"), rows)
    # A release's deployments are checked against it; a source checkout's are what is there.
    for entry in entries:
        if entry["modified"]:
            print(f"note: {entry['name']} differs from the release it came with")
    return 0


def report(error: Exception) -> None:
    # What the command printed comes before its error, also through a pipe.
    sys.stdout.flush()
    print(f"error: {error}", file=sys.stderr)


def is_path(argument: str) -> bool:
    """A deployment or workspace named by its directory, such as ./my-kit."""
    return "/" in argument or argument.startswith(".")


def deployment_name(root: Path, catalog: Catalog, argument: str) -> str:
    if not is_path(argument):
        return argument
    directory = Path(argument).expanduser().resolve()
    for name, reference in catalog.deployments.items():
        if (root / reference.path).resolve() == directory:
            return name
    # A kit's deployment goes by its directory also while it has none.
    if not directory.exists():
        raise OpenADKitError(f"{argument}: no such directory")
    raise OpenADKitError(f"{argument} is not a deployment of {root}")


def require_deployment_name(command: str) -> None:
    print("error: deployment name required", file=sys.stderr)
    print(f"usage: openadkit {command} <deployment>", file=sys.stderr)
    print(file=sys.stderr)


def autoware_line(autoware: dict[str, Any]) -> str:
    backports = len(autoware.get("backports", []))
    fixes = f", {backports} backported fix{'es' if backports > 1 else ''}" if backports else ""
    return f"autoware: {autoware['version']} ({autoware['ref']}{fixes})"


def show_version(root, catalog, *, json_output: bool = False) -> int:
    # A kit reports the Open AD Kit it extends: its own repository is not one.
    described, described_root = (catalog.extended, catalog.extended_root) if catalog.extended else (catalog, root)
    if described.kind == "release":
        version = described.version
        commit = None
    else:
        result = subprocess.run(
            ["git", "-C", str(described_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        version = None
        commit = result.stdout.strip() or None
    if json_output:
        print(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": catalog.kind,
                    "version": version,
                    "commit": commit,
                    "extends": catalog.extends,
                    "bom": catalog.bom(),
                }
            )
        )
        return 0
    if catalog.extends is not None:
        print(f"kit: {root}")
        # A pinned release, or a source checkout named by its path.
        pinned = f"{catalog.extends} ({catalog.extended_root})" if VERSION_RE.fullmatch(catalog.extends) else f"at {catalog.extended_root}"
        print(f"extends: Open AD Kit {pinned}")
        if catalog.autoware:
            print(autoware_line(catalog.autoware))
    elif catalog.kind == "release":
        autoware = f" · Autoware {catalog.autoware['version']}" if catalog.autoware else ""
        print(f"Open AD Kit {catalog.version or 'unknown'}{autoware}")
        print("from: release bundle")
        if catalog.autoware:
            print(autoware_line(catalog.autoware))
    else:
        print("Open AD Kit development")
        print(f"commit: {commit or 'unknown'}")
        print("from: source checkout")
    return 0


@functools.cache
def warn_unread_kit_files(root: Path, deployments: tuple[str, ...]) -> None:
    """Name the files a kit holds where the CLI does not read them; they
    would otherwise be ignored without a word."""
    unread = []
    if (root / "compose.yaml").exists():
        unread.append("compose.yaml at its root: a deployment's services go in deployments/<name>/compose.yaml")
    directory = root / KIT_DEPLOYMENTS_DIRECTORY
    for candidate in sorted(directory.iterdir()) if directory.is_dir() else []:
        relative = f"{KIT_DEPLOYMENTS_DIRECTORY}/{candidate.name}"
        if candidate.name in deployments:
            if (candidate / "compose.gpu.yaml").exists():
                unread.append(f"{relative}/compose.gpu.yaml: a kit deployment's GPU mode is its base's")
            if (candidate / "compose.yml").exists():
                unread.append(f"{relative}/compose.yml: the file is named compose.yaml")
            if (candidate / "overlay_ws").exists():
                unread.append(f"{relative}/overlay_ws: the kit's packages go in overlay_ws at its root")
        elif any((candidate / name).exists() for name in ("settings.env", "compose.yaml", "config")):
            unread.append(f"{relative}/: openadkit.json has no deployment of that name")
    for item in unread:
        print(f"warning: this kit does not read {item}", file=sys.stderr)


def warn_if_modified(root, deployment, catalog) -> None:
    if deployment_modified(root, deployment, catalog):
        print(
            f"warning: {deployment.name} has been modified from this release",
            file=sys.stderr,
        )
    if deployment.evidence_exemption:
        print(
            f"warning: {deployment.name} is not verified in CI: "
            f"{deployment.evidence_exemption}",
            file=sys.stderr,
        )


# Data a deployment can run with: what the CLI installed and still declares,
# and the user's own directory, which it does not check.
DATA_USABLE = ("ok", "own")


def report_data_gaps(deployment_name: str, results: list[dict[str, object]]) -> None:
    gaps = [item for item in results if item["status"] not in DATA_USABLE]
    if not gaps:
        return
    for item in gaps:
        if item["recovery"] != "remove":
            continue
        print(
            f"error: {item['name']} at {item['destination']} cannot be replaced "
            "in place; remove it and run: "
            f"openadkit fetch {deployment_name}",
            file=sys.stderr,
        )
    if any(item["recovery"] == "fetch-force" for item in gaps):
        print(
            "error: installed data is incomplete; run: "
            f"openadkit fetch {deployment_name} --force",
            file=sys.stderr,
        )
    elif any(item["recovery"] == "fetch" for item in gaps):
        state = "outdated" if all(item["status"] == "outdated" for item in gaps) else "missing"
        print(
            f"error: installed data is {state}; run: "
            f"openadkit fetch {deployment_name}",
            file=sys.stderr,
        )


def print_run_next_steps(
    deployment, services: set[str], role: str | None, output: str | None, *, tls: bool = False
) -> None:
    target = deployment.name if role is None else f"{deployment.name} --role {role}"
    # A kit deployment names what it runs, which its own name may not say.
    on_base = f" ({deployment.base.name} with the kit's files on top)" if deployment.base else ""
    print(f"running: {target}{on_base}")
    if "visualizer" in services:
        print(live.visualizer_address(tls))
        print(
            "password: REMOTE_PASSWORD (default openadkit; override in "
            f"{deployment.host_settings})"
        )
    if output:
        print(f"output: {output}")
    print(f"stop with: openadkit stop{f' --role {role}' if role else ''}")


ROLE_HELP = "role from this deployment's manifest (omit for single host; experimental)"
LIVE_ROLE_HELP = "role to act on when several roles run on this host (experimental)"
VERBOSE_HELP = "print the docker commands it runs, status queries aside (or set OPENADKIT_VERBOSE=1)"


def json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", dest="json_output", help="print machine-readable JSON")


def deployment_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "deployment", nargs="?",
        help="deployment name or directory (omitted: a kit's only deployment, or else list them)",
    )


def selection_arguments(parser: argparse.ArgumentParser) -> None:
    """The deployment and how to run it."""
    deployment_argument(parser)
    parser.add_argument(
        "--ros-distro", metavar="DISTRO",
        help="ROS distro (default: this Open AD Kit's default, or the deployment's first if it does not run on that)",
    )
    parser.add_argument(
        "--gpu", action="store_true",
        help="run in GPU mode, for a deployment with an optional one (one that requires a GPU always uses it)",
    )
    parser.add_argument("--role", metavar="ROLE", help=ROLE_HELP)
    parser.add_argument(
        "--ws", metavar="PATH",
        help="mount this built workspace as the overlay, for a deployment without its own",
    )


def validate_arguments(parser: argparse.ArgumentParser) -> None:
    selection_arguments(parser)
    parser.add_argument(
        "--data", action="store_true", help="also check that the deployment's downloaded data is complete"
    )
    json_argument(parser)


def fetch_arguments(parser: argparse.ArgumentParser) -> None:
    # Data destinations do not depend on the distro, so fetch takes none.
    deployment_argument(parser)
    parser.add_argument("--force", action="store_true", help="replace existing data even if it already validates")


def run_arguments(parser: argparse.ArgumentParser) -> None:
    selection_arguments(parser)
    parser.add_argument(
        "--no-visualizer", action="store_true", help="start without the visualizer, for hosts nobody watches"
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="once ready, run the deployment's verify step and exit with its result",
    )


def build_arguments(parser: argparse.ArgumentParser) -> None:
    parser.usage = "openadkit build [-h] [--ros-distro DISTRO] [PATH] [-- COLCON_ARGS ...]"
    parser.epilog = (
        "arguments after -- go to colcon build, for example:\n"
        "  openadkit build -- --packages-select my_pkg\n"
        "  openadkit build -- --cmake-args -DCMAKE_BUILD_TYPE=Debug"
    )
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.add_argument(
        "workspace", nargs="?", metavar="PATH",
        help="workspace with a src/ directory (default: the kit's overlay_ws)",
    )
    parser.add_argument(
        "--ros-distro", metavar="DISTRO",
        help="ROS distro (default: this Open AD Kit's default, or the first that every kit deployment runs on)",
    )


def new_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", metavar="NAME", help="the kit's name and directory, created here")
    parser.add_argument(
        "--base", default="planning-simulation", metavar="DEPLOYMENT",
        help="the deployment the kit builds on (default: planning-simulation)",
    )


def clean_arguments(parser: argparse.ArgumentParser) -> None:
    deployment_argument(parser)
    parser.add_argument("--yes", action="store_true", help="delete without asking")


def logs_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("services", nargs="*", metavar="SERVICE", help="only these services")
    parser.add_argument("--follow", action="store_true", help="stream logs, from each service's last 100 lines")


def restart_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "services", nargs="*", metavar="SERVICE",
        help="services to recreate (default: those that take config overrides or an overlay workspace, and those whose settings changed)",
    )
    parser.add_argument(
        "--all", action="store_true", dest="all_services",
        help="recreate the whole deployment, one-shot services included",
    )


def shell_arguments(parser: argparse.ArgumentParser) -> None:
    # argparse prints a REMAINDER argument as a bare "..." in the usage line.
    parser.usage = "%(prog)s [-h] [--role ROLE] [--verbose] [SERVICE [COMMAND ...]]"
    parser.add_argument("service", nargs="?", default="api", metavar="SERVICE", help="service (default: api)")
    parser.add_argument("command_args", nargs=argparse.REMAINDER, metavar="COMMAND", help="command to run")


def record_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("topics", nargs="*", metavar="TOPIC", help="topics to record")
    parser.add_argument("--all", action="store_true", dest="all_topics", help="record every topic")
    parser.add_argument(
        "--output", metavar="DIRECTORY",
        help="where bags go (default: <deployment>/recordings in the output directory)",
    )


# Catalog commands: list, version, new and build.


def list_command(root: Path, catalog: Catalog, args: argparse.Namespace) -> int:
    return list_deployments(root, catalog, json_output=args.json_output)


def version_command(root: Path, catalog: Catalog, args: argparse.Namespace) -> int:
    return show_version(root, catalog, json_output=args.json_output)


def new_command(root: Path, catalog: Catalog, args: argparse.Namespace) -> int:
    target = create_kit(root, catalog, args.name, args.base, Path.cwd())
    print(f"created: {target}")
    print(f"deployment: {args.name}-{args.base}, which runs {args.base} with the kit's files on top")
    print(f"next: cd {args.name} && openadkit run --verify")
    return 0


def build_command(root: Path, catalog: Catalog, args: argparse.Namespace) -> int:
    if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        raise OpenADKitError(
            "run build without sudo: the build would leave root-owned files"
            " that your next build cannot replace"
        )
    if args.workspace:
        workspace = Path(args.workspace).expanduser().resolve()
    elif catalog.kind == "kit":
        workspace = root / "overlay_ws"
    else:
        raise UsageError("name the workspace to build: openadkit build PATH")
    if not (workspace / "src").is_dir():
        raise OpenADKitError(f"{workspace} has no src/ to build")
    if not holds_packages(workspace):
        print(f"nothing to build: {workspace / 'src'} holds no packages")
        return 0
    ros_distro = args.ros_distro or build_ros_distro(root, catalog)
    image = catalog.devel_image(ros_distro)
    if not image and catalog.images and ros_distro not in catalog.images:
        raise OpenADKitError(
            f"this Open AD Kit does not support ROS distro {ros_distro}; expected {', '.join(sorted(catalog.images))}"
        )
    if not image:
        raise OpenADKitError(f"this release pins no {ros_distro} devel image to build a workspace in")
    compose.require_local_devel_image(catalog, image)
    compose.build_overlay(workspace, image, ros_distro, args.colcon)
    return 0


def build_ros_distro(root: Path, catalog: Catalog) -> str:
    """In a kit, the default distro if every kit deployment runs on it, else
    the first one they all run on."""
    if catalog.kind != "kit":
        return catalog.default_ros_distro
    supported = [get_deployment(root, catalog, name).requirements["rosDistros"] for name in catalog.deployments]
    common = [distro for distro in supported[0] if all(distro in distros for distros in supported)] if supported else []
    return default_ros_distro(catalog, common)


# Deployment commands: validate, config, fetch, run and clean.


def select(root: Path, catalog: Catalog, deployment: Deployment, args: argparse.Namespace) -> Selection:
    """The deployment as this command runs it."""
    warn_if_modified(root, deployment, catalog)
    if catalog.kind == "kit":
        warn_unread_kit_files(root, tuple(catalog.deployments))
    if getattr(args, "ws", None):
        deployment.use_workspace(Path(args.ws).expanduser().resolve())
    compose.ensure_runtime_user()
    return settings.resolve(
        deployment, catalog, getattr(args, "ros_distro", None), getattr(args, "gpu", False),
        role=getattr(args, "role", None), data_only=args.command == "fetch",
    )


def check_deployment(deployment: Deployment, catalog: Catalog, selection: Selection) -> set[str]:
    """What validate and run check before starting anything; the services Compose would start."""
    data.validate_destinations(deployment, selection)
    services = compose.render(deployment, selection)
    compose.check_overlay_build(deployment, selection, catalog.devel_image(selection.ros_distro))
    return services


def validate_command(root: Path, catalog: Catalog, deployment: Deployment, args: argparse.Namespace) -> int:
    selection = select(root, catalog, deployment, args)
    check_deployment(deployment, catalog, selection)
    results = data.check_installed_data(deployment, selection) if args.data else None
    if args.json_output:
        print(json.dumps({
            "schemaVersion": 1,
            "deployment": deployment.name,
            "valid": True,
            "base": deployment.base.name if deployment.base else None,
            "rosDistro": selection.ros_distro,
            "gpu": selection.gpu,
            "role": selection.role,
            "dataValid": None if results is None else all(item["status"] in DATA_USABLE for item in results),
            "data": [{"name": item["name"], "status": item["status"]} for item in results or []],
        }))
    else:
        role = f", role {selection.role}" if selection.role else ""
        gpu = "with GPU" if selection.gpu else "without GPU"
        print(f"{deployment.name} is valid (ROS 2 {selection.ros_distro.capitalize()}, {gpu}{role})")
        for item in results or []:
            status = "your own directory, not checked" if item["status"] == "own" else item["status"]
            print(f"  data {item['name']}: {status} ({item['destination']})")
    if results is not None and any(item["status"] not in DATA_USABLE for item in results):
        report_data_gaps(deployment.name, results)
        return 1
    return 0


def config_command(root: Path, catalog: Catalog, deployment: Deployment, args: argparse.Namespace) -> int:
    selection = select(root, catalog, deployment, args)
    print(compose.run_compose(deployment, selection, ["config", "--format", "json"]).stdout, end="")
    return 0


def protect_outdated_data(deployment: Deployment, selection) -> None:
    """install_data replaces outdated data, which no live container may mount."""
    compose.require_data_unused(
        item["destination"] for item in data.check_installed_data(deployment, selection)
        if item["status"] == "outdated"
    )


def fetch_command(root: Path, catalog: Catalog, deployment: Deployment, args: argparse.Namespace) -> int:
    selection = select(root, catalog, deployment, args)
    if args.force:
        # Replacing data a live container mounts deletes it under that container.
        compose.require_stopped(deployment)
        compose.require_data_unused(item["destination"] for item in data.check_installed_data(deployment, selection))
    else:
        protect_outdated_data(deployment, selection)
    data.install_data(deployment, selection, args.force)
    return 0


def run_command(root: Path, catalog: Catalog, deployment: Deployment, args: argparse.Namespace) -> int:
    selection = select(root, catalog, deployment, args)
    services = check_deployment(deployment, catalog, selection)
    if args.verify and deployment.verify is None:
        raise OpenADKitError(f"{deployment.name} declares no verify step")
    compose.check_daemon(selection)
    # Deployments share host networking, fixed container names and the
    # default DDS domain, so only one runs at a time. Rerunning the same
    # project updates it in place; other roles of it may share this host.
    others = compose.other_projects(deployment)
    if others:
        raise OpenADKitError(
            f"{', '.join(live.display_name(project) for project in others)} is already running; "
            "stop it with openadkit stop before starting this deployment"
        )
    conflict = compose.live_state_conflict(deployment, selection)
    if conflict:
        raise OpenADKitError(conflict)
    # A start that failed, or a Docker that restarted, leaves containers that
    # no longer run but keep their names; they stay until stop, for their logs.
    leftover = compose.stopped_other_projects(deployment, selection.role)
    if leftover:
        raise OpenADKitError(
            f"{', '.join(live.display_name(project) for project in leftover)} left stopped containers on this host; "
            "remove them with openadkit stop before starting this deployment"
        )
    protect_outdated_data(deployment, selection)
    data.install_data(deployment, selection, force=False)
    model = compose.create_writable_mounts(deployment, selection)
    skipped = services & ({"visualizer"} if args.no_visualizer else set())
    compose.require_local_images(catalog, selection, model, services - skipped)
    compose.write_run_state(deployment.project_name(selection.role), {
        "schemaVersion": 1,
        "cli": str(root_path()),
        "kit": str(root) if catalog.kind == "kit" else None,
        "deployment": deployment.name,
        "role": selection.role,
        "rosDistro": selection.ros_distro,
        "gpu": selection.gpu,
        "workspace": str(Path(args.ws).expanduser().resolve()) if args.ws else None,
        "skipped": sorted(skipped),
    })
    started = time.monotonic()
    compose.start(deployment, selection, services, skipped)
    run_report = compose.run_report(deployment, selection, catalog, model, started)
    compose.write_run_report(deployment, run_report)
    print_run_next_steps(
        deployment, services - skipped, selection.role, selection.environment.get("OUTPUT_HOST_PATH"),
        tls=bool(selection.environment.get("NOVNC_CERT")),
    )
    if args.verify:
        return compose.verify(deployment, selection, services - skipped, run_report)
    return 0


def sharing_deployments(root: Path, catalog: Catalog, deployment: Deployment) -> dict[str, list[str]]:
    """The catalog deployments that declare the same data, by resource name.

    They install it to the same place unless a host's settings move one, so
    deleting it for one deletes it for all of them.
    """
    owner, owner_root = (catalog, root) if catalog.extended is None else (catalog.extended, catalog.extended_root)
    assert owner_root is not None
    digests = {resource["name"]: data.source_digest(resource) for resource in deployment.data}
    sharing: dict[str, list[str]] = {}
    for name in sorted(owner.deployments):
        if owner is catalog and name == deployment.name:
            continue
        for resource in get_deployment(owner_root, owner, name).data:
            if digests.get(resource["name"]) == data.source_digest(resource):
                sharing.setdefault(resource["name"], []).append(name)
    return sharing


def clean_command(root: Path, catalog: Catalog, deployment: Deployment, args: argparse.Namespace) -> int:
    if not deployment.data:
        print("no data resources declared")
        return 0
    selection = settings.resolve(deployment, catalog, data_only=True)
    installed = data.check_installed_data(deployment, selection)
    compose.require_stopped(deployment)
    compose.require_data_unused(item["destination"] for item in installed)
    # The user's own directories stay: clean deletes only what the CLI installed.
    present = {
        item["destination"]: item["name"] for item in installed
        if data.is_managed(item["destination"])
    }
    if not present:
        print(f"no data of {deployment.name} is installed")
        return 0
    sharing = sharing_deployments(root, catalog, deployment)
    print("delete:")
    for destination, name in present.items():
        shared = f" (also used by {', '.join(sharing[name])})" if name in sharing else ""
        print(f"  {destination}{shared}")
    if not args.yes:
        if not sys.stdin.isatty():
            raise OpenADKitError("clean deletes data; pass --yes to confirm without a terminal")
        try:
            answer = input("continue? [y/N] ")
        except EOFError:
            answer = ""
            print()
        if answer.strip().lower() not in ("y", "yes"):
            print("nothing deleted")
            return 0
    data.remove_installed_data(deployment, selection)
    return 0


# Live commands act on what runs on this host, from any directory: no deployment name.


def status_command(args: argparse.Namespace) -> int:
    """status and stop: what runs here, and what a stopped stack left behind."""
    projects = live.running_projects(args.role)
    stopped = live.stopped_projects(args.role)
    if not projects and not stopped:
        print("nothing is running" if args.role is None else f"role {args.role} is not running here")
        return 0
    several = len(projects) + len(stopped) > 1
    for project in projects:
        if several:
            print(f"== {live.display_name(project)}", flush=True)
        if args.command == "status":
            live.status(project)
        else:
            live.stop(project)
    for project in stopped:
        if several or args.command == "status":
            print(f"== {live.display_name(project)} (stopped)", flush=True)
        if args.command == "status":
            live.status_stopped(project)
        else:
            live.stop(project)
    if stopped and args.command == "status":
        # stop without a role also stops what still runs here.
        role = stopped[0].partition("_")[2] if len(stopped) == 1 else ""
        print(f"remove the stopped containers with: openadkit stop{f' --role {role}' if role else ''}")
    return 0


def logs_command(args: argparse.Namespace) -> int:
    live.logs(live.running_project(args.role, stopped=True), args.follow, args.services)
    return 0


def restart_command(args: argparse.Namespace) -> int:
    """Recreate services of the running deployment, as run started them but
    with the current settings, config overrides and overlay workspace; from any directory."""
    if args.services and args.all_services:
        raise UsageError("name the services to restart, or pass --all")
    project = live.running_project(args.role)
    state = compose.read_run_state(project)
    if state is None:
        raise OpenADKitError(
            f"{live.display_name(project)} has no record of how it was started; start it again with openadkit run"
        )
    # The CLI that ran the deployment recreates it: it resolves the kit the same way.
    run_with(Path(state["cli"]))
    root, catalog = load_catalog_around(Path(state["kit"]) if state["kit"] else root_path())
    deployment = get_deployment(root, catalog, state["deployment"])
    if state["workspace"]:
        deployment.use_workspace(Path(state["workspace"]))
    selection = settings.resolve(deployment, catalog, state["rosDistro"], state["gpu"], role=state["role"])
    compose.check_overlay_build(deployment, selection, catalog.devel_image(selection.ros_distro))
    skipped = set(state["skipped"])
    running = set(live.running_services(project))
    if args.all_services:
        services = compose.render(deployment, selection) - skipped
    elif args.services:
        # A service that is not up yet, such as a skipped visualizer, is still one to start.
        known = compose.render(deployment, selection)
        services = set(live.resolve_services(project, args.services, known))
    else:
        # What a restart is for: changed config or workspaces, and changed settings.
        services = set(live.hooked_services(project)) | compose.changed_services(deployment, selection)
    if not services:
        raise OpenADKitError(f"{live.display_name(project)} has no service that takes config overrides or an overlay workspace to restart")
    if not args.all_services:
        services |= live.pid_followers(project, services)
    compose.recreate(deployment, selection, services)
    print(f"restarted: {', '.join(sorted(services))}")
    kept = sorted(running - services)
    if kept:
        print(f"kept running: {', '.join(kept)} (restart --all includes them)")
    return 0


def shell_command(args: argparse.Namespace) -> int:
    return live.shell(live.running_project(args.role), args.service, args.command_args)


def record_command(args: argparse.Namespace) -> int:
    if bool(args.topics) == args.all_topics:
        raise UsageError("name the topics to record, or pass --all")
    output = Path(args.output).expanduser().resolve() if args.output else None
    bag = live.record(live.running_project(args.role), args.topics, output)
    print(f"recorded: {bag}")
    return 0


@dataclass(frozen=True)
class Command:
    # install: the launcher runs it, so it has no handler. catalog: needs the kit. deployment: needs
    # a deployment of the kit. live: acts on what runs on this host.
    group: str
    help: str
    handler: Callable[..., int] | None = None
    arguments: Callable[[argparse.ArgumentParser], None] | None = None


COMMANDS = {
    "install": Command("install", "download and install a release bundle"),
    "upgrade": Command("install", "upgrade an installed release to the latest stable version"),
    "setup": Command("install", "install Ubuntu host dependencies"),
    "uninstall": Command("install", "remove the installed release and its launcher"),
    "list": Command("catalog", "list the deployments you can run", list_command, json_argument),
    "version": Command("catalog", "show the Open AD Kit version", version_command, json_argument),
    "validate": Command(
        "deployment", "validate a deployment without starting it", validate_command, validate_arguments
    ),
    "config": Command(
        "deployment", "print a deployment's resolved Compose model as JSON", config_command, selection_arguments
    ),
    "fetch": Command("deployment", "download deployment data", fetch_command, fetch_arguments),
    "run": Command("deployment", "fetch data and start a deployment", run_command, run_arguments),
    "build": Command(
        "catalog", "build an overlay workspace in the pinned devel image", build_command, build_arguments
    ),
    "new": Command("catalog", "create a kit on top of a deployment", new_command, new_arguments),
    "clean": Command("deployment", "delete a deployment's downloaded data", clean_command, clean_arguments),
    "status": Command("live", "show the running deployment", status_command),
    "logs": Command("live", "show the running deployment's logs", logs_command, logs_arguments),
    "restart": Command(
        "live", "recreate services to apply changed settings, config overrides and overlay workspaces", restart_command,
        restart_arguments,
    ),
    "shell": Command(
        "live", "open a shell, or run a command, in a running service with ROS sourced", shell_command,
        shell_arguments,
    ),
    "record": Command(
        "live", "record topics of the running deployment into a bag on the host", record_command, record_arguments
    ),
    "stop": Command("live", "stop and remove the running deployment", status_command),
}

# These act on a kit, so they run with the CLI of the release it pins and
# download that release when it is missing. list, version and new only read
# the kit, and Tab completion asks list for the names: a directory someone else
# wrote must not start a download or a program it names there. They run with
# the pinned release only when it is installed, so an older openadkit never
# has to read a newer release's manifests.
ACTING_COMMANDS = frozenset({"validate", "config", "fetch", "run", "build", "clean"})
READING_COMMANDS = frozenset({"list", "version", "new"})
# Without a deployment name, these act on every deployment of the kit around them.
ALL_DEPLOYMENTS_COMMANDS = frozenset({"validate", "fetch"})

# The launcher runs these itself; main.py sees them only from a broken install.
INSTALL_USAGE = {
    "install": "openadkit install [--version vX.Y.Z] [--force]",
    "upgrade": "openadkit upgrade [--check]",
    "setup": "openadkit setup [--gpu] [--no-check]",
    "uninstall": "openadkit uninstall [--all]",
}


def build_parser() -> OpenADKitParser:
    parser = OpenADKitParser(
        prog="openadkit",
        description="Run Open AD Kit deployments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  openadkit install --version vX.Y.Z\n"
            "  openadkit upgrade\n"
            "  openadkit setup\n"
            "  openadkit list\n"
            "  openadkit run planning-simulation\n"
            "  openadkit run logging-simulation --gpu\n"
            "  openadkit stop"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", parser_class=OpenADKitParser)
    parser.commands = subparsers.choices
    for name, command in COMMANDS.items():
        # Not capitalize(): it would lower the case of ROS, Compose and JSON.
        description = command.help[0].upper() + command.help[1:] + "."
        subparser = subparsers.add_parser(name, help=command.help, description=description)
        if command.arguments:
            command.arguments(subparser)
        if command.group == "deployment":
            subparser.help_inventory = "catalog"
        if command.group == "live":
            subparser.add_argument("--role", metavar="ROLE", help=LIVE_ROLE_HELP)
        if command.group != "install":
            subparser.add_argument("--verbose", action="store_true", help=VERBOSE_HELP)
    return parser


def handle_each(handler: Callable[..., int], root: Path, catalog: Catalog, args: argparse.Namespace) -> list[int]:
    """Run a command on every deployment of a kit: one that fails does not hide the next."""
    results = []
    for name in catalog.deployments:
        try:
            results.append(handler(root, catalog, get_deployment(root, catalog, name), args))
        except UsageError:
            raise
        except OpenADKitError as error:
            print(f"error: {name}: {error}", file=sys.stderr)
            results.append(1)
    return results


def command_and_target(parser: OpenADKitParser, arguments: list[str]) -> tuple[str | None, str | None]:
    """The command and the deployment or workspace it names, read before parsing."""
    words = iter(arguments)
    name = next((word for word in words if not word.startswith("-")), None)
    if name not in COMMANDS or COMMANDS[name].group not in ("catalog", "deployment"):
        return name, None
    takes_value = {
        flag for action in parser.commands[name]._actions if action.nargs != 0 for flag in action.option_strings
    }
    for word in words:
        if word in takes_value:
            next(words, None)
        elif not word.startswith("-"):
            return name, word
    return name, None


def hand_over_before_parsing(parser: OpenADKitParser, arguments: list[str]) -> None:
    """Run a kit's command with the CLI of the release it pins before reading
    its options: this CLI may be older and not know them.

    The kit is the one around the deployment or workspace the command names by
    its directory, or else around the working directory. Only a command that
    acts or reads the kit hands over, and never to print its help.
    """
    name, target = command_and_target(parser, arguments)
    if name not in ACTING_COMMANDS | READING_COMMANDS or {"-h", "--help"} & set(arguments):
        return
    start = Path(target).expanduser().resolve() if target and is_path(target) else Path.cwd()
    hand_over(start, act=name in ACTING_COMMANDS)


def main() -> int:
    arguments = sys.argv[1:]
    # `build ... -- ARGS` hands ARGS to colcon build as they are.
    colcon: list[str] = []
    if arguments[:1] == ["build"] and "--" in arguments:
        split = arguments.index("--")
        arguments, colcon = arguments[:split], arguments[split + 1:]
    parser = build_parser()
    try:
        hand_over_before_parsing(parser, arguments)
        args = parser.parse_args(arguments)
        args.colcon = colcon
        return dispatch(parser, args)
    except OpenADKitError as error:
        name, target = command_and_target(parser, arguments)
        if name != "validate" or "--json" not in arguments:
            raise
        # validate --json: one JSON document on stdout, also when the kit or
        # the deployment is invalid.
        print(json.dumps({"schemaVersion": 1, "deployment": target, "valid": False, "error": str(error)}))
        report(error)
        return 2 if isinstance(error, UsageError) else 1


def dispatch(parser: OpenADKitParser, args: argparse.Namespace) -> int:
    """Run the parsed command."""
    if getattr(args, "verbose", False):
        os.environ["OPENADKIT_VERBOSE"] = "1"
    if not args.command:
        parser.print_help()
        return 2
    command = COMMANDS[args.command]
    handler = command.handler
    if handler is None:
        print(f"error: run: {INSTALL_USAGE[args.command]}", file=sys.stderr)
        return 2
    if command.group == "live":
        compose.ensure_runtime_user()
        compose.require_docker()
        return handler(args)

    # A deployment or workspace named by its directory belongs to the kit around it.
    target = getattr(args, "deployment", None) or getattr(args, "workspace", None)
    start = Path(target).expanduser().resolve() if target and is_path(target) else Path.cwd()
    root, catalog = load_catalog_around(start, act=args.command in ACTING_COMMANDS)
    if command.group == "catalog":
        return handler(root, catalog, args)
    kit_argument = None
    if args.deployment and catalog.kind == "kit" and is_path(args.deployment) and start == root.resolve():
        # A kit named by its directory is the kit, as when the command runs inside it.
        kit_argument, args.deployment = args.deployment, None
    if not args.deployment and catalog.kind == "kit" and len(catalog.deployments) == 1:
        # A kit made by `openadkit new` is one deployment; naming it again adds nothing.
        args.deployment = next(iter(catalog.deployments))
    json_output = getattr(args, "json_output", False)
    if not args.deployment and catalog.kind == "kit" and args.command in ALL_DEPLOYMENTS_COMMANDS and not json_output:
        # Checking a kit, or fetching its data, covers each of its deployments.
        return max(handle_each(handler, root, catalog, args))
    if not args.deployment:
        if kit_argument:
            # From outside the kit, only its directory names a deployment.
            names = ", ".join(
                f"{kit_argument.rstrip('/')}/{KIT_DEPLOYMENTS_DIRECTORY}/{name}" for name in catalog.deployments
            )
            raise UsageError(f"{kit_argument} has several deployments; name one by its directory: {names}")
        if json_output:
            # One JSON document covers one deployment.
            raise UsageError(f"deployment name required; available: {available_deployments(catalog)}")
        require_deployment_name(args.command)
        list_deployments(root, catalog)
        return 2
    deployment = get_deployment(root, catalog, deployment_name(root, catalog, args.deployment))
    return handler(root, catalog, deployment, args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UsageError as error:
        report(error)
        raise SystemExit(2) from None
    except OpenADKitError as error:
        report(error)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        # Ctrl+C (for example during `logs --follow`) is a normal way to stop.
        print(file=sys.stderr)
        raise SystemExit(130) from None
    except PermissionError as error:
        print(f"error: permission denied: {error.filename or error}", file=sys.stderr)
        print("hint: check that your user owns this path", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError as error:
        report(error)
        raise SystemExit(1) from None
