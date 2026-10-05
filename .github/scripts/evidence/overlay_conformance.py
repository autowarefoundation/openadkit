"""Collect entrypoint overlay reports from every hooked service in a cell.

No report is not a clean report: a missing/invalid report is recorded as a
warning. Services without the overlay mounts (e.g. third-party simulators)
do not participate. Contract warnings remain non-blocking, like validate.
"""
import argparse
import json
import subprocess
from pathlib import Path


def collect_reports(containers, read_report):
    reports = []
    for container in containers:
        mounts = [mount.get("Destination", "") for mount in container.get("Mounts", [])]
        if not any(path.startswith("/openadkit/config/") or path == "/openadkit/overlay_ws" for path in mounts):
            continue
        name = container["Name"].lstrip("/")
        report = read_report(container["Id"])
        try:
            data = json.loads(report)
            if not isinstance(data, dict) or set(data) != {"unknownPackages", "unknownFiles", "unknownKeys"} or any(
                not isinstance(items, list) or any(not isinstance(item, str) for item in items)
                for items in data.values()
            ):
                raise ValueError("invalid overlay report")
            reports.append({"container": name, "conformant": not any(data.values()), "report": data})
        except (ValueError, TypeError):
            reports.append({"container": name, "conformant": False, "error": "missing or invalid overlay report"})
    return reports


def capture(*command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ids = []
    for project in args.project:
        ids.extend(capture("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}").split())
    containers = json.loads(capture("docker", "inspect", *ids) or "[]") if ids else []
    reports = collect_reports(containers, lambda id: capture("docker", "exec", id, "cat", "/tmp/openadkit/overlay-report.json"))
    data = {"overlayConformant": bool(reports) and all(item["conformant"] for item in reports), "reports": reports}
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
