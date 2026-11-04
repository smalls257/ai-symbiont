"""Muse Code's TUI flashes `systemMessage`, so the model is asked to say each note aloud.

Violation prevented: Black Box at the screen. A note only the model could read left the developer
watching the session blind to what symbiont said. Claude Code shows `systemMessage` itself, so its
output must stay exactly as it was.
"""

import json

import pytest

from symbiont.delivery import hooks
from symbiont.delivery.hooks import (
    ECHO_TO_DEVELOPER,
    HookEvent,
    HookSettings,
    NoteStyle,
    NoteVisibility,
)

pytestmark = pytest.mark.periphery

NOTE = "Last time `python3` failed with AssertionError (50.00); it was fixed when you ran x."
ECHO = (
    'Before you continue, tell the developer in one line, starting with "symbiont:", '
    "what this note says."
)
INPUTS = {
    HookEvent.SESSION_START: {"session_id": "s", "cwd": "/w/p", "source": "startup"},
    HookEvent.USER_PROMPT_SUBMIT: {"session_id": "s", "cwd": "/w/p", "prompt": "fix it"},
    HookEvent.POST_TOOL_USE: {
        "session_id": "s",
        "cwd": "/w/p",
        "tool_name": "edit_file",
        "tool_input": {"path": "a.py"},
        "tool_response": "ok",
    },
    HookEvent.POST_TOOL_USE_FAILURE: {
        "session_id": "s",
        "cwd": "/w/p",
        "tool_name": "bash",
        "tool_input": {"command": "python3 t.py"},
        "error": "AssertionError",
    },
}


def delivered(monkeypatch, event, harness, reply, visibility=NoteVisibility.SHOWN):
    monkeypatch.setattr(hooks, "call_service", lambda route, body, port: reply)
    settings = HookSettings(harness, NoteStyle.PLAIN, 1, "p", visibility)
    return json.loads(hooks.run_hook(event, json.dumps(INPUTS[event]), settings).context)


def test_the_echo_sentence_is_the_agreed_plain_prose():
    assert ECHO_TO_DEVELOPER == ECHO


@pytest.mark.parametrize(
    "event",
    [
        HookEvent.SESSION_START,
        HookEvent.USER_PROMPT_SUBMIT,
        HookEvent.POST_TOOL_USE,
        HookEvent.POST_TOOL_USE_FAILURE,
    ],
)
def test_every_note_kind_on_muse_ends_with_the_echo_request(monkeypatch, event):
    out = delivered(monkeypatch, event, "muse_code", {"notes": [NOTE]})
    assert out["hookSpecificOutput"]["additionalContext"] == f"{NOTE}\n{ECHO}"
    assert out["systemMessage"].startswith("symbiont")


def test_an_onboarding_announcement_on_muse_carries_the_echo_request_once(monkeypatch):
    reply = {"notes": [], "announce": ["Welcome to symbiont."], "tell_model": ["Relay it."]}
    out = delivered(monkeypatch, HookEvent.SESSION_START, "muse_code", reply)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert text == f"Welcome to symbiont.\nRelay it.\n{ECHO}"


def test_model_only_on_muse_is_unchanged(monkeypatch):
    out = delivered(
        monkeypatch,
        HookEvent.POST_TOOL_USE_FAILURE,
        "muse_code",
        {"notes": [NOTE]},
        NoteVisibility.MODEL_ONLY,
    )
    assert out == {
        "hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": NOTE}
    }


def test_no_note_on_muse_means_no_echo_request(monkeypatch):
    monkeypatch.setattr(hooks, "call_service", lambda route, body, port: {"notes": []})
    settings = HookSettings("muse_code", NoteStyle.PLAIN, 1, "p")
    event = HookEvent.SESSION_START
    assert hooks.run_hook(event, json.dumps(INPUTS[event]), settings).context == ""


@pytest.mark.parametrize("event", list(INPUTS))
def test_claude_code_output_is_byte_for_byte_what_it_was(monkeypatch, event):
    out = delivered(monkeypatch, event, "claude_code", {"notes": [NOTE]})
    assert ECHO not in json.dumps(out)
    expected = {
        "hookSpecificOutput": {"hookEventName": event.value, "additionalContext": NOTE},
        "systemMessage": out["systemMessage"],
    }
    assert out == expected
