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
    discover,
    get_deployment,
    is_verified,
    load_context,
    root_path,
    validate_manifest,
)


def add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("deployment")
    parser.add_argument("--ros-distro")
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--group")
    parser.add_argument("--enable", action="append", default=[], metavar="FEATURE")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openadkit", description="Run Open AD Kit deployments."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="list available deployments")
    subparsers.add_parser("version", help="show repository or release version")

    validate = subparsers.add_parser(
        "validate", help="validate a deployment without starting it"
    )
    add_selection_arguments(validate)

    data_parser = subparsers.add_parser("data", help="download deployment data")
    add_selection_arguments(data_parser)
    data_parser.add_argument("--force", action="store_true")

    run = subparsers.add_parser("run", help="start and verify a deployment")
    add_selection_arguments(run)
    run.add_argument("--skip-verify", action="store_true")
    run.add_argument(
        "--pull", choices=("missing", "always", "never"), default="missing"
    )

    verify = subparsers.add_parser("verify", help="verify a running deployment")
    add_selection_arguments(verify)

    for name in ("status", "stop", "down"):
        command = subparsers.add_parser(name)
        command.add_argument("deployment")
        command.add_argument("--ros-distro")
        command.add_argument("--gpu", action="store_true")
    logs = subparsers.add_parser("logs")
    logs.add_argument("deployment")
    logs.add_argument("--ros-distro")
    logs.add_argument("--gpu", action="store_true")
    logs.add_argument("--follow", action="store_true")
    return parser


def list_deployments(root, current_context) -> int:
    found = discover(root)
    if not found:
        print("No deployments found.")
        return 0
    for name, directory in found.items():
        try:
            deployment = validate_manifest(root, directory)
            trust = (
                "verified"
                if is_verified(root, deployment, current_context)
                else "custom/unverified"
            )
            groups = ",".join(sorted(deployment.compose["groups"])) or "-"
            features = ",".join(sorted(deployment.compose["features"])) or "-"
            print(f"{name}\t{trust}\tgroups={groups}\tfeatures={features}")
        except OpenADKitError as error:
            print(f"{name}\tinvalid\t{error}")
    return 0


def show_version(root, current_context) -> int:
    if current_context.kind == "release":
        print(f"Open AD Kit {current_context.version or 'unknown'}")
        print("context: release")
    else:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        print("Open AD Kit development")
        print(f"commit: {result.stdout.strip() or 'unknown'}")
        print("context: repository")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    root = root_path()
    current_context = load_context(root)

    if args.command == "list":
        return list_deployments(root, current_context)
    if args.command == "version":
        return show_version(root, current_context)

    deployment = get_deployment(root, args.deployment)
    if not is_verified(root, deployment, current_context):
        print(f"warning: {deployment.name} is custom/unverified", file=sys.stderr)
    compose.ensure_runtime_user()

    if args.command in ("data", "validate", "run", "verify"):
        selection = deployment.select(
            current_context,
            args.ros_distro,
            args.gpu,
            args.group,
            args.enable,
        )
        if args.command == "data":
            data.install_data(deployment, selection, args.force)
            return 0

        if args.command in ("validate", "run"):
            data.validate_destinations(deployment, selection)
        configured_services = compose.render(deployment, selection)
        if args.command == "validate":
            print(f"valid: {deployment.name}")
            return 0
        if args.command == "verify":
            compose.verify(deployment, selection)
            print(f"verified: {deployment.name}")
            return 0

        compose.check_daemon(selection)
        compose.run_hook(deployment, "preflight", selection)
        data.install_data(deployment, selection, False)
        compose.start(deployment, selection, args.pull, configured_services)
        if not args.skip_verify:
            compose.verify(deployment, selection)
        print(f"running: {deployment.name}")
        return 0

    operational_gpu = args.gpu or deployment.requirements["gpu"] == "required"
    selection = deployment.select(
        current_context,
        args.ros_distro,
        operational_gpu,
        None,
        [],
        require_group=False,
    )
    compose.require_docker()
    if args.command == "status":
        compose.status(deployment, selection)
    elif args.command == "logs":
        compose.logs(deployment, selection, args.follow)
    elif args.command == "stop":
        compose.stop(deployment, selection)
    elif args.command == "down":
        compose.down(deployment, selection)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OpenADKitError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
