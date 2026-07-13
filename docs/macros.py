"""mkdocs-macros module — single-source repeated reference facts.

Facts that were retyped across many pages (the install command, the registry path,
the default ROS distro) live here as variables, and the component image table is
generated from the catalog (.github/image-inventory.json) so the docs cannot
drift from what CI actually builds.

Used by the `macros` plugin configured in mkdocs.yaml. Reference in any page
under docs/ as `{{ install_command }}`, `{{ registry }}`, `{{ default_distro }}`,
`{{ default_distro_title }}`, or `{{ component_table() }}`.

Parameterless shared blocks live as plain markdown under docs/includes/ and are
inserted with pymdownx snippets (`--8<--`) — keep markdown in markdown files,
not in Python strings.
"""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
INVENTORY = REPO_ROOT / ".github" / "image-inventory.json"

# The container registry + repository that all Open AD Kit component images share.
REGISTRY = "ghcr.io/autowarefoundation/openadkit"

# The ROS distro the default `<target>` image aliases resolve to. When the
# published default changes, change it here only.
DEFAULT_DISTRO = "humble"

# CI sets this to the exact checked-out commit. Local builds resolve HEAD so the
# rendered command never downloads a mutable branch.
INSTALL_REF = os.environ.get("OPENADKIT_INSTALL_REF")
if not INSTALL_REF:
    try:
        INSTALL_REF = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "Set OPENADKIT_INSTALL_REF to the commit SHA used for this docs build"
        ) from exc
if not re.fullmatch(r"[0-9a-fA-F]{40,64}", INSTALL_REF):
    raise RuntimeError("OPENADKIT_INSTALL_REF must be a full commit SHA")

INSTALL_SHA256 = hashlib.sha256((REPO_ROOT / "install.sh").read_bytes()).hexdigest()

INSTALL_COMMAND = (
    "install_openadkit() (\n"
    "  set -eu\n"
    '  install_tmp="$(mktemp)"\n'
    "  trap 'rm -f \"$install_tmp\"' EXIT\n"
    "  curl -fsSL --output \"$install_tmp\" "
    f"https://raw.githubusercontent.com/autowarefoundation/openadkit/{INSTALL_REF}/install.sh\n"
    f"  printf '%s  %s\\n' '{INSTALL_SHA256}' \"$install_tmp\" | sha256sum --check -\n"
    '  sudo bash "$install_tmp" "$@"\n'
    ")\n"
    "install_openadkit"
)


def _load_inventory():
    """Load and return the image inventory, with a clear error on failure."""
    try:
        return json.loads(INVENTORY.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Failed to read image catalog at {INVENTORY}: {exc}"
        ) from exc


def _components():
    """Component images from the catalog, in catalog order."""
    data = _load_inventory()
    return [img for img in data["images"] if img.get("stage") == "component"]


def define_env(env):
    env.variables["registry"] = REGISTRY
    env.variables["default_distro"] = DEFAULT_DISTRO
    env.variables["default_distro_title"] = DEFAULT_DISTRO.capitalize()
    env.variables["install_command"] = INSTALL_COMMAND

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
        for img in _components():
            target = img["target"]
            distros = ", ".join(img.get("ros_distros", global_distros))
            arches = ", ".join(p.rsplit("/", 1)[-1] for p in img["platforms"])
            rows.append(
                f"| `{target}` | `{REGISTRY}:{target}` | {distros} | {arches} |"
            )
        return "\n".join(rows)
