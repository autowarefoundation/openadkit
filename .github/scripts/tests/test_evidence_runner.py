"""Role lifecycle wiring without Docker/ROS runtime claims."""
import json
import os
import subprocess
import sys

import pytest
import yaml
from release_fixtures import ROOT, executable

import validation_matrix

RUNNER = ROOT / ".github/scripts/evidence/run_cell.sh"
# A Docker with no container, except the map: it answers the cell's last check
# as a service with a killed node, unhealthy and still running.
DOCKER = '''#!/usr/bin/env bash
if [ "$1" = inspect ] && [ "${!#}" = autoware-map ]; then echo "${MAP_STATE-running unhealthy}"; fi
if [ "$1 $2" = "ps -aq" ] && [ "${HEALTH_ERROR:-}" = list ]; then echo "container listing failed" >&2; exit 1; fi
if [ "$1" = ps ] && [ -n "${UNHEALTHY:-}" ]; then echo id; fi
if [ "$1" = inspect ] && [ "${!#}" = id ] && [ "${HEALTH_ERROR:-}" = inspect ]; then echo "container inspection failed" >&2; exit 1; fi
if [ "$1" = inspect ] && [ "${!#}" = id ]; then echo "/${UNHEALTHY} ${CONTAINER_STATE-0 running 0 on-failure unhealthy}"; fi
exit 0
'''


def matrix_cell(deployment, role="", launch_arguments=False):
    """The real evidence-matrix row the workflow hands to the runner.

    Without the launch-argument check, which starts the images, unless a test asks for it.
    """
    runtime = validation_matrix.load_runtime(ROOT)
    cells = validation_matrix.evidence_cells(runtime, ROOT) + validation_matrix.example_kit_cells(runtime, ROOT)
    cell = next(cell for cell in cells if cell["deployment"] == deployment and cell["distro"] == "humble"
                and cell.get("role", "") == role)
    return cell if launch_arguments else {key: value for key, value in cell.items() if key != "launch_arguments"}


def manifest(deployment):
    return json.loads((ROOT / f"deployments/{deployment}/deployment.json").read_text())


def test_evidence_cells_carry_the_manifest_plan():
    split = matrix_cell("scenario-simulation", "split")
    scenario = manifest("scenario-simulation")
    assert split["roles"].split() == list(scenario["roles"]) and json.loads(split["verify"]) == scenario["verify"]
    drive = manifest("planning-simulation")["verify"]
    # A deployment with a base runs the base's verify step on top of its own layer.
    for name in ("example-kit-planning-simulation", "safety-island-simulation", "planning-simulation"):
        assert json.loads(matrix_cell(name)["verify"]) == drive
    assert matrix_cell("planning-simulation")["roles"] == ""
    for cell in (split, matrix_cell("example-kit-planning-simulation"), matrix_cell("safety-island-simulation")):
        assert cell["name"] == validation_matrix.evidence_cell_name(cell)


def test_one_plain_cell_per_distro_checks_the_launch_arguments():
    runtime = validation_matrix.load_runtime(ROOT)
    cells = validation_matrix.evidence_cells(runtime, ROOT)
    checking = [cell for cell in cells if cell.get("launch_arguments") == "all"]
    assert sorted(cell["distro"] for cell in checking) == sorted({cell["distro"] for cell in cells})
    assert not any(cell.get("role") or cell.get("backend") for cell in checking)
    assert not any("launch_arguments" in cell for cell in validation_matrix.example_kit_cells(runtime, ROOT))


def test_a_cell_runs_on_every_architecture_its_deployment_supports():
    runtime = validation_matrix.load_runtime(ROOT)
    cells = validation_matrix.evidence_cells(runtime, ROOT)
    platforms = {name: {cell["platform"] for cell in cells if cell["deployment"] == name}
                 for name in {cell["deployment"] for cell in cells}}
    for name, found in platforms.items():
        assert found == {f"linux/{arch}" for arch in manifest(name)["requirements"]["architectures"]}, name
    assert platforms["planning-simulation"] == {"linux/amd64", "linux/arm64"}
    assert platforms["safety-island-simulation"] == {"linux/amd64", "linux/arm64"}
    # A pull request lists one platform.
    amd64 = validation_matrix.evidence_cells(runtime, ROOT, platforms=("linux/amd64",))
    assert amd64 and {cell["platform"] for cell in amd64} == {"linux/amd64"}


