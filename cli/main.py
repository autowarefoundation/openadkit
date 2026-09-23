#!/usr/bin/env python3
"""Open AD Kit command-line parser and runtime orchestrator."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

import compose
import data
from manifest import (
    OpenADKitError,
    deployment_integrity,
    get_deployment,
    load_kit,
    root_path,
)


class OpenADKitParser(argparse.ArgumentParser):
    help_inventory = None

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(2)

    def print_help(self, file=None) -> None:
        super().print_help(file)
        if self.help_inventory != "catalog":
            return
        try:
            root = root_path()
            kit = load_kit(root)
        except OpenADKitError:
            return
        print(file=file)
        list_deployments(root, kit)


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
    run.add_argument(
        "--pull",
        choices=("missing", "always", "never"),
        default="missing",
        help="image pull policy (default: missing)",
    )
    run.add_argument(
        "--force",
        action="store_true",
        help="replace existing data even if it already validates",
    )
    for catalog in (validate, fetch, run):
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
        help="curated deployment name from list; omit to list running",
    )
    logs = subparsers.add_parser("logs", help="show deployment logs")
    logs.add_argument(
        "deployment",
        nargs="?",
        help="curated deployment name from list; omit to list running",
    )
    logs.add_argument("--follow", action="store_true", help="stream logs")
    stop = subparsers.add_parser("stop", help="stop and remove a deployment")
    stop.add_argument(
        "deployment",
        nargs="?",
        help="curated deployment name from list; omit to list running",
    )
    return parser


def _print_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
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
                }
            )
        )
        return 0
    if kit.kind == "release":
        print(f"Open AD Kit {kit.version or 'unknown'}")
        print("bundle: release")
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
        print(
            "error: installed data is incomplete; run: "
            f"openadkit fetch {deployment_name} --force",
            file=sys.stderr,
        )
    elif any(item["recovery"] == "fetch" for item in gaps):
        print(
            "error: installed data is missing; run: "
            f"openadkit fetch {deployment_name}",
            file=sys.stderr,
        )


def print_run_next_steps(deployment, services: set[str]) -> None:
    print(f"running: {deployment.name}")
    if "visualizer" in services:
        print("visualizer: https://localhost:6080/vnc.html")
        print("password: REMOTE_PASSWORD (default openadkit; override in config.local.env)")
    print(f"stop with: openadkit stop {deployment.name}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.show_version:
        root = root_path()
        kit = load_kit(root)
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

    root = root_path()
    kit = load_kit(root)

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
        results = data.check_installed_data(
            deployment, selection, include_gpu=True
        )
        if not args.data:
            if not results:
                print("no data resources declared")
                return 0
            for item in results:
                print(
                    f"{item['name']}: {item['status']} ({item['destination']})"
                )
            return 0
        data.remove_installed_data(deployment, selection, include_gpu=True)
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
            require_gpu=args.command != "fetch",
        )
        if args.command == "fetch":
            data.install_data(deployment, selection, args.force, include_gpu=True)
            return 0

        data.validate_destinations(deployment, selection)
        configured_services = compose.render(deployment, selection)
        if args.command == "validate":
            mode = "gpu" if selection.gpu else "cpu"
            results = (
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
                            "rosDistro": selection.ros_distro,
                            "gpu": selection.gpu,
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
        data.install_data(deployment, selection, args.force)
        compose.start(deployment, selection, args.pull)
        print_run_next_steps(deployment, configured_services)
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
    selection = deployment.select(kit, None, False, operational=True)
    if args.command == "status":
        compose.status(deployment, selection)
    elif args.command == "logs":
        compose.logs(deployment, selection, args.follow)
    elif args.command == "stop":
        compose.stop(deployment, selection)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OpenADKitError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
