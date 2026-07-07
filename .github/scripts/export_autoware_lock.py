#!/usr/bin/env python3
"""Export an Autoware repos file with every git dependency pinned to a SHA."""
import json
import pathlib
import re
import subprocess
import sys

import yaml


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def ls_remote(url, ref):
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", url, ref],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()[0]


def resolve(url, version):
    if SHA_RE.fullmatch(version):
        return version.lower()
    for ref in (
        f"refs/tags/{version}^{{}}",
        f"refs/tags/{version}",
        f"refs/heads/{version}",
        version,
    ):
        sha = ls_remote(url, ref)
        if sha and SHA_RE.fullmatch(sha):
            return sha.lower()
    raise RuntimeError(f"Could not resolve {url}@{version} to a commit SHA")


def export_lock(source, target):
    data = yaml.safe_load(source.read_text())
    repos = data.get("repositories", {})
    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("w") as out:
        out.write("repositories:\n")
        for path, repo in repos.items():
            repo_type = repo.get("type")
            url = repo.get("url")
            version = str(repo.get("version", ""))
            if repo_type != "git" or not url or not version:
                raise RuntimeError(f"Unsupported repository entry: {path}")
            resolved = resolve(url, version)
            print(f"{path}: {version} -> {resolved}", file=sys.stderr)
            out.write(f"  {json.dumps(path)}:\n")
            out.write(f"    type: {json.dumps(repo_type)}\n")
            out.write(f"    url: {json.dumps(url)}\n")
            out.write(f"    version: {json.dumps(resolved)}\n")


def main(argv):
    if len(argv) != 3:
        print("usage: export_autoware_lock.py <source.repos> <target.repos>", file=sys.stderr)
        return 2
    export_lock(pathlib.Path(argv[1]), pathlib.Path(argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
