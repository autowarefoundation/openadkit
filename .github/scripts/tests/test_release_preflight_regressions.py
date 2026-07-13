import json
import os
import pathlib
import re
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[3]
VALIDATE_RELEASE = ROOT / ".github/scripts/validate_release.sh"
PACKAGE_BUNDLES = ROOT / ".github/scripts/package_release_bundles.sh"
OPENADKIT_REF = re.compile(
    r"ghcr\.io/autowarefoundation/openadkit:([a-z-]+)-(humble|jazzy)-v9\.8\.7"
)


def test_validate_inventory_coverage_handles_global_and_image_distros(tmp_path):
    build_dir = tmp_path / "release-input/build"
    build_dir.mkdir(parents=True)
    (build_dir / "image-inventory.json").write_text(
        json.dumps(
            {
                "ros_distros": ["humble", "jazzy"],
                "images": [
                    {
                        "repo": "common",
                        "target": "universe-common",
                        "platforms": ["linux/arm64", "linux/amd64"],
                    },
                    {
                        "repo": "component",
                        "target": "carla-interface",
                        "ros_distros": ["humble"],
                        "platforms": ["linux/amd64"],
                    },
                ],
            }
        )
    )
    (build_dir / "build-metadata.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "repo": "example/common",
                        "target": "universe-common",
                        "ros_distro": distro,
                        "platforms": ["linux/amd64", "linux/arm64"],
                    }
                    for distro in ("humble", "jazzy")
                ]
                + [
                    {
                        "repo": "example/component",
                        "target": "carla-interface",
                        "ros_distro": "humble",
                        "platforms": ["linux/amd64"],
                    }
                ]
            }
        )
    )
    env = os.environ | {
        "BUILD_TAG": "1-1",
        "VERSION": "v9.8.7",
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
            'source "$1"; validate_inventory_coverage',
            "bash",
            str(VALIDATE_RELEASE),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
    )


def test_jazzy_release_bundles_keep_carla_humble_and_bind_mounts(tmp_path):
    env = os.environ | {
        "SOURCE_DIR": str(ROOT),
        "VERSION": "v9.8.7",
        "DEFAULT_ROS_DISTRO": "jazzy",
    }
    result = subprocess.run(
        ["bash", str(PACKAGE_BUNDLES)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    bundle_names = {
        "planning-simulation",
        "scenario-simulation",
        "logging-simulation",
        "carla-simulation",
        "zenoh-bridge",
    }
    assert {path.stem.removesuffix(".tar") for path in (tmp_path / "dist").glob("*.tar.gz")} == bundle_names
    assert result.stdout.count("packaged dist/") == len(bundle_names)

    for name in bundle_names:
        bundle_dir = tmp_path / "staging" / name
        refs = []
        for path in bundle_dir.rglob("*"):
            if path.suffix in {".yaml", ".env"} or path.name == ".env":
                refs.extend(OPENADKIT_REF.findall(path.read_text()))
        assert refs, f"no pinned Open AD Kit refs found in {name}"
        expected_distro = "humble" if name == "carla-simulation" else "jazzy"
        assert {distro for _, distro in refs} == {expected_distro}

    assert (tmp_path / "staging/zenoh-bridge/.env").is_file()

    carla_dir = tmp_path / "staging/carla-simulation"
    carla_compose = (carla_dir / "docker-compose.yaml").read_text()
    assert "../base/" not in carla_compose
    assert "./base/cyclonedds.xml" in carla_compose
    rendered = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "carla-simulation.env",
            "config",
            "--format",
            "json",
        ],
        cwd=carla_dir,
        text=True,
        capture_output=True,
        check=True,
    )
    services = json.loads(rendered.stdout)["services"]
    cyclonedds_mount = next(
        mount
        for mount in services["carla-interface"]["volumes"]
        if mount["target"] == "/etc/cyclonedds/cyclonedds.xml"
    )
    assert cyclonedds_mount["type"] == "bind"
    assert pathlib.Path(cyclonedds_mount["source"]) == carla_dir / "base/cyclonedds.xml"

    helper = tmp_path / "staging/planning-simulation/start-planning-e2e-demo.sh"
    dry_run = subprocess.run(
        [str(helper), "--dry-run"],
        text=True,
        capture_output=True,
        check=True,
    )
    compose_command = next(
        line for line in dry_run.stdout.splitlines() if line.startswith("[DRY-RUN]")
    )
    assert compose_command.count("--env-file") == 1
    assert "planning-simulation.env" in compose_command
    assert "base.env" not in compose_command
