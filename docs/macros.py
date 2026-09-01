"""mkdocs-macros module — single-source repeated reference facts.

Facts that were retyped across many pages (the registry path and default ROS
distro) live here as variables, and the component image table is generated from
the catalog (.github/image-inventory.json) so the docs cannot drift from what CI
actually builds.

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

# The container registry + repository that all Open AD Kit component images share.
REGISTRY = "ghcr.io/autowarefoundation/openadkit"

# The ROS distro the default `<target>` image aliases resolve to. When the
# published default changes, change it here only.
DEFAULT_DISTRO = "humble"

def _load_inventory():
    """Load and return the image inventory, with a clear error on failure."""
    try:
        return json.loads(INVENTORY.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Failed to read image catalog at {INVENTORY}: {exc}"
        ) from exc


def define_env(env):
    env.variables["registry"] = REGISTRY
    env.variables["default_distro_title"] = DEFAULT_DISTRO.capitalize()

    @env.macro
    def component_table():
        """Markdown table of component images, generated from the catalog.

        The ROS Distros column reflects the per-image `ros_distros` override in
        the catalog when present, otherwise the catalog-wide `ros_distros` list.
        """
        data = _load_inventory()
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
