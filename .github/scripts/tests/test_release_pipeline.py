import hashlib
import json
import os
from pathlib import Path
import shutil
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
    "carla-interface",
    "localization-mapping",
    "planning-control",
    "sensing-perception",
    "sensing-perception-cuda",
    "simulator",
    "vehicle-system",
    "visualizer",
}


def manifest_validation_matrix():
    kit = json.loads((ROOT / "openadkit.json").read_text())
    rows = []
    for name in sorted(kit["deployments"]):
        manifest = json.loads(
            (ROOT / kit["deployments"][name]["path"] / "deployment.json").read_text()
        )
        gpu = manifest["requirements"]["gpu"]
        roles = [""] + sorted((manifest["compose"].get("roles") or {}).keys())
        for distro in manifest["requirements"]["rosDistros"]:
            for role in roles:
                if gpu in ("none", "optional"):
                    rows.append(
                        {
                            "deployment": name,
                            "gpu": False,
                            "rosDistro": distro,
                            "role": role,
                        }
                    )
                if gpu in ("required", "optional"):
                    rows.append(
                        {
                            "deployment": name,
                            "gpu": True,
                            "rosDistro": distro,
                            "role": role,
                        }
                    )
    rows.sort(
        key=lambda row: (row["deployment"], row["rosDistro"], row["gpu"], row["role"])
    )
    return rows


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
        ["python3", str(PLANNER), "--source-root", str(ROOT),
         "--build-metadata", str(metadata), "--version", VERSION,
         "--release-sha", RELEASE_SHA, "--packager-sha", "c" * 40,
         "--default-ros-distro", "humble", "--stable-release", "true",
         "--publish-latest-aliases", "true", "--output", str(output)],
        text=True,
        capture_output=True,
    )
    return result, output


def run_validator(tmp_path, function, **env):
    """Run one validate_release.sh check in the release workflow environment."""
    kit = json.loads((ROOT / "openadkit.json").read_text())
    return subprocess.run(
        ["bash", "-c", f'source "$1"; release_sha="$2"; {function}', "bash",
         str(VALIDATOR), RELEASE_SHA],
        cwd=tmp_path,
        env=os.environ | {
            "BUILD_TAG": BUILD_TAG,
            "VERSION": VERSION,
            "GH_TOKEN": "test",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": "example/repo",
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "IMAGE_PREFIX_COMMON": "ghcr.io/example/openadkit-common",
            "IMAGE_PREFIX_COMPONENT": kit["imagePrefixComponent"],
            "DEFAULT_ROS_DISTRO": kit["defaultRosDistro"],
            **env,
        },
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    ("version", "ref_type", "input_ref", "accepted"),
    [
        ("v2.0.0", "tag", "1.8.0", True),
        ("v2.0.0-rc.1", "tag", "1.8.0", True),
        ("v2.0.0-rc.1", "sha", "a" * 40, True),
        ("v2.0.0", "sha", "a" * 40, False),
        ("v2.0.0-rc.1", "branch", "main", False),
        ("v2.0.0-rc.1", "sha", "abc123", False),
    ],
)
def test_release_rules_accept_only_supported_autoware_refs(
    tmp_path, version, ref_type, input_ref, accepted
):
    build = tmp_path / "release-input/build"
    build.mkdir(parents=True)
    (build / "build-metadata.json").write_text(
        json.dumps(
            {
                "openadkit_sha": RELEASE_SHA,
                "autoware_input_ref": input_ref,
                "autoware_ref_type": ref_type,
                "autoware_base_version": "1.8.0",
            }
        )
    )
    result = run_validator(tmp_path, "validate_release_rules", VERSION=version)
    assert (result.returncode == 0) is accepted, result.stderr


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, None),
        ({"DEFAULT_ROS_DISTRO": "jazzy"}, "must match openadkit.json defaultRosDistro"),
        (
            {"IMAGE_PREFIX_COMPONENT": "ghcr.io/example/openadkit"},
            "must match openadkit.json imagePrefixComponent",
        ),
    ],
)
def test_manifest_consistency_checks_release_inputs(tmp_path, env, message):
    result = run_validator(tmp_path, "validate_manifest_consistency", **env)
    if message is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert message in result.stderr


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


ASSETS = {
    "release-plan.json": "release-plan.json",
    "release-metadata.json": "release-metadata.json",
    "autoware-lock.repos": "release-input/build/autoware-lock.repos",
    "upstream-images.json": "release-input/build/upstream-images.json",
    "openadkit": "dist/openadkit",
    f"openadkit-{VERSION}.tar.gz": f"dist/openadkit-{VERSION}.tar.gz",
}


