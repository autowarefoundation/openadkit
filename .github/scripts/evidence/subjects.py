"""Compute the evidence subject set from build metadata and the source tree.

Subjects are the built image digests plus the deployment and shared asset
checksums. The evidence workflow attests to this set and the release gate
recomputes it independently from the release tree.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path


def load_manifest_module(source_root: Path):
    path = source_root / "cli" / "manifest.py"
    spec = importlib.util.spec_from_file_location("openadkit_subjects_manifest", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_subjects(metadata: dict, source_root: Path):
    subjects: list[tuple[str, str]] = []
    build_tag = metadata.get("build_tag", "unknown")
    for image in metadata.get("images", []):
        digest = image.get("digest", "")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            subjects.append(
                (
                    digest.removeprefix("sha256:"),
                    f'{image["repo"]}:{image["target"]}-{image["ros_distro"]}-{build_tag}',
                )
            )

    manifest = load_manifest_module(source_root)
    kit = manifest.load_kit(source_root)
    shared: set[str] = set()
    for name in sorted(kit.deployments):
        deployment = manifest.get_deployment(source_root, kit, name)
        checksum = manifest.deployment_checksum(deployment.directory)
        subjects.append((checksum, f"deployment:{name}"))
        shared.update(deployment.shared)
    for name in sorted(shared):
        checksum = manifest.deployment_checksum(source_root / "deployments" / name)
        subjects.append((checksum, f"shared:{name}"))

    subjects.sort(key=lambda item: item[1])
    return subjects


def write_subjects(path: Path, subjects) -> None:
    path.write_text(
        "".join(f"{digest}  {name}\n" for digest, name in subjects), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-metadata", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    metadata = json.loads(Path(args.build_metadata).read_text(encoding="utf-8"))
    subjects = build_subjects(metadata, Path(args.source_root).resolve())
    write_subjects(Path(args.output), subjects)
    print(json.dumps({"subjects": len(subjects)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())