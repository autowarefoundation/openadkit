"""Focused guards for the runtime, documentation, and security fixes."""

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[3]
ZENOH = ROOT / "deployments" / "zenoh-bridge"


def test_install_macro_uses_exact_ref_and_checked_out_checksum(monkeypatch):
    ref = "1" * 40
    monkeypatch.setenv("OPENADKIT_INSTALL_REF", ref)
    spec = importlib.util.spec_from_file_location("docs_macros_test", ROOT / "docs/macros.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    checksum = hashlib.sha256((ROOT / "install.sh").read_bytes()).hexdigest()
    assert f"/{ref}/install.sh" in module.INSTALL_COMMAND
    assert checksum in module.INSTALL_COMMAND
    assert "/main/install.sh" not in module.INSTALL_COMMAND
    assert "sha256sum --check" in module.INSTALL_COMMAND
    assert module.INSTALL_COMMAND.endswith("install_openadkit")
    subprocess.run(
        ["bash", "-n"],
        input=module.INSTALL_COMMAND,
        check=True,
        text=True,
    )


def test_docs_action_pins_checked_out_installer_ref():
    action = (ROOT / ".github/actions/build-docs/action.yaml").read_text()
    preview = (ROOT / ".github/workflows/pr-preview.yaml").read_text()
    deploy = (ROOT / ".github/workflows/deploy-docs.yaml").read_text()
    assert "OPENADKIT_INSTALL_REF" in action
    assert "git rev-parse HEAD" in action
    assert "|| echo" not in action
    assert "--allow-stale-on-fetch-error" in action
    assert "allow-stale-release-notes: 'true'" in preview
    assert "allow-stale-release-notes: ${{ github.event_name != 'release' }}" in deploy

    expected_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for target in ("serve", "build", "generate-release-notes"):
        dry_run = subprocess.run(
            ["make", "-n", "-C", "docs", target],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        docker_runs = [line for line in dry_run.splitlines() if "docker run" in line]
        assert docker_runs
        assert all(
            f"-e OPENADKIT_INSTALL_REF={expected_ref}" in line for line in docker_runs
        )


def test_lint_paths_cover_inputs_consumed_by_checks():
    workflow = yaml.safe_load((ROOT / ".github/workflows/lint.yaml").read_text())
    paths = set(workflow[True]["pull_request"]["paths"])

    assert {
        ".gitignore",
        "**/*.json5",
        ".hadolint.yaml",
        ".markdownlint.yaml",
        ".yamllint.yaml",
    } <= paths


def test_production_docs_build_and_deploy_have_separate_permissions():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-docs.yaml").read_text())
    jobs = workflow["jobs"]

    assert workflow["permissions"] == {"contents": "read"}
    assert set(jobs) == {"build", "deploy"}
    assert jobs["build"]["permissions"] == {"contents": "read"}
    assert jobs["deploy"]["permissions"] == {
        "actions": "read",
        "contents": "write",
    }
    assert jobs["deploy"]["needs"] == "build"
    build_steps = jobs["build"]["steps"]
    deploy_steps = jobs["deploy"]["steps"]
    assert any(step.get("uses") == "./.github/actions/build-docs" for step in build_steps)
    assert any(step.get("uses") == "actions/upload-artifact@v4" for step in build_steps)
    checkout = next(
        step for step in deploy_steps if step.get("uses") == "actions/checkout@v6"
    )
    assert checkout["with"]["persist-credentials"] is False
    assert any(step.get("uses") == "actions/download-artifact@v4" for step in deploy_steps)
    assert all(step.get("uses") != "./.github/actions/build-docs" for step in deploy_steps)


def test_semantic_pr_uses_pinned_action_with_read_only_permissions():
    workflow_text = (ROOT / ".github/workflows/semantic-pull-request.yaml").read_text()
    workflow = yaml.safe_load(workflow_text)
    job = workflow["jobs"]["semantic-pull-request"]
    expected_permissions = {"contents": "read", "pull-requests": "read"}

    assert workflow["permissions"] == expected_permissions
    assert job["permissions"] == expected_permissions
    assert job["timeout-minutes"] == 5
    assert len(job["steps"]) == 1
    assert job["steps"][0]["uses"] == (
        "amannn/action-semantic-pull-request@"
        "48f256284bd46cdaab1048c3721360e808335d50"
    )
    assert "autoware-github-actions/.github/workflows" not in workflow_text
    assert "@v6" not in workflow_text


def test_dotenv_reader_does_not_execute_values_and_preserves_environment(tmp_path):
    marker = tmp_path / "executed"
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"MAP_PATH=$(touch {marker})\n")
    command = (
        f'source "{ZENOH / "common.sh"}"; '
        'unset MAP_PATH; '
        f'read_dotenv_value MAP_PATH "{dotenv}"'
    )
    result = subprocess.run(
        ["bash", "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip().startswith("$(touch ")
    assert not marker.exists()

    environment = os.environ.copy()
    environment["MAP_PATH"] = "/external/map"
    result = subprocess.run(
        ["bash", "-c", command.replace("unset MAP_PATH; ", "")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.stdout.strip() == "/external/map"
    assert not marker.exists()


def test_zenoh_uses_wall_time_and_defines_teleop_color():
    compose = (ZENOH / "docker-compose.yaml").read_text()
    bridge_config = (ZENOH / "config/zenoh-bridge-ros2dds.json5").read_text()
    common = (ZENOH / "common.sh").read_text()
    docs = (ROOT / "docs/deployment/zenoh-bridge/index.md").read_text()

    assert "use_sim_time:=false" in compose
    assert "USE_SIM_TIME=false" in compose
    assert '"/clock"' not in bridge_config
    assert "CYAN=" in common
    assert "/clock` is intentionally not routed" in docs
    assert "service_completed_successfully" in compose
    assert "edge_zenoh_ready" in compose
    assert "cloud_zenoh_ready" in compose
    assert "ZENOH_READY_TIMEOUT" in compose


def test_runtime_network_and_playback_defaults_are_bounded():
    cyclonedds = (ROOT / "deployments/base/cyclonedds.xml").read_text()
    base_env = (ROOT / "deployments/base/base.env").read_text()
    base_compose = (ROOT / "deployments/base/docker-compose.yaml").read_text()
    logging = (ROOT / "deployments/logging-simulation/docker-compose.yaml").read_text()

    assert 'name="${CYCLONEDDS_NETWORK_INTERFACE}"' in cyclonedds
    assert "CYCLONEDDS_NETWORK_INTERFACE=lo" in base_env
    assert base_compose.count(
        "CYCLONEDDS_NETWORK_INTERFACE=${CYCLONEDDS_NETWORK_INTERFACE:-lo}"
    ) == 8
    assert "ROSBAG_READY_TOPIC" in logging
    assert "ROSBAG_READY_TIMEOUT" in logging
    assert "Subscription count: [1-9][0-9]*" in logging
    assert logging.index("Subscription count:") < logging.index("exec ros2 bag play")


def test_runtime_commands_support_upstream_non_root_entrypoint():
    compose = (ROOT / "deployments/base/docker-compose.yaml").read_text()
    visualizer = (
        ROOT / "components/visualizer/etc/visualizer_entrypoint.sh"
    ).read_text()

    assert 'sudo -n sed -i "s/use_emergency_handling: true/' in compose
    assert 'set +u\nsource "/opt/ros/${ROS_DISTRO}/setup.bash"' in visualizer
    assert 'source "/opt/autoware/setup.bash"\nset -u' in visualizer


def test_sample_ownership_and_visualizer_restart_are_bounded():
    installer = (ROOT / "install.sh").read_text()
    visualizer = (
        ROOT / "components/visualizer/etc/visualizer_entrypoint.sh"
    ).read_text()

    assert 'chown -R "${TARGET_USER}:" "$MAP_ROOT"' not in installer
    assert 'Refusing sample target symlink' in installer
    assert "reject_symlink_path_components" in installer
    assert "realpath -ms" in installer
    assert 'env -u SUDO_USER HOME="$USER_HOME"' in installer
    assert "atomic_rename_directories" in installer
    assert "renameat2(-100, candidate, -100, target, flags)" in installer
    assert 'atomic_rename_directories "$candidate" "$target" 1' in installer
    assert 'atomic_rename_directories "$candidate" "$target" 2' in installer
    assert "validate_zip_archive" in installer
    assert "install_sample_data_dependencies" in installer
    assert "ca-certificates curl unzip coreutils python3" in installer
    assert installer.index("detect_host_architecture\nrequire_sudo") < installer.index(
        "install_docker\n"
    )
    assert 'log_error "NVIDIA GPU runtime verification failed."' in installer
    assert 'log_error "Could not pull NVIDIA CUDA test image."' in installer
    assert 'grep -qxF "$HOME/.local/bin/start-rviz2.sh"' in visualizer
    assert 'grep -qxF "export DISPLAY=:99" ~/.bashrc' in visualizer
    assert "pkill" not in visualizer
    assert "vncserver -kill" not in visualizer
    assert "websockify --daemon" not in visualizer
    assert "vncserver :99 -fg" in visualizer
    assert "VNC_PID=$!" in visualizer
    assert "WEBSOCKIFY_PID=$!" in visualizer
    assert 'terminate_child "$VNC_PID"' in visualizer
    assert 'terminate_child "$WEBSOCKIFY_PID"' in visualizer


def test_sample_checksum_failure_stops_before_extraction(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "while (($#)); do\n"
        "  if [ \"$1\" = -o ]; then shift; : > \"$1\"; fi\n"
        "  shift\n"
        "done\n"
    )
    sha256sum = bin_dir / "sha256sum"
    sha256sum.write_text("#!/usr/bin/env bash\nprintf '%064d  %s\\n' 0 \"$1\"\n")
    unzip = bin_dir / "unzip"
    unzip.write_text("#!/usr/bin/env bash\ntouch \"$EXTRACT_MARKER\"\n")
    for command in (curl, sha256sum, unzip):
        command.chmod(0o755)

    marker = tmp_path / "extracted"
    environment = os.environ | {
        "AUTOWARE_MAP_DIR": str(tmp_path / "maps"),
        "EXTRACT_MARKER": str(marker),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "sample-data", "planning-simulation"],
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "checksum mismatch" in result.stdout
    assert not marker.exists()


def test_scan_policy_is_pinned_to_and_validated_against_build_sha():
    scan = (ROOT / ".github/workflows/scan.yaml").read_text()
    release_validation = (ROOT / ".github/scripts/validate_release.sh").read_text()

    assert "policy_sha=$(jq -r '.openadkit_sha'" in scan
    assert "ref: ${{ needs.prepare.outputs.policy_sha }}" in scan
    assert "policy_sha: $policy_sha" in scan
    assert "Scan policy SHA ${policy_sha} does not match build SHA ${build_sha}" in release_validation


def test_operational_docs_preserve_runtime_requirements_and_paths():
    getting_started = (ROOT / "docs/getting-started/index.md").read_text()
    troubleshooting = (ROOT / "docs/getting-started/troubleshooting.md").read_text()
    hardware = (ROOT / "docs/platforms/hardware/index.md").read_text()
    zenoh = (ROOT / "docs/deployment/zenoh-bridge/index.md").read_text()
    visualizer_readme = (ROOT / "components/visualizer/README.md").read_text()
    carla_interface = (ROOT / "docs/components/carla-interface.md").read_text()

    activation_marker = '--8<-- "includes/docker-group-activation.md"'
    activation = (ROOT / "docs/includes/docker-group-activation.md").read_text()
    assert "newgrp docker" in activation
    assert "log out and back in" in activation
    deployment_pages = [
        ROOT / "docs/deployment/planning-simulation/index.md",
        ROOT / "docs/deployment/scenario-simulation/index.md",
        ROOT / "docs/deployment/logging-simulation/index.md",
        ROOT / "docs/deployment/carla-simulation/index.md",
        ROOT / "docs/deployment/zenoh-bridge/index.md",
    ]
    assert activation_marker in getting_started
    for page in deployment_pages:
        content = page.read_text()
        assert content.count(activation_marker) == 1
        assert content.index("{{ install_command }}") < content.index(activation_marker)
    assert "../../install.sh sample-data <deployment> --force" in troubleshooting
    assert "do not automatically fall back to CPU" in hardware
    assert "`sensing-perception-cuda` image currently supports `linux/amd64` only" in hardware
    assert "ARM64, use the standard `sensing-perception` image" in hardware
    assert "run on CPU" in hardware
    assert "127.0.0.1:8080:6080" in zenoh
    assert "change `6081:6080` to `8080:6080`" not in zenoh
    assert "-p 127.0.0.1:6080:6080" in visualizer_readme
    assert "bridge image itself does not require a GPU" in carla_interface


def test_local_build_docs_pin_source_and_base_images_to_one_ref():
    guide = (ROOT / "docs/development/build-from-source.md").read_text()
    readme = (ROOT / "components/carla-interface/README.md").read_text()

    assert "AUTOWARE_REF=1.8.0" in guide
    assert 'export UPSTREAM_TAG="$AUTOWARE_REF"' in guide
    assert '--branch "$AUTOWARE_REF" --depth 1' in guide
    assert guide.index('--branch "$AUTOWARE_REF"') < guide.index("vcs import --shallow")
    assert 'UPSTREAM_TAG="$AUTOWARE_REF"' in guide
    assert "ROS_DISTRO=humble UPSTREAM_TAG=1.8.0" not in guide
    assert "cd deployments/carla-simulation" in readme
    assert "./start-carla-e2e-demo.sh" in readme
    assert "docker compose --env-file carla-simulation.env up -d" not in readme
    assert "from the repository root" in readme.lower()


def test_source_and_release_bundle_commands_are_complete():
    deployments = {
        "planning-simulation": "planning-simulation",
        "scenario-simulation": "scenario-simulation",
        "logging-simulation": "logging-simulation",
    }
    for page_name, deployment in deployments.items():
        page = (ROOT / f"docs/deployment/{page_name}/index.md").read_text()
        readme = (ROOT / f"deployments/{deployment}/README.md").read_text()
        env_file = f"{deployment}.env"

        assert f"../../install.sh sample-data {deployment}" in page
        assert f"./install.sh sample-data {deployment}" in page
        assert f"../../install.sh sample-data {deployment} --force" in page
        assert f"./install.sh sample-data {deployment} --force" in page
        assert f"--env-file ../base/base.env --env-file {env_file} up -d" in page
        assert f"docker compose --env-file {env_file} up -d" in page
        assert f"--env-file ../base/base.env --env-file {env_file} logs -f" in page
        assert f"docker compose --env-file {env_file} logs -f" in page
        assert f"--env-file ../base/base.env --env-file {env_file}" in page
        assert f"docker compose --env-file {env_file}" in page
        assert "## Source Checkout" in readme
        assert "## Release Bundle" in readme
        assert f"./install.sh sample-data {deployment}" in readme
        assert f"docker compose --env-file {env_file} up -d" in readme

    planning = (ROOT / "docs/deployment/planning-simulation/index.md").read_text()
    scenario = (ROOT / "docs/deployment/scenario-simulation/index.md").read_text()
    logging = (ROOT / "docs/deployment/logging-simulation/index.md").read_text()
    getting_started = (ROOT / "docs/getting-started/index.md").read_text()

    assert "docker compose --env-file planning-simulation.env down" in planning
    assert "docker compose --env-file scenario-simulation.env down" in scenario
    assert "logs -f scenario_simulator" in scenario
    assert "in `base.env` for cloned-repo users" not in scenario
    assert "--env-file logging-simulation.env --env-file logging-simulation.gpu.env" in logging
    assert "--profile rosbag up -d rosbag" in logging
    assert "--profile rosbag logs -f rosbag" in logging
    assert "--profile rosbag down" in logging
    assert "docker compose --env-file logging-simulation.env --profile rosbag down" in logging
    assert "./install.sh sample-data planning-simulation" in getting_started
    assert "docker compose --env-file planning-simulation.env up -d" in getting_started


def test_runtime_images_use_lean_base_and_installed_package_manifests():
    bake = (ROOT / "components/docker-bake.hcl").read_text()
    common = (ROOT / "components/universe-common/Dockerfile").read_text()

    assert 'autoware-base       = upstream("base")' in bake
    assert 'autoware-core       = upstream("core")' not in bake
    assert "FROM ${BASE_IMAGE} AS universe-common" in common
    devel, runtime = common.split("FROM ${BASE_IMAGE} AS universe-common", 1)
    upgrade = "apt-get install -y --only-upgrade --no-install-recommends"
    assert upgrade in devel
    assert upgrade in runtime
    assert "autoware/src/**/package.xml" not in runtime
    assert '--skip-keys "${internal_packages}"' in runtime

    dockerfiles = [
        ROOT / "components/api/Dockerfile",
        ROOT / "components/localization-mapping/Dockerfile",
        ROOT / "components/planning-control/Dockerfile",
        ROOT / "components/sensing-perception/Dockerfile",
        ROOT / "components/sensing-perception/Dockerfile.cuda",
        ROOT / "components/simulator/Dockerfile",
        ROOT / "components/vehicle-system/Dockerfile",
        ROOT / "components/visualizer/Dockerfile",
    ]
    for dockerfile in dockerfiles:
        content = dockerfile.read_text()
        assert "rosdep install -y --from-paths /tmp /opt/autoware" not in content
        assert "rosdep install -y --from-paths /opt/autoware/*/share" in content
        assert '--skip-keys "${internal_packages}"' in content

    cuda = (ROOT / "components/sensing-perception/Dockerfile.cuda").read_text()
    cuda_runtime = cuda.split("FROM ${BASE_CUDA_RUNTIME_IMAGE}", 1)[1]
    assert upgrade in cuda_runtime

    cleanup = (ROOT / "components/runtime-cleanup.sh").read_text()
    assert "/usr/include" not in cleanup
    assert "/usr/lib/gcc" not in cleanup
    assert "/usr/lib/jvm" not in cleanup
    assert "/opt/ros" not in cleanup

    visualizer = (ROOT / "components/visualizer/Dockerfile").read_text()
    entrypoint = (
        ROOT / "components/visualizer/etc/visualizer_entrypoint.sh"
    ).read_text()
    assert "USER aw\nENTRYPOINT" in visualizer
    assert 'if [ "$(id -u)" -eq 0 ]' in entrypoint


def test_build_source_defaults_to_the_pinned_upstream_tag():
    build_all = (ROOT / ".github/workflows/build-all-images.yaml").read_text()
    build_single = (ROOT / ".github/workflows/build-single-image.yaml").read_text()

    assert "inputs.autoware_ref || vars.UPSTREAM_TAG || 'main'" in build_all
    assert build_all.count(
        "UPSTREAM_TAG: ${{ needs.prepare.outputs.autoware_base_version }}"
    ) == 2
    assert "resolve_upstream_images.sh" in build_all
    assert "contexts.autoware-core-devel=${{ fromJSON" in build_all
    assert "contexts.autoware-base-cuda-runtime=${{ fromJSON" in build_all
    assert "UPSTREAM_TAG: ${{ vars.UPSTREAM_TAG }}" not in build_all
    assert "vars.UPSTREAM_TAG || 'main'" in build_single
    assert "Require one Autoware release revision" in build_single
    assert "registry_manifest_digest" in build_single
    assert "UPSTREAM_TAG: ${{ needs.prepare.outputs.autoware_base_version }}" in build_single


def test_carla_bundle_build_fails_with_clear_message(tmp_path):
    launcher = (ROOT / "deployments/carla-simulation/start-carla-e2e-demo.sh").read_text()
    assert 'REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)' in launcher
    assert "run_compose logs --tail 160" in launcher

    deployment = tmp_path / "deployments" / "carla-simulation"
    shutil.copytree(ROOT / "deployments/carla-simulation", deployment)
    shutil.copytree(ROOT / "deployments/base", tmp_path / "deployments" / "base")

    result = subprocess.run(
        [str(deployment / "start-carla-e2e-demo.sh"), "--build", "--dry-run"],
        cwd=deployment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Cannot use --build" in result.stderr
    assert "release bundles" in result.stderr


def test_carla_launcher_uses_compose_scoped_env_and_removal(tmp_path):
    launcher_path = ROOT / "deployments/carla-simulation/start-carla-e2e-demo.sh"
    launcher = launcher_path.read_text()

    assert "config --environment" in launcher
    assert 'source "$ENV_FILE"' not in launcher
    assert "BASE_ENV_FILE" not in launcher
    assert "docker rm -f" not in launcher
    assert "run_compose rm --stop --force" in launcher
    assert "remove_compose_service carla" in launcher
    assert "remove_compose_service carla-interface" in launcher
    assert "remove_compose_service visualizer" in launcher
    assert 'BUNDLE_BASE_DIR="$SCRIPT_DIR/base"' in launcher
    assert 'SOURCE_BASE_DIR="$SCRIPT_DIR/../base"' in launcher
    assert "download_verified" in launcher
    assert "sha256sum --check --status" in launcher
    assert "Startup failed; removing services started by this invocation" in launcher
    assert "sysctl -qw" not in launcher
    assert launcher.index("require_host_prerequisites") < launcher.index(
        "require_udp_buffers\n"
    )

    deployment = tmp_path / "deployments" / "carla-simulation"
    shutil.copytree(ROOT / "deployments/carla-simulation", deployment)
    shutil.copytree(ROOT / "deployments/base", tmp_path / "deployments" / "base")
    marker = tmp_path / "dotenv-executed"
    with (deployment / "carla-simulation.env").open("a") as dotenv:
        dotenv.write(f"\nCARLA_WORLD=$(touch {marker})\n")

    result = subprocess.run(
        [
            str(deployment / "start-carla-e2e-demo.sh"),
            "--dry-run",
            "--skip-verify",
            "--no-visualizer",
        ],
        cwd=deployment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert not marker.exists()
    assert result.stdout.count("--env-file") > 0
    assert "deployments/carla-simulation/../base/base.env" in result.stdout


def test_cloud_launcher_rejects_effective_wildcard_zenoh_binding(tmp_path):
    deployment = tmp_path / "zenoh-bridge"
    shutil.copytree(ZENOH, deployment)
    dotenv = deployment / ".env"
    def write_dotenv(binding):
        dotenv.write_text(
            "\n".join(
                [
                    f"MAP_PATH={tmp_path}",
                    "ROS_DISTRO=humble",
                    "REMOTE_PASSWORD=ci-secret-must-not-leak",
                    f"ZENOH_ROUTER_BIND_IP={binding}",
                    "",
                ]
            )
        )

    for binding in (
        "0.0.0.0 # Compose strips this comment",
        "[::]",
        "0:0:0:0:0:0:0:0",
        "[::0.0.0.0]",
        "[::ffff:0.0.0.0]",
        "[::ffff:0:0]",
        "[0:0:0:0:0:ffff:0:0]",
    ):
        write_dotenv(binding)
        result = subprocess.run(
            ["bash", "cloud.sh", "dry-run"],
            cwd=deployment,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Refusing wildcard Zenoh binding" in result.stdout
        assert "no transport authentication or encryption" in result.stdout

    write_dotenv("127.0.0.1")
    environment = os.environ | {"ZENOH_ROUTER_BIND_IP": "0.0.0.0"}
    result = subprocess.run(
        ["bash", "cloud.sh", "dry-run"],
        cwd=deployment,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode != 0
    assert "Refusing wildcard Zenoh binding 0.0.0.0" in result.stdout

    result = subprocess.run(
        ["bash", "cloud.sh", "dry-run"],
        cwd=deployment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "ci-secret-must-not-leak" not in result.stdout
    assert "ci-secret-must-not-leak" not in result.stderr


def test_pr_preview_separates_untrusted_build_from_trusted_deploy():
    build_path = ROOT / ".github/workflows/pr-preview.yaml"
    deploy_path = ROOT / ".github/workflows/pr-preview-deploy.yaml"
    build_workflow = build_path.read_text()
    deploy_workflow = deploy_path.read_text()
    build_jobs = yaml.safe_load(build_workflow)["jobs"]
    deploy_jobs = yaml.safe_load(deploy_workflow)["jobs"]

    assert "\n  pull_request:\n" in build_workflow
    assert "\n  pull_request_target:\n" not in build_workflow
    assert set(build_jobs) == {"build-preview"}
    assert build_jobs["build-preview"]["permissions"] == {"contents": "read"}
    assert "contents: write" not in build_workflow

    assert "\n  workflow_run:\n" in deploy_workflow
    assert "\n  pull_request_target:\n" in deploy_workflow
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in deploy_workflow
    assert deploy_jobs["deploy-preview"]["concurrency"] == {
        "group": "preview-deploy-${{ github.event.workflow_run.pull_requests[0].number }}",
        "cancel-in-progress": True,
    }
    assert deploy_jobs["deploy-preview"]["permissions"] == {
        "actions": "read",
        "contents": "write",
        "pull-requests": "write",
    }
    deploy_steps = deploy_jobs["deploy-preview"]["steps"]
    assert all(
        not step.get("uses", "").startswith("./")
        for step in deploy_steps
    )
    checkout_steps = [
        step for step in deploy_steps if step.get("uses") == "actions/checkout@v6"
    ]
    assert checkout_steps[0]["with"]["ref"] == (
        "${{ github.event.repository.default_branch }}"
    )
    assert "Check pull request state" in [step.get("name") for step in deploy_steps]
    assert "Recheck pull request state" in [step.get("name") for step in deploy_steps]
    step_names = [step.get("name") for step in deploy_steps]
    assert step_names.index("Update preview comment") < step_names.index(
        "Recheck pull request state"
    )
    download_step = next(
        step for step in deploy_steps if step.get("name") == "Download preview artifact"
    )
    assert download_step["with"]["run-id"] == "${{ github.event.workflow_run.id }}"
    assert deploy_jobs["remove-preview"]["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
    }
    assert "github.event.pull_request.head.repo.full_name == github.repository" in (
        deploy_jobs["remove-preview"]["if"]
    )
    remove_checkout = next(
        step
        for step in deploy_jobs["remove-preview"]["steps"]
        if step.get("uses") == "actions/checkout@v6"
    )
    assert remove_checkout["with"]["ref"] == (
        "${{ github.event.repository.default_branch }}"
    )


def test_zenoh_example_env_and_scripts_do_not_source_dotenv():
    assert (ZENOH / ".env.example").is_file()
    assert "/deployments/zenoh-bridge/.env" in (ROOT / ".gitignore").read_text()
    for name in ("common.sh", "cloud.sh", "edge.sh"):
        script = (ZENOH / name).read_text()
        assert ". ./.env" not in script
        assert "source .env" not in script