def release_assets():
    return [{"id": 101 + index, "name": name} for index, name in enumerate(ASSETS)]


def release_workspace(tmp_path):
    for relative in ("dist", "release-input/build"):
        (tmp_path / relative).mkdir(parents=True)
    executable(tmp_path / "dist/openadkit", "#!/usr/bin/env bash\n")
    (tmp_path / f"dist/openadkit-{VERSION}.tar.gz").write_bytes(b"bundle")
    (tmp_path / "release-input/build/autoware-lock.repos").write_text("repositories: {}\n")
    (tmp_path / "release-input/build/upstream-images.json").write_text("[]\n")
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
                    {"name": name, "path": path} for name, path in ASSETS.items()
                ],
            }
        )
    )
    (tmp_path / "release-assets.sha256").write_text(
        "".join(
            f"{hashlib.sha256((tmp_path / ASSETS[name]).read_bytes()).hexdigest()}  {name}\n"
            for name in sorted(ASSETS)
        )
    )


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
    for asset in state.get("assets", []):
        source = tmp_path / ASSETS[asset["name"]]
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


def publish_env(env):
    return env | {
        "RELEASE_ID": "42",
        "RELEASE_BODY_SHA256": hashlib.sha256((MARKER + "\n").encode()).hexdigest(),
        "PUBLISH_LATEST_ALIASES": "true",
    }


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
    changed = release_record(body=MARKER + "\nchanged\n", assets=release_assets())
    env, _ = fake_gh_environment(tmp_path, changed)
    env = publish_env(env)
    result = run_manager(tmp_path, env, "publish")
    assert result.returncode != 0
    assert "Draft release body changed" in result.stderr
    assert not (tmp_path / "patched").exists()


def test_publish_patches_the_revalidated_release_id(tmp_path):
    release_workspace(tmp_path)
    owned = release_record(assets=release_assets())
    env, log = fake_gh_environment(tmp_path, owned)
    env = publish_env(env)
    result = run_manager(tmp_path, env, "publish")
    assert result.returncode == 0, result.stderr
    patch = next(call for call in log.read_text().splitlines() if "PATCH" in call)
    assert "releases/42" in patch
    assert "draft=false" in patch


def test_publish_rejects_changed_draft_asset(tmp_path):
    release_workspace(tmp_path)
    owned = release_record(assets=release_assets())
    env, _ = fake_gh_environment(tmp_path, owned)
    (tmp_path / "responses/asset-106").write_bytes(b"replaced bundle")
    env = publish_env(env)
    result = run_manager(tmp_path, env, "publish")
    assert result.returncode != 0
    assert not (tmp_path / "patched").exists()


def run_promoter(
    tmp_path, *, latest=VERSION, publish_latest=True, aliases=("api-humble",),
    fail_create="-no-such-ref", deny_aliases=False,
):
    """Promote one image against a fake registry.

    Build-tag refs and refs this run created resolve; alias lookups fail with
    401 when deny_aliases is set; creating a ref ending in fail_create fails.
    Returns the result, the refs created, and every create attempt.
    """
    repo = "ghcr.io/example/openadkit"
    (tmp_path / "release-plan.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "release": {
                    "version": VERSION,
                    "defaultRosDistro": "humble",
                    "stable": True,
                    "publishLatestAliases": publish_latest,
                },
                "images": [
                    {
                        "repo": repo,
                        "rosDistro": "humble",
                        "digest": DIGEST,
                        "sourceRef": f"{repo}:api-humble-{BUILD_TAG}",
                        "releaseRef": f"{repo}:api-humble-{VERSION}",
                        "aliases": [f"{repo}:{alias}" for alias in aliases],
                    }
                ],
            }
        )
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    promoted, calls = tmp_path / "promoted", tmp_path / "docker-calls"
    digest = json.dumps({"manifest": {"digest": DIGEST}})
    deny = f'[[ "$4" != *"-{VERSION}" ]] && {{ echo "401 Unauthorized" >&2; exit 1; }}\n' if deny_aliases else ""
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> {json.dumps(str(calls))}\n'
        'if [ "$1 $2 $3" = "buildx imagetools inspect" ]; then\n'
        f'  if [[ "$4" == *"-{BUILD_TAG}" ]] || grep -Fxq "$4" {json.dumps(str(promoted))} 2>/dev/null; then\n'
        f"    printf '%s\\n' '{digest}'; exit\n"
        "  fi\n"
        f"  {deny}"
        '  echo "ERROR: $4: not found" >&2; exit 1\n'
        "fi\n"
        'if [ "$1 $2 $3" = "buildx imagetools create" ]; then\n'
        f'  if [[ "$5" == *"{fail_create}" ]]; then echo "create failed" >&2; exit 1; fi\n'
        f'  printf "%s\\n" "$5" >> {json.dumps(str(promoted))}; exit\n'
        "fi\n"
        "exit 2\n",
    )
    executable(bin_dir / "sleep", "#!/usr/bin/env bash\n")
    executable(bin_dir / "gh", f"#!/usr/bin/env bash\nprintf '%s\\n' {latest}\n")
    result = subprocess.run(
        ["bash", str(PROMOTER)],
        cwd=tmp_path,
        env=os.environ | {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "example/repo",
            "REGISTRY_LOOKUP_MAX_ATTEMPTS": "1",
            "REGISTRY_LOOKUP_RETRY_DELAY_SECONDS": "0",
        },
        text=True,
        capture_output=True,
    )
    created = promoted.read_text().splitlines() if promoted.exists() else []
    attempts = [  # buildx imagetools create --tag <ref> <source>
        call.split()[4]
        for call in (calls.read_text().splitlines() if calls.exists() else [])
        if "imagetools create" in call
    ]
    return result, created, attempts


