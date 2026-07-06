"""mkdocs-macros module — single-source repeated reference facts.

Facts that were retyped across many pages (the install command, the registry path,
the default ROS distro) live here as variables, and the component image table is
generated from the catalog (.github/image-inventory.json) so the docs cannot
drift from what CI actually builds.

Used by the `macros` plugin configured in mkdocs.yaml. Reference in any page
under docs/ as `{{ install_command }}`, `{{ registry }}`, `{{ default_distro }}`,
`{{ default_distro_title }}`, or `{{ component_table() }}`.

Deployment pages share their repeated blocks through macros as well:
`{{ bundle_download(name) }}`, `{{ first_release_note(name) }}`,
`{{ cloned_repo_env_note() }}`, `{{ visualizer_access() }}`,
`{{ compose_stop(name) }}`, and `{{ monolithic_image_note(service) }}`.
Macros (not pymdownx snippet files) are required for parameterized blocks:
the macros plugin renders before snippets are inserted, so `{{ }}` inside an
`--8<--` include file would never be expanded.
"""

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
INVENTORY = REPO_ROOT / ".github" / "image-inventory.json"

# The container registry + repository that all Open AD Kit component images share.
REGISTRY = "ghcr.io/autowarefoundation/openadkit"

# The ROS distro the default `<target>` image aliases resolve to. When the
# published default changes, change it here only.
DEFAULT_DISTRO = "humble"

# Derive the branch/tag from the build environment so release docs point to
# the matching script. Falls back to "main" for local builds.
# PR merge refs (e.g. "42/merge") are not valid for raw.githubusercontent.com,
# so we fall back to "main" when the ref contains a slash.
_raw_ref = os.environ.get("GITHUB_REF_NAME", "main")
INSTALL_BRANCH = "main" if "/" in _raw_ref else _raw_ref

INSTALL_COMMAND = (
    "curl -fsSL "
    f"https://raw.githubusercontent.com/autowarefoundation/openadkit/{INSTALL_BRANCH}/install.sh "
    "| sudo bash"
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

    @env.macro
    def bundle_download(name):
        """Fenced bash block: download and enter a deployment release bundle."""
        return (
            "```bash\n"
            "curl -fL https://github.com/autowarefoundation/openadkit/releases/latest/"
            f"download/{name}.tar.gz | tar xz\n"
            f"cd {name}\n"
            "```"
        )

    @env.macro
    def first_release_note(name, sample_data=True):
        """'Releases' admonition: bundles pending first release; cloned-repo fallback."""
        fetch = (
            f"; from that folder, run `../../install.sh sample-data {name}` "
            "to fetch the sample data"
            if sample_data
            else ""
        )
        return (
            '!!! note "Releases"\n'
            "    Deployment bundles ship as assets on each "
            "[GitHub Release](https://github.com/autowarefoundation/openadkit/releases). "
            "Until the first official release is published, developers can use the "
            f"`deployments/{name}/` folder from a cloned repository instead{fetch}.\n"
        )

    @env.macro
    def cloned_repo_env_note():
        """'Cloned repository' warning: pass ../base/base.env to every compose command."""
        return (
            '!!! warning "Cloned repository"\n'
            "    If running from a cloned repository rather than a release bundle, "
            "prepend `--env-file ../base/base.env` to **every** `docker compose` "
            "command on this page. Release bundles merge both env files into one; "
            "from a clone you need both so shared variables such as `ROS_DOMAIN_ID` "
            "and `REMOTE_PASSWORD` resolve.\n"
        )

    @env.macro
    def visualizer_access(
        port=6080,
        password=None,
        host_networking=True,
        heading="## Access the Visualizer",
    ):
        """'Access the Visualizer' section: heading, URL, password, remote-access tip."""
        if password is None:
            password_line = "Use the default password **`openadkit`**."
        else:
            password_line = (
                f"Log in with the password you set as `{password}` in `.env`."
            )
        if host_networking:
            tip = (
                '!!! tip "Remote Access"\n'
                "    The visualizer runs under `network_mode: host`, so `ports:` is "
                f"ignored and the loopback bind (`127.0.0.1:{port}`) lives in the "
                "visualizer entrypoint. To reach noVNC from another machine, either "
                "forward the port over SSH:\n"
                "\n"
                "    ```bash\n"
                f"    ssh -L 8080:localhost:{port} <user>@<host>\n"
                "    # then open http://localhost:8080/vnc.html\n"
                "    ```\n"
                "\n"
                "    or put a TLS-terminating reverse proxy in front of "
                f"`127.0.0.1:{port}` and set a strong `REMOTE_PASSWORD` in "
                "`base.env`. Editing `docker-compose.yaml` to add a `ports:` "
                "mapping has no effect under host networking.\n"
            )
        else:
            tip = (
                '!!! tip "Remote Access"\n'
                "    To reach noVNC from another machine, change the `ports:` "
                "mapping for the visualizer service in `docker-compose.yaml` "
                f"(e.g. `8080:{port}`) or forward the port over SSH.\n"
            )
        return (
            f"{heading}\n"
            "\n"
            "Open your browser and navigate to:\n"
            "\n"
            "```text\n"
            f"http://localhost:{port}/vnc.html\n"
            "```\n"
            "\n"
            f"{password_line}\n"
            "\n"
            f"{tip}"
        )

    @env.macro
    def compose_stop(name, profile=None):
        """Fenced bash block: stop a deployment's containers."""
        p = f" --profile {profile}" if profile else ""
        return f"```bash\ndocker compose --env-file {name}.env{p} down\n```"

    @env.macro
    def monolithic_image_note(service):
        """Known-limitations note: service still uses upstream autoware:universe."""
        return (
            f"The `{service}` service in this deployment uses the upstream "
            "`ghcr.io/autowarefoundation/autoware:universe` image rather than an "
            "Open AD Kit component image. This is a temporary measure while "
            "Open AD Kit migrates from monolithic to component-based architecture; "
            "a component-based replacement will ship in a future release."
        )