def test_a_failed_launch_argument_check_fails_l0(tmp_path):
    # The stub's catalog has no deployment, so the check finds no launch command.
    executable(tmp_path / "bin/openadkit", '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[:2] == ["list", "--json"]:
    print(json.dumps({"deployments": []}))
elif args[0] == "run" and "--verify" in args:
    report = Path(os.environ["OPENADKIT_HOME"], "output", args[1], "results/run.json")
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"readySeconds": 1, "verify": {"seconds": 1, "result": "PASSED"}}))
''')
    executable(tmp_path / "bin/docker", DOCKER)
    out = tmp_path / "out"
    env = os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
                        "OPENADKIT_CLI": str(tmp_path / "bin/openadkit")}
    runtime = validation_matrix.load_runtime(ROOT)
    checking = next(cell for cell in validation_matrix.evidence_cells(runtime, ROOT)
                    if cell.get("launch_arguments") and cell["distro"] == "humble")
    cell = matrix_cell(checking["deployment"], launch_arguments=True)
    result = subprocess.run(["bash", str(RUNNER), json.dumps(cell), str(out)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    record = json.loads((out / "cell.json").read_text())
    assert result.returncode != 0 and record["result"] == "FAILED" and record["levels"]["L0"]["ok"] is False
    assert "no ros2 launch command found" in (out / "launch-arguments.log").read_text()


def test_launch_argument_check_reads_the_ros2_launch_commands(tmp_path):
    sys.path.insert(0, str(ROOT / ".github/scripts/evidence"))
    import launch_arguments
    (tmp_path / "launch").mkdir()
    model = {"services": {
        "planning": {"image": "planning", "command": ["ros2", "launch", "autoware_launch", "planning.launch.xml", "a:=1", "b:=x=y"],
                     "volumes": [{"type": "bind", "source": str(tmp_path / "launch"), "target": "/openadkit/launch"},
                                 {"type": "bind", "source": str(tmp_path / "missing"), "target": "/data"}]},
        "map": {"image": "map", "command": ["ros2", "launch", "/openadkit/launch/component.launch.py", "component:=component_map"]},
        "probe": {"image": "probe", "command": ["sleep", "infinity"]},
        "idle": {"image": "idle"},
    }}
    found = {launch["service"]: launch for launch in launch_arguments.launches(model)}
    assert sorted(found) == ["map", "planning"]
    assert found["planning"]["spec"] == ["autoware_launch", "planning.launch.xml"]
    assert found["planning"]["values"] == {"a": "1", "b": "x=y"}
    assert found["planning"]["mounts"] == [(str(tmp_path / "launch"), "/openadkit/launch")]
    assert found["map"]["spec"] == ["/openadkit/launch/component.launch.py"] and found["map"]["values"] == {"component": "component_map"}


def test_quadlet_cell_runs_the_drive_to_goal_check_on_a_runner_with_quadlet():
    runtime = validation_matrix.load_runtime(ROOT)
    cells = [cell for cell in validation_matrix.evidence_cells(runtime, ROOT) if cell.get("backend")]
    assert [cell["name"] for cell in cells] == [
        f"planning-simulation-{distro}-quadlet-linux-{arch}" for distro in ("humble", "jazzy") for arch in ("amd64", "arm64")
    ]
    for cell in cells:
        runner = "ubuntu-24.04-arm" if cell["platform"] == "linux/arm64" else "ubuntu-24.04"
        assert cell["backend"] == "quadlet" and cell["runner"] == runner
        assert json.loads(cell["verify"]) == manifest("planning-simulation")["verify"] and cell["roles"] == ""
        assert cell["name"] == validation_matrix.evidence_cell_name(cell)


def test_unexempt_deployment_without_a_verify_step_fails_enumeration(monkeypatch):
    runtime = validation_matrix.load_runtime(ROOT)
    real = runtime.get_deployment

    def without_verify(root, kit, name):
        deployment = real(root, kit, name)
        if name == "scenario-simulation":
            deployment.verify = None
        return deployment
    monkeypatch.setattr(runtime, "get_deployment", without_verify)
    with pytest.raises(ValueError, match="scenario-simulation declares no verify step"):
        validation_matrix.evidence_cells(runtime, ROOT)


@pytest.mark.parametrize(("role", "failure"), [
    ("", ""), ("", "verify"), ("", "run"), ("autoware", "validate"), ("split", "validate"), ("split", "run"),
])
def test_cell_lifecycle_keeps_role_order_failures_and_cleanup(tmp_path, role, failure):
    cli = tmp_path / "bin/openadkit"
    executable(cli, '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['CALLS']).open('a') as log:
    log.write(json.dumps([args, os.getenv('ZENOH_LISTEN'), os.getenv('ZENOH_PEER')]) + '\\n')
if args[0] == 'validate': print(json.dumps({'deployment': args[1]}))
if args[0] == 'run' and '--verify' in args and os.environ['FAILURE'] != 'run':
    report = Path(os.environ['OPENADKIT_HOME'], 'output', args[1], 'results/run.json')
    report.parent.mkdir(parents=True)
    passed = os.environ['FAILURE'] != 'verify'
    report.write_text(json.dumps({'readySeconds': 1.5, 'verify': {'seconds': 2.5, 'result': 'PASSED' if passed else 'FAILED'}}))
sys.exit(1 if args[0] == os.environ['FAILURE'] or (args[0] == 'run' and os.environ['FAILURE'] == 'verify') else 0)
''')
    executable(tmp_path / "bin/docker", DOCKER)
    calls = tmp_path / "calls"
    out = tmp_path / "out"
    env = os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "OPENADKIT_CLI": str(cli),
                        "CALLS": str(calls), "FAILURE": failure, "BUILD_TAG": "123-1", "SOURCE_SHA": "b" * 40}
    roles = "autoware scenario" if role == "split" else ""
    cell = matrix_cell("planning-simulation") | {"role": role, "roles": roles}
    result = subprocess.run(["bash", str(RUNNER), json.dumps(cell), str(out)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert (result.returncode == 0) is (not failure), result.stderr
    report = json.loads((out / "cell.json").read_text())
    assert report["result"] == ("FAILED" if failure else "PASSED")
    if not role:
        # One host runs the verify step with the stack; its report sets L1 and L2.
        levels = report["levels"]
        assert (levels["L1"]["ok"], levels["L2"]["ok"]) == {"": (True, True), "verify": (True, False), "run": (False, None)}[failure]
        if failure != "run":
            assert (report["metrics"]["ready_s"], report["metrics"]["arrival_s"]) == (1, 2)
    assert report["build_tag"] == "123-1" and report["role"] == role and report["name"] == cell["name"]
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    def target(args):
        return args[args.index("--role") + 1] if "--role" in args else ""
    roles = ["autoware", "scenario"] if role == "split" else [role]
    for operation in ("validate", "run", "stop"):
        expected = [] if operation == "run" and failure == "validate" else list(reversed(roles)) if operation == "stop" else roles
        assert [target(args) for args, _, _ in recorded if args[0] == operation] == expected
    if role == "split":
        for operation in ("validate", "run"):
            if operation == "run" and failure == "validate":
                continue
            assert [(listen, peer) for args, listen, peer in recorded if args[0] == operation] == [
                ("tcp/127.0.0.1:7447", env.get("ZENOH_PEER")), ("tcp/127.0.0.1:7448", "tcp/127.0.0.1:7447")]


def test_cell_ignores_host_settings_and_inherited_kit(tmp_path):
    # The CLI prints the paths it would use; the cell must point them at its own
    # output and inherit no kit selection from the runner's environment.
    cli = tmp_path / "bin/openadkit"
    executable(cli, '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
report = {
    "home": os.environ.get("OPENADKIT_HOME"),
    "kit": os.environ.get("OPENADKIT_KIT"),
    "delegated": os.environ.get("OPENADKIT_DELEGATED"),
    "site_exists": Path(os.environ["HOME"], ".config/openadkit/planning-simulation.env").exists(),
}
with Path(os.environ["CALLS"]).open("a") as log:
    log.write(json.dumps(report) + "\\n")
if args[0] == "validate":
    print(json.dumps({"deployment": args[1]}))
if args[0] == "run" and "--verify" in args:
    report = Path(os.environ["OPENADKIT_HOME"], "output", args[1], "results/run.json")
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"readySeconds": 1, "verify": {"seconds": 1, "result": "PASSED"}}))
''')
    executable(tmp_path / "bin/docker", DOCKER)
    home = tmp_path / "home"
    site = home / ".config/openadkit/planning-simulation.env"
    site.parent.mkdir(parents=True)
    site.write_text("MAP_PATH=/from/site\nCYCLONEDDS_NETWORK_INTERFACE=eth0\n")
    calls = tmp_path / "calls"
    out = tmp_path / "out"
    env = os.environ | {
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "OPENADKIT_CLI": str(cli), "CALLS": str(calls),
        "BUILD_TAG": "123-1", "SOURCE_SHA": "b" * 40, "HOME": str(home),
        "OPENADKIT_KIT": str(tmp_path / "elsewhere"), "OPENADKIT_DELEGATED": "1",
    }
    result = subprocess.run(["bash", str(RUNNER), json.dumps(matrix_cell("planning-simulation")), str(out)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    seen = [json.loads(line) for line in calls.read_text().splitlines()]
    assert seen and all(row["kit"] is None and row["delegated"] is None for row in seen)
    assert all(row["home"] == f"{out}/home" for row in seen)
    # The host settings file is outside the cell's configuration directory.
    assert all(row["site_exists"] for row in seen)


def test_split_l0_uses_real_manifest_endpoint_requirements(tmp_path):
    cli = tmp_path / "bin/openadkit"
    executable(cli, f'''#!{sys.executable}
