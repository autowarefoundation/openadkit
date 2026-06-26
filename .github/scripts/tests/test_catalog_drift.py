"""Catalog drift guard: keeps the image catalog (the single source of truth)
consistent across its three manifests: `image-inventory.json`,
`docker-bake.hcl`, and the resolved build matrices.

If any of these drift, one or the other build path will silently pick up
a stale target list. Run alongside the matrix-resolver tests so CI fails
fast instead of producing a wrong-shape artifact.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import resolve_image_matrices as r

INVENTORY_PATH = pathlib.Path(".github/image-inventory.json")
BAKE_PATH = pathlib.Path("components/docker-bake.hcl")


def inventory_targets():
    return [img["target"] for img in json.loads(INVENTORY_PATH.read_text())["images"]]


def bake_metadata_action_targets():
    """Targets declared as `target "docker-metadata-action-…"` stubs."""
    text = BAKE_PATH.read_text()
    return re.findall(r'target\s+"docker-metadata-action-([\w-]+)"', text)


def bake_real_targets():
    """Real target blocks, excluding internal helpers (`_`-prefixed) and the
    empty `docker-metadata-action-*` stubs (which only exist to receive tags
    from docker/metadata-action)."""
    text = BAKE_PATH.read_text()
    all_targets = re.findall(r'^target\s+"([\w-]+)"', text, flags=re.MULTILINE)
    return [
        t
        for t in all_targets
        if not t.startswith("_") and not t.startswith("docker-metadata-action-")
    ]


def test_inventory_matches_metadata_action_stubs():
    """Every inventory target must have a docker-metadata-action stub in bake.hcl.

    The stubs are load-bearing — docker/metadata-action references them by
    name to inject tags — so a missing stub breaks local builds silently.
    """
    inv = set(inventory_targets())
    stubs = set(bake_metadata_action_targets())
    assert inv == stubs, (
        f"inventory targets and docker-metadata-action stubs diverge.\n"
        f"  in inventory, missing in bake: {sorted(inv - stubs)}\n"
        f"  in bake, missing in inventory: {sorted(stubs - inv)}"
    )


def test_inventory_matches_real_bake_targets():
    """Every inventory target must have a real bake target block (non-internal)."""
    inv = set(inventory_targets())
    real = set(bake_real_targets())
    assert inv == real, (
        f"inventory targets and bake target blocks diverge.\n"
        f"  in inventory, missing in bake: {sorted(inv - real)}\n"
        f"  in bake, missing in inventory: {sorted(real - inv)}"
    )


def test_resolved_matrices_cover_every_inventory_target():
    """Every inventory target must appear in the resolved matrices.

    Common-stage targets surface only in `common_matrix` (no `target` key);
    component-stage targets surface in `component_matrix` (with `target` key).
    Walk the manifest_matrix to cover both stages uniformly.
    """
    inventory = json.loads(INVENTORY_PATH.read_text())
    inv_targets = {img["target"] for img in inventory["images"]}
    matrices = r.build_matrices(inventory)
    matrix_targets = {
        entry["target"]
        for entry in matrices["manifest_matrix"]["include"]
    }
    missing = inv_targets - matrix_targets
    assert not missing, f"matrices are missing targets: {sorted(missing)}"
