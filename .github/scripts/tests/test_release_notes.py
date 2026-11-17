import json
import sys

from release_fixtures import ROOT, VERSION, build_metadata, passing_summary, write_plan

sys.path.insert(0, str(ROOT / ".github/scripts"))
import release_notes  # noqa: E402

PUBLISHED = ["v0.0.0-test", "v2.0.0-rc.1", "v2.0.0-rc.2", "v2.0.0", "v2.0.1-rc.1", "v2.0.1-rc.2", "nightly"]


def test_previous_release_skips_candidates_for_a_stable_release():
    assert release_notes.previous_release("v2.0.1", PUBLISHED) == "v2.0.0"
    assert release_notes.previous_release("v2.0.1-rc.3", PUBLISHED) == "v2.0.1-rc.2"
    assert release_notes.previous_release("v2.0.0-rc.10", PUBLISHED) == "v2.0.0-rc.2"
    assert release_notes.previous_release("v2.0.0", ["v2.0.0-rc.1"]) is None
    assert release_notes.previous_release("v1.0.0", PUBLISHED) is None


def test_changes_are_grouped_by_pull_request_type():
    body = "\n".join([
        "## What's Changed",
        "* feat(images)!: split planning and control by @a in https://github.com/o/r/pull/1",
        "* feat(cli): add restart by @a in https://github.com/o/r/pull/2",
        "* fix: wait for healthchecks by @b in https://github.com/o/r/pull/3",
        "* docs: move the roadmap by @b in https://github.com/o/r/pull/4",
        "* Bump an action by @dependabot[bot] in https://github.com/o/r/pull/5",
        "",
        "## New Contributors",
        "* @b made their first contribution in https://github.com/o/r/pull/3",
        "* @dependabot[bot] made their first contribution in https://github.com/o/r/pull/5",
        "",
        "**Full Changelog**: https://github.com/o/r/compare/v2.0.0...v2.0.1",
    ])
    text = release_notes.group_changes(body)
    sections = {title: text.index(f"### {title}") for title in
                ("⚠️ Breaking changes", "Features", "Fixes", "Other changes", "New contributors")}
    assert list(sections.values()) == sorted(sections.values())
    assert text.index("pull/1") < sections["Features"] < text.index("pull/2") < sections["Fixes"]
    assert sections["Other changes"] < text.index("pull/4") < text.index("pull/5") < sections["New contributors"]
    assert text.rstrip().endswith("compare/v2.0.0...v2.0.1") and "@dependabot[bot] made" not in text


def test_a_long_change_list_becomes_a_count():
    body = "\n".join(f"* fix: change {n} by @a in https://github.com/o/r/pull/{n}" for n in range(50))
    text = release_notes.group_changes("## What's Changed\n" + body + "\n\n**Full Changelog**: link\n")
    assert "50 pull requests" in text and "pull/1\n" not in text and "**Full Changelog**: link" in text
    assert release_notes.group_changes("") == ""


def test_notes_lead_with_people_and_keep_digests_folded(tmp_path):
    result, output = write_plan(tmp_path, summary=passing_summary(build_metadata()))
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_text())
    plan["evidence"]["exempt"] = [{"deployment": "carla-simulation", "reason": "Needs a GPU."}]
    plan["releaseContext"]["autoware"]["backports"] = [
        {"subject": "fix a crash", "repository": "autoware_universe", "upstream": "https://example/pull/9"}]
    notes = release_notes.render(plan, "example/repo", "Big release.\n", "## What's Changed\n\n* fix: x\n")
    # The title is the version alone, so the note opens with what the release runs.
    first, _, rest = notes.partition("\n\n")
    autoware = plan["releaseContext"]["autoware"]
    assert first.splitlines()[0] == "| Autoware | ROS 2 | Architectures |"
    assert first.splitlines()[2].startswith(
        f"| [{autoware['version']}](https://github.com/autowarefoundation/autoware/releases/tag/{autoware['version']}) |")
    assert rest.startswith("Big release.\n\n## Install")
    assert f"releases/download/{VERSION}/openadkit" in notes
    assert "now point to this release" in notes
    assert notes.index("## What's Changed") < notes.index("## Verification")
    assert "**1/1** evidence cells passed · [How to verify this release]" in notes
    assert "Run: https://github.com/example/repo/actions/runs/456" in notes[notes.index("<summary>Evidence cells</summary>"):]
    # What CI does not verify is listed with the cells, folded.
    assert "- `carla-simulation`: Needs a GPU." in notes[notes.index("<summary>Evidence cells</summary>"):]
    assert "carla" not in notes[:notes.index("<details>")]
    assert "Passing cells" not in notes and "| Cell | Result |" in notes
    # The long parts stay folded, the backported fixes among them.
    digests = notes.index("<summary>Image digests</summary>")
    assert notes.index("<summary>Evidence cells</summary>") < digests and plan["images"][0]["digest"] in notes[digests:]
    assert "fix a crash (`autoware_universe`)" in notes[notes.index("<summary>Fixes backported to Autoware"):]
    assert notes.endswith("</details>\n")
