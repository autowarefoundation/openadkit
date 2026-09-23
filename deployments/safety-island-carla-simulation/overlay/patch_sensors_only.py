#!/usr/bin/env python3
"""Skip ego.apply_control() so the CAN-CARLA bridge is the sole driver."""

from __future__ import annotations

import sys
from pathlib import Path

APPLY = "self.ego_actor.apply_control(ego_action)"
DISABLED = "pass  # safety-island: CAN bridge owns CARLA actuation"
SPAWN_ANCHOR = "        spawn_point, randomize = self._parse_spawn_point()\n"
DESTROY_BLOCK = (
    "        for actor in list(self.world.get_actors()):\n"
    '            if "vehicle" in getattr(actor, "type_id", "") and actor.attributes.get(\n'
    '                "role_name"\n'
    '            ) in ("ego_vehicle", "hero"):\n'
    "                actor.destroy()\n"
)


def patch_sensors_only(text: str) -> str:
    if DISABLED in text and not any(
        APPLY in line and not line.lstrip().startswith("#") for line in text.splitlines()
    ):
        return text
    lines = []
    replaced = 0
    for line in text.splitlines(keepends=True):
        if APPLY in line and not line.lstrip().startswith("#"):
            indent = line[: len(line) - len(line.lstrip())]
            newline = "\n" if line.endswith("\n") else ""
            lines.append(f"{indent}{DISABLED}{newline}")
            replaced += 1
        else:
            lines.append(line)
    if replaced != 1:
        raise ValueError(f"expected exactly one active CARLA apply_control call, found {replaced}")
    return "".join(lines)


def patch_destroy_leftover_egos(text: str) -> str:
    if DESTROY_BLOCK in text:
        return text
    if SPAWN_ANCHOR not in text:
        raise ValueError("CARLA ego spawn anchor not found")
    return text.replace(SPAWN_ANCHOR, DESTROY_BLOCK + SPAWN_ANCHOR, 1)


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/autoware")
    matches = sorted(root.glob("**/autoware_carla_interface/carla_autoware.py"))
    if len(matches) != 1:
        print(
            f"expected one carla_autoware.py under {root}, found {len(matches)}",
            file=sys.stderr,
        )
        return 1
    path = matches[0]
    original = path.read_text()
    try:
        updated = patch_destroy_leftover_egos(patch_sensors_only(original))
    except ValueError as error:
        print(f"cannot safely patch {path}: {error}", file=sys.stderr)
        return 1
    if updated == original:
        print(f"already patched: {path}")
        return 0
    try:
        path.write_text(updated)
    except OSError as error:
        print(f"could not write {path}: {error}", file=sys.stderr)
        return 1
    print(f"sensors-only: patched {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
