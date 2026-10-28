#!/usr/bin/env python3
"""Plan CI builds: inventory matrices, changed targets and the shared Bake recipe.

Prints `KEY=<compact-json>` lines for each matrix to stdout. The `prepare`
job redirects this into `$GITHUB_OUTPUT`. Uses only the standard library so
it runs before any pip/apt install step.
"""
import fnmatch
import json
import os
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
        "components/shared/*",
        ".github/image-inventory.json",
        ".github/scripts/export_autoware_lock.py",
        ".github/scripts/build.py",
        ".github/scripts/resolve_build_inputs.sh",
        ".github/scripts/resolve_registry_contexts.sh",
        ".github/scripts/resolve_upstream_images.sh",
        ".github/scripts/registry_lookup.sh",
        ".github/actions/free-disk-space/*",
        ".github/actions/build-image/*",
        ".github/actions/setup-build-env/*",
        ".github/workflows/build-single-image.yaml",
        ".github/workflows/build-single-image-distro.yaml",
        ".trivyignore",
    )
    targets = set(target_input.split())
    use_local_common = False
    use_local_simulator = False

    if not target_input:
        for changed_file in changed_files:
            if not changed_file:
                continue
            # These shape every image's sources, context and dependency graph.
            # Autoware patches change the sources every image compiles, as a new
            # Autoware revision does.
            if changed_file in ("components/docker-bake.hcl", ".dockerignore", ".github/autoware.ref", ".github/autoware-lock.repos",
                                ".github/autoware-base-images.json", ".github/scripts/autoware_patches.py") or fnmatch.fnmatchcase(
                changed_file, ".github/autoware-patches/*"
            ):
                targets.update(all_targets)
                use_local_common = True
                use_local_simulator = True
            # A component's own README documents it; a README deeper down may be
            # copied into the image (fnmatch's "*" would also match "/").
            elif changed_file == "components/README.md" or (
                changed_file.endswith("/README.md") and changed_file.count("/") == 2
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


# Image creation time of the compile bases (the development core and
# universe-common-build). Images built on a base are cached against its
# config digest, and that digest records when each layer was built: with
# identical layers, a rebuild at another time still recompiled every jazzy
# component. These images are internal, so a fixed time costs nothing.
COMPILE_BASE_EPOCH = "0"


def bake_recipe(inventory, prepared, target, distro, platform, *, publish, shared_common, common_cached, owner, source_sha, run_id,
                core_devel=None):
    """Overlay the local HCL graph, preserving local dependency builds in PRs.

    core_devel is the pushed development core (ref@digest, see core_recipe)
    that universe-common builds on instead of compiling it in the same Bake.
    """
    images = {image["target"]: image for image in inventory["images"]}
    if target not in images or distro not in image_distros(images[target], inventory["ros_distros"]) or platform not in images[target]["platforms"]:
        raise ValueError(f"Unsupported build cell: {target}/{distro}/{platform}")
    arch = platform_label(platform)
    build_tag = prepared["build_tag"]
    def cache_ref(name):
        return f"ghcr.io/{owner}/openadkit-buildcache:{name}-{arch}-{distro}-{prepared['cache_scope']}"
    cache = cache_ref(target)
    # universe-common's build and runtime stages, and the core development
    # builds compile, export separate caches so none overwrites another; the
    # devel image adds only its per-build refresh, which nothing reuses.
    common_stages = ("autoware-core-devel", "universe-common-build", "universe-common")
    common_cache_from = [f"type=registry,ref={cache_ref(name)}" for name in common_stages]
    # Internal compile base for components (the devel image without its
    # per-build refresh). Without per-build labels or provenance its digest
    # only changes with its inputs, which keeps component compiles cached.
    common_build = f"ghcr.io/{owner}/openadkit-buildcache:universe-common-build-{arch}-{distro}-{build_tag}"
    contexts = {}
    args = {"ROS_DISTRO": distro}
    labels = {}
    cache_from = common_cache_from.copy() if target == "universe-common" else [f"type=registry,ref={cache}"]
    cuda_contexts = {}
    if publish:
        if target == "universe-common":
            # Development builds have no upstream core image; HCL compiles it.
            upstream = json.loads(prepared["upstream_images"])[distro]
            contexts.update({f"autoware-{name}": upstream[name]["uri"] for name in ("core-devel", "base") if name in upstream})
            if core_devel:
                contexts["autoware-core-devel"] = f"docker-image://{core_devel}"
            args["SECURITY_REFRESH"] = build_tag
        else:
            contexts["universe-common-devel"] = f"docker-image://{common_build}"
            contexts["universe-common"] = f"docker-image://ghcr.io/{owner}/openadkit-common:universe-common-{arch}-{distro}-{build_tag}"
            if target != "carla-interface":
                upstream = json.loads(prepared["upstream_images"])[distro]
                cuda_contexts = {f"autoware-{name}": upstream[name]["uri"] for name in ("base-cuda-runtime", "base-cuda-devel")}
        if target == "carla-interface":
            contexts["simulator"] = f"docker-image://ghcr.io/{owner}/openadkit:simulator-amd64-{distro}-{build_tag}"
        labels = {f"org.opencontainers.image.{key.replace('_', '-')}": prepared[key] for key in (
            "autoware_input_ref", "autoware_ref_type", "autoware_ref", "autoware_base_version", "autoware_lock_sha256",
        )}
        labels.update({"org.opencontainers.image.build-tag": build_tag, "org.opencontainers.image.run-id": run_id,
                       "org.opencontainers.image.openadkit-sha": source_sha})
        # Match the existing Bake --set label spelling; context readers accept
        # these legacy quoted keys as well as canonical OCI keys.
        labels = {f'"{key}"': value for key, value in labels.items()}
    else:
        for key, name in (("upstream_core_devel", "autoware-core-devel"), ("upstream_base", "autoware-base"),
                          ("devel_context", "universe-common-devel"), ("runtime_context", "universe-common")):
            if prepared.get(key) and not (shared_common and name.startswith("universe-common")):
                contexts[name] = prepared[key]
        for key, name in (("upstream_cuda_runtime", "autoware-base-cuda-runtime"), ("upstream_cuda_devel", "autoware-base-cuda-devel")):
            if prepared.get(key) and not shared_common:
                cuda_contexts[name] = prepared[key]
        if target == "carla-interface" and prepared.get("use_local_simulator") != "true":
            contexts["simulator"] = prepared["simulator_context"]
        if not shared_common:
            if prepared.get("use_local_common") == "true":
                cache_from.extend(common_cache_from)
            if common_cached:
                cache_from.extend(f"type=gha,scope=pr-common-{stage}-{distro}-{run_id}" for stage in ("devel", "runtime"))
            if prepared.get("use_local_simulator") == "true":
                cache_from.append(f"type=registry,ref={cache_ref('simulator')}")

    # Apply the same settings to dependency targets too, as the previous *.set
    # overrides did. HCL remains the owner of Dockerfiles and local graph edges.
    overrides = {}
    for name in [*images, "universe-common-build", "autoware-core-devel"]:
        overrides[name] = {"platforms": [platform], "args": args.copy(), "labels": labels.copy(),
                           "contexts": contexts.copy(), "cache-from": cache_from.copy()}
        if publish:
            overrides[name]["cache-to"] = [f"type=registry,ref={cache},mode=max"]
    # Development core is the compile base's FROM: per-build labels would reach
    # universe-common-build through it.
    overrides["autoware-core-devel"]["labels"] = {}
    if publish and target == "universe-common":
        overrides["universe-common-build"].update(
            tags=[common_build], labels={}, attest=["type=provenance,disabled=true"],
            args={**args, "SOURCE_DATE_EPOCH": COMPILE_BASE_EPOCH},
            **{"cache-to": [f"type=registry,ref={cache_ref('universe-common-build')},mode=max"]})
        overrides["autoware-core-devel"]["cache-to"] = [f"type=registry,ref={cache_ref('autoware-core-devel')},mode=max"]
        del overrides["universe-common-devel"]["cache-to"]
    overrides["sensing-perception-cuda"]["contexts"].update(cuda_contexts)
    if publish and target not in ("universe-common", "carla-interface"):
        overrides["sensing-perception-cuda"]["args"]["SECURITY_REFRESH"] = build_tag
    if shared_common:
        for name, stage in (("universe-common-build", "devel"), ("universe-common", "runtime")):
            overrides[name]["cache-to"] = [f"type=gha,scope=pr-common-{stage}-{distro}-{run_id},mode=min"]
    targets = (["universe-common-build", "universe-common-devel", "universe-common"]
               if publish and target == "universe-common" else [target])
    return {"target": overrides}, targets


def core_recipe(prepared, distro, platform, *, owner):
    """The development core image, pushed before universe-common builds on it.

    Development builds have no upstream core-devel image, so they compile it.
    Built in the same Bake as universe-common (a target: context), every
    stage on top of it missed the registry cache on each new build, while
    release builds, which start from the upstream image's digest, stayed
    cached. Pushing core first lets universe-common start from a digest too.
    Returns None when the upstream image exists.
    """
    upstream = json.loads(prepared["upstream_images"])[distro]
    if "core-devel" in upstream:
        return None
    arch = platform_label(platform)
    def cache_ref(name):
        return f"ghcr.io/{owner}/openadkit-buildcache:{name}-{arch}-{distro}-{prepared['cache_scope']}"
    image = f"ghcr.io/{owner}/openadkit-buildcache:autoware-core-devel-{arch}-{distro}-{prepared['build_tag']}"
    # No per-build labels, arguments, timestamps or provenance: they would
    # change the digest universe-common starts from.
    recipe = {"target": {"autoware-core-devel": {
        "platforms": [platform], "args": {"ROS_DISTRO": distro, "SOURCE_DATE_EPOCH": COMPILE_BASE_EPOCH}, "labels": {},
        "contexts": {"autoware-base": upstream["base"]["uri"]},
        "cache-from": [f"type=registry,ref={cache_ref(name)}" for name in ("autoware-core-devel", "universe-common-build", "universe-common")],
        "cache-to": [f"type=registry,ref={cache_ref('autoware-core-devel')},mode=max"],
        "tags": [image], "attest": ["type=provenance,disabled=true"],
    }}}
    return recipe, image


def write_recipe():
    inventory = json.loads(pathlib.Path(DEFAULT_INVENTORY).read_text())
    target = os.environ["BUILD_TARGET"]
    distro = os.environ["ROS_DISTRO"]
    platform = os.environ["BUILD_PLATFORM"]
    prepared = json.loads(os.environ["BUILD_INPUTS"])
    publish = os.environ["PUBLISH"] == "true"
    owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
    # Set on the second run, after the core image was pushed (build-image).
    core_devel = os.environ.get("CORE_DEVEL_IMAGE") or None
    core = core_recipe(prepared, distro, platform, owner=owner) if publish and target == "universe-common" else None
    recipe, targets = bake_recipe(
        inventory, prepared, target, distro, platform,
        publish=publish, shared_common=os.environ["SHARED_COMMON"] == "true",
        common_cached=os.environ["COMMON_CACHED"] == "true", owner=owner,
        source_sha=os.environ["GITHUB_SHA"], run_id=os.environ["GITHUB_RUN_ID"], core_devel=core_devel,
    )
    pathlib.Path(".build-recipe.json").write_text(json.dumps(recipe))
    if core:
        pathlib.Path(".core-recipe.json").write_text(json.dumps(core[0]))
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"cache_prefix=buildkit-mounts-{target}-{distro}-{platform_label(platform)}-\n")
        output.write("targets<<BUILD_TARGETS\n" + "\n".join(targets) + "\nBUILD_TARGETS\n")
        output.write(f"core_image={core[1] if core else ''}\n")


def main(argv):
    if len(argv) > 1 and argv[1] == "recipe":
        write_recipe()
        return 0
    if len(argv) > 1 and argv[1] == "single-image":
        if len(argv) != 4:
            print("usage: build.py single-image ROS_DISTRO TARGETS", file=sys.stderr)
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