import json, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / 'cli')!r})
import catalog, settings
args = sys.argv[1:]
if args[0] == 'validate':
    root = Path({str(ROOT)!r}); kit = catalog.load_catalog(root)
    settings.resolve(catalog.get_deployment(root, kit, args[1]), kit, 'humble', False, role=args[args.index('--role') + 1])
    print(json.dumps({{'deployment': args[1]}}))
sys.exit(1 if args[0] == 'run' else 0)
''')
    executable(tmp_path / "bin/docker", DOCKER)
    env = {k: v for k, v in os.environ.items() if k not in ("ZENOH_LISTEN", "ZENOH_PEER", "OPENADKIT_KIT")}
    env.update(PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", OPENADKIT_CLI=str(cli),
               HOME=str(tmp_path))
    subprocess.run(["bash", str(RUNNER), json.dumps(matrix_cell("scenario-simulation", "split")), str(tmp_path / "out")],
                   env=env, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert json.loads((tmp_path / "out/cell.json").read_text())["levels"]["L0"]["ok"] is True


@pytest.mark.parametrize(("topics", "rc", "expected"), [("/clock", 0, "0"), ("/api/routing/state", 0, "1"), ("", 1, "failed"), ("", 124, "failed")])
def test_isolation_counts_zero_without_hiding_discovery_failure(tmp_path, topics, rc, expected):
    # Capture and execute the actual Docker probe command from the shell runner.
    executable(tmp_path / "bin/docker", '''#!/usr/bin/env python3
