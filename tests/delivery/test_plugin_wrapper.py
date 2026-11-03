"""The plugin's hook wrapper keeps its promises on every platform: exit 0, one visible line.

Failure guarded against: Silent Fallback (a missing install that looks like "no notes") and a
wrapper that cannot find a uv-installed command where uv puts it (`~/.local/bin`, also on Windows).
On Windows the wrapper runs under Git Bash, as Claude Code runs it.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.periphery

PLUGIN = Path(__file__).resolve().parents[2] / "plugin" / "symbiont"
WRAPPER = PLUGIN / "bin" / "symbiont-hook.sh"
COMMAND = "symbiont-hook"


def shell() -> str:
    found = shutil.which("sh") or shutil.which("bash")
    assert found, "the wrapper needs sh (Git Bash on Windows); none is on PATH"
    return found


def path_without_the_command() -> str:
    entries = os.environ["PATH"].split(os.pathsep)
    return os.pathsep.join(e for e in entries if e and not shutil.which(COMMAND, path=e))


def run_wrapper(home: Path, event: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PATH": path_without_the_command(),
    }
    return subprocess.run(
        [shell(), WRAPPER.as_posix(), event],
        env=env,
        capture_output=True,
        text=True,
        input="",
        check=False,
        timeout=60,
    )


def test_a_missing_install_says_so_once_at_session_start_and_exits_zero(tmp_path):
    done = run_wrapper(tmp_path, "SessionStart")

    assert done.returncode == 0
    assert "symbiont is not installed" in json.loads(done.stdout)["systemMessage"]


def test_a_missing_install_is_silent_on_other_events_and_exits_zero(tmp_path):
    done = run_wrapper(tmp_path, "PostToolUse")

    assert (done.returncode, done.stdout) == (0, "")


def test_a_command_installed_in_the_home_local_bin_is_found_and_given_the_event(tmp_path):
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / COMMAND
    fake.write_bytes(b'#!/bin/sh\nprintf "ran %s" "$1"\n')
    fake.chmod(0o755)

    done = run_wrapper(tmp_path, "Stop")

    assert (done.returncode, done.stdout) == (0, "ran Stop")


def test_every_hook_entry_runs_the_wrapper_with_its_own_event_name():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    for event, groups in hooks.items():
        for group in groups:
            for hook in group["hooks"]:
                sh_part, _, cmd_part = hook["command"].partition(" || ")
                assert sh_part.endswith(f'symbiont-hook.sh" {event}')
                assert cmd_part == f'"%CLAUDE_PLUGIN_ROOT%\\bin\\symbiont-hook.cmd" {event}'


def test_the_wrapper_is_checked_out_with_unix_line_endings():
    assert b"\r" not in WRAPPER.read_bytes()


def test_the_mcp_server_is_a_bare_command_so_windows_can_start_it_without_a_shell():
    server = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][
        "symbiont"
    ]

    assert server["command"] == "symbiont" and server["args"] == ["mcp"]
    assert set(server) == {"command", "args"}


CMD_WRAPPER = PLUGIN / "bin" / "symbiont-hook.cmd"


def test_the_cmd_wrapper_uses_no_labels_because_git_checks_it_out_with_lf_endings():
    # .gitattributes forces LF everywhere; cmd.exe mis-reads goto labels in LF-only batch files.
    text = CMD_WRAPPER.read_text(encoding="utf-8")
    assert not [row for row in text.splitlines() if row.startswith(":")]
    assert "goto" not in text.lower()


def run_cmd_wrapper(home: Path, event: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "USERPROFILE": str(home), "PATH": path_without_the_command()}
    return subprocess.run(
        ["cmd.exe", "/c", str(CMD_WRAPPER), event],
        env=env,
        capture_output=True,
        text=True,
        input="",
        check=False,
        timeout=60,
    )


# cmd.exe exists only on Windows; the suite allows no skips, so these tests exist only there.
if os.name == "nt":

    def test_the_cmd_wrapper_says_a_missing_install_once_and_exits_zero(tmp_path):
        started = run_cmd_wrapper(tmp_path, "SessionStart")
        later = run_cmd_wrapper(tmp_path, "PostToolUse")

        assert started.returncode == 0
        assert "symbiont is not installed" in json.loads(started.stdout)["systemMessage"]
        assert (later.returncode, later.stdout) == (0, "")

    def test_the_cmd_wrapper_runs_the_command_from_home_local_bin_with_the_event(tmp_path):
        bin_dir = tmp_path / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / f"{COMMAND}.cmd").write_bytes(b"@echo off\r\necho ran %1\r\nexit /b 3\r\n")

        done = run_cmd_wrapper(tmp_path, "Stop")

        assert (done.returncode, done.stdout.strip()) == (0, "ran Stop")

    def test_the_cmd_wrapper_traces_when_the_marker_exists(tmp_path):
        (tmp_path / ".symbiont").mkdir()
        (tmp_path / ".symbiont" / "hook-trace.on").write_text("", encoding="utf-8")

        run_cmd_wrapper(tmp_path, "Stop")

        line = (tmp_path / ".symbiont" / "hook-trace.jsonl").read_text(encoding="utf-8")
        assert json.loads(line)["stage"] == "wrapper"
