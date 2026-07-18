import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_LOOKUP = ROOT / ".github/scripts/registry_lookup.sh"
PROMOTE_IMAGES = ROOT / ".github/scripts/promote_release_images.sh"
MANAGE_RELEASE = ROOT / ".github/scripts/manage_github_release.sh"
WRITE_RELEASE_NOTES = ROOT / ".github/scripts/write_release_notes.sh"
VALIDATE_RELEASE = ROOT / ".github/scripts/validate_release.sh"
RESOLVE_UPSTREAM = ROOT / ".github/scripts/resolve_upstream_images.sh"
DIGEST = "sha256:" + "a" * 64
RELEASE_SHA = "b" * 40
PACKAGER_SHA = "c" * 40
VERSION = "v9.8.7"
MARKER = "<!-- openadkit-release-workflow:v1 -->"


def executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


def run_registry_lookup(tmp_path, docker_script):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(bin_dir / "docker", docker_script)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REGISTRY_LOOKUP_RETRY_DELAY_SECONDS": "0",
    }
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; registry_manifest_digest ghcr.io/example/image:tag',
            "bash",
            str(REGISTRY_LOOKUP),
        ],
        env=env,
        text=True,
        capture_output=True,
    )


def test_registry_lookup_returns_validated_digest(tmp_path):
    result = run_registry_lookup(
        tmp_path,
        f"#!/usr/bin/env bash\nprintf '%s\\n' '{json.dumps({'manifest': {'digest': DIGEST}})}'\n",
    )

    assert result.returncode == 0
    assert result.stdout.strip() == DIGEST


@pytest.mark.parametrize(
    ("message", "expected_status"),
    [
        ("ERROR: ghcr.io/example/image:tag: not found", 1),
        ("unexpected status: 404 Not Found", 1),
        ("MANIFEST_UNKNOWN: manifest unknown", 1),
        ("unexpected status: 401 Unauthorized", 2),
        ("failed to authorize: insufficient_scope", 2),
        ("arbitrary resolver failure", 2),
    ],
)
def test_registry_lookup_classifies_failures(tmp_path, message, expected_status):
    result = run_registry_lookup(
        tmp_path,
        f"#!/usr/bin/env bash\nprintf '%s\\n' {json.dumps(message)} >&2\nexit 1\n",
    )

    assert result.returncode == expected_status


def test_registry_lookup_retries_transient_failure_then_succeeds(tmp_path):
    count = tmp_path / "count"
    result = run_registry_lookup(
        tmp_path,
        "#!/usr/bin/env bash\n"
        f"count_file={json.dumps(str(count))}\n"
        'count=$(cat "$count_file" 2>/dev/null || printf 0)\n'
        'count=$((count + 1)); printf "%s\\n" "$count" > "$count_file"\n'
        'if [ "$count" -lt 3 ]; then printf "%s\\n" "503 Service Unavailable" >&2; exit 1; fi\n'
        f"printf '%s\\n' '{json.dumps({'manifest': {'digest': DIGEST}})}'\n",
    )

    assert result.returncode == 0
    assert result.stdout.strip() == DIGEST
    assert count.read_text().strip() == "3"


def test_upstream_images_are_resolved_once_to_immutable_contexts(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' '{json.dumps({'manifest': {'digest': DIGEST}})}'\n",
    )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"ros_distros": ["humble", "jazzy"]}))
    output = tmp_path / "upstream-images.json"
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AUTOWARE_BASE_VERSION": "1.8.0",
        "IMAGE_INVENTORY": str(inventory),
        "UPSTREAM_IMAGES_OUTPUT": str(output),
        "REGISTRY_LOOKUP_RETRY_DELAY_SECONDS": "0",
    }

    subprocess.run(["bash", str(RESOLVE_UPSTREAM)], env=env, check=True)

    images = json.loads(output.read_text())
    assert len(images) == 8
    assert len({(image["name"], image["ros_distro"]) for image in images}) == 8
    assert all(image["digest"] == DIGEST for image in images)
    assert all(image["uri"] == f"docker-image://{image['ref']}@{DIGEST}" for image in images)


