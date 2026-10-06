import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("fetch_baseline", ROOT / ".github/scripts/evidence/fetch_baseline.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def test_previous_release_is_semver_ordered_and_before_target():
    releases = [{"tag_name": version, "draft": False, "prerelease": False} for version in ("v2.9.0", "v2.10.0", "v3.0.0", "v2.11.0-rc.1")]
    assert baseline.previous_release(releases, "v2.11.0-rc.2")["tag_name"] == "v2.10.0"
    assert baseline.previous_release(releases, "v2.10.0")["tag_name"] == "v2.9.0"
    assert baseline.previous_release(releases, "v2.0.0") is None


def test_bad_or_current_build_cannot_be_a_baseline():
    summary = {"result": "PASSED", "build_tag": "123-1", "cells": [{"result": "PASSED"}]}
    assert not baseline.usable_summary(summary, "123-1")
    assert baseline.usable_summary(summary, "124-1")
    assert not baseline.usable_summary(summary | {"result": "WARNED"}, "124-1")
    assert not baseline.usable_summary(summary | {"cells": []}, "124-1")


def test_first_release_uses_different_successful_main_run(tmp_path, monkeypatch):
    summary = {"result": "PASSED", "build_tag": "123-1", "cells": [{"result": "PASSED"}]}
    calls = []

    def gh(*args):
        calls.append(args)
        if args[0] == "api":
            return "[[]]"
        if args[:2] == ("run", "list"):
            return '[{"databaseId": 10}, {"databaseId": 9}]'
        directory = Path(args[args.index("--dir") + 1])
        directory.mkdir()
        current = summary if args[2] == "10" else summary | {"build_tag": "122-1"}
        (directory / "evidence-summary.json").write_text(json.dumps(current))
        return ""

    monkeypatch.setattr(baseline, "gh", gh)
    result = baseline.fetch({"release": {"version": "v2.0.0", "buildTag": "123-1"}}, "example/repo", tmp_path)
    assert result["build_tag"] == "122-1"
    assert result["baseline"] == {"kind": "main", "runId": 9}
    run_list = next(call for call in calls if call[:2] == ("run", "list"))
    assert "main" in run_list and "success" in run_list
