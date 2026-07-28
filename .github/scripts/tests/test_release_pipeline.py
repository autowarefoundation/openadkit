import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
MANAGER = ROOT / ".github/scripts/manage_github_release.sh"
PACKAGER = ROOT / ".github/scripts/package_release_bundles.sh"
PROMOTER = ROOT / ".github/scripts/promote_release_images.sh"
REGISTRY_LOOKUP = ROOT / ".github/scripts/registry_lookup.sh"
VALIDATOR = ROOT / ".github/scripts/validate_release.sh"
DIGEST = "sha256:" + "a" * 64
RELEASE_SHA = "b" * 40
VERSION = "v9.8.7"
MARKER = "<!-- openadkit-release-workflow:v1 -->"


def executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


def run_release_rules(tmp_path, *, version, ref_type, input_ref, base_version="1.8.0"):
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "build-metadata.json").write_text(
        json.dumps(
            {
                "openadkit_sha": RELEASE_SHA,
                "autoware_input_ref": input_ref,
                "autoware_ref_type": ref_type,
                "autoware_base_version": base_version,
            }
        )
    )
    env = os.environ | {
        "BUILD_TAG": "123-1",
        "GH_TOKEN": "test",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "example/repo",
        "IMAGE_PREFIX_COMMON": "ghcr.io/example/openadkit-common",
        "IMAGE_PREFIX_COMPONENT": "ghcr.io/example/openadkit",
        "VERSION": version,
    }
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; release_sha="$2"; validate_release_rules',
            "bash",
            str(VALIDATOR),
            RELEASE_SHA,
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    ("version", "ref_type", "input_ref"),
    [
        ("v2.0.0", "tag", "1.8.0"),
        ("v2.0.0-rc.1", "tag", "1.8.0"),
        ("v2.0.0-rc.1", "sha", "a" * 40),
    ],
)
def test_release_rules_accept_supported_autoware_refs(
    tmp_path, version, ref_type, input_ref
):
    result = run_release_rules(
        tmp_path, version=version, ref_type=ref_type, input_ref=input_ref
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("version", "ref_type", "input_ref"),
    [
        ("v2.0.0", "sha", "a" * 40),
        ("v2.0.0-rc.1", "branch", "main"),
        ("v2.0.0-rc.1", "sha", "abc123"),
    ],
)
def test_release_rules_reject_unsupported_autoware_refs(
    tmp_path, version, ref_type, input_ref
):
    result = run_release_rules(
        tmp_path, version=version, ref_type=ref_type, input_ref=input_ref
    )
    assert result.returncode != 0


def test_registry_lookup_retries_and_classifies_failures(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    count = tmp_path / "count"
    docker = bin_dir / "docker"
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REGISTRY_LOOKUP_RETRY_DELAY_SECONDS": "0",
    }

    executable(
        docker,
        "#!/usr/bin/env bash\n"
        f"count_file={json.dumps(str(count))}\n"
        'count=$(cat "$count_file" 2>/dev/null || printf 0)\n'
        'count=$((count + 1)); printf "%s\\n" "$count" > "$count_file"\n'
        'if [ "$count" -lt 3 ]; then echo "503 Service Unavailable" >&2; exit 1; fi\n'
        f"printf '%s\\n' '{json.dumps({'manifest': {'digest': DIGEST}})}'\n",
    )
    command = [
        "bash",
        "-c",
        'source "$1"; registry_manifest_digest ghcr.io/example/image:tag',
        "bash",
        str(REGISTRY_LOOKUP),
    ]
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    assert result.returncode == 0
    assert result.stdout.strip() == DIGEST
    assert count.read_text().strip() == "3"

    executable(docker, '#!/usr/bin/env bash\necho "401 Unauthorized" >&2\nexit 1\n')
    assert subprocess.run(command, env=env).returncode == 2


def release_record(
    *, release_id=42, body=MARKER + "\n", target=RELEASE_SHA, assets=None
):
    return {
        "id": release_id,
        "tag_name": VERSION,
        "target_commitish": target,
        "name": VERSION,
        "draft": True,
        "prerelease": False,
        "body": body,
        "assets": assets or [],
    }


def release_assets():
    return [
        {"id": 101, "name": "release-metadata.json"},
        {"id": 102, "name": "autoware-lock.repos"},
        {"id": 103, "name": "upstream-images.json"},
        {"id": 104, "name": "example.tar.gz"},
    ]


def release_workspace(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/example.tar.gz").write_bytes(b"bundle")
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "autoware-lock.repos").write_text("repositories: {}\n")
    (build / "upstream-images.json").write_text("[]\n")
    (tmp_path / "release-metadata.json").write_text("{}\n")
    (tmp_path / "release-notes.md").write_text(MARKER + "\n")
    files = [
        tmp_path / "release-metadata.json",
        build / "autoware-lock.repos",
        build / "upstream-images.json",
        tmp_path / "dist/example.tar.gz",
    ]
    manifest = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(files, key=lambda path: path.name)
    )
    (tmp_path / "release-assets.sha256").write_text(manifest)


