import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
MANAGER = ROOT / ".github/scripts/manage_github_release.sh"
PACKAGER = ROOT / ".github/scripts/package_release_bundles.sh"
PLANNER = ROOT / ".github/scripts/release_plan.py"
PROMOTER = ROOT / ".github/scripts/promote_release_images.sh"
REGISTRY_LOOKUP = ROOT / ".github/scripts/registry_lookup.sh"
VALIDATOR = ROOT / ".github/scripts/validate_release.sh"
WRITE_NOTES = ROOT / ".github/scripts/write_release_notes.sh"
DIGEST = "sha256:" + "a" * 64
RELEASE_SHA = "b" * 40
VERSION = "v9.8.7"
MARKER = "<!-- openadkit-release-workflow:v1 -->"
BUILD_TAG = "123-1"
RUNTIME_TARGETS = {
    "api",
    "localization-mapping",
    "planning-control",
    "sensing-perception",
    "sensing-perception-cuda",
    "simulator",
    "vehicle-system",
    "visualizer",
}


def executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


def build_images():
    inventory = json.loads((ROOT / ".github/image-inventory.json").read_text())
    rows = []
    for image in inventory["images"]:
        repo = (
            "ghcr.io/example/openadkit-common"
            if image["repo"] == "common"
            else "ghcr.io/example/openadkit"
        )
        for distro in image.get("ros_distros", inventory["ros_distros"]):
            rows.append(
                {
                    "repo": repo,
                    "target": image["target"],
                    "ros_distro": distro,
                    "ref": f"{repo}:{image['target']}-{distro}-{BUILD_TAG}",
                    "digest": DIGEST,
                    "platforms": image["platforms"],
                }
            )
    return rows


def write_plan(tmp_path, *, images=None):
    metadata = tmp_path / "build-metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "build_tag": BUILD_TAG,
                "openadkit_sha": RELEASE_SHA,
                "images": images if images is not None else build_images(),
            }
        )
    )
    output = tmp_path / "release-plan.json"
    result = subprocess.run(
        [
            "python3",
            str(PLANNER),
            "--source-root",
            str(ROOT),
            "--build-metadata",
            str(metadata),
            "--version",
            VERSION,
            "--release-sha",
            RELEASE_SHA,
            "--packager-sha",
            "c" * 40,
            "--default-ros-distro",
            "humble",
            "--stable-release",
            "true",
            "--publish-latest-aliases",
            "true",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
    )
    return result, output


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
        {"id": 101, "name": "release-plan.json"},
        {"id": 102, "name": "release-metadata.json"},
        {"id": 103, "name": "autoware-lock.repos"},
        {"id": 104, "name": "upstream-images.json"},
        {"id": 105, "name": f"openadkit-{VERSION}.tar.gz"},
    ]


