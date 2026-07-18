import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "docs/scripts/generate_release_notes.py"
SPEC = importlib.util.spec_from_file_location("generate_release_notes_test", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def release_batch():
    return [
        {
            "tag_name": "v1.0.0",
            "name": "v1.0.0",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
            "html_url": "https://example.test/v1.0.0",
            "body": "notes",
        }
    ]


def test_fetch_releases_validates_schema(monkeypatch):
    monkeypatch.setattr(
        MODULE.urllib.request,
        "urlopen",
        lambda *args, **kwargs: Response(json.dumps({"not": "a list"}).encode()),
    )

    with pytest.raises(SystemExit):
        MODULE.fetch_releases("example/repo", None)


def test_fetch_releases_classifies_only_transient_errors(monkeypatch):
    def unavailable(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", unavailable)
    with pytest.raises(MODULE.TemporaryFetchError):
        MODULE.fetch_releases("example/repo", None)

    def unauthorized(*args, **kwargs):
        raise urllib.error.HTTPError("url", 401, "unauthorized", {}, None)

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", unauthorized)
    with pytest.raises(SystemExit):
        MODULE.fetch_releases("example/repo", None)


def test_fetch_releases_accepts_valid_api_response(monkeypatch):
    monkeypatch.setattr(
        MODULE.urllib.request,
        "urlopen",
        lambda *args, **kwargs: Response(json.dumps(release_batch()).encode()),
    )

    assert MODULE.fetch_releases("example/repo", None) == release_batch()


def test_main_keeps_existing_output_only_in_explicit_stale_mode(monkeypatch, tmp_path):
    output = tmp_path / "releases.md"
    output.write_text("sentinel\n")

    def unavailable(*args, **kwargs):
        raise MODULE.TemporaryFetchError("offline")

    monkeypatch.setattr(MODULE, "fetch_releases", unavailable)
    monkeypatch.setattr(
        MODULE,
        "parse_args",
        lambda: SimpleNamespace(
            repo="example/repo",
            output=output,
            allow_stale_on_fetch_error=True,
        ),
    )
    MODULE.main()
    assert output.read_text() == "sentinel\n"

    monkeypatch.setattr(
        MODULE,
        "parse_args",
        lambda: SimpleNamespace(
            repo="example/repo",
            output=output,
            allow_stale_on_fetch_error=False,
        ),
    )
    with pytest.raises(SystemExit):
        MODULE.main()
    assert output.read_text() == "sentinel\n"
