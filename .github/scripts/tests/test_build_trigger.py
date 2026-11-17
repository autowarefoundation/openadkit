"""build-all-images.yaml runs on a push that changes what the build runs."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/build-all-images.yaml"


def code(path: Path) -> str:
    return "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("#"))


def what_the_build_runs() -> tuple[set[str], set[str]]:
    """The scripts and local actions build-all-images.yaml runs, followed through actions and `source`."""
    actions: set[str] = set()
    texts = [code(WORKFLOW)]
    pending = [code(WORKFLOW)]
    while pending:
        for action in re.findall(r"uses: \./(\.github/actions/[\w-]+)", pending.pop()):
            if action not in actions:
                actions.add(action)
                texts.append(code(ROOT / action / "action.yaml"))
                pending.append(texts[-1])
    scripts: set[str] = set()
    found = [script for text in texts for script in re.findall(r"\.github/scripts/[\w.-]+\.(?:py|sh)", text)]
    while found:
        script = found.pop()
        if script not in scripts:
            scripts.add(script)
            sourced = re.findall(r'source "\$\{script_dir\}/([\w.-]+)"', code(ROOT / script))
            found += [f".github/scripts/{name}" for name in sourced]
    return scripts, actions


def trigger_paths() -> list[str]:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return workflow[True]["push"]["paths"]  # PyYAML reads the `on` key as True.


def test_a_change_to_anything_the_build_runs_starts_a_build():
    paths = trigger_paths()
    scripts, actions = what_the_build_runs()
    assert scripts and actions
    assert sorted(s for s in scripts if s not in paths) == []
    assert sorted(a for a in actions if f"{a}/**" not in paths) == []


def test_every_listed_script_exists():
    for path in trigger_paths():
        if path.startswith(".github/scripts/"):
            assert (ROOT / path).is_file(), path
