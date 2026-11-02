"""Node lifecycle wiring without Docker/ROS runtime claims."""
import json
import os
import subprocess
import sys

import pytest
import yaml
from release_fixtures import ROOT, executable

import validation_matrix

RUNNER = ROOT / ".github/scripts/evidence/run_cell.sh"


def matrix_cell(deployment, node=""):
    """The real evidence-matrix row the workflow hands to the runner."""
    runtime = validation_matrix.load_runtime(ROOT)
    cells = validation_matrix.evidence_cells(runtime, ROOT) + validation_matrix.example_kit_cells(runtime, ROOT)
    return next(cell for cell in cells if cell["deployment"] == deployment and cell["distro"] == "humble"
                and cell.get("node", "") == node)


def test_evidence_cells_carry_the_manifest_plan():
    split = matrix_cell("scenario-simulation", "split")
    nodes = json.loads((ROOT / "deployments/scenario-simulation/deployment.json").read_text())["nodes"]
    assert split["nodes"].split() == list(nodes) and split["l2"] == "scenario" and "/clock" in split["fresh"].split()
    kit = matrix_cell("custom-kit")
    assert kit["l2"] == "golden" and kit["l1"] == "custom-kit" and "/acme/probe" in kit["fresh"].split()
    assert matrix_cell("planning-simulation")["nodes"] == ""
    for cell in (split, kit):
        assert cell["name"] == validation_matrix.evidence_cell_name(cell)


def test_unexempt_deployment_without_an_l2_check_fails_enumeration(monkeypatch):
    monkeypatch.delitem(validation_matrix.BEHAVIOUR_CHECKS, "scenario-simulation")
    with pytest.raises(ValueError, match="scenario-simulation has no L2 evidence check"):
        validation_matrix.evidence_cells(validation_matrix.load_runtime(ROOT), ROOT)


@pytest.mark.parametrize(("node", "failure"), [("", ""), ("autoware", "validate"), ("split", "validate"), ("split", "run")])
def test_cell_lifecycle_keeps_node_order_failures_and_cleanup(tmp_path, node, failure):
    cli = tmp_path / "bin/openadkit"
    executable(cli, '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['CALLS']).open('a') as log:
    log.write(json.dumps([args, os.getenv('ZENOH_LISTEN'), os.getenv('ZENOH_PEER')]) + '\\n')
if args[0] == 'validate': print(json.dumps({'deployment': args[1]}))
sys.exit(1 if args[0] == os.environ['FAILURE'] else 0)
''')
    executable(tmp_path / "bin/docker", "#!/usr/bin/env bash\nexit 0\n")
    calls = tmp_path / "calls"
    out = tmp_path / "out"
    env = os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "OPENADKIT_CLI": str(cli),
                        "CALLS": str(calls), "FAILURE": failure, "BUILD_TAG": "123-1", "SOURCE_SHA": "b" * 40}
    nodes = "autoware scenario" if node == "split" else ""
    cell = matrix_cell("planning-simulation") | {"node": node, "nodes": nodes}
    result = subprocess.run(["bash", str(RUNNER), json.dumps(cell), str(out)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert (result.returncode == 0) is (not failure), result.stderr
    report = json.loads((out / "cell.json").read_text())
    assert report["result"] == ("FAILED" if failure else "PASSED")
    assert report["build_tag"] == "123-1" and report["node"] == node and report["name"] == cell["name"]
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    def target(args):
        return args[args.index("--node") + 1] if "--node" in args else ""
    nodes = ["autoware", "scenario"] if node == "split" else [node]
    for operation in ("validate", "run", "stop"):
        expected = [] if operation == "run" and failure == "validate" else list(reversed(nodes)) if operation == "stop" else nodes
        assert [target(args) for args, _, _ in recorded if args[0] == operation] == expected
    if node == "split":
        for operation in ("validate", "run"):
            if operation == "run" and failure == "validate":
                continue
            assert [(listen, peer) for args, listen, peer in recorded if args[0] == operation] == [
                ("tcp/127.0.0.1:7447", env.get("ZENOH_PEER")), ("tcp/127.0.0.1:7448", "tcp/127.0.0.1:7447")]


def test_cell_ignores_host_site_config_and_inherited_kit(tmp_path):
    # The CLI prints the paths it would use; the cell must point them at its own
    # output and inherit no kit selection from the runner's environment.
    cli = tmp_path / "bin/openadkit"
    executable(cli, '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
report = {
    "config": os.environ.get("OPENADKIT_CONFIG_DIR"),
    "kit": os.environ.get("OPENADKIT_KIT"),
    "delegated": os.environ.get("OPENADKIT_DELEGATED"),
    "state": os.environ.get("OPENADKIT_STATE_DIR"),
    "site_exists": Path(os.environ["HOME"], ".config/openadkit/planning-simulation.env").exists(),
}
with Path(os.environ["CALLS"]).open("a") as log:
    log.write(json.dumps(report) + "\\n")
if args[0] == "validate":
    print(json.dumps({"deployment": args[1]}))
''')
    executable(tmp_path / "bin/docker", "#!/usr/bin/env bash\nexit 0\n")
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
    assert all(row["config"] == f"{out}/config" and row["state"] == f"{out}/state" for row in seen)
    # The host site file is outside the cell's configuration directory.
    assert all(row["site_exists"] for row in seen)


