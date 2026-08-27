#!/usr/bin/env python3
"""Resolve GitHub Actions build matrices from the image inventory.

Prints `KEY=<compact-json>` lines for each matrix to stdout. The `prepare`
job redirects this into `$GITHUB_OUTPUT`. Uses only the standard library so
it runs before any pip/apt install step.
"""
import fnmatch
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

    def matrix_for(stage, include_target=None, exclude_targets=None):
        exclude_targets = set(exclude_targets or [])
        include = []
        for image in images:
            if image["stage"] != stage:
                continue
            if include_target is not None and image["target"] != include_target:
                continue
            if image["target"] in exclude_targets:
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
        "component_matrix": matrix_for("component", exclude_targets={"carla-interface"}),
        "carla_matrix": matrix_for("component", include_target="carla-interface"),
        "manifest_matrix": manifest_matrix,
    }


def build_single_image_plan(inventory, changed_files=(), target_input="", distro="humble"):
    images = inventory["images"]
    images_by_target = {image["target"]: image for image in images}
    all_targets = set(images_by_target)
    shared_build_inputs = (
        "components/runtime-cleanup.sh",
        ".github/image-inventory.json",
        ".github/scripts/export_autoware_lock.py",
        ".github/scripts/resolve_image_matrices.py",
        ".github/scripts/resolve_build_inputs.sh",
        ".github/scripts/resolve_registry_contexts.sh",
        ".github/scripts/resolve_upstream_images.sh",
        ".github/scripts/registry_lookup.sh",
        ".github/actions/free-disk-space/*",
        ".github/actions/inject-ccache/*",
        ".github/actions/setup-build-env/*",
        ".github/workflows/build-single-image.yaml",
        ".trivyignore",
    )
    targets = set(target_input.split())
    use_local_common = False
    use_local_simulator = False

    if not target_input:
        for changed_file in changed_files:
            if not changed_file:
                continue
            if changed_file == "components/docker-bake.hcl":
                targets.update(all_targets)
                use_local_common = True
                use_local_simulator = True
            elif changed_file == "components/README.md" or fnmatch.fnmatchcase(
                changed_file, "components/*/README.md"
            ):
                continue
            elif any(
                fnmatch.fnmatchcase(changed_file, pattern)
                for pattern in shared_build_inputs
            ):
                targets.update(all_targets)
            elif changed_file.startswith("components/"):
                component, separator, component_path = changed_file.removeprefix(
                    "components/"
                ).partition("/")
                if component == "sensing-perception" and separator:
                    if component_path == "Dockerfile":
                        mapped_targets = {"sensing-perception"}
                    elif component_path == "Dockerfile.cuda":
                        mapped_targets = {"sensing-perception-cuda"}
                    else:
                        mapped_targets = {
                            "sensing-perception",
                            "sensing-perception-cuda",
                        }
                elif component == "universe-common" and separator:
                    mapped_targets = all_targets
                elif component == "simulator" and separator:
                    mapped_targets = {"simulator", "carla-interface"}
                elif component in images_by_target and separator:
                    mapped_targets = {component}
                else:
                    mapped_targets = None

                if mapped_targets is None:
                    raise ValueError(f"Unmapped component build input: {changed_file}")
                targets.update(mapped_targets)
                use_local_common |= component == "universe-common"
                use_local_simulator |= component == "simulator"

    if use_local_simulator and "carla-interface" in targets:
        targets.discard("simulator")

    unknown_targets = targets - all_targets
    if unknown_targets:
        raise ValueError(f"Unknown Bake target: {sorted(unknown_targets)[0]}")

    distro = distro or "humble"
    if distro not in inventory["ros_distros"]:
        raise ValueError(f"Unsupported ROS distro: {distro}")

    for target in sorted(targets):
        supported_distros = image_distros(
            images_by_target[target], inventory["ros_distros"]
        )
        if distro not in supported_distros:
            supported = ", ".join(supported_distros)
            raise ValueError(
                f"Target '{target}' does not support ROS distro '{distro}' "
                f"(supported: {supported})"
            )

    return {
        "targets_json": sorted(targets),
        "setup_autoware": any(target != "carla-interface" for target in targets),
        "with_middleware": bool(
            targets & {"universe-common-devel", "universe-common"}
        ),
        "use_local_common": use_local_common,
        "use_local_simulator": use_local_simulator,
    }


def format_outputs(matrices):
    lines = [f"{k}={json.dumps(v, separators=(',', ':'))}" for k, v in matrices.items()]
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) > 1 and argv[1] == "single-image":
        if len(argv) != 4:
            print("usage: resolve_image_matrices.py single-image ROS_DISTRO TARGETS", file=sys.stderr)
            return 2
        inventory = json.loads(pathlib.Path(DEFAULT_INVENTORY).read_text())
        try:
            plan = build_single_image_plan(
                inventory,
                changed_files=sys.stdin.read().splitlines(),
                target_input=argv[3],
                distro=argv[2],
            )
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        sys.stdout.write(format_outputs(plan))
        targets = " ".join(plan["targets_json"])
        print(f"Detected targets: '{targets}'", file=sys.stderr)
        return 0

    path = argv[1] if len(argv) > 1 else DEFAULT_INVENTORY
    inventory = json.loads(pathlib.Path(path).read_text())
    sys.stdout.write(format_outputs(build_matrices(inventory)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
