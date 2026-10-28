#!/usr/bin/env python3
"""Open AD Kit command-line parser and runtime orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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


def load_context() -> tuple[Path, RuntimeContext]:
    """The kit to act on, run by the CLI of the Open AD Kit it pins."""
    cli_root = root_path()
    kit_root = find_kit(Path.cwd())
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
            root, kit = load_context()
        except OpenADKitError:
            return
        print(file=file)
        list_deployments(root, kit)


def add_node_argument(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument("--node", metavar="NODE", help=help_text)


NODE_HELP = "node from this deployment's manifest (omit for single host)"
LIVE_NODE_HELP = "node to act on when several nodes of the deployment run here"


def add_run_arguments(parser: argparse.ArgumentParser, *, gpu: bool = True) -> None:
    parser.add_argument(
        "deployment",
        nargs="?",
        help="curated deployment name; omit to print the catalog",
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
            "  openadkit stop planning-simulation"
        ),
    )
    parser.add_argument(
        "--version",
        action="store_true",
        dest="show_version",
        help="show version information and exit",
    )
    subparsers = parser.add_subparsers(dest="command", parser_class=OpenADKitParser)
    subparsers.add_parser(
        "install", help="downloads and installs a release bundle"
    )
    subparsers.add_parser(
        "upgrade", help="upgrades an installed release to the latest stable version"
    )
    subparsers.add_parser(
        "setup", help="installs Ubuntu host dependencies"
    )
    subparsers.add_parser(
        "uninstall", help="removes the installed release and its launcher"
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
    build_overlay = subparsers.add_parser(
        "build-overlay",
        help="build overlay workspaces in the pinned devel image (in a kit, its own without a deployment)",
    )
    add_run_arguments(build_overlay, gpu=False)
    for catalog in (validate, fetch, run, build_overlay):
        catalog.help_inventory = "catalog"

    clean = subparsers.add_parser(
        "clean", help="remove downloaded data for a deployment"
    )
    clean.add_argument(
        "deployment",
        nargs="?",
        help="curated deployment name; omit to print the catalog",
    )
    clean.add_argument(
        "--data",
        action="store_true",
        help="delete the deployment's downloaded data",
    )

    status = subparsers.add_parser("status", help="show deployment status")
    status.add_argument(
        "deployment",
        nargs="?",
        help="curated deployment name; required when one is running",
    )
    logs = subparsers.add_parser("logs", help="show deployment logs")
    logs.add_argument(
        "deployment",
        nargs="?",
        help="curated deployment name; required when one is running",
    )
    logs.add_argument("services", nargs="*", metavar="SERVICE", help="only these services")
    logs.add_argument("--follow", action="store_true", help="stream logs")
    record = subparsers.add_parser(
        "record", help="record topics of a running deployment into a bag on the host"
    )
    record.add_argument(
        "deployment",
        nargs="?",
        help="curated deployment name; required when one is running",
    )
    record.add_argument("topics", nargs="*", metavar="TOPIC", help="topics to record")
    record.add_argument("--all", action="store_true", dest="all_topics", help="record every topic")
    record.add_argument(
        "--output",
        metavar="DIRECTORY",
        default="~/openadkit-recordings",
        help="where bags go (default: ~/openadkit-recordings)",
    )
    stop = subparsers.add_parser("stop", help="stop and remove a deployment")
    stop.add_argument(
        "deployment",
        nargs="?",
        help="curated deployment name; required when one is running",
    )
    for operational in (status, logs, stop, record):
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


def require_deployment_name(command: str, extra: str = "") -> None:
    print("error: deployment name required", file=sys.stderr)
    suffix = f" {extra}" if extra else ""
    print(f"usage: openadkit {command} <deployment>{suffix}", file=sys.stderr)
    print(file=sys.stderr)


def show_running(root, kit, command: str, running: list[str], *, extra: str = "") -> int:
    if not running:
        print("no running deployments")
        return 0
    require_deployment_name(command, extra)
    list_deployments(root, kit, running)
    return 2


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
    legacy = deployment.directory / "config.local.env"
    if legacy.exists():
        print(
            f"warning: {legacy} is no longer read; move its settings to "
            f"{deployment.site_config}",
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
        # Plain HTTP unless the site gives noVNC its own certificate.
        print(f"visualizer: {'https' if tls else 'http'}://localhost:6080/vnc.html")
        print(
            "password: REMOTE_PASSWORD (default openadkit; override in "
            f"{deployment.site_config})"
        )
    if output:
        print(f"output: {output}")
    print(f"stop with: openadkit stop {target}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.show_version:
        root, kit = load_context()
        return show_version(root, kit)
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

    root, kit = load_context()

    if args.command == "list":
        return list_deployments(root, kit, json_output=args.json_output)
    if args.command == "version":
        return show_version(root, kit, json_output=args.json_output)

    if args.command == "clean":
        if not args.deployment:
            require_deployment_name("clean", "--data")
            list_deployments(root, kit)
            return 2
        deployment = get_deployment(root, kit, args.deployment)
        selection = deployment.select(kit, None, False, operational=True)
        if deployment.data:
            selection = compose.resolve_settings(deployment, selection)
        installed = data.check_installed_data(
            deployment, selection, include_gpu=True
        )
        if not args.data:
            if not installed:
                print("no data resources declared")
                return 0
            for item in installed:
                print(
                    f"{item['name']}: {item['status']} ({item['destination']})"
                )
            return 0
        compose.require_stopped(deployment.name)
        compose.require_data_unused(item["destination"] for item in installed)
        data.remove_installed_data(deployment, selection, include_gpu=True)
        return 0

    if args.command == "build-overlay":
        if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
            raise OpenADKitError(
                "run build-overlay without sudo: the build would leave root-owned files"
                " that your next build cannot replace"
            )
        if args.deployment:
            deployment = get_deployment(root, kit, args.deployment)
            ros_distro = deployment.select(kit, args.ros_distro, False, require_gpu=False).ros_distro
            workspaces = compose.overlay_workspaces(deployment)
            owner = deployment.name
        elif kit.kind == "kit":
            # The kit's workspace serves all of its deployments: no name needed.
            ros_distro = args.ros_distro or kit.default_ros_distro
            workspaces = [
                (path, compose.OVERLAY_TARGETS["OPENADKIT_OVERLAY_WS"])
                for path in [root / "overlay_ws"]
                if (path / "src").is_dir()
            ]
            owner = "this kit"
        else:
            require_deployment_name(args.command)
            list_deployments(root, kit)
            return 2
        if not workspaces:
            raise OpenADKitError(f"{owner} has no overlay_ws/src to build")
        image = os.environ.get("DEVEL_IMAGE") or kit.devel_image(ros_distro)
        if not image:
            raise OpenADKitError(
                f"this Open AD Kit pins no {ros_distro} devel image; set DEVEL_IMAGE to the "
                "universe-common-devel image of the build your runtime images come from"
            )
        compose.build_overlay(workspaces, image, ros_distro)
        return 0

    if args.command in ("fetch", "validate", "run"):
        if not args.deployment:
            require_deployment_name(args.command)
            list_deployments(
                root, kit, json_output=getattr(args, "json_output", False)
            )
            return 2
        deployment = get_deployment(root, kit, args.deployment)
        warn_if_modified(root, deployment, kit)
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

        data.validate_destinations(deployment, selection)
        configured_services = compose.render(deployment, selection)
        overlay_warnings = compose.check_overlay(deployment, selection, kit)
        compose.check_overlay_builds(deployment, selection, kit.devel_image(selection.ros_distro))
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
                            "overlayConformant": not overlay_warnings,
                            "overlayWarnings": overlay_warnings,
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

        compose.check_daemon(selection)
        # Deployments share host networking, fixed container names and the
        # default DDS domain, so only one runs at a time. Rerunning the same
        # view updates it in place; other nodes of it may share this host.
        others = compose.other_projects(deployment)
        if others:
            raise OpenADKitError(
                f"{', '.join(others)} is already running; "
                "stop it from its owning kit before starting this deployment"
            )
        conflict = compose.live_state_conflict(deployment, selection)
        if conflict:
            raise OpenADKitError(conflict)
        data.install_data(deployment, selection, force=False)
        compose.create_writable_mounts(deployment, selection)
        skipped = configured_services & ({"visualizer"} if args.no_visualizer else set())
        compose.start(deployment, selection, args.pull, configured_services, skipped)
        print_run_next_steps(
            deployment, configured_services - skipped, selection.node, output_path(selection),
            tls=bool(selection.environment.get("NOVNC_CERT")),
        )
        return 0

    compose.ensure_runtime_user()
    compose.require_docker()
    if not args.deployment:
        extra = "--follow" if args.command == "logs" and args.follow else ""
        running = compose.running_names(kit.deployments)
        if extra and not running:
            require_deployment_name(args.command, extra)
            print("no running deployments")
            return 2
        return show_running(root, kit, args.command, running, extra=extra)
    deployment = get_deployment(root, kit, args.deployment)
    warn_if_modified(root, deployment, kit)
    node = args.node
    if node is None:
        live = compose.live_nodes(deployment)
        if len(live) > 1:
            names = ", ".join(compose.view_label(item) for item in live)
            raise OpenADKitError(
                f"{deployment.name} runs as {names}; choose one with --node"
            )
        node = live[0] if live else None
    selection = deployment.select(kit, None, False, node=node, operational=True)
    if args.command == "status":
        compose.status(deployment, selection)
    elif args.command == "logs":
        compose.logs(deployment, selection, args.follow, args.services)
    elif args.command == "record":
        if bool(args.topics) == args.all_topics:
            raise OpenADKitError("name the topics to record, or pass --all")
        if not compose.live_nodes(deployment):
            raise OpenADKitError(f"{deployment.name} is not running")
        bag = compose.record(
            deployment, selection, args.topics, Path(args.output).expanduser().resolve()
        )
        print(f"recorded: {bag}")
    elif args.command == "stop":
        compose.stop(deployment, selection)
    return 0


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