def release_workspace(tmp_path):
    (tmp_path / "dist").mkdir()
    bundle = tmp_path / f"dist/openadkit-{VERSION}.tar.gz"
    bundle.write_bytes(b"bundle")
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "autoware-lock.repos").write_text("repositories: {}\n")
    (build / "upstream-images.json").write_text("[]\n")
    (tmp_path / "release-metadata.json").write_text("{}\n")
    (tmp_path / "release-notes.md").write_text(MARKER + "\n")
    (tmp_path / "release-plan.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "release": {
                    "version": VERSION,
                    "releaseSha": RELEASE_SHA,
                    "stable": True,
                    "publishLatestAliases": True,
                },
                "githubAssets": [
                    {"name": "release-plan.json", "path": "release-plan.json"},
                    {"name": "release-metadata.json", "path": "release-metadata.json"},
                    {
                        "name": "autoware-lock.repos",
                        "path": "release-input/build/autoware-lock.repos",
                    },
                    {
                        "name": "upstream-images.json",
                        "path": "release-input/build/upstream-images.json",
                    },
                    {
                        "name": bundle.name,
                        "path": f"dist/{bundle.name}",
                    },
                ],
            }
        )
    )
    files = [
        tmp_path / "release-plan.json",
        tmp_path / "release-metadata.json",
        build / "autoware-lock.repos",
        build / "upstream-images.json",
        bundle,
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
        "release-plan.json": tmp_path / "release-plan.json",
        "release-metadata.json": tmp_path / "release-metadata.json",
        "autoware-lock.repos": tmp_path / "release-input/build/autoware-lock.repos",
        "upstream-images.json": tmp_path / "release-input/build/upstream-images.json",
        f"openadkit-{VERSION}.tar.gz": tmp_path / f"dist/openadkit-{VERSION}.tar.gz",
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
    (tmp_path / "responses/asset-105").write_bytes(b"replaced bundle")
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
        'if [ "$1 $2 $3" = "buildx imagetools inspect" ]; then\n'
        f'  if [[ "$4" == *"-{BUILD_TAG}" ]]; then printf \'%s\\n\' \'{json.dumps({"manifest": {"digest": DIGEST}})}\'; exit; fi\n'
        f'  if [[ "$4" == *"-{VERSION}" ]]; then echo "ERROR: $4: not found" >&2; exit 1; fi\n'
        '  echo "401 Unauthorized" >&2; exit 1\n'
        'fi\n'
        "exit 1\n",
    )
    executable(bin_dir / "gh", "#!/usr/bin/env bash\nprintf '%s\\n' v9.8.7\n")
    (tmp_path / "release-plan.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "release": {
                    "version": VERSION,
                    "defaultRosDistro": "humble",
                    "stable": True,
                    "publishLatestAliases": True,
                },
                "images": [
                    {
                        "repo": "ghcr.io/example/openadkit",
                        "rosDistro": "humble",
                        "digest": DIGEST,
                        "sourceRef": f"ghcr.io/example/openadkit:api-humble-{BUILD_TAG}",
                        "releaseRef": f"ghcr.io/example/openadkit:api-humble-{VERSION}",
                        "aliases": ["ghcr.io/example/openadkit:api-humble"],
                    }
                ]
            }
        )
    )
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "example/repo",
        "REGISTRY_LOOKUP_RETRY_DELAY_SECONDS": "0",
    }
    result = subprocess.run(["bash", str(PROMOTER)], cwd=tmp_path, env=env)
    assert result.returncode != 0
    assert all("imagetools create" not in call for call in calls.read_text().splitlines())


def test_failed_version_tag_never_updates_stable_aliases(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls"
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        'if [ "$1 $2 $3" = "buildx imagetools inspect" ]; then\n'
        f'  if [[ "$4" == *"-{BUILD_TAG}" ]]; then printf \'%s\\n\' \'{json.dumps({"manifest": {"digest": DIGEST}})}\'; exit; fi\n'
        '  echo "ERROR: $4: not found" >&2; exit 1\n'
        'fi\n'
        f'printf "%s\\n" "$*" >> {json.dumps(str(calls))}\n'
        "exit 1\n",
    )
    executable(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    executable(bin_dir / "gh", f"#!/usr/bin/env bash\nprintf '%s\\n' {VERSION}\n")
    (tmp_path / "release-plan.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "release": {
                    "version": VERSION,
                    "defaultRosDistro": "humble",
                    "stable": True,
                    "publishLatestAliases": True,
                },
                "images": [
                    {
                        "repo": "ghcr.io/example/openadkit",
                        "rosDistro": "humble",
                        "digest": DIGEST,
                        "sourceRef": f"ghcr.io/example/openadkit:api-humble-{BUILD_TAG}",
                        "releaseRef": f"ghcr.io/example/openadkit:api-humble-{VERSION}",
                        "aliases": ["ghcr.io/example/openadkit:api-humble"],
                    }
                ]
            }
        )
    )
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "example/repo",
        "REGISTRY_LOOKUP_MAX_ATTEMPTS": "1",
    }
    result = subprocess.run(["bash", str(PROMOTER)], cwd=tmp_path, env=env)
    assert result.returncode != 0
    assert all(f"-{VERSION}" in call for call in calls.read_text().splitlines())