def test_split_l0_uses_real_manifest_endpoint_requirements(tmp_path):
    cli = tmp_path / "bin/openadkit"
    executable(cli, f'''#!{sys.executable}
import json, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / 'cli')!r})
import manifest
args = sys.argv[1:]
if args[0] == 'validate':
    root = Path({str(ROOT)!r}); kit = manifest.load_kit(root)
    manifest.get_deployment(root, kit, args[1]).select(kit, 'humble', False, node=args[args.index('--node') + 1])
    print(json.dumps({{'deployment': args[1]}}))
sys.exit(1 if args[0] == 'run' else 0)
''')
    executable(tmp_path / "bin/docker", "#!/usr/bin/env bash\nexit 0\n")
    env = {k: v for k, v in os.environ.items() if k not in ("ZENOH_LISTEN", "ZENOH_PEER", "OPENADKIT_KIT")}
    env.update(PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", OPENADKIT_CLI=str(cli),
               HOME=str(tmp_path), OPENADKIT_CONFIG_DIR=str(tmp_path / 'config'))
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
    probe = text[text.index('isolation=$(\n'):text.index('\n                else', text.index('isolation=$(\n'))]
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
PASSED = "[openscenario_interpreter_node-3] [INFO] [simulation.openscenario_interpreter]: \x1b[32mPassed\x1b[0m\n"


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
# Lists every name. /flaky exits at once until its FLAKY_AFTER-th echo, like
# an echo before discovery; /late and /soon publish 3 s and 1 s after the
# subscriber starts; /never stays silent.
case "$1 $2" in
  "service list"|"topic list") printf '%s\\n' /api/a /flaky /late /soon /never ;;
  "topic echo")
    echo "$4" >> "${ECHO_LOG}"
    case "$4" in
      /flaky) [ "$(grep -c /flaky "${ECHO_LOG}")" -ge "${FLAKY_AFTER}" ] || exit 1 ;;
      /late) sleep 3 ;;
      /soon) sleep 1 ;;
      /never) sleep 1000 ;;
    esac
    echo "data: 1" ;;
esac
"""


@pytest.mark.parametrize(("fresh", "timeout", "ok", "echoes"), [
    # Echo exits at once while the topic is unknown: retried until it arrives.
    (["/flaky"], "60", [True], ["/flaky", "/flaky"]),
    # A publisher later than the 2 s window reaches the one subscriber that
    # keeps waiting until the deadline.
    (["/late"], "60", [True], ["/late"]),
    # A silent topic waits out the deadline; the next topic still gets its
    # own full window.
    (["/never", "/soon"], "2", [False, True], ["/never", "/soon"]),
])
def test_readiness_waits_for_late_publishers_until_the_deadline(tmp_path, fresh, timeout, ok, echoes):
    executable(tmp_path / "ros2", FAKE_ROS2)
    env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "ECHO_LOG": str(tmp_path / "echoes"),
                        "FLAKY_AFTER": "2"}
    command = [sys.executable, str(ROOT / ".github/scripts/evidence/readiness.py"), "--service", "/api/a",
               "--timeout", timeout, "--fresh-timeout", "2", "--output", str(tmp_path / "readiness.json")]
    for name in fresh:
        command += ["--fresh", name]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert (result.returncode == 0) is all(ok), result.stdout + result.stderr
    items = json.loads((tmp_path / "readiness.json").read_text())["items"][1:]
    assert [item["ok"] for item in items] == ok
    assert (tmp_path / "echoes").read_text().split() == echoes


def resolve_tested_commit_step():
    jobs = yaml.safe_load((ROOT / ".github/workflows/evidence.yaml").read_text())["jobs"]
    return next(step for step in jobs["prepare"]["steps"] if step["name"] == "Resolve the tested commit")["run"]


@pytest.mark.parametrize(("event", "change", "release", "skip"), [
    # A build verified at its own commit is release evidence.
    ("workflow_dispatch", None, "true", "false"),
    # A deployment change runs against the build's images but is not attested.
    ("workflow_dispatch", "deployments/planning-simulation/config.env", "false", "false"),
    ("pull_request", "deployments/planning-simulation/config.env", "false", "false"),
    # A pull request whose images would differ waits for its build.
    ("pull_request", "components/api/Dockerfile", "false", "true"),
    ("workflow_dispatch", "components/api/Dockerfile", "false", "false"),
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


@pytest.mark.parametrize(("machine", "platform", "ok"), [
    ("x86_64", "linux/amd64", True),
    ("aarch64", "linux/arm64", True),
    # A cell planned for another machine must not claim this one.
    ("aarch64", "linux/amd64", False),
    ("x86_64", "linux/arm64", False),
])
def test_a_cell_only_runs_on_the_machine_it_is_planned_for(tmp_path, machine, platform, ok):
    executable(tmp_path / "bin/openadkit", "#!/usr/bin/env bash\nexit 0\n")
    executable(tmp_path / "bin/docker", "#!/usr/bin/env bash\nexit 0\n")
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
