"""Hook profiles: how each harness's hooks talk, kept out of the shared hook code."""

import io
import json

import pytest

from symbiont.delivery import hook_main
from symbiont.delivery.hook_profiles import EchoPolicy, ProjectNaming, profile
from symbiont.readers.harnesses import UnknownHarnessError


def test_the_tool_names_split_per_harness():
    claude, muse = profile("claude_code"), profile("muse_code")

    assert "Bash" in claude.shell_tools and "Bash" not in muse.shell_tools
    assert "exec_command" in muse.shell_tools and "exec_command" not in claude.shell_tools
    assert "read_file" in muse.read_tools and "Read" in claude.read_tools


def test_only_muse_asks_the_model_to_repeat_and_only_claude_names_projects_from_git():
    assert profile("muse_code").echo is EchoPolicy.ASK_MODEL_TO_REPEAT
    assert profile("claude_code").echo is EchoPolicy.NONE
    assert profile("claude_code").project_naming is ProjectNaming.GIT_ROOT_WHEN_KNOWN
    assert profile("muse_code").project_naming is ProjectNaming.CWD_NAME


def test_an_unknown_profile_names_the_known_ids():
    with pytest.raises(UnknownHarnessError, match="nope"):
        profile("nope")


def test_a_hook_with_no_harness_marker_warns_visibly_and_exits_0(monkeypatch, capsys, tmp_path):
    for marker in ("MUSE_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "CLAUDECODE"):
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    parser_args = ["SessionStart", "--data-dir", str(tmp_path)]

    code = hook_main.main(parser_args)

    seen = capsys.readouterr()
    line = (
        "symbiont: cannot tell which harness runs this hook; "
        "reinstall the plugin or pass --harness <id>"
    )
    assert code == 0
    assert line in seen.err
    assert json.loads(seen.out)["systemMessage"] == line