def fake_gh_environment(tmp_path, listed, refreshed=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    responses = tmp_path / "responses"
    responses.mkdir()
    created = release_record(release_id=43)
    (responses / "listed").write_text(json.dumps([listed] if listed else []))
    (responses / "refreshed").write_text(json.dumps(refreshed or listed or {}))
    (responses / "created").write_text(json.dumps(created))
    state = refreshed or listed or {}
    asset_sources = {
        "release-metadata.json": tmp_path / "release-metadata.json",
        "autoware-lock.repos": tmp_path / "release-input/build/autoware-lock.repos",
        "upstream-images.json": tmp_path / "release-input/build/upstream-images.json",
        "example.tar.gz": tmp_path / "dist/example.tar.gz",
    }
    for asset in state.get("assets", []):
        source = asset_sources.get(asset["name"])
        if source is not None:
            (responses / f"asset-{asset['id']}").write_bytes(source.read_bytes())
    log = tmp_path / "gh-calls"
    executable(
        bin_dir / "gh",
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'printf "%s\\n" "$*" >> "$GH_LOG"\n'
        'if [[ "$*" == *"/git/refs/tags/"* ]]; then '
        f"printf '%s\\n' '{json.dumps({'object': {'type': 'commit', 'sha': RELEASE_SHA}})}'; exit; fi\n"
        'if [[ "$*" == *"--paginate --slurp"* ]]; then '
        'if [ -f "$GH_CREATED" ]; then printf "[["; cat "$GH_RESPONSES/created"; printf "]]\\n"; '
        'else printf "["; cat "$GH_RESPONSES/listed"; printf "]\\n"; fi; exit; fi\n'
        'if [[ "$*" == *"--method DELETE"* ]]; then touch "$GH_DELETED"; exit; fi\n'
        'if [[ "$*" == *"--method PATCH"* ]]; then touch "$GH_PATCHED"; exit; fi\n'
        'if [[ "$*" == *"/releases/assets/"* ]]; then uri="${!#}"; cat "$GH_RESPONSES/asset-${uri##*/}"; exit; fi\n'
        'if [[ "$1" == api && "$*" == *"/releases/"* ]]; then cat "$GH_RESPONSES/refreshed"; exit; fi\n'
        'if [[ "$1 $2" == "release create" ]]; then touch "$GH_CREATED"; exit; fi\n'
        'echo "unhandled gh call: $*" >&2; exit 2\n',
    )
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GH_RESPONSES": str(responses),
        "GH_CREATED": str(tmp_path / "created"),
        "GH_DELETED": str(tmp_path / "deleted"),
        "GH_PATCHED": str(tmp_path / "patched"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_REPOSITORY": "example/repo",
        "RELEASE_SHA": RELEASE_SHA,
        "STABLE_RELEASE": "true",
        "VERSION": VERSION,
    }
    return env, log


def run_manager(tmp_path, env, operation="prepare"):
    return subprocess.run(
        ["bash", str(MANAGER), operation],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )


def test_prepare_replaces_only_unchanged_owned_draft(tmp_path):
    release_workspace(tmp_path)
    owned = release_record()
    env, log = fake_gh_environment(tmp_path, owned)
    result = run_manager(tmp_path, env)
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert next(i for i, call in enumerate(calls) if "DELETE" in call) < next(
        i for i, call in enumerate(calls) if "release create" in call
    )
    assert (tmp_path / "output").read_text().startswith("created=true\nrelease_id=43\n")


@pytest.mark.parametrize(
    ("listed", "refreshed"),
    [
        (release_record(body="manual draft\n"), None),
        (release_record(), release_record(target="f" * 40)),
    ],
)
def test_prepare_refuses_unowned_or_changed_draft(tmp_path, listed, refreshed):
    release_workspace(tmp_path)
    env, _ = fake_gh_environment(tmp_path, listed, refreshed)
    result = run_manager(tmp_path, env)
    assert result.returncode != 0
    assert not (tmp_path / "deleted").exists()
    assert not (tmp_path / "created").exists()


def test_publish_revalidates_body_before_mutation(tmp_path):
    release_workspace(tmp_path)
    changed = release_record(body=MARKER + "\nchanged\n")
    env, _ = fake_gh_environment(tmp_path, changed)
    env |= {
        "RELEASE_ID": "42",
        "RELEASE_BODY_SHA256": hashlib.sha256((MARKER + "\n").encode()).hexdigest(),
        "PUBLISH_LATEST_ALIASES": "true",
    }
    result = run_manager(tmp_path, env, "publish")
    assert result.returncode != 0
    assert not (tmp_path / "patched").exists()


def test_publish_patches_the_revalidated_release_id(tmp_path):
    release_workspace(tmp_path)
    owned = release_record(assets=release_assets())
    env, log = fake_gh_environment(tmp_path, owned)
    env |= {
        "RELEASE_ID": "42",
        "RELEASE_BODY_SHA256": hashlib.sha256((MARKER + "\n").encode()).hexdigest(),
        "PUBLISH_LATEST_ALIASES": "true",
    }
    result = run_manager(tmp_path, env, "publish")
    assert result.returncode == 0, result.stderr
    patch = next(call for call in log.read_text().splitlines() if "PATCH" in call)
    assert "releases/42" in patch
    assert "draft=false" in patch


def test_publish_rejects_changed_draft_asset(tmp_path):
    release_workspace(tmp_path)
    owned = release_record(assets=release_assets())
    env, _ = fake_gh_environment(tmp_path, owned)
    (tmp_path / "responses/asset-104").write_bytes(b"replaced bundle")
    env |= {
        "RELEASE_ID": "42",
        "RELEASE_BODY_SHA256": hashlib.sha256((MARKER + "\n").encode()).hexdigest(),
        "PUBLISH_LATEST_ALIASES": "true",
    }
    result = run_manager(tmp_path, env, "publish")
    assert result.returncode != 0
    assert not (tmp_path / "patched").exists()


def test_registry_auth_failure_never_mutates_image_tags(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls"
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> {json.dumps(str(calls))}\n'
        'echo "401 Unauthorized" >&2\nexit 1\n',
    )
    executable(bin_dir / "gh", "#!/usr/bin/env bash\nprintf '%s\\n' v9.8.7\n")
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "build-metadata.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "repo": "ghcr.io/example/openadkit",
                        "target": "api",
                        "ros_distro": "humble",
                        "digest": DIGEST,
                    }
                ]
            }
        )
    )
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DEFAULT_ROS_DISTRO": "humble",
        "GITHUB_REPOSITORY": "example/repo",
        "PUBLISH_LATEST_ALIASES": "true",
        "REGISTRY_LOOKUP_RETRY_DELAY_SECONDS": "0",
        "STABLE_RELEASE": "true",
        "VERSION": VERSION,
    }
    result = subprocess.run(["bash", str(PROMOTER)], cwd=tmp_path, env=env)
    assert result.returncode != 0
    assert all("imagetools create" not in call for call in calls.read_text().splitlines())