def release_record(*, release_id=42, draft=True, body=MARKER + "\n", assets=None):
    return {
        "id": release_id,
        "tag_name": VERSION,
        "target_commitish": RELEASE_SHA,
        "name": VERSION,
        "draft": draft,
        "prerelease": False,
        "body": body,
        "assets": assets or [],
    }


def setup_release_files(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/example.tar.gz").write_bytes(b"bundle")
    build_dir = tmp_path / "release-input/build"
    build_dir.mkdir(parents=True)
    (build_dir / "autoware-lock.repos").write_text("repositories: {}\n")
    (build_dir / "upstream-images.json").write_text("[]\n")
    (tmp_path / "release-metadata.json").write_text('{"identity":"expected"}\n')
    (tmp_path / "release-notes.md").write_text(MARKER + "\n\nnotes\n")


def install_fake_gh(tmp_path, *, listed, refreshed=None, created=None, existing_dir=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    responses = tmp_path / "responses"
    responses.mkdir(exist_ok=True)
    (responses / "list.json").write_text(json.dumps([listed] if listed else []))
    (responses / "refresh.json").write_text(json.dumps(refreshed or listed or {}))
    (responses / "created.json").write_text(
        json.dumps(created or release_record(release_id=43))
    )
    tag = {"object": {"type": "commit", "sha": RELEASE_SHA}}
    (responses / "tag.json").write_text(json.dumps(tag))
    call_log = tmp_path / "gh-calls"
    executable(
        bin_dir / "gh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s\\n" "$*" >> "$GH_CALL_LOG"\n'
        'if [[ "$*" == *"/git/refs/tags/"* ]]; then cat "$GH_RESPONSES/tag.json"; exit 0; fi\n'
        'if [[ "$*" == *"--paginate --slurp"*"releases?per_page=100"* ]]; then '
        'if [[ -f "$GH_CREATED" ]]; then printf "[["; cat "$GH_RESPONSES/created.json"; '
        'printf "]]\\n"; else printf "["; cat "$GH_RESPONSES/list.json"; printf "]\\n"; fi; '
        'exit 0; fi\n'
        'if [[ "$*" == *"--method DELETE"* ]]; then touch "$GH_DELETED"; exit 0; fi\n'
        'if [[ "$*" == *"--method PATCH"* ]]; then touch "$GH_PATCHED"; exit 0; fi\n'
        'if [[ "$*" == *"/releases/tags/"* ]]; then cat "$GH_RESPONSES/created.json"; exit 0; fi\n'
        'if [[ "$1" == api && "$*" == *"/releases/"* ]]; then cat "$GH_RESPONSES/refresh.json"; exit 0; fi\n'
        'if [[ "$1" == release && "$2" == create ]]; then touch "$GH_CREATED"; exit 0; fi\n'
        'if [[ "$1" == release && "$2" == download ]]; then\n'
        '  while (($#)); do if [[ "$1" == --dir ]]; then shift; dest="$1"; break; fi; shift; done\n'
        '  mkdir -p "$dest"; cp "$GH_EXISTING_DIR"/* "$dest"/; exit 0\n'
        "fi\n"
        'printf "unhandled gh call: %s\\n" "$*" >&2\nexit 2\n',
    )
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_CALL_LOG": str(call_log),
        "GH_RESPONSES": str(responses),
        "GH_DELETED": str(tmp_path / "deleted"),
        "GH_CREATED": str(tmp_path / "created"),
        "GH_PATCHED": str(tmp_path / "patched"),
        "GH_EXISTING_DIR": str(existing_dir or tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "github-output"),
        "GITHUB_REPOSITORY": "example/repo",
        "RELEASE_SHA": RELEASE_SHA,
        "STABLE_RELEASE": "true",
        "VERSION": VERSION,
    }
    return env, call_log


def run_manager(tmp_path, env, command="prepare"):
    return subprocess.run(
        ["bash", str(MANAGE_RELEASE), command],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )


def test_prepare_replaces_only_owned_draft_by_release_id(tmp_path):
    setup_release_files(tmp_path)
    owned = release_record()
    env, call_log = install_fake_gh(tmp_path, listed=owned, refreshed=owned)

    result = run_manager(tmp_path, env)

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text().splitlines()
    delete_index = next(i for i, call in enumerate(calls) if "--method DELETE" in call)
    create_index = next(i for i, call in enumerate(calls) if "release create" in call)
    assert "releases/42" in calls[delete_index]
    assert delete_index < create_index
    assert not any("/releases/tags/" in call for call in calls)
    assert (tmp_path / "deleted").exists()
    assert (tmp_path / "created").exists()
    assert (tmp_path / "github-output").read_text().splitlines() == [
        "created=true",
        "release_id=43",
        "release_body_sha256="
        + hashlib.sha256((MARKER + "\n\nnotes\n").encode()).hexdigest(),
    ]


def test_prepare_refuses_unowned_draft_without_mutation(tmp_path):
    setup_release_files(tmp_path)
    unowned = release_record(body="manual draft\n")
    env, _ = install_fake_gh(tmp_path, listed=unowned, refreshed=unowned)

    result = run_manager(tmp_path, env)

    assert result.returncode != 0
    assert not (tmp_path / "deleted").exists()
    assert not (tmp_path / "created").exists()


def test_prepare_refuses_draft_changed_during_recheck(tmp_path):
    setup_release_files(tmp_path)
    owned = release_record()
    changed = release_record()
    changed["target_commitish"] = "f" * 40
    env, _ = install_fake_gh(tmp_path, listed=owned, refreshed=changed)

    result = run_manager(tmp_path, env)

    assert result.returncode != 0
    assert not (tmp_path / "deleted").exists()
    assert not (tmp_path / "created").exists()


@pytest.mark.parametrize("mismatch", ["body", "metadata"])
def test_published_release_compares_complete_body_and_metadata(tmp_path, mismatch):
    setup_release_files(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    expected_notes = (tmp_path / "release-notes.md").read_text()
    expected_metadata = (tmp_path / "release-metadata.json").read_text()
    (existing / "release-metadata.json").write_text(
        '{"identity":"different","formerly_omitted":true}\n'
        if mismatch == "metadata"
        else expected_metadata
    )
    (existing / "autoware-lock.repos").write_text("repositories: {}\n")
    (existing / "upstream-images.json").write_text("[]\n")
    (existing / "example.tar.gz").write_bytes(b"bundle")
    assets = [
        {"name": "release-metadata.json"},
        {"name": "autoware-lock.repos"},
        {"name": "upstream-images.json"},
        {"name": "example.tar.gz"},
    ]
    published = release_record(
        draft=False,
        body="different body\n" if mismatch == "body" else expected_notes,
        assets=assets,
    )
    env, _ = install_fake_gh(
        tmp_path,
        listed=published,
        refreshed=published,
        existing_dir=existing,
    )

    result = run_manager(tmp_path, env)

    assert result.returncode != 0
    assert not (tmp_path / "deleted").exists()
    assert not (tmp_path / "created").exists()


def test_matching_published_release_is_left_unchanged(tmp_path):
    setup_release_files(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    for path in (
        tmp_path / "release-metadata.json",
        tmp_path / "release-input/build/autoware-lock.repos",
        tmp_path / "release-input/build/upstream-images.json",
        tmp_path / "dist/example.tar.gz",
    ):
        target = existing / path.name
        target.write_bytes(path.read_bytes())
    assets = [
        {"name": "release-metadata.json"},
        {"name": "autoware-lock.repos"},
        {"name": "upstream-images.json"},
        {"name": "example.tar.gz"},
    ]
    published = release_record(
        draft=False,
        body=(tmp_path / "release-notes.md").read_text(),
        assets=assets,
    )
    env, _ = install_fake_gh(
        tmp_path,
        listed=published,
        refreshed=published,
        existing_dir=existing,
    )

    result = run_manager(tmp_path, env)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "github-output").read_text().splitlines()[:2] == [
        "created=false",
        "release_id=42",
    ]
    assert not (tmp_path / "deleted").exists()
    assert not (tmp_path / "created").exists()


def test_publish_revalidates_and_patches_exact_release_id(tmp_path):
    setup_release_files(tmp_path)
    owned = release_record()
    env, call_log = install_fake_gh(tmp_path, listed=owned, refreshed=owned)
    env |= {
        "RELEASE_ID": "42",
        "RELEASE_BODY_SHA256": hashlib.sha256((MARKER + "\n").encode()).hexdigest(),
        "PUBLISH_LATEST_ALIASES": "true",
    }

    result = run_manager(tmp_path, env, "publish")

    assert result.returncode == 0, result.stderr
    patch_call = next(
        call for call in call_log.read_text().splitlines() if "--method PATCH" in call
    )
    assert "releases/42" in patch_call
    assert "draft=false" in patch_call
    assert "make_latest=true" in patch_call


def test_publish_refuses_changed_draft_body(tmp_path):
    setup_release_files(tmp_path)
    changed = release_record(body=MARKER + "\nchanged after prepare\n")
    env, _ = install_fake_gh(tmp_path, listed=changed, refreshed=changed)
    env |= {
        "RELEASE_ID": "42",
        "RELEASE_BODY_SHA256": hashlib.sha256((MARKER + "\n").encode()).hexdigest(),
        "PUBLISH_LATEST_ALIASES": "true",
    }

    result = run_manager(tmp_path, env, "publish")

    assert result.returncode != 0
    assert "body changed" in result.stderr
    assert not (tmp_path / "patched").exists()


def test_release_metadata_records_packager_and_bundle_hashes(tmp_path):
    build = tmp_path / "release-input/build"
    scan = tmp_path / "release-input/scan"
    dist = tmp_path / "dist"
    build.mkdir(parents=True)
    scan.mkdir(parents=True)
    dist.mkdir()
    (dist / "one.tar.gz").write_bytes(b"one")
    (dist / "two.tar.gz").write_bytes(b"two")
    (build / "build-metadata.json").write_text(
        json.dumps(
            {
                "openadkit_sha": RELEASE_SHA,
                "build_tag": "1-1",
                "autoware_input_ref": "1.8.0",
                "autoware_ref_type": "tag",
                "autoware_ref": "d" * 40,
                "autoware_base_version": "1.8.0",
                "autoware_lock_sha256": "e" * 64,
                "upstream_images_sha256": "f" * 64,
                "upstream_images": [],
                "images": [],
            }
        )
    )
    (scan / "scan-metadata.json").write_text("{}\n")
    env = os.environ | {
        "VERSION": VERSION,
        "RELEASE_SHA": RELEASE_SHA,
        "DEFAULT_ROS_DISTRO": "humble",
        "PACKAGER_SHA": PACKAGER_SHA,
        "PUBLISH_LATEST_ALIASES": "false",
        "STABLE_RELEASE": "false",
    }

    subprocess.run(
        ["bash", str(WRITE_RELEASE_NOTES)], cwd=tmp_path, env=env, check=True
    )

    metadata = json.loads((tmp_path / "release-metadata.json").read_text())
    assert metadata["packager_sha"] == PACKAGER_SHA
    assert metadata["bundles"] == [
        {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(dist.glob("*.tar.gz"))
    ]
    assert (tmp_path / "release-notes.md").read_text().startswith(MARKER + "\n")

    invalid_env = env | {"PACKAGER_SHA": "not-a-sha"}
    invalid = subprocess.run(
        ["bash", str(WRITE_RELEASE_NOTES)], cwd=tmp_path, env=invalid_env
    )
    assert invalid.returncode != 0


def test_prerelease_rejects_autoware_sha_builds(tmp_path):
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "build-metadata.json").write_text(
        json.dumps(
            {
                "openadkit_sha": RELEASE_SHA,
                "autoware_input_ref": "d" * 40,
                "autoware_ref_type": "sha",
                "autoware_base_version": "1.8.0",
            }
        )
    )
    env = os.environ | {
        "BUILD_TAG": "1-1",
        "VERSION": "v9.8.7-rc.1",
        "GH_TOKEN": "test",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "IMAGE_PREFIX_COMMON": "example/common",
        "IMAGE_PREFIX_COMPONENT": "example/component",
    }

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; release_sha="$2"; validate_release_rules',
            "bash",
            str(VALIDATE_RELEASE),
            RELEASE_SHA,
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "Releases must be built from an Autoware release tag" in result.stderr


def test_upstream_metadata_schema_and_coverage_are_release_gates(tmp_path):
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    lock = build / "autoware-lock.repos"
    inventory_path = build / "image-inventory.json"
    upstream_path = build / "upstream-images.json"
    lock.write_text("repositories: {}\n")
    inventory = {
        "ros_distros": ["humble"],
        "images": [
            {
                "repo": "component",
                "target": "api",
                "platforms": ["linux/amd64"],
            }
        ],
    }
    inventory_path.write_text(json.dumps(inventory))
    upstream = [
        {
            "name": name,
            "ros_distro": "humble",
            "ref": f"ghcr.io/autowarefoundation/autoware:{name}-humble-1.8.0",
            "digest": DIGEST,
            "uri": f"docker-image://ghcr.io/autowarefoundation/autoware:{name}-humble-1.8.0@{DIGEST}",
        }
        for name in ("core-devel", "base", "base-cuda-runtime", "base-cuda-devel")
    ]
    upstream_path.write_text(json.dumps(upstream))
    metadata = {
        "build_tag": "1-1",
        "run_id": "1",
        "run_attempt": "1",
        "openadkit_sha": RELEASE_SHA,
        "autoware_input_ref": "1.8.0",
        "autoware_ref_type": "tag",
        "autoware_ref": "d" * 40,
        "autoware_base_version": "1.8.0",
        "autoware_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "image_inventory_sha256": hashlib.sha256(
            inventory_path.read_bytes()
        ).hexdigest(),
        "upstream_images_sha256": hashlib.sha256(
            upstream_path.read_bytes()
        ).hexdigest(),
        "scan_requested": True,
        "images": [
            {
                "repo": "example/component",
                "target": "api",
                "ros_distro": "humble",
                "ref": "example/component:api-humble-1-1",
                "digest": DIGEST,
                "platforms": ["linux/amd64"],
            }
        ],
        "upstream_images": upstream,
    }
    (build / "build-metadata.json").write_text(json.dumps(metadata))
    env = os.environ | {
        "BUILD_TAG": "1-1",
        "VERSION": VERSION,
        "GH_TOKEN": "test",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "IMAGE_PREFIX_COMMON": "example/common",
        "IMAGE_PREFIX_COMPONENT": "example/component",
    }

    subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; run_id=1; run_attempt=1; validate_build_metadata_schema; validate_metadata_files; validate_upstream_coverage',
            "bash",
            str(VALIDATE_RELEASE),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
    )

    metadata["upstream_images"].pop()
    (build / "build-metadata.json").write_text(json.dumps(metadata))
    invalid = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; validate_upstream_coverage',
            "bash",
            str(VALIDATE_RELEASE),
        ],
        cwd=tmp_path,
        env=env,
    )
    assert invalid.returncode != 0


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "duplicate", "distro-skew", "platform-skew"],
)
def test_inventory_coverage_rejects_incomplete_or_skewed_metadata(tmp_path, mutation):
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    inventory = {
        "ros_distros": ["humble", "jazzy"],
        "images": [
            {
                "repo": "component",
                "target": "api",
                "platforms": ["linux/amd64", "linux/arm64"],
            }
        ],
    }
    images = [
        {
            "repo": "example/component",
            "target": "api",
            "ros_distro": distro,
            "platforms": ["linux/amd64", "linux/arm64"],
        }
        for distro in ("humble", "jazzy")
    ]
    if mutation == "missing":
        images.pop()
    elif mutation == "extra":
        images.append(
            {
                "repo": "example/component",
                "target": "unknown",
                "ros_distro": "humble",
                "platforms": ["linux/amd64"],
            }
        )
    elif mutation == "duplicate":
        images.append(images[0].copy())
    elif mutation == "distro-skew":
        images[1]["ros_distro"] = "rolling"
    elif mutation == "platform-skew":
        images[1]["platforms"] = ["linux/amd64"]
    (build / "image-inventory.json").write_text(json.dumps(inventory))
    (build / "build-metadata.json").write_text(json.dumps({"images": images}))
    env = os.environ | {
        "BUILD_TAG": "1-1",
        "VERSION": VERSION,
        "GH_TOKEN": "test",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "IMAGE_PREFIX_COMMON": "example/common",
        "IMAGE_PREFIX_COMPONENT": "example/component",
    }

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; validate_inventory_coverage',
            "bash",
            str(VALIDATE_RELEASE),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0