def test_stable_promotion_creates_the_version_tag_then_aliases(tmp_path):
    result, created, _ = run_promoter(tmp_path)
    assert result.returncode == 0, result.stderr
    assert created == [
        f"ghcr.io/example/openadkit:api-humble-{VERSION}",
        "ghcr.io/example/openadkit:api-humble",
    ]


def test_older_stable_does_not_update_aliases(tmp_path):
    result, created, _ = run_promoter(tmp_path, latest="v9.9.0", publish_latest=False)
    assert result.returncode == 0, result.stderr
    assert created == [f"ghcr.io/example/openadkit:api-humble-{VERSION}"]


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"deny_aliases": True}, "401"),
        ({"latest": "v9.9.0"}, "Latest alias policy changed"),
    ],
)
def test_promotion_aborts_before_any_tag_changes(tmp_path, options, message):
    result, _, attempts = run_promoter(tmp_path, **options)
    assert result.returncode != 0
    assert message in result.stderr
    assert attempts == []


def test_failed_version_tag_never_updates_aliases(tmp_path):
    result, created, attempts = run_promoter(tmp_path, fail_create=f"-{VERSION}")
    assert result.returncode != 0
    assert created == []
    assert attempts and all(ref.endswith(f"-{VERSION}") for ref in attempts)


def test_alias_loop_reports_unconverged_and_continues(tmp_path):
    result, created, _ = run_promoter(
        tmp_path, aliases=("api-humble-latest", "api-humble"), fail_create="-latest"
    )
    assert result.returncode != 0
    assert "Unconverged aliases: ghcr.io/example/openadkit:api-humble-latest" in result.stderr
    assert created == [
        f"ghcr.io/example/openadkit:api-humble-{VERSION}",
        "ghcr.io/example/openadkit:api-humble",
    ]


def test_release_plan_builds_complete_dual_distro_context(tmp_path):
    result, output = write_plan(tmp_path)
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_text())
    assert plan["bundle"]["asset"] == f"openadkit-{VERSION}.tar.gz"
    assert plan["bundle"]["root"] == f"openadkit-{VERSION}"
    assert plan["bundle"]["runtime"] == ["openadkit", "openadkit.json", "cli"]
    assert {asset["name"] for asset in plan["githubAssets"]} >= {"openadkit", plan["bundle"]["asset"]}
    assert plan["bundle"]["shared"] == ["shared"]
    assert plan["bundle"]["deployments"] == sorted(
        json.loads((ROOT / "openadkit.json").read_text())["deployments"]
    )
    assert plan["bundle"]["validation"] == manifest_validation_matrix()
    context = plan["releaseContext"]
    assert context["defaultRosDistro"] == "humble"
    assert context["componentImages"]["CARLA_INTERFACE_IMAGE"] == "carla-interface"
    assert set(context["deployments"]) == set(plan["bundle"]["deployments"])
    assert set(context["shared"]) == {"shared"}
    for distro in ("humble", "jazzy"):
        assert set(context["images"][distro]) == RUNTIME_TARGETS
        assert all(
            reference.endswith(f"@{DIGEST}")
            and f"-{distro}-{VERSION}@" in reference
            for reference in context["images"][distro].values()
        )
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


def packager_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls"
    executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        f'printf "%s|%s\\n" "${{ROS_DISTRO:-}}" "$*" >> {json.dumps(str(calls))}\n'
        'if [[ "$*" == *"config --services"* ]]; then\n'
        "  printf '%s\\n' map map-check planning vehicle system control simulator api visualizer sensing perception localization rosbag scenario_simulator carla carla-interface carla-map-loader zenoh-bridge\n"
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
        "GITHUB_REPOSITORY": "example/repo",
    }
    return env, calls