def test_release_bundles_pin_images_and_are_reproducible(tmp_path):
    refs = [
        "ghcr.io/autowarefoundation/autoware:universe",
        "eclipse/zenoh-bridge-ros2dds:latest",
        "ghcr.io/evshary/autoware_manual_control:latest",
        "ghcr.io/tier4/scenario_simulator_v2:humble-25.0.20-runtime",
        "carlasim/carla:0.9.16",
        "busybox:1.36.1",
    ]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(bin_dir / "docker", "#!/usr/bin/env bash\nexit 0\n")
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    images = []
    for image in json.loads((ROOT / ".github/image-inventory.json").read_text())["images"]:
        if image["repo"] != "component":
            continue
        for distro in image.get("ros_distros", ["humble", "jazzy"]):
            images.append(
                {
                    "repo": "ghcr.io/example/openadkit",
                    "target": image["target"],
                    "ros_distro": distro,
                    "digest": DIGEST,
                }
            )
    (build / "build-metadata.json").write_text(json.dumps({"images": images}))
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SOURCE_DIR": str(ROOT),
        "VERSION": VERSION,
        "DEFAULT_ROS_DISTRO": "jazzy",
        "IMAGE_PREFIX_COMPONENT": "ghcr.io/example/openadkit",
        "THIRD_PARTY_IMAGE_DIGESTS_JSON": json.dumps({ref: DIGEST for ref in refs}),
    }
    subprocess.run(["bash", str(PACKAGER)], cwd=tmp_path, env=env, check=True)
    first = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (tmp_path / "dist").glob("*.tar.gz")
    }
    assert len(first) == 5
    for name in (
        "planning-simulation",
        "scenario-simulation",
        "logging-simulation",
        "carla-simulation",
        "zenoh-bridge",
    ):
        text = "\n".join(
            path.read_text()
            for path in (tmp_path / "staging" / name).rglob("*")
            if path.is_file() and (path.suffix in {".yaml", ".env"} or path.name == ".env")
        )
        assert "ghcr.io/autowarefoundation/openadkit:" not in text
        refs = re.findall(r"ghcr.io/example/openadkit:[a-z-]+-(?:humble|jazzy)-v9\.8\.7[^\s\"}]*", text)
        assert refs
        assert all(ref.endswith(f"@{DIGEST}") for ref in refs)
    subprocess.run(["bash", str(PACKAGER)], cwd=tmp_path, env=env, check=True)
    second = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (tmp_path / "dist").glob("*.tar.gz")
    }
    assert second == first
