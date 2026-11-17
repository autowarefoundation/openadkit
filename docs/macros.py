"""mkdocs-macros module — single-source repeated reference facts.

The registry prefix and default ROS distro title come from openadkit.json, the
release manifest the release reads them from, so the published docs cannot
contradict the release. The component image table is generated from the image inventory
(.github/image-inventory.json) so the docs cannot drift from what CI builds.

Used by the `macros` plugin configured in mkdocs.yaml. Reference in any page
under docs/ as `{{ registry }}`, `{{ default_distro_title }}`, or
`{{ component_table() }}`.

Parameterless shared blocks live as plain markdown under docs/includes/ and are
inserted with pymdownx snippets (`--8<--`) — keep markdown in markdown files,
not in Python strings.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
INVENTORY = REPO_ROOT / ".github" / "image-inventory.json"
MANIFEST = REPO_ROOT / "openadkit.json"


def _load_json(path, label):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to read {label} at {path}: {exc}") from exc


def define_env(env):
    manifest = _load_json(MANIFEST, "release manifest")
    registry = manifest["imageRepository"]
    if not isinstance(registry, str) or not registry.strip():
        raise RuntimeError(
            "release manifest imageRepository must be a non-empty string"
        )
    env.variables["registry"] = registry
    env.variables["default_distro_title"] = manifest["defaultRosDistro"].capitalize()

    @env.macro
    def component_table():
        """Markdown table of component images, generated from the image inventory.

        The ROS Distros column reflects the per-image `ros_distros` override in
        the inventory when present, otherwise the inventory-wide `ros_distros` list.
        """
        data = _load_json(INVENTORY, "image inventory")
        global_distros = data["ros_distros"]
        rows = [
            "| Component | Image | ROS Distros | Platforms |",
            "|-----------|-------|-------------|-----------|",
        ]
        for img in data["images"]:
            if img.get("stage") != "component":
                continue
            target = img["target"]
            distros = ", ".join(img.get("ros_distros", global_distros))
            arches = ", ".join(p.rsplit("/", 1)[-1] for p in img["platforms"])
            rows.append(
                f"| `{target}` | `{registry}:{target}-<distro>` | {distros} | {arches} |"
            )
        return "\n".join(rows)