import os, subprocess, sys
if '--entrypoint' not in sys.argv: sys.exit(0)
command = sys.argv[sys.argv.index('-c') + 1]
command = command.replace('source "/opt/ros/${ROS_DISTRO}/setup.bash"', 'true')
sys.exit(subprocess.run(['bash', '-c', command]).returncode)
''')
    executable(tmp_path / "bin/ros2", f"#!/usr/bin/env bash\nprintf '%s\\n' {topics!r}\nexit {rc}\n")
    text = RUNNER.read_text()
    probe = text[text.index('isolation=$(\n'):text.index('\n        else', text.index('isolation=$(\n'))]
    env = os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "ROS_DISTRO": "humble"}
    result = subprocess.run(["bash", "-c", 'distro=humble; image=test; ' + probe + '\nprintf "%s" "$isolation"'],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout == expected, result.stderr


def test_evidence_metadata_survives_checkout_and_cells_install_compose(tmp_path):
    jobs = yaml.safe_load((ROOT / ".github/workflows/evidence.yaml").read_text())["jobs"]
    steps = jobs["prepare"]["steps"]
    executable(tmp_path / "bin/gh", '''#!/usr/bin/env python3
import json, sys
from pathlib import Path
destination = Path(sys.argv[sys.argv.index('--dir') + 1])
(destination / 'build-metadata.json').write_text(json.dumps({'openadkit_sha': 'b' * 40}))
''')
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path / "runner"),
                        "GITHUB_EVENT_NAME": "workflow_dispatch", "DISPATCH_BUILD_TAG": "123-1",
                        "GITHUB_REPOSITORY": "example/repo", "GITHUB_OUTPUT": str(tmp_path / "outputs")}
    result = subprocess.run(["bash", "-c", steps[0]["run"]], cwd=workspace, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not list(workspace.iterdir())  # Nothing for checkout to remove.
    assert json.loads((tmp_path / "runner/openadkit-build-metadata/build-metadata.json").read_text())["openadkit_sha"] == "b" * 40
    assert '$RUNNER_TEMP/openadkit-build-metadata/build-metadata.json' in next(s["run"] for s in steps if s["name"] == "Stage evidence kit")
    assert next(s["with"]["path"] for s in steps if s["name"] == "Upload build metadata").startswith('${{ runner.temp }}')
    cell_steps = jobs["cell"]["steps"]
    install = next(i for i, s in enumerate(cell_steps) if s.get("run") == "bash .github/scripts/install-compose.sh")
    assert install < next(i for i, s in enumerate(cell_steps) if s["name"] == "Run evidence cell")


RUN = "[scenario_test_runner.py-1] Run sample_{i}.xosc (1 of 1)\n"
# The interpreter colors "Passed"; a colored verdict must still count.
PASSED = "[openscenario_interpreter_role-3] [INFO] [simulation.openscenario_interpreter]: \x1b[32mPassed\x1b[0m\n"


@pytest.mark.parametrize(("cases", "log", "ok"), [
    (['<testcase name="sample_0"/>', '<testcase name="sample_1"/>'], RUN.format(i=0) + PASSED + RUN.format(i=1) + PASSED, True),
    # One of two scenarios ran and passed: incomplete, not a pass.
    (['<testcase name="sample_0"/>', '<testcase name="sample_1"/>'], RUN.format(i=0) + PASSED, False),
    # A skipped case did not run.
    (['<testcase name="sample_0"><skipped/></testcase>'], RUN.format(i=0) + PASSED, False),
    (['<testcase name="sample_0"><failure/></testcase>'], RUN.format(i=0), False),
])
def test_scenario_metrics_pass_only_complete_runs(tmp_path, cases, log, ok):
    (tmp_path / "out").mkdir()
    (tmp_path / "out/result.junit.xml").write_text(f"<testsuites><testsuite>{''.join(cases)}</testsuite></testsuites>")
    (tmp_path / "scenario.log").write_text(log)
    result = subprocess.run([sys.executable, str(ROOT / ".github/scripts/evidence/scenario_metrics.py"),
                             "--output-dir", str(tmp_path / "out"), "--log", str(tmp_path / "scenario.log"),
                             "--json", str(tmp_path / "metrics.json")], capture_output=True, text=True)
    assert (result.returncode == 0) is ok, result.stdout
    assert json.loads((tmp_path / "metrics.json").read_text())["ok"] is ok



FAKE_ROS2 = """#!/usr/bin/env bash
# Lists /api/a and /quiet; /api/a publishes and /quiet does not.
case "$1 $2" in
  "service list"|"topic list") printf '%s\\n' /api/a /quiet ;;
  "topic echo")
    echo "$4" >> "${ECHO_LOG}"
    [ "$4" = /api/a ] || exit 1
    echo "data: 1" ;;
esac
"""


@pytest.mark.parametrize(("arguments", "ok", "echoes"), [
    ([], True, []),
    (["--service", "/api/a", "--topic", "/api/a", "--fresh", "/api/a"], True, ["/api/a"]),
    # Nothing is echoed until every name is listed.
    (["--service", "/api/missing", "--fresh", "/api/a"], False, []),
    (["--topic", "/api/a", "--fresh", "/quiet"], False, ["/quiet"]),
])
def test_readiness_checks_once_and_fails_until_ready(tmp_path, arguments, ok, echoes):
    # Docker reruns the healthcheck until it passes; the check itself never waits.
    executable(tmp_path / "ros2", FAKE_ROS2)
    (tmp_path / "echoes").touch()
    env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "ECHO_LOG": str(tmp_path / "echoes")}
    result = subprocess.run([sys.executable, str(ROOT / "deployments/shared/checks/readiness.py"), *arguments],
                            env=env, capture_output=True, text=True, timeout=30)
    assert (result.returncode == 0) is ok, result.stdout + result.stderr
    assert (tmp_path / "echoes").read_text().split() == echoes


def resolve_tested_commit_step():
    jobs = yaml.safe_load((ROOT / ".github/workflows/evidence.yaml").read_text())["jobs"]
    return next(step for step in jobs["prepare"]["steps"] if step["name"] == "Resolve the tested commit")["run"]


@pytest.mark.parametrize(("event", "change", "release", "skip"), [
    # A build verified at its own commit is release evidence.
    ("workflow_dispatch", None, "true", "false"),
    # A deployment change runs against the build's images but is not attested.
    ("workflow_dispatch", "deployments/planning-simulation/settings.env", "false", "false"),
    ("pull_request", "deployments/planning-simulation/settings.env", "false", "false"),
    # A pull request whose images would differ waits for its build.
    ("pull_request", "components/control/Dockerfile", "false", "true"),
    ("workflow_dispatch", "components/control/Dockerfile", "false", "false"),
])
def test_a_commit_tested_against_other_images_is_not_release_evidence(tmp_path, event, change, release, skip):
    repo = tmp_path / "repo"
    repo.mkdir()
    # What build.py reads to tell which images a change touches.
    for path in (".github", "components", "deployments"):
        subprocess.run(["cp", "-r", str(ROOT / path), str(repo / path)], check=True)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "build"], check=True)
    build_sha = subprocess.run(git[:3] + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if change:
        with open(repo / change, "a", encoding="utf-8") as handle:
            handle.write("\n# changed\n")
        subprocess.run(git + ["commit", "-qam", "change"], check=True)
    output = tmp_path / "outputs"
    env = os.environ | {"GITHUB_EVENT_NAME": event, "BUILD_SHA": build_sha, "GITHUB_OUTPUT": str(output)}
    result = subprocess.run(["bash", "-c", resolve_tested_commit_step()], cwd=repo, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert (values["release_evidence"], values["skip"]) == (release, skip)
    assert (values["source_sha"] == build_sha) is (change is None)


@pytest.mark.parametrize(("event", "skip"), [("pull_request", "true"), ("workflow_dispatch", "false")])
def test_a_build_outside_the_tested_history_counts_as_other_images(tmp_path, event, skip):
    # The latest build of a branch that was rewritten since: its commit is not
    # in the checkout, so no diff can tell which images differ.
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "rewritten"], check=True)
    output = tmp_path / "outputs"
    env = os.environ | {"GITHUB_EVENT_NAME": event, "BUILD_SHA": "f" * 40, "GITHUB_OUTPUT": str(output)}
    result = subprocess.run(["bash", "-c", resolve_tested_commit_step()], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "is not in the history" in result.stdout
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert (values["release_evidence"], values["skip"]) == ("false", skip)


@pytest.mark.parametrize(("machine", "platform", "ok"), [
    ("x86_64", "linux/amd64", True),
    ("aarch64", "linux/arm64", True),
    # A cell planned for another machine must not claim this one.
    ("aarch64", "linux/amd64", False),
    ("x86_64", "linux/arm64", False),
])
def test_a_cell_only_runs_on_the_machine_it_is_planned_for(tmp_path, machine, platform, ok):
    executable(tmp_path / "bin/openadkit", '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == "run" and "--verify" in args:
    report = Path(os.environ["OPENADKIT_HOME"], "output", args[1], "results/run.json")
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"readySeconds": 1, "verify": {"seconds": 1, "result": "PASSED"}}))
''')
    executable(tmp_path / "bin/docker", DOCKER)
    executable(tmp_path / "bin/uname", f"#!/usr/bin/env bash\necho {machine}\n")
    out = tmp_path / "out"
    env = os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
                        "OPENADKIT_CLI": str(tmp_path / "bin/openadkit")}
    cell = matrix_cell("planning-simulation") | {"platform": platform}
    result = subprocess.run(["bash", str(RUNNER), json.dumps(cell), str(out)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert (result.returncode == 0) is ok, result.stderr
    if not ok:
        assert f"planned for {platform}" in result.stderr
        assert not (out / "cell.json").exists()


def test_allowlists_name_their_topics_and_a_rename_is_caught():
    sys.path.insert(0, str(ROOT / ".github/scripts/evidence"))
    import allowlist
    for deployment in ("scenario-simulation", "carla-simulation"):
        entries = allowlist.allowed_topics((ROOT / f"deployments/{deployment}/config/zenoh.json5").read_text())
        assert "/clock" in entries and "/api/.*" in entries
        # Commented lines are not entries.
        assert not any(entry.startswith("//") or " " in entry for entry in entries)
    graph = {"/clock", "/api/routing/state", "/planning/scenario_planning/velocity_smoother/virtual_wall"}
    assert allowlist.missing(["/clock", "/api/.*", "/(planning|control)/.*/virtual_walls?(/.*)?"], graph) == []
    # Entries are full-name matches: a prefix or a renamed topic is missing.
    assert allowlist.missing(["/clock_old", "/api", "/planning/trajectory"], graph) == [
        "/clock_old", "/api", "/planning/trajectory"]


@pytest.mark.parametrize(("environment", "ok", "logged"), [
    ({}, True, "after killing a node of the map: running unhealthy"),
    # The map's healthcheck missed the death of its node, or the map stopped.
    ({"MAP_STATE": "running healthy"}, False, "after killing a node of the map: running healthy"),
    ({"MAP_STATE": "exited unhealthy"}, False, "after killing a node of the map: exited unhealthy"),
    ({"HEALTH_ERROR": "list"}, False, "container listing failed"),
    ({"HEALTH_ERROR": "inspect", "UNHEALTHY": "autoware-planning"}, False, "container inspection failed"),
    # A node of another service died during the checks.
    ({"UNHEALTHY": "autoware-planning"}, False, "/autoware-planning 0 running 0 on-failure unhealthy"),
    # Its launch failed and the service restarted, healthy again, or it exited cleanly and stays down.
    ({"UNHEALTHY": "autoware-planning", "CONTAINER_STATE": "1 running 0 on-failure healthy"}, False, "/autoware-planning 1"),
    ({"UNHEALTHY": "autoware-planning", "CONTAINER_STATE": "0 exited 0 on-failure none"}, False, "exited 0 on-failure"),
    # A one-shot service may finish, but not fail.
    ({"UNHEALTHY": "autoware-prepare", "CONTAINER_STATE": "0 exited 0 no none"}, True, "exited 0 no"),
    ({"UNHEALTHY": "autoware-prepare", "CONTAINER_STATE": "0 exited 1 no none"}, False, "exited 1 no"),
])
def test_a_cell_fails_l1_when_a_node_died_or_a_death_does_not_show(tmp_path, environment, ok, logged):
    cli = tmp_path / "bin/openadkit"
    executable(cli, '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == 'validate': print(json.dumps({'deployment': args[1]}))
if args[0] == 'run':
    report = Path(os.environ['OPENADKIT_HOME'], 'output', args[1], 'results/run.json')
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'readySeconds': 1, 'verify': {'seconds': 2, 'result': 'PASSED'}}))
''')
    executable(tmp_path / "bin/docker", DOCKER)
    # The cell waits a minute for the map to turn unhealthy; the test does not.
    executable(tmp_path / "bin/sleep", "#!/usr/bin/env bash\nexit 0\n")
    executable(tmp_path / "bin/date", "#!/usr/bin/env bash\necho $(( $(/usr/bin/date +%s%N) / 1000000 ))\n")
    env = os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "OPENADKIT_CLI": str(cli)} | environment
    result = subprocess.run(["bash", str(RUNNER), json.dumps(matrix_cell("planning-simulation")), str(tmp_path / "out")],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    report = json.loads((tmp_path / "out/cell.json").read_text())
    assert report["levels"]["L1"]["ok"] is ok and report["levels"]["L2"]["ok"] is True
    assert (result.returncode == 0) is (report["result"] == "PASSED") is ok, result.stderr
    assert logged in (tmp_path / "out/health.log").read_text()


@pytest.mark.parametrize(("verify", "loop", "l3"), [
    ("PASSED", 0, True), ("PASSED", 1, False), ("FAILED", 0, None),
])
def test_a_kit_cell_runs_its_development_loop_after_its_verify_step(tmp_path, verify, loop, l3):
    cli = tmp_path / "bin/openadkit"
    executable(cli, '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == 'validate': print(json.dumps({'deployment': args[1]}))
if args[0] == 'run':
    report = Path(os.environ['OPENADKIT_HOME'], 'output', args[1], 'results/run.json')
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'readySeconds': 1, 'verify': {'seconds': 2, 'result': os.environ['VERIFY']}}))
''')
    executable(tmp_path / "bin/docker", DOCKER)
    # The kit's loop gets the CLI and the distro, and runs in the kit.
    executable(tmp_path / "checks/dev_loop.sh", f'#!/usr/bin/env bash\necho "$@" > called\nexit {loop}\n')
    env = os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "OPENADKIT_CLI": str(cli), "VERIFY": verify}
    cell = matrix_cell("example-kit-planning-simulation")
    result = subprocess.run(["bash", str(RUNNER), json.dumps(cell), str(tmp_path / "out")],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    report = json.loads((tmp_path / "out/cell.json").read_text())
    assert report["levels"]["L3"]["ok"] is l3
    assert (result.returncode == 0) is (report["result"] == "PASSED") is (l3 is True), result.stderr
    assert (tmp_path / "called").exists() is (l3 is not None)
    if l3 is not None:
        assert (tmp_path / "called").read_text().split() == [str(cli), "humble"]


def test_the_launch_argument_check_reads_the_list_output_as_the_cli_prints_it():
    # The check takes each deployment's GPU requirement from `list --json`.
    listed = json.loads(subprocess.run([str(ROOT / "openadkit"), "list", "--json"], capture_output=True, text=True, check=True).stdout)
    source = (ROOT / ".github/scripts/evidence/launch_arguments.py").read_text()
    assert 'deployment["requirements"]["gpu"]' in source
    assert all(deployment["requirements"]["gpu"] in ("none", "optional", "required") for deployment in listed["deployments"])
