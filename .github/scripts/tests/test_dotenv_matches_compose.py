"""The env reader must agree with the Compose that runs the deployments."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "cli"))
import manifest as cli_manifest  # noqa: E402

FIXTURE = '''PLAIN=value
export EXPORTED=ok
TRAIL="C:\\\\"
MULTI="line1
line2"
SINGLE='C:\path'
HASH_UNQUOTED=value # comment
HASH_NO_SPACE=value#still
DQ_ESCAPE="a\\tb"
SQ_DQ='a\\tb'
EMPTY=
SPACED = spaced value  
DQ_QUOTE="a\\"b"
DQ_N="a\\nb"
DQ_DOLLAR="a\\$b"
QUOTED_COMMENT="v" # note
UNQUOTED_TAB=value\t# tab before comment
COLON: colon value
COLON_TIGHT:tight
URL=http://host:8080/x
FROM_SHELL
export FROM_SHELL_EXPORTED
DOT.NAME=dot
DASH-NAME=dash
'''

EXPECTED = {
    "PLAIN": "value", "EXPORTED": "ok", "TRAIL": "C:\\", "MULTI": "line1\nline2",
    "SINGLE": "C:\\path", "HASH_UNQUOTED": "value", "HASH_NO_SPACE": "value#still",
    "DQ_ESCAPE": "a\tb", "SQ_DQ": "a\\tb", "EMPTY": "", "SPACED": "spaced value",
    "DQ_QUOTE": 'a"b', "DQ_N": "a\nb", "DQ_DOLLAR": "a$b", "QUOTED_COMMENT": "v",
    "UNQUOTED_TAB": "value\t# tab before comment", "COLON": "colon value",
    "COLON_TIGHT": "tight", "URL": "http://host:8080/x",
}
# Keys Compose reads but cannot interpolate, so they are checked on the reader only.
NOT_INTERPOLATED = {"DOT.NAME": "dot", "DASH-NAME": "dash"}


def compose_environment(tmp_path):
    """Compose's own reading of the fixture, or None without Compose."""
    if shutil.which("docker") is None:
        return None
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        return None
    (tmp_path / "a.env").write_text(FIXTURE)
    names = "\n".join(f"      - {name}=${{{name}}}" for name in EXPECTED)
    (tmp_path / "compose.yaml").write_text(
        f"services:\n  a:\n    image: busybox\n    environment:\n{names}\n")
    result = subprocess.run(["docker", "compose", "--env-file", "a.env", "config", "--format", "json"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]["a"]["environment"]


def test_dotenv_matches_compose(tmp_path):
    compose = compose_environment(tmp_path)
    if compose is None:
        pytest.skip("needs Docker Compose")
    parsed = cli_manifest.parse_dotenv(tmp_path / "a.env")
    # `compose config` renders a literal dollar as "$$" (Compose's own escape);
    # a container receives one, which is what the reader returns.
    rendered = {name: value.replace("$$", "$") for name, value in compose.items()}
    assert {name: parsed.pop(name) for name in NOT_INTERPOLATED} == NOT_INTERPOLATED
    # A name alone takes the shell's value: the file sets nothing for it.
    assert "FROM_SHELL" not in parsed and "FROM_SHELL_EXPORTED" not in parsed
    assert parsed == rendered == EXPECTED