def run_packager(tmp_path, env, *, umask="022"):
    subprocess.run(
        ["bash", "-c", 'umask "$1"; exec bash "$2"', "bash", umask, str(PACKAGER)],
        cwd=tmp_path,
        env=env,
        check=True,
    )


def test_release_bundle_is_unified_verified_and_reproducible(tmp_path):
    env, calls = packager_env(tmp_path)
    run_packager(tmp_path, env)
    asset = tmp_path / f"dist/openadkit-{VERSION}.tar.gz"
    assert sorted(path.name for path in (tmp_path / "dist").iterdir()) == ["openadkit", asset.name]
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
    assert (root / "cli/main.py").is_file()
    assert (root / "cli/manifest.py").is_file()
    assert not (root / "openadkit.d").exists()
    bundled_context = json.loads((root / "openadkit.json").read_text())
    assert bundled_context["kind"] == "release"
    kit = json.loads((ROOT / "openadkit.json").read_text())
    assert bundled_context["componentImages"] == kit["componentImages"]
    assert "carla-interface" in bundled_context["images"]["humble"]
    expected_deployments = set(kit["deployments"])
    for name, reference in kit["deployments"].items():
        manifest = json.loads((ROOT / reference["path"] / "deployment.json").read_text())
        expected_deployments.update(manifest["shared"])
    bundled_deployments = {
        path.name for path in (root / "deployments").iterdir() if path.is_dir()
    }
    assert bundled_deployments == expected_deployments
    assert not (root / "install.sh").exists()
    assert (tmp_path / "dist/openadkit").read_bytes() == (ROOT / "openadkit").read_bytes()
    listed = subprocess.run(
        [str(root / "openadkit"), "list"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    states = [
        line.split()[1]
        for line in listed.splitlines()[1:]
        if line.strip()
    ]
    assert states == ["intact"] * len(bundled_context["deployments"])
    assert "modified" not in listed
    assert "zenoh" not in listed

    docker_calls = calls.read_text()
    assert "humble|" in docker_calls
    assert "jazzy|" in docker_calls
    assert "docker-compose.gpu.yaml" in docker_calls

    (tmp_path / "dist/stale.tar.gz").write_bytes(b"stale")
    run_packager(tmp_path, env, umask="077")
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == first_asset
    assert hashlib.sha256((tmp_path / "release-plan.json").read_bytes()).hexdigest() == first_plan
    assert sorted(path.name for path in (tmp_path / "dist").iterdir()) == ["openadkit", asset.name]

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
    installer_asset = tmp_path / "dist/openadkit"
    installer_sha256 = hashlib.sha256(installer_asset.read_bytes()).hexdigest()
    assert "## Install" in notes
    assert f"| `openadkit` | `{installer_sha256}` |" in notes
    assert f"releases/download/{VERSION}/openadkit" in notes
    assert f"install --version {VERSION}" in notes


def test_release_installer_and_bundle_entrypoint_come_from_the_packager(tmp_path):
    env, _ = packager_env(tmp_path)
    promoted = tmp_path / "promoted"
    promoted.mkdir()
    shutil.copy2(ROOT / "openadkit.json", promoted / "openadkit.json")
    shutil.copytree(ROOT / "cli", promoted / "cli")
    shutil.copytree(ROOT / "deployments", promoted / "deployments")
    stale = promoted / "openadkit"
    stale.write_text("#!/usr/bin/env bash\necho stale promoted build\n")
    stale.chmod(0o755)

    run_packager(tmp_path, env | {"SOURCE_DIR": str(promoted)})

    launcher = (ROOT / "openadkit").read_bytes()
    assert (tmp_path / "dist/openadkit").read_bytes() == launcher
    asset = tmp_path / f"dist/openadkit-{VERSION}.tar.gz"
    with tarfile.open(asset) as archive:
        member = archive.extractfile(f"openadkit-{VERSION}/openadkit")
        assert member is not None
        assert member.read() == launcher


def test_release_packager_requires_an_install_capable_launcher(tmp_path):
    env, _ = packager_env(tmp_path)
    stale = tmp_path / "stale"
    stale.mkdir()
    launcher = stale / "openadkit"
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'exec python3 "$(dirname -- "$0")/cli/main.py" "$@"\n'
    )
    launcher.chmod(0o755)

    with pytest.raises(subprocess.CalledProcessError):
        run_packager(tmp_path, env | {"INSTALLER_SOURCE_DIR": str(stale)})
