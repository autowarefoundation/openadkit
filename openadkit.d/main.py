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


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("deployment")
    parser.add_argument("--ros-distro")
    parser.add_argument("--gpu", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openadkit", description="Run Open AD Kit deployments."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="list curated deployments")
    subparsers.add_parser("version", help="show repository or release version")

    validate = subparsers.add_parser(
        "validate", help="validate a deployment without starting it"
    )
    add_run_arguments(validate)

    fetch = subparsers.add_parser("fetch", help="download deployment data")
    add_run_arguments(fetch)
    fetch.add_argument("--force", action="store_true")

    run = subparsers.add_parser("run", help="fetch data and start a deployment")
    add_run_arguments(run)
    run.add_argument(
        "--pull", choices=("missing", "always", "never"), default="missing"
    )

    status = subparsers.add_parser("status", help="show deployment status")
    status.add_argument("deployment")
    logs = subparsers.add_parser("logs", help="show deployment logs")
    logs.add_argument("deployment")
    logs.add_argument("--follow", action="store_true")
    stop = subparsers.add_parser("stop", help="stop and remove a deployment")
    stop.add_argument("deployment")
    return parser


def list_deployments(root, kit) -> int:
    if not kit.deployments:
        print("No deployments found.")
        return 0
    for name in kit.deployments:
        try:
            deployment = get_deployment(root, kit, name)
            print(f"{name}\t{deployment_integrity(root, deployment, kit)}")
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


def main() -> int:
    args = build_parser().parse_args()
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
            args.gpu,
            require_gpu=args.command != "fetch",
        )
        if args.command == "fetch":
            data.install_data(deployment, selection, args.force, include_gpu=True)
            return 0

        data.validate_destinations(deployment, selection)
        configured_services = compose.render(deployment, selection)
        if args.command == "validate":
            print(f"valid: {deployment.name}")
            return 0

        compose.check_daemon(selection)
        data.install_data(deployment, selection, False)
        compose.start(deployment, selection, args.pull, configured_services)
        print(f"running: {deployment.name}")
        return 0

    selection = deployment.select(kit, None, False, operational=True)
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
