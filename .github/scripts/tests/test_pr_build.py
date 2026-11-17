"""A pull request's build is completed in the CI package (assemble_pr_build.sh)."""
import json
import subprocess

from release_fixtures import ROOT, executable

SCRIPT = ROOT / ".github/scripts/assemble_pr_build.sh"
CI = "ghcr.io/example/openadkit-ci"


def test_the_build_uses_its_images_and_copies_the_rest_from_the_base(tmp_path):
    inventory = {"ros_distros": ["humble", "jazzy"], "images": [
        {"target": "api"}, {"target": "planning"}, {"target": "planning-cuda", "ros_distros": ["humble"]}]}
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    base = {"images": [{"repo": "ghcr.io/example/openadkit", "target": target, "ros_distro": distro,
                        "digest": f"sha256:{target}-{distro}"}
                       for target, distro in (("api", "humble"), ("api", "jazzy"), ("planning", "humble"),
                                              ("planning", "jazzy"), ("planning-cuda", "humble"))]}
    (tmp_path / "base.json").write_text(json.dumps(base))
    # This run built planning on both distros; jazzy's in the first attempt,
    # which a rerun of the failed jobs keeps.
    built = {f"{CI}:planning-amd64-humble-7-2", f"{CI}:planning-amd64-jazzy-7-1"}
    calls = tmp_path / "calls"
    executable(tmp_path / "bin/docker", f'''#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args[:3] == ["buildx", "imagetools", "inspect"]:
    sys.exit(0 if args[3] in {sorted(built)!r} else 1)
with open({str(calls)!r}, "a") as log:
    log.write(" ".join(args) + "\\n")
''')
    env = {"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "CI_REPO": CI, "BUILD_TAG": "7-2", "RUN_ID": "7",
           "RUN_ATTEMPT": "2", "PR_NUMBER": "42", "BASE_METADATA": str(tmp_path / "base.json"),
           "INVENTORY": str(tmp_path / "inventory.json")}
    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "2"
    created = {line.split()[-1]: line for line in calls.read_text().splitlines()}
    assert set(created) == {f"{CI}:planning-amd64-humble-7-2", f"{CI}:planning-amd64-jazzy-7-1",
                            "ghcr.io/example/openadkit@sha256:api-humble", "ghcr.io/example/openadkit@sha256:api-jazzy",
                            "ghcr.io/example/openadkit@sha256:planning-cuda-humble"}
    # Every image gets the build's tag and the pull request's moving tag.
    line = created["ghcr.io/example/openadkit@sha256:api-jazzy"]
    assert f"--tag {CI}:api-jazzy-7-2" in line and f"--tag {CI}:api-jazzy-pr42" in line


def test_an_image_missing_from_the_base_fails(tmp_path):
    (tmp_path / "inventory.json").write_text(json.dumps({"ros_distros": ["humble"], "images": [{"target": "api"}]}))
    (tmp_path / "base.json").write_text(json.dumps({"images": []}))
    executable(tmp_path / "bin/docker", "#!/usr/bin/env bash\nexit 1\n")
    env = {"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "CI_REPO": CI, "BUILD_TAG": "7-1", "RUN_ID": "7",
           "RUN_ATTEMPT": "1", "PR_NUMBER": "42", "BASE_METADATA": str(tmp_path / "base.json"),
           "INVENTORY": str(tmp_path / "inventory.json")}
    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)
    assert result.returncode != 0 and "no api-humble image" in result.stderr
