"""mkdocs-macros module — single-source repeated reference facts.

The default ROS distro title comes from openadkit.json. The component image
table is generated from the catalog (.github/image-inventory.json) so the docs
cannot drift from what CI actually builds.

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
KIT = REPO_ROOT / "openadkit.json"

# The container registry + repository that all Open AD Kit component images share.
REGISTRY = "ghcr.io/autowarefoundation/openadkit"


def _load_json(path, label):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to read {label} at {path}: {exc}") from exc


def define_env(env):
    kit = _load_json(KIT, "bundle manifest")
    env.variables["registry"] = REGISTRY
    env.variables["default_distro_title"] = kit["defaultRosDistro"].capitalize()

    @env.macro
    def component_table():
        """Markdown table of component images, generated from the catalog.

        The ROS Distros column reflects the per-image `ros_distros` override in
        the catalog when present, otherwise the catalog-wide `ros_distros` list.
        """
        data = _load_json(INVENTORY, "image catalog")
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
                f"| `{target}` | `{REGISTRY}:{target}` | {distros} | {arches} |"
            )
        return "\n".join(rows)
