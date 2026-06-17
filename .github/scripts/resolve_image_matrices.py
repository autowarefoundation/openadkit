#!/usr/bin/env python3
"""Resolve GitHub Actions build matrices from the image inventory.

Prints `KEY=<compact-json>` lines for each matrix to stdout. The `prepare`
job redirects this into `$GITHUB_OUTPUT`. Uses only the standard library so
it runs before any pip/apt install step.
"""
import json
import pathlib
import sys

DEFAULT_INVENTORY = ".github/image-inventory.json"


def platform_label(platform):
    if platform == "linux/amd64":
        return "amd64"
    if platform == "linux/arm64":
        return "arm64"
    raise ValueError(f"unsupported platform: {platform}")


def image_distros(image, default_distros):
    return image.get("ros_distros", default_distros)


def build_matrices(inventory):
    distros = inventory["ros_distros"]
    images = inventory["images"]

    def matrix_for(stage):
        include = []
        for image in images:
            if image["stage"] != stage:
                continue
            for distro in image_distros(image, distros):
                for platform in image["platforms"]:
                    include.append({
                        "platform": platform,
                        "platform-label": platform_label(platform),
                        "ros-distro": distro,
                        "target": image["target"],
                    })
        return {"include": include}

    common_pairs = sorted({
        (platform, distro)
        for image in images if image["stage"] == "common"
        for distro in image_distros(image, distros)
        for platform in image["platforms"]
    })
    common_matrix = {"include": [
        {"platform": p, "platform-label": platform_label(p), "ros-distro": d}
        for p, d in common_pairs
    ]}
    ros_distro_matrix = {"include": [{"ros-distro": d} for d in distros]}

    manifest_include = []
    for image in images:
        arches = " ".join(platform_label(p) for p in image["platforms"])
        for distro in image_distros(image, distros):
            manifest_include.append({
                "repo": image["repo"],
                "target": image["target"],
                "ros-distro": distro,
                "arches": arches,
            })
    manifest_matrix = {"include": manifest_include}

    return {
        "common_matrix": common_matrix,
        "component_matrix": matrix_for("component"),
        "ros_distro_matrix": ros_distro_matrix,
        "manifest_matrix": manifest_matrix,
    }


def format_outputs(matrices):
    lines = [f"{k}={json.dumps(v, separators=(',', ':'))}" for k, v in matrices.items()]
    return "\n".join(lines) + "\n"


def main(argv):
    path = argv[1] if len(argv) > 1 else DEFAULT_INVENTORY
    inventory = json.loads(pathlib.Path(path).read_text())
    sys.stdout.write(format_outputs(build_matrices(inventory)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
