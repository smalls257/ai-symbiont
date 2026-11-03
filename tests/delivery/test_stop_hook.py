"""The Stop hook asks the session's own model for one reflection, and can never loop.

Failures guarded against: a runaway loop (the reflection turn ends in another Stop), a silent
hook that hides why nothing was asked, and a host-specific output shape that one harness
rejects. Payloads are synthetic: Claude Code's `stop_hook_active` and Muse Code's session_id.
"""

import io
import json
import threading

import pytest

from symbiont import cli
from symbiont.delivery.hooks import (
    CLAUDE_CODE,
    MUSE_CODE,
    HookInputError,
    HookSettings,
    NoteStyle,
    NoteVisibility,
)
from symbiont.delivery.recall import ServiceOfflineError, ServiceReplyError
from symbiont.delivery.stop_hook import run_stop
from symbiont.service import server
from symbiont.service.app import ServiceMode
from symbiont.service.reflection import REFLECTION_QUESTION
from symbiont.service.wiring import Guards, open_service
from symbiont.store.repos import RepoRegistry, RepoStance

STOP_INPUT = {"session_id": "s1", "cwd": "/work/demo", "stop_hook_active": False}


def settings(harness=CLAUDE_CODE):
    return HookSettings(harness, NoteStyle.PLAIN, 1, "fallback")


LET_THROUGH = {"block": "", "why_not": "no failed check is waiting for a passing re-run"}


class FakeService:
    """Answers /stop/guard with `guard` and every other route with `reply`."""

    def __init__(self, reply, guard=None):
        self.reply, self.guard, self.calls = reply, guard or LET_THROUGH, []

    def __call__(self, route, body, port):
        self.calls.append((route, body))
        return self.guard if route == "/stop/guard" else self.reply

    def reflect_calls(self):
        return [call for call in self.calls if call[0] != "/stop/guard"]


@pytest.mark.parametrize("harness", [CLAUDE_CODE, MUSE_CODE])
def test_a_question_becomes_a_block_with_the_question_as_its_reason(harness):
    service = FakeService({"ask": "reflect now"})

    result = run_stop(json.dumps(STOP_INPUT), settings(harness), service)

    assert json.loads(result.context) == {"decision": "block", "reason": "reflect now"}
    assert service.reflect_calls() == [
        ("/reflect", {"project": "demo", "session_id": "s1", "harness": harness})
    ]


def test_the_reflection_turn_is_never_asked_again_even_if_the_service_would():
    service = FakeService({"ask": "reflect now"})

    result = run_stop(json.dumps(STOP_INPUT | {"stop_hook_active": True}), settings(), service)

    assert result.context == ""
    assert service.reflect_calls() == [
        ("/reflect/finished", {"project": "demo", "session_id": "s1", "harness": CLAUDE_CODE})
    ]


RED_BLOCK = {
    "block": "The last run of `pytest x` in this session failed; the work is not done yet.",
    "check": "pytest x",
}


@pytest.mark.parametrize("harness", [CLAUDE_CODE, MUSE_CODE])
def test_a_red_check_blocks_the_stop_before_any_reflection(harness):
    service = FakeService({"ask": "reflect now"}, guard=RED_BLOCK)

    held = json.loads(run_stop(json.dumps(STOP_INPUT), settings(harness), service).context)

    assert held["decision"] == "block" and "the work is not done yet" in held["reason"]
    assert held["systemMessage"].startswith("symbiont · the last run of `pytest x`")
    assert service.reflect_calls() == [], "the reflection ask waits for a later stop"
    assert service.calls[0][1]["stop_hook_active"] is False


def test_model_only_visibility_sends_no_system_message():
    quiet = HookSettings(CLAUDE_CODE, NoteStyle.PLAIN, 1, "fallback", NoteVisibility.MODEL_ONLY)

    held = json.loads(
        run_stop(json.dumps(STOP_INPUT), quiet, FakeService({"ask": ""}, RED_BLOCK)).context
    )

    assert "systemMessage" not in held


def test_the_stop_after_the_guard_is_a_fresh_stop_for_the_reflection():
    guard = {"block": "", "why_not": "after", "after_guard": True}
    service = FakeService({"ask": "reflect now"}, guard=guard)

    result = run_stop(json.dumps(STOP_INPUT | {"stop_hook_active": True}), settings(), service)

    assert json.loads(result.context)["reason"] == "reflect now"
    assert service.reflect_calls()[0][0] == "/reflect"


def test_no_question_prints_nothing_for_the_host_to_act_on():
    service = FakeService({"ask": "", "why_not": "symbiont is not switched on for demo"})

    assert run_stop(json.dumps(STOP_INPUT), settings(), service).context == ""


def test_the_project_falls_back_when_the_host_sends_no_cwd():
    service = FakeService({"ask": ""})

    run_stop(json.dumps({"session_id": "s1"}), settings(), service)

    assert service.calls[0][1]["project"] == "fallback"  # the guard is asked first


def test_an_offline_service_is_said_aloud_not_read_as_nothing_to_reflect_on():
    def down(route, body, port):
        raise ServiceOfflineError("nothing listening on 1")

    said = json.loads(run_stop(json.dumps(STOP_INPUT), settings(), down).context)

    assert said == {"systemMessage": "symbiont offline: nothing listening on 1"}


def test_input_without_a_session_id_is_refused_by_name():
    with pytest.raises(HookInputError, match="session_id"):
        run_stop(json.dumps({"cwd": "/work/demo"}), settings(), FakeService({"ask": ""}))


def test_a_question_that_is_not_text_is_a_reply_error():
    with pytest.raises(ServiceReplyError):
        run_stop(json.dumps(STOP_INPUT), settings(), FakeService({"ask": 3}))


@pytest.mark.periphery
def test_through_the_cli_and_a_real_service_a_worked_session_is_blocked_once(
    tmp_path, monkeypatch, capsys
):
    registry = RepoRegistry(tmp_path)
    registry.record_stance("demo", RepoStance.GIVEN)
    service = open_service(tmp_path, ServiceMode.WARN_AND_RECALL, guards=Guards(repos=registry))
    httpd = server.bind(service, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = str(httpd.server_address[1])

    def hook(event, payload):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        argv = ["hook", event, "--harness", "muse_code", "--port", port]
        assert cli.main(argv) == 0
        return capsys.readouterr().out

    try:
        edit = {"session_id": "s1", "cwd": "/work/demo", "tool_name": "edit_file"}
        edit["tool_input"] = {"path": "app.py"}
        edit["tool_response"] = "ok"
        assert hook("PostToolUse", edit) == ""
        assert hook("Stop", STOP_INPUT) == "", "an edit alone is not a milestone"
        check = {"session_id": "s1", "cwd": "/work/demo", "tool_name": "bash"}
        check["tool_input"] = {"command": "make check"}
        check["tool_response"] = json.dumps({"exit_code": 0, "output": "ok"})
        assert hook("PostToolUse", check) == ""
        first = json.loads(hook("Stop", STOP_INPUT))
        second = hook("Stop", STOP_INPUT)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert first == {"decision": "block", "reason": REFLECTION_QUESTION}
    assert second == ""