def test_stable_promotion_consumes_planned_version_and_aliases(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    promoted = tmp_path / "promoted"
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'if [ "$1 $2 $3" = "buildx imagetools inspect" ]; then\n'
        '  ref="$4"\n'
        f'  if [[ "$ref" == *"-{BUILD_TAG}" ]] || grep -Fxq "$ref" "$PROMOTED" 2>/dev/null; then\n'
        f'    printf \'%s\\n\' \'{json.dumps({"manifest": {"digest": DIGEST}})}\'; exit\n'
        '  fi\n'
        '  echo "ERROR: $ref: not found" >&2; exit 1\n'
        'fi\n'
        'if [ "$1 $2 $3" = "buildx imagetools create" ]; then printf \'%s\\n\' "$5" >> "$PROMOTED"; exit; fi\n'
        'exit 2\n',
    )
    executable(bin_dir / "gh", f"#!/usr/bin/env bash\nprintf '%s\\n' {VERSION}\n")
    (tmp_path / "release-plan.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "release": {
                    "version": VERSION,
                    "defaultRosDistro": "humble",
                    "stable": True,
                    "publishLatestAliases": True,
                },
                "images": [
                    {
                        "repo": "ghcr.io/example/openadkit",
                        "rosDistro": "humble",
                        "digest": DIGEST,
                        "sourceRef": f"ghcr.io/example/openadkit:api-humble-{BUILD_TAG}",
                        "releaseRef": f"ghcr.io/example/openadkit:api-humble-{VERSION}",
                        "aliases": ["ghcr.io/example/openadkit:api-humble"],
                    }
                ],
            }
        )
    )
    result = subprocess.run(
        ["bash", str(PROMOTER)],
        cwd=tmp_path,
        env=os.environ
        | {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "example/repo",
            "PROMOTED": str(promoted),
            "REGISTRY_LOOKUP_MAX_ATTEMPTS": "1",
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert promoted.read_text().splitlines() == [
        f"ghcr.io/example/openadkit:api-humble-{VERSION}",
        "ghcr.io/example/openadkit:api-humble",
    ]


def test_release_plan_builds_complete_dual_distro_context(tmp_path):
    result, output = write_plan(tmp_path)
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_text())
    assert plan["bundle"] == {
        "asset": f"openadkit-{VERSION}.tar.gz",
        "deployments": [
            "carla-simulation",
            "logging-simulation",
            "planning-simulation",
            "scenario-simulation",
        ],
        "root": f"openadkit-{VERSION}",
        "runtime": ["openadkit", "openadkit.d"],
        "shared": ["base"],
    }
    context = plan["releaseContext"]
    assert context["defaultRosDistro"] == "humble"
    assert set(context["deployments"]) == set(plan["bundle"]["deployments"])
    assert set(context["shared"]) == {"base"}
    for distro in ("humble", "jazzy"):
        assert set(context["images"][distro]) == RUNTIME_TARGETS
        assert all(
            reference.endswith(f"@{DIGEST}")
            and f"-{distro}-{VERSION}@" in reference
            for reference in context["images"][distro].values()
        )
    assert "carla-interface" not in context["images"]["humble"]
    assert "universe-common" not in context["images"]["humble"]


@pytest.mark.parametrize("case", ("missing", "duplicate"))
def test_release_plan_rejects_incomplete_or_duplicate_runtime_images(tmp_path, case):
    images = build_images()
    if case == "missing":
        images = [
            image
            for image in images
            if (image["target"], image["ros_distro"]) != ("api", "jazzy")
        ]
    else:
        images.append(dict(images[0]))
    result, _ = write_plan(tmp_path, images=images)
    assert result.returncode != 0
    assert case in result.stderr


def test_release_bundle_is_unified_verified_and_reproducible(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls"
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        f'printf "%s|%s\\n" "${{ROS_DISTRO:-}}" "$*" >> {json.dumps(str(calls))}\n'
        'if [[ "$*" == *"config --services"* ]]; then\n'
        "  printf '%s\\n' map map-check planning vehicle system control simulator api visualizer sensing perception localization rosbag scenario_simulator carla carla-interface carla-map-loader\n"
        "fi\n"
        "exit 0\n",
    )
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "build-metadata.json").write_text(
        json.dumps(
            {
                "build_tag": BUILD_TAG,
                "openadkit_sha": RELEASE_SHA,
                "autoware_input_ref": "1.8.0",
                "autoware_ref_type": "tag",
                "autoware_ref": "d" * 40,
                "autoware_base_version": "1.8.0",
                "autoware_lock_sha256": "e" * 64,
                "upstream_images_sha256": "f" * 64,
                "images": build_images(),
            }
        )
    )
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SOURCE_DIR": str(ROOT),
        "VERSION": VERSION,
        "RELEASE_SHA": RELEASE_SHA,
        "PACKAGER_SHA": "c" * 40,
        "DEFAULT_ROS_DISTRO": "jazzy",
        "PUBLISH_LATEST_ALIASES": "true",
        "STABLE_RELEASE": "true",
    }
    command = [
        "bash",
        "-c",
        'umask "$1"; exec bash "$2"',
        "bash",
        "022",
        str(PACKAGER),
    ]
    subprocess.run(command, cwd=tmp_path, env=env, check=True)
    asset = tmp_path / f"dist/openadkit-{VERSION}.tar.gz"
    assert [path.name for path in (tmp_path / "dist").iterdir()] == [asset.name]
    first_asset = hashlib.sha256(asset.read_bytes()).hexdigest()
    first_plan = hashlib.sha256((tmp_path / "release-plan.json").read_bytes()).hexdigest()

    with tarfile.open(asset) as archive:
        members = archive.getmembers()
        assert members
        assert all(member.mtime == 0 and member.uid == 0 and member.gid == 0 for member in members)
        assert all(not member.issym() and not member.islnk() for member in members)
        assert all("__pycache__" not in member.name and not member.name.endswith(".pyc") for member in members)
        extract = tmp_path / "extracted"
        archive.extractall(extract, filter="data")

    root = extract / f"openadkit-{VERSION}"
    assert os.access(root / "openadkit", os.X_OK)
    assert (root / "openadkit.json").is_file()
    bundled_deployments = {
        path.name for path in (root / "deployments").iterdir() if path.is_dir()
    }
    assert bundled_deployments == {
        "base",
        "carla-simulation",
        "logging-simulation",
        "planning-simulation",
        "scenario-simulation",
    }
    assert not (root / "install.sh").exists()
    listed = subprocess.run(
        [str(root / "openadkit"), "list"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert listed.count("\tintact") == 4
    assert "modified" not in listed
    assert "zenoh" not in listed

    docker_calls = calls.read_text()
    assert "humble|" in docker_calls
    assert "jazzy|" in docker_calls
    assert "docker-compose.gpu.yaml" in docker_calls

    (tmp_path / "dist/stale.tar.gz").write_bytes(b"stale")
    command[-2] = "077"
    subprocess.run(command, cwd=tmp_path, env=env, check=True)
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == first_asset
    assert hashlib.sha256((tmp_path / "release-plan.json").read_bytes()).hexdigest() == first_plan
    assert [path.name for path in (tmp_path / "dist").iterdir()] == [asset.name]

    scan = tmp_path / "release-input/scan"
    scan.mkdir()
    (scan / "scan-metadata.json").write_text(json.dumps({"scan_status": "passed"}))
    subprocess.run(
        ["bash", str(WRITE_NOTES)],
        cwd=tmp_path,
        env=env | {"RELEASE_PLAN_FILE": "release-plan.json"},
        check=True,
    )
    release_metadata = json.loads((tmp_path / "release-metadata.json").read_text())
    assert release_metadata["bundles"] == [
        {"name": asset.name, "sha256": first_asset}
    ]
    assert release_metadata["release_plan_sha256"] == first_plan
    notes = (tmp_path / "release-notes.md").read_text()
    assert "## Open AD Kit Bundle" in notes
    assert notes.count(asset.name) == 1
