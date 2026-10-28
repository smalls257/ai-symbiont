import json

import pytest

from symbiont import cli
from symbiont.delivery.hooks import HookEvent, NoteStyle
from symbiont.delivery.install.claude_code import claude_code_install
from symbiont.delivery.install.muse_code import muse_code_install
from symbiont.delivery.install.transaction import (
    InstallError,
    InstallOutcome,
    install,
    uninstall,
)

pytestmark = pytest.mark.periphery

ORIGINAL_SETTINGS = b'{"model":  "x",\n  "hooks": {"Stop": [{"hooks": []}]}}'
ORIGINAL_MCP = b'{"mcpServers": {"other": {"command": "o"}}}\r\n'
yes = lambda diff: True  # noqa: E731
no = lambda diff: False  # noqa: E731


def seeded(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/settings.local.json").write_bytes(ORIGINAL_SETTINGS)
    (tmp_path / ".mcp.json").write_bytes(ORIGINAL_MCP)
    return tmp_path


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_install_is_idempotent_and_reversible(tmp_path):
    project = seeded(tmp_path)
    before = snapshot(project)
    spec = claude_code_install(NoteStyle.PLAIN)
    assert install(spec, project, yes) is InstallOutcome.INSTALLED
    after = snapshot(project)
    assert (project / ".symbiont/install-claude_code/.gitignore").read_text() == "*\n"
    assert install(spec, project, yes) is InstallOutcome.ALREADY_INSTALLED
    assert snapshot(project) == after
    settings = json.loads((project / ".claude/settings.local.json").read_text())
    assert settings["model"] == "x" and "Stop" in settings["hooks"]
    assert set(settings["hooks"]) >= {"SessionStart", "UserPromptSubmit", "PostToolUse"}
    uninstall(spec, project)
    assert snapshot(project) == before


def test_uninstall_removes_files_the_install_created(tmp_path):
    before = snapshot(tmp_path)
    spec = muse_code_install(NoteStyle.FINDING)
    assert install(spec, tmp_path, yes) is InstallOutcome.INSTALLED
    written = json.loads((tmp_path / ".muse/settings.json").read_text())
    assert set(written["hooks"]) == {e.value for e in HookEvent}
    command = written["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert command == "symbiont hook PostToolUse --harness muse_code --notes finding"
    uninstall(spec, tmp_path)
    assert snapshot(tmp_path) == before and not (tmp_path / ".symbiont").exists()


def test_declining_the_diff_writes_nothing(tmp_path):
    project = seeded(tmp_path)
    before = snapshot(project)
    shown = []
    outcome = install(
        claude_code_install(NoteStyle.PLAIN), project, lambda d: shown.append(d) or False
    )
    assert outcome is InstallOutcome.DECLINED and snapshot(project) == before
    assert "+++ b/.claude/settings.local.json" in shown[0] and "symbiont hook" in shown[0]


def test_uninstall_refuses_after_the_developer_edited_the_file(tmp_path):
    project = seeded(tmp_path)
    spec = claude_code_install(NoteStyle.PLAIN)
    install(spec, project, yes)
    (project / ".mcp.json").write_text("{}")
    with pytest.raises(InstallError, match=r"\.mcp\.json changed since install"):
        uninstall(spec, project)


def test_uninstall_without_install_and_invalid_json_are_named(tmp_path):
    spec = claude_code_install(NoteStyle.PLAIN)
    with pytest.raises(InstallError, match="not installed"):
        uninstall(spec, tmp_path)
    (tmp_path / ".mcp.json").write_text("{nope")
    with pytest.raises(InstallError, match=r"\.mcp\.json is not valid JSON"):
        install(spec, tmp_path, yes)


def test_cli_install_asks_first_and_uninstall_restores(tmp_path, monkeypatch, capsys):
    project = seeded(tmp_path)
    before = snapshot(project)
    base = ["install", "claude_code", "--project-dir", str(project)]
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(base) == 0 and snapshot(project) == before
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert cli.main(base) == 0 and snapshot(project) != before
    assert cli.main(["uninstall", "claude_code", "--project-dir", str(project)]) == 0
    assert snapshot(project) == before
    assert cli.main(["uninstall", "claude_code", "--project-dir", str(project)]) == 1
    assert "not installed" in capsys.readouterr().err
