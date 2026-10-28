import io
import json
import socket
import threading

import pytest

from symbiont import cli
from symbiont.delivery import hooks
from symbiont.delivery.hooks import HookEvent, HookInputError, HookSettings, NoteStyle
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.wiring import open_service

pytestmark = pytest.mark.periphery

PROMPT_INPUT = {"session_id": "s1", "cwd": "/work/demo", "prompt": "fix the build"}
TOOL_INPUT = {
    "session_id": "s1",
    "cwd": "/work/demo",
    "tool_name": "Bash",
    "tool_input": {"command": "pytest -q"},
    "tool_response": {"stdout": "boom", "exit_code": 1},
}
INPUTS = {
    HookEvent.SESSION_START: {"session_id": "s1", "source": "startup"},
    HookEvent.USER_PROMPT_SUBMIT: PROMPT_INPUT,
    HookEvent.PRE_LLM_CALL: {"session_id": "s1", "messages": [{}, {}]},
    HookEvent.POST_TOOL_USE: TOOL_INPUT,
    HookEvent.POST_TOOL_USE_FAILURE: TOOL_INPUT | {"tool_response": None, "error": "denied"},
}


@pytest.fixture
def service(tmp_path):
    httpd = server.bind(open_service(tmp_path, ServiceMode.WARN_AND_RECALL), 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], tmp_path
    httpd.shutdown()
    httpd.server_close()


def unused_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run_cli(monkeypatch, capsys, event, payload, port):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code = cli.main(["hook", event.value, "--harness", "muse_code", "--port", str(port)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def inline_text(context):
    return json.loads(context)["hookSpecificOutput"]["additionalContext"]


def test_service_down_prints_offline_note_and_exits_zero(monkeypatch, capsys):
    free = unused_port()
    code, out, _ = run_cli(monkeypatch, capsys, HookEvent.USER_PROMPT_SUBMIT, PROMPT_INPUT, free)
    assert code == 0
    assert json.loads(out)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert inline_text(out).startswith("symbiont offline: could not reach")


def test_service_down_on_a_silent_event_warns_on_stderr_and_exits_zero(monkeypatch, capsys):
    event = HookEvent.PRE_LLM_CALL
    code, out, err = run_cli(monkeypatch, capsys, event, INPUTS[event], unused_port())
    assert (code, out) == (0, "")
    assert err.startswith("symbiont offline:")


@pytest.mark.parametrize("event", list(HookEvent))
def test_each_event_maps_to_observe(service, monkeypatch, capsys, event):
    port, data_dir = service
    code, _, err = run_cli(monkeypatch, capsys, event, INPUTS[event], port)
    assert (code, err) == (0, "")
    (log,) = (data_dir / "runs").glob("*/events.jsonl")
    logged = [json.loads(line) for line in log.read_text().splitlines()]
    assert [(e["route"], e["hook"], "status" in e) for e in logged] == [
        ("observe", event.value, False)
    ]


@pytest.mark.parametrize(
    ("event", "kind", "expected"),
    [
        (HookEvent.USER_PROMPT_SUBMIT, "user_turn", {"raw": "fix the build"}),
        (HookEvent.POST_TOOL_USE, "command", {"command": "pytest -q", "exit_code": 1}),
        (HookEvent.POST_TOOL_USE_FAILURE, "command", {"command": "pytest -q", "exit_code": 1}),
    ],
)
def test_the_observed_record_carries_what_the_harness_reported(event, kind, expected):
    body = hooks.observe_body(event, INPUTS[event], "muse_code", "fallback")
    record = body["payload"]["record"]
    assert (body["event"], body["harness"], record["kind"]) == (event.value, "muse_code", kind)
    assert record["project"] == "demo" and record["provenance"]["spark_safe"] is False
    assert expected.items() <= record.items()


def observed(data, tool=None):
    if tool:
        data = data | {"tool_name": tool}
    return hooks.observe_body(HookEvent.POST_TOOL_USE, data, "claude_code", "p")["payload"][
        "record"
    ]


def test_a_shell_success_with_no_reported_code_is_not_assumed_zero():
    assert observed(TOOL_INPUT | {"tool_response": {"stdout": "ok"}})["exit_code"] is None


def test_edits_and_reads_name_their_file():
    data = TOOL_INPUT | {"tool_input": {"file_path": "a.py"}}
    edit, read = observed(data, "Edit"), observed(data, "Read")
    assert (edit["kind"], edit["files"], read["kind"]) == ("edit", ["a.py"], "read")


def test_notes_come_back_as_inline_context(monkeypatch):
    monkeypatch.setattr(hooks, "call_service", lambda route, body, port: {"notes": ["Careful."]})
    args = (json.dumps(PROMPT_INPUT), HookSettings("muse_code", NoteStyle.PLAIN, 1, "p"))
    result = hooks.run_hook(HookEvent.USER_PROMPT_SUBMIT, *args)
    expected = {"hookEventName": "UserPromptSubmit", "additionalContext": "Careful."}
    assert json.loads(result.context) == {"hookSpecificOutput": expected}


def test_finding_style_words_a_post_tool_use_note_as_a_finding(monkeypatch):
    monkeypatch.setattr(hooks, "call_service", lambda route, body, port: {"notes": ["It failed."]})
    tool = hooks.run_hook(
        HookEvent.POST_TOOL_USE,
        json.dumps(TOOL_INPUT),
        HookSettings("muse_code", NoteStyle.FINDING, 1, "p"),
    )
    prompt = hooks.run_hook(
        HookEvent.USER_PROMPT_SUBMIT,
        json.dumps(PROMPT_INPUT),
        HookSettings("muse_code", NoteStyle.FINDING, 1, "p"),
    )
    assert inline_text(tool.context) == "Finding: It failed."
    assert inline_text(prompt.context) == "It failed."


def test_no_notes_prints_nothing(monkeypatch):
    monkeypatch.setattr(hooks, "call_service", lambda route, body, port: {"notes": []})
    args = (json.dumps(PROMPT_INPUT), HookSettings("muse_code", NoteStyle.PLAIN, 1, "p"))
    assert hooks.run_hook(HookEvent.USER_PROMPT_SUBMIT, *args) == hooks.HookResult()


def test_unusable_input_is_named_and_exits_one(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert cli.main(["hook", "SessionStart", "--harness", "muse_code"]) == 1
    assert "hook input is not JSON" in capsys.readouterr().err
    with pytest.raises(HookInputError, match="session_id"):
        hooks.observe_body(HookEvent.SESSION_START, {}, "muse_code", "p")


def test_recall_with_an_unusable_reply_prints_one_line_and_exits_one(monkeypatch, capsys):
    from symbiont.delivery import recall

    monkeypatch.setattr(recall, "post_json", lambda destination, body, timeout_s: {})
    assert cli.main(["recall", "q", "--port", "1"]) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "no usable answer" in err
