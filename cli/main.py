#!/usr/bin/env python3
"""Open AD Kit command-line parser and runtime orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

import compose
import data
from manifest import (
    OpenADKitError,
    RuntimeContext,
    deployment_integrity,
    get_deployment,
    load_json,
    load_kit,
    require_string,
    resolve_extends,
    root_path,
)


def find_kit(start: Path) -> Path | None:
    """The integrator kit around the working directory, if any.

    Like git, the nearest openadkit.json wins; it is a kit only when its kind
    is "kit". OPENADKIT_KIT names the kit directly.
    """
    explicit = os.environ.get("OPENADKIT_KIT")
    if explicit:
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


def load_context(start: Path) -> tuple[Path, RuntimeContext]:
    """The kit around start, run by the CLI of the Open AD Kit it pins."""
    cli_root = root_path()
    kit_root = find_kit(start)
    if kit_root is None:
        return cli_root, load_kit(cli_root)
    # Hand over before reading anything else: only the pinned release's CLI
    # is guaranteed to understand that release's manifests.
    base_root = resolve_extends(kit_root, read_extends(kit_root))
    if base_root != cli_root:
        if os.environ.get("OPENADKIT_DELEGATED"):
            raise OpenADKitError(f"{base_root}/openadkit did not run this kit as its own CLI")
        launcher = base_root / "openadkit"
        if not launcher.is_file():
            raise OpenADKitError(f"{base_root} has no openadkit launcher")
        environment = os.environ | {
            "OPENADKIT_KIT": str(kit_root),
            "OPENADKIT_DELEGATED": "1",
        }
        os.execve(launcher, [str(launcher), *sys.argv[1:]], environment)
    return kit_root, load_kit(kit_root)


class OpenADKitParser(argparse.ArgumentParser):
    help_inventory: str | None = None

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(2)

    def print_help(self, file=None) -> None:
        super().print_help(file)
        if self.help_inventory != "catalog":
            return
        try:
            root, kit = load_context(Path.cwd())
        except OpenADKitError:
            return
        print(file=file)
        list_deployments(root, kit)


def add_node_argument(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument("--node", metavar="NODE", help=help_text)


NODE_HELP = "node from this deployment's manifest (omit for single host)"
LIVE_NODE_HELP = "node to act on when several nodes run on this host"


def add_run_arguments(parser: argparse.ArgumentParser, *, gpu: bool = True) -> None:
    parser.add_argument(
        "deployment",
        nargs="?",
        help="deployment name or directory; omit to print the catalog",
    )
    parser.add_argument(
        "--ros-distro",
        metavar="DISTRO",
        help="ROS distro (default: bundle default)",
    )
    if gpu:
        parser.add_argument(
            "--gpu",
            action="store_true",
            help="use the GPU compose overlay when the deployment provides one",
        )


def add_workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ws", metavar="PATH",
        help="mount this built workspace as the overlay, for a deployment without its own",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = OpenADKitParser(
        prog="openadkit",
        description="Run Open AD Kit deployments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  openadkit install --version vX.Y.Z\n"
            "  openadkit upgrade\n"
            "  openadkit setup --verify\n"
            "  openadkit list\n"
            "  openadkit run planning-simulation\n"
            "  openadkit run logging-simulation --gpu\n"
            "  openadkit stop"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", parser_class=OpenADKitParser)
    subparsers.add_parser(
        "install", help="download and install a release bundle"
    )
    subparsers.add_parser(
        "upgrade", help="upgrade an installed release to the latest stable version"
    )
    subparsers.add_parser(
        "setup", help="install Ubuntu host dependencies"
    )
    subparsers.add_parser(
        "uninstall", help="remove the installed release and its launcher"
    )
    list_parser = subparsers.add_parser("list", help="list curated deployments")
    list_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="print machine-readable JSON",
    )
    version_parser = subparsers.add_parser(
        "version", help="show repository or release version"
    )
    version_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="print machine-readable JSON",
    )

    validate = subparsers.add_parser(
        "validate", help="validate a deployment without starting it"
    )
    add_run_arguments(validate)
    add_node_argument(validate, NODE_HELP)
    add_workspace_argument(validate)
    validate.add_argument(
        "--data",
        action="store_true",
        help="also check that the deployment's downloaded data is complete",
    )
    validate.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="print machine-readable JSON",
    )

    config = subparsers.add_parser(
        "config", help="print a deployment's resolved Compose model as JSON"
    )
    add_run_arguments(config)
    add_node_argument(config, NODE_HELP)
    add_workspace_argument(config)

    fetch = subparsers.add_parser("fetch", help="download deployment data")
    add_run_arguments(fetch, gpu=False)
    fetch.add_argument(
        "--force",
        action="store_true",
        help="replace existing data even if it already validates",
    )

    run = subparsers.add_parser("run", help="fetch data and start a deployment")
    add_run_arguments(run)
    add_node_argument(run, NODE_HELP)
    add_workspace_argument(run)
    run.add_argument(
        "--pull",
        choices=("missing", "always", "never"),
        default="missing",
        help="image pull policy (default: missing)",
    )
    run.add_argument(
        "--no-visualizer",
        action="store_true",
        help="start without the visualizer, for hosts nobody watches",
    )
    run.add_argument(
        "--verify",
        action="store_true",
        help="once ready, run the deployment's verify step (the CI end-to-end check) and exit with its result",
    )
    build = subparsers.add_parser(
        "build", help="build an overlay workspace in the pinned devel image"
    )
    build.add_argument(
        "workspace", nargs="?", metavar="PATH",
        help="workspace with a src/ directory (default: the kit's overlay_ws)",
    )
    build.add_argument("--ros-distro", metavar="DISTRO", help="ROS distro (default: bundle default)")

    clean = subparsers.add_parser("clean", help="delete a deployment's downloaded data")
    clean.add_argument(
        "deployment",
        nargs="?",
        help="deployment name or directory; omit to print the catalog",
    )
    for catalog in (validate, config, fetch, run, clean):
        catalog.help_inventory = "catalog"

    # These act on what runs on this host, from any directory: no deployment name.
    status = subparsers.add_parser("status", help="show the running deployment")
    logs = subparsers.add_parser("logs", help="show the running deployment's logs")
    logs.add_argument("services", nargs="*", metavar="SERVICE", help="only these services")
    logs.add_argument("--follow", action="store_true", help="stream logs")
    restart = subparsers.add_parser(
        "restart",
        help="restart services so they reread config and overlay workspaces",
    )
    restart.add_argument(
        "services", nargs="*", metavar="SERVICE",
        help="services to restart (default: every service with Open AD Kit config)",
    )
    restart.add_argument(
        "--all", action="store_true", dest="all_services",
        help="restart the whole deployment, one-shot services included",
    )
    shell = subparsers.add_parser(
        "shell", help="open a shell, or run a command, in a running service with ROS sourced"
    )
    shell.add_argument("service", nargs="?", default="api", help="service (default: api)")
    shell.add_argument("command_args", nargs=argparse.REMAINDER, metavar="COMMAND", help="command to run")
    record = subparsers.add_parser(
        "record", help="record topics of the running deployment into a bag on the host"
    )
    record.add_argument("topics", nargs="*", metavar="TOPIC", help="topics to record")
    record.add_argument("--all", action="store_true", dest="all_topics", help="record every topic")
    record.add_argument(
        "--output",
        metavar="DIRECTORY",
        help="where bags go (default: ~/openadkit-output/<deployment>/recordings)",
    )
    stop = subparsers.add_parser("stop", help="stop and remove the running deployment")
    for operational in (status, logs, restart, shell, record, stop):
        add_node_argument(operational, LIVE_NODE_HELP)
    return parser


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
    root, kit, names: list[str] | None = None, *, json_output: bool = False
) -> int:
    selected = list(kit.deployments if names is None else names)
    if not selected:
        if json_output:
            print(json.dumps({"schemaVersion": 1, "deployments": []}))
        else:
            print("No deployments found.")
        return 0
    entries: list[dict[str, object]] = []
    for name in selected:
        try:
            deployment = get_deployment(root, kit, name)
            entries.append(
                {
                    "name": name,
                    "kind": deployment_integrity(root, deployment, kit),
                    "gpu": deployment.requirements["gpu"],
                    "description": deployment.manifest["description"],
                }
            )
        except OpenADKitError as error:
            entries.append(
                {
                    "name": name,
                    "kind": "invalid",
                    "gpu": None,
                    "description": None,
                    "error": str(error).replace("\n", " "),
                }
            )
    if json_output:
        print(json.dumps({"schemaVersion": 1, "deployments": entries}))
        return 0
    rows = [
        (
            str(entry["name"]),
            str(entry["kind"]),
            "" if entry["gpu"] is None else str(entry["gpu"]),
            str(entry.get("error") or entry.get("description") or ""),
        )
        for entry in entries
    ]
    _print_table(("NAME", "KIND", "GPU", "DESCRIPTION"), rows)
    return 0


def is_path(argument: str) -> bool:
    """A deployment or workspace named by its directory, such as ./my-kit."""
    return "/" in argument or argument.startswith(".")


def deployment_name(root: Path, kit: RuntimeContext, argument: str) -> str:
    if not is_path(argument):
        return argument
    directory = Path(argument).expanduser().resolve()
    for name, reference in kit.deployments.items():
        if (root / reference.path).resolve() == directory:
            return name
    raise OpenADKitError(f"{argument} is not a deployment of {root}")


def require_deployment_name(command: str, extra: str = "") -> None:
    print("error: deployment name required", file=sys.stderr)
    suffix = f" {extra}" if extra else ""
    print(f"usage: openadkit {command} <deployment>{suffix}", file=sys.stderr)
    print(file=sys.stderr)


def autoware_line(autoware: dict[str, Any]) -> str:
    backports = len(autoware.get("backports", []))
    fixes = f", {backports} backported fix{'es' if backports > 1 else ''}" if backports else ""
    return f"autoware: {autoware['version']} ({autoware['ref']}{fixes})"


def show_version(root, kit, *, json_output: bool = False) -> int:
    if kit.kind == "release":
        version = kit.version
        commit = None
    else:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
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
                    "bundle": kit.kind,
                    "version": version,
                    "commit": commit,
                    "extends": kit.extends,
                    "bom": kit.bom(),
                }
            )
        )
        return 0
    if kit.extends is not None:
        print(f"kit: {root}")
        print(f"extends: Open AD Kit {kit.extends} ({kit.base_root})")
        if kit.autoware:
            print(autoware_line(kit.autoware))
    elif kit.kind == "release":
        autoware = f" · Autoware {kit.autoware['version']}" if kit.autoware else ""
        print(f"Open AD Kit {kit.version or 'unknown'}{autoware}")
        print("bundle: release")
        if kit.autoware:
            print(autoware_line(kit.autoware))
    else:
        print("Open AD Kit development")
        print(f"commit: {commit or 'unknown'}")
        print("bundle: repository")
    return 0


def warn_if_modified(root, deployment, kit) -> None:
    if deployment_integrity(root, deployment, kit) == "modified":
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


def output_path(selection) -> str | None:
    """Where the deployment writes results (resolved by compose.resolve_settings)."""
    return selection.environment.get("OUTPUT_HOST_PATH") or None


def report_data_gaps(deployment_name: str, results: list[dict[str, object]]) -> None:
    gaps = [item for item in results if item["status"] != "ok"]
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
        state = "outdated" if all(item["status"] == "outdated" for item in gaps) else "incomplete"
        print(
            f"error: installed data is {state}; run: "
            f"openadkit fetch {deployment_name} --force",
            file=sys.stderr,
        )
    elif any(item["recovery"] == "fetch" for item in gaps):
        print(
            "error: installed data is missing; run: "
            f"openadkit fetch {deployment_name}",
            file=sys.stderr,
        )


def print_run_next_steps(
    deployment, services: set[str], node: str | None, output: str | None, *, tls: bool = False
) -> None:
    target = deployment.name if node is None else f"{deployment.name} --node {node}"
    print(f"running: {target}")
    if "visualizer" in services:
        print(compose.visualizer_address(tls))
        print(
            "password: REMOTE_PASSWORD (default openadkit; override in "
            f"{deployment.site_config})"
        )
    if output:
        print(f"output: {output}")
    print("stop with: openadkit stop")


OPERATIONAL_COMMANDS = ("status", "logs", "restart", "shell", "record", "stop")


def operate(args: argparse.Namespace) -> int:
    compose.ensure_runtime_user()
    compose.require_docker()
    if args.command == "record" and bool(args.topics) == args.all_topics:
        raise OpenADKitError("name the topics to record, or pass --all")
    if args.command == "restart" and args.services and args.all_services:
        raise OpenADKitError("name the services to restart, or pass --all")
    if args.command in ("status", "stop"):
        projects = compose.live_views(args.node)
        if not projects:
            print("nothing is running" if args.node is None else f"node {args.node} is not running here")
            return 0
        for project in projects:
            if len(projects) > 1:
                print(f"== {compose.view_name(project)}")
            if args.command == "status":
                compose.status(project)
            else:
                compose.stop(project)
        return 0
    project = compose.live_view(args.node)
    if args.command == "logs":
        compose.logs(project, args.follow, args.services)
    elif args.command == "restart":
        restarted, kept = compose.restart(project, args.services, args.all_services)
        print(f"restarted: {', '.join(restarted)}")
        if kept:
            print(f"kept running: {', '.join(kept)} (restart --all includes them)")
    elif args.command == "shell":
        compose.shell(project, args.service, args.command_args)
    else:
        output = Path(args.output).expanduser().resolve() if args.output else None
        bag = compose.record(project, args.topics, output)
        print(f"recorded: {bag}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 2
    if args.command in ("install", "upgrade", "setup", "uninstall"):
        usage = {
            "install": "openadkit install [--version vX.Y.Z] [--destination DIRECTORY] [--force]",
            "upgrade": "openadkit upgrade [--check]",
            "setup": "openadkit setup [--gpu] [--verify]",
            "uninstall": "openadkit uninstall [--all]",
        }[args.command]
        print(f"error: run: {usage}", file=sys.stderr)
        return 2

    if args.command in OPERATIONAL_COMMANDS:
        return operate(args)

    # A deployment or workspace named by its directory belongs to the kit around it.
    target = getattr(args, "deployment", None) or getattr(args, "workspace", None)
    start = Path(target).expanduser().resolve() if target and is_path(target) else Path.cwd()
    root, kit = load_context(start)

    if args.command == "list":
        return list_deployments(root, kit, json_output=args.json_output)
    if args.command == "version":
        return show_version(root, kit, json_output=args.json_output)

    if args.command == "build":
        if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
            raise OpenADKitError(
                "run build without sudo: the build would leave root-owned files"
                " that your next build cannot replace"
            )
        if args.workspace:
            workspace = Path(args.workspace).expanduser().resolve()
        elif kit.kind == "kit":
            workspace = root / "overlay_ws"
        else:
            raise OpenADKitError("name the workspace to build: openadkit build PATH")
        if not (workspace / "src").is_dir():
            raise OpenADKitError(f"{workspace} has no src/ to build")
        ros_distro = args.ros_distro or kit.default_ros_distro
        image = os.environ.get("DEVEL_IMAGE") or kit.devel_image(ros_distro)
        if not image:
            raise OpenADKitError(
                f"this Open AD Kit pins no {ros_distro} devel image; set DEVEL_IMAGE to the "
                "universe-common-devel image of the build your runtime images come from"
            )
        compose.build_overlay(workspace, image, ros_distro)
        return 0

    if not args.deployment:
        require_deployment_name(args.command)
        list_deployments(root, kit, json_output=getattr(args, "json_output", False))
        return 2
    deployment = get_deployment(root, kit, deployment_name(root, kit, args.deployment))

    if args.command == "clean":
        if not deployment.data:
            print("no data resources declared")
            return 0
        selection = compose.resolve_settings(deployment, deployment.select(kit, None, False, operational=True))
        installed = data.check_installed_data(deployment, selection, include_gpu=True)
        if not installed:
            print("no data resources declared")
            return 0
        compose.require_stopped(deployment.name)
        compose.require_data_unused(item["destination"] for item in installed)
        data.remove_installed_data(deployment, selection, include_gpu=True)
        return 0

    if args.command in ("fetch", "validate", "config", "run"):
        warn_if_modified(root, deployment, kit)
        if getattr(args, "ws", None):
            deployment.use_workspace(Path(args.ws).expanduser().resolve())
        compose.ensure_runtime_user()
        selection = deployment.select(
            kit,
            args.ros_distro,
            getattr(args, "gpu", False),
            node=getattr(args, "node", None),
            require_gpu=args.command != "fetch",
        )
        selection = compose.resolve_settings(deployment, selection)
        if args.command == "fetch":
            if args.force:
                # Replacing data a live container mounts deletes it under that container.
                compose.require_stopped(deployment.name)
                compose.require_data_unused(
                    item["destination"]
                    for item in data.check_installed_data(deployment, selection, include_gpu=True)
                )
            data.install_data(deployment, selection, args.force, include_gpu=True)
            return 0

        if args.command == "config":
            print(compose.compose_capture(deployment, selection, ["config", "--format", "json"]).stdout, end="")
            return 0

        data.validate_destinations(deployment, selection)
        configured_services = compose.render(deployment, selection)
        compose.check_overlay_build(deployment, selection, kit.devel_image(selection.ros_distro))
        if args.command == "validate":
            mode = "gpu" if selection.gpu else "cpu"
            results: list[dict[str, Any]] | None = (
                data.check_installed_data(deployment, selection)
                if args.data
                else None
            )
            if args.json_output:
                print(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "deployment": deployment.name,
                            "manifestValid": True,
                            "base": deployment.base.name if deployment.base else None,
                            "rosDistro": selection.ros_distro,
                            "gpu": selection.gpu,
                            "node": selection.node,
                            "dataValid": (
                                None
                                if results is None
                                else all(item["status"] == "ok" for item in results)
                            ),
                            "data": [
                                {"name": item["name"], "status": item["status"]}
                                for item in results or []
                            ],
                        }
                    )
                )
            else:
                print(f"valid: {deployment.name} ({selection.ros_distro}, {mode})")
                for item in results or []:
                    print(
                        f"data: {item['name']} {item['status']} "
                        f"({item['destination']})"
                    )
            if results is not None and any(
                item["status"] != "ok" for item in results
            ):
                report_data_gaps(deployment.name, results)
                return 1
            return 0

        if getattr(args, "verify", False) and deployment.verify is None:
            raise OpenADKitError(f"{deployment.name} declares no verify step")
        compose.check_daemon(selection)
        # Deployments share host networking, fixed container names and the
        # default DDS domain, so only one runs at a time. Rerunning the same
        # view updates it in place; other nodes of it may share this host.
        others = compose.other_projects(deployment)
        if others:
            raise OpenADKitError(
                f"{', '.join(others)} is already running; "
                "stop it with openadkit stop before starting this deployment"
            )
        conflict = compose.live_state_conflict(deployment, selection)
        if conflict:
            raise OpenADKitError(conflict)
        data.install_data(deployment, selection, force=False)
        model = compose.create_writable_mounts(deployment, selection)
        skipped = configured_services & ({"visualizer"} if args.no_visualizer else set())
        started = time.monotonic()
        compose.start(deployment, selection, args.pull, configured_services, skipped)
        record = compose.run_record(deployment, selection, kit, model, started)
        compose.write_run_record(deployment, record)
        print_run_next_steps(
            deployment, configured_services - skipped, selection.node, output_path(selection),
            tls=bool(selection.environment.get("NOVNC_CERT")),
        )
        if args.verify:
            return compose.verify(deployment, selection, configured_services - skipped, record)
        return 0

    raise AssertionError(args.command)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OpenADKitError as error:
        print(f"error: {error}", file=sys.stderr)
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
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
