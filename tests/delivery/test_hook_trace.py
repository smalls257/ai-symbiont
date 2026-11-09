import io
import json

import pytest

from symbiont.delivery import hook_main, hook_trace

pytestmark = pytest.mark.periphery

STDIN = json.dumps({"session_id": "s1", "cwd": "/work/demo", "prompt": "hi"})


def test_tracing_is_off_unless_asked(tmp_path):
    assert hook_trace.trace_path({}, tmp_path) is None


def test_the_environment_variable_names_the_trace_file(tmp_path):
    named = tmp_path / "t.jsonl"
    assert hook_trace.trace_path({hook_trace.TRACE_VARIABLE: str(named)}, tmp_path) == named


def test_a_marker_file_in_the_data_directory_switches_it_on(tmp_path):
    (tmp_path / hook_trace.TRACE_MARKER).write_text("")
    assert hook_trace.trace_path({}, tmp_path) == tmp_path / hook_trace.TRACE_FILE


def test_a_hook_writes_what_arrived_before_it_says_what_it_did(tmp_path, monkeypatch):
    (tmp_path / hook_trace.TRACE_MARKER).write_text("")
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    hook_main.main(
        ["UserPromptSubmit", "--harness", "claude_code", "--data-dir", str(tmp_path), "--port", "1"]
    )
    lines = [
        json.loads(x)
        for x in (tmp_path / hook_trace.TRACE_FILE).read_text(encoding="utf-8").splitlines()
    ]
    assert [(x["stage"], x["event"]) for x in lines] == [
        ("received", "UserPromptSubmit"),
        ("outcome", "UserPromptSubmit"),
    ]
    assert lines[0]["stdin"] == "not json" and lines[1]["outcome"] == "dropped"
