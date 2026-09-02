#!/usr/bin/env python3
"""Open AD Kit command-line parser and runtime orchestrator."""

from __future__ import annotations

import argparse
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
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(2)


def add_run_arguments(parser: argparse.ArgumentParser, *, gpu: bool = True) -> None:
    parser.add_argument("deployment", help="curated deployment name from list")
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
            "  ./openadkit setup --verify\n"
            "  ./openadkit list\n"
            "  ./openadkit run planning-simulation\n"
            "  ./openadkit run logging-simulation --gpu\n"
            "  ./openadkit stop planning-simulation"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", parser_class=OpenADKitParser)
    subparsers.add_parser(
        "setup", help="installs Ubuntu host dependencies"
    )
    subparsers.add_parser("list", help="list curated deployments")
    subparsers.add_parser("version", help="show repository or release version")

    validate = subparsers.add_parser(
        "validate", help="validate a deployment without starting it"
    )
    add_run_arguments(validate)

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

    status = subparsers.add_parser("status", help="show deployment status")
    status.add_argument("deployment", help="curated deployment name from list")
    logs = subparsers.add_parser("logs", help="show deployment logs")
    logs.add_argument("deployment", help="curated deployment name from list")
    logs.add_argument("--follow", action="store_true", help="stream logs")
    stop = subparsers.add_parser("stop", help="stop and remove a deployment")
    stop.add_argument("deployment", help="curated deployment name from list")
    return parser


def list_deployments(root, kit) -> int:
    if not kit.deployments:
        print("No deployments found.")
        return 0
    for name in kit.deployments:
        try:
            deployment = get_deployment(root, kit, name)
            integrity = deployment_integrity(root, deployment, kit)
            gpu = deployment.requirements["gpu"]
            description = deployment.manifest["description"]
            print(f"{name}\t{integrity}\t{gpu}\t{description}")
        except OpenADKitError as error:
            print(f"{name}\tinvalid\t{error}")
    return 0


def show_version(root, kit) -> int:
    if kit.kind == "release":
        print(f"Open AD Kit {kit.version or 'unknown'}")
        print("bundle: release")
    else:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        print("Open AD Kit development")
        print(f"commit: {result.stdout.strip() or 'unknown'}")
        print("bundle: repository")
    return 0


def warn_if_modified(root, deployment, kit) -> None:
    if deployment_integrity(root, deployment, kit) == "modified":
        print(
            f"warning: {deployment.name} has been modified from this release",
            file=sys.stderr,
        )


def print_run_next_steps(deployment, selection) -> None:
    print(f"running: {deployment.name}")
    if "visualizer" in selection.services:
        print("visualizer: https://localhost:6080/vnc.html")
        print("password: REMOTE_PASSWORD in config.env")
    print(f"stop with: ./openadkit stop {deployment.name}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 2
    if args.command == "setup":
        print(
            "error: run: ./openadkit setup [--gpu] [--verify]",
            file=sys.stderr,
        )
        return 2

    root = root_path()
    kit = load_kit(root)

    if args.command == "list":
        return list_deployments(root, kit)
    if args.command == "version":
        return show_version(root, kit)

    deployment = get_deployment(root, kit, args.deployment)
    warn_if_modified(root, deployment, kit)
    compose.ensure_runtime_user()

    if args.command in ("fetch", "validate", "run"):
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
            print(f"valid: {deployment.name} ({selection.ros_distro}, {mode})")
            return 0

        compose.check_daemon(selection)
        data.install_data(deployment, selection, args.force)
        compose.start(deployment, selection, args.pull, configured_services)
        compose.save_runtime(deployment, selection)
        print_run_next_steps(deployment, selection)
        return 0

    saved = compose.load_runtime(deployment)
    ros_distro, gpu = saved if saved else (None, False)
    selection = deployment.select(kit, ros_distro, gpu, operational=True)
    compose.require_docker()
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