def setup_promotion(tmp_path, docker_script, gh_script):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(bin_dir / "docker", docker_script)
    executable(bin_dir / "gh", gh_script)
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
    return os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DEFAULT_ROS_DISTRO": "humble",
        "GITHUB_REPOSITORY": "example/repo",
        "PUBLISH_LATEST_ALIASES": "true",
        "REGISTRY_LOOKUP_RETRY_DELAY_SECONDS": "0",
        "STABLE_RELEASE": "true",
        "VERSION": VERSION,
    }


def test_alias_policy_is_rechecked_after_immutable_promotion(tmp_path):
    calls = tmp_path / "docker-calls"
    docker_script = (
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {json.dumps(str(calls))}\n"
        'if [[ "$*" == *"imagetools inspect"* ]]; then printf "ERROR: %s: not found\\n" "$4" >&2; exit 1; fi\n'
        "exit 0\n"
    )
    gh_script = "#!/usr/bin/env bash\nprintf '%s\n' v9.9.0\n"
    env = setup_promotion(tmp_path, docker_script, gh_script)

    result = subprocess.run(
        ["bash", str(PROMOTE_IMAGES)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    creates = [line for line in calls.read_text().splitlines() if "imagetools create" in line]
    assert len(creates) == 1
    assert f"api-humble-{VERSION}" in creates[0]
    assert "Latest alias policy changed" in result.stderr


def test_promotion_never_mutates_after_registry_auth_failure(tmp_path):
    calls = tmp_path / "docker-calls"
    docker_script = (
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {json.dumps(str(calls))}\n"
        'printf "%s\\n" "401 Unauthorized" >&2\nexit 1\n'
    )
    env = setup_promotion(
        tmp_path, docker_script, "#!/usr/bin/env bash\nprintf '%s\n' v9.8.7\n"
    )

    result = subprocess.run(
        ["bash", str(PROMOTE_IMAGES)], cwd=tmp_path, env=env
    )

    assert result.returncode != 0
    assert all("imagetools create" not in line for line in calls.read_text().splitlines())


def test_promotion_never_mutates_after_exhausted_registry_retries(tmp_path):
    calls = tmp_path / "docker-calls"
    docker_script = (
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {json.dumps(str(calls))}\n"
        'printf "%s\\n" "503 Service Unavailable" >&2\nexit 1\n'
    )
    env = setup_promotion(
        tmp_path, docker_script, "#!/usr/bin/env bash\nprintf '%s\n' v9.8.7\n"
    )

    result = subprocess.run(
        ["bash", str(PROMOTE_IMAGES)], cwd=tmp_path, env=env
    )

    assert result.returncode != 0
    inspects = [line for line in calls.read_text().splitlines() if "imagetools inspect" in line]
    assert len(inspects) == 3
    assert all("imagetools create" not in line for line in calls.read_text().splitlines())


def test_alias_api_failure_happens_before_mutable_aliases(tmp_path):
    calls = tmp_path / "docker-calls"
    docker_script = (
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {json.dumps(str(calls))}\n"
        'if [[ "$*" == *"imagetools inspect"* ]]; then printf "ERROR: %s: not found\\n" "$4" >&2; exit 1; fi\n'
        "exit 0\n"
    )
    env = setup_promotion(
        tmp_path, docker_script, "#!/usr/bin/env bash\nexit 1\n"
    )

    result = subprocess.run(
        ["bash", str(PROMOTE_IMAGES)], cwd=tmp_path, env=env
    )

    assert result.returncode != 0
    creates = [line for line in calls.read_text().splitlines() if "imagetools create" in line]
    assert len(creates) == 1
    assert f"api-humble-{VERSION}" in creates[0]
