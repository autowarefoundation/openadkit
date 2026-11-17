"""Production publication ordering using local Git history, never GitHub writes."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(("case", "expected"), [("older", False), ("same", True), ("newer", True),
                                              ("first", True), ("unmarked-old", False),
                                              ("diverged", False), ("invalid", None),
                                              ("foreign", True), ("foreign-old", False)])
def test_production_site_cannot_regress_published_source(tmp_path, case, expected):
    jobs = yaml.safe_load((ROOT / ".github/workflows/deploy-docs.yaml").read_text())["jobs"]
    guard = next(step for step in jobs["deploy"]["steps"] if step.get("id") == "freshness")
    def git(*args, input=None):
        return subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
                              cwd=tmp_path, input=input, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "--initial-branch=main")
    git("commit", "--allow-empty", "-m", "old source")
    old = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "new source")
    new = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", new)
    source = old if case in ("older", "unmarked-old", "foreign-old") else new
    published = old if case == "newer" else new
    if case in ("foreign", "foreign-old"):
        published = "deadbeef" * 5  # Valid SHA, absent from this repository.
    if case == "diverged":
        empty = git("mktree", input="")
        source = git("commit-tree", empty, input="unrelated source\n")
    if case != "first":
        tree = ""
        if case != "unmarked-old":
            blob = git("hash-object", "-w", "--stdin", input=("invalid" if case == "invalid" else published) + "\n")
            tree = f"100644 blob {blob}\topenadkit-docs-source.txt\n"
        pages = git("commit-tree", git("mktree", input=tree), input="published site\n")
        git("update-ref", "refs/remotes/origin/gh-pages", pages)
    output = tmp_path / "output"
    result = subprocess.run(["bash", "-c", guard["run"]], cwd=tmp_path, capture_output=True, text=True,
                            env=os.environ | {"SOURCE_SHA": source, "DEFAULT_BRANCH": "main", "GITHUB_OUTPUT": str(output)})
    if expected is None:
        assert result.returncode != 0 and not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert output.read_text().strip() == f"current={str(expected).lower()}"
    assert jobs["build"]["outputs"]["source_sha"] == "${{ steps.checkout.outputs.commit }}"
    marker = next(step for step in jobs["build"]["steps"] if step["name"] == "Record site source")
    assert "site/openadkit-docs-source.txt" in marker["run"]  # Not hidden: artifact upload must retain it.
    for name in ("Download production site", "Deploy to GitHub Pages"):
        step = next(step for step in jobs["deploy"]["steps"] if step["name"] == name)
        assert step["if"] == "${{ steps.freshness.outputs.current == 'true' }}"
    assert jobs["deploy"]["concurrency"]["group"] == "gh-pages"
