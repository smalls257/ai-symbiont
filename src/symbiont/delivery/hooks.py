"""Harness hooks: forward one hook event to /observe and hand the notes back as context.

An offline service must be audible, not an empty note that reads as "nothing to warn
about", so offline prints a visible note and exits 0: the harness is never blocked.
"""

import json
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from symbiont.delivery.recall import ServiceOfflineError, call_service

DATASET_PREFIX = "live-"
LIVE_LICENSE = "local-session"


class HookEvent(StrEnum):
    """The harness events the hooks understand (day-1 G2 for Muse Code; Claude Code's docs)."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_LLM_CALL = "PreLLMCall"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"


class NoteStyle(StrEnum):
    """How a PostToolUse note is worded: plain prose, or a finding in the tool result's voice."""

    PLAIN = "plain"
    FINDING = "finding"


@dataclass(frozen=True)
class HookResult:
    """What the hook prints: `context` for the harness, `warning` for the developer's stderr."""

    context: str = ""
    warning: str = ""


@dataclass(frozen=True)
class HookSettings:
    """How one installed hook is configured: its harness, note wording, service port, project."""

    harness: str
    style: NoteStyle
    port: int
    fallback_project: str


class HookInputError(ValueError):
    """The harness sent hook input the hook cannot use; the message names the field."""


# PreLLMCall additionalContext was not seen in messages on echo (G2); it only observes.
SPEAKING_EVENTS = frozenset(
    {HookEvent.SESSION_START, HookEvent.USER_PROMPT_SUBMIT, HookEvent.POST_TOOL_USE}
)
_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
_SHELL_TOOLS = frozenset({"Bash", "shell", "bash"})


def offline_note(reason: object) -> str:
    """The visible line that stands in for notes when the service cannot be reached."""
    return f"symbiont offline: {reason}"


def run_hook(event: HookEvent, stdin_text: str, settings: HookSettings) -> HookResult:
    """What to print; raises HookInputError for unusable input."""
    data = _parsed(stdin_text)
    body = observe_body(event, data, settings.harness, settings.fallback_project)
    try:
        reply = call_service("/observe", body, settings.port)
    except ServiceOfflineError as offline:
        note = offline_note(offline)
        if event in SPEAKING_EVENTS:
            return HookResult(context=_inline_context(event, note))
        return HookResult(warning=note)
    notes = reply.get("notes")
    if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
        raise HookInputError("the local service sent notes that are not a list of sentences")
    text = _worded(event, notes, settings.style)
    if not text or event not in SPEAKING_EVENTS:
        return HookResult()
    return HookResult(context=_inline_context(event, text))


def observe_body(
    event: HookEvent, data: dict[str, Any], harness: str, fallback_project: str
) -> dict[str, Any]:
    """The /observe request for one hook event."""
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise HookInputError("hook input has no session_id")
    cwd = data.get("cwd")
    project = Path(cwd).name if isinstance(cwd, str) and cwd else fallback_project
    record = _record(event, data, harness, project, session_id)
    return {
        "harness": harness,
        "session_id": session_id,
        "event": event.value,
        "payload": {"record": record},
    }


def _parsed(stdin_text: str) -> dict[str, Any]:
    try:
        data = json.loads(stdin_text)
    except ValueError as exc:
        raise HookInputError(f"hook input is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise HookInputError("hook input must be a JSON object")
    return data


def _record(
    event: HookEvent, data: dict[str, Any], harness: str, project: str, session_id: str
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "harness": harness,
        "project": project,
        "session_id": session_id,
        # Arrival order: wall-clock ms, since every hook call is a fresh process.
        "step": time.time_ns() // 1_000_000,
        "provenance": {
            "dataset": DATASET_PREFIX + harness,
            "license": LIVE_LICENSE,
            "spark_safe": False,
        },
        "files": [],
    }
    return base | _shaped(event, data)


def _shaped(event: HookEvent, data: dict[str, Any]) -> dict[str, Any]:
    if event is HookEvent.USER_PROMPT_SUBMIT:
        return {"kind": "user_turn", "raw": str(data.get("prompt", ""))}
    if event is HookEvent.SESSION_START:
        return {"kind": "user_turn", "raw": f"session started ({data.get('source', 'startup')})"}
    if event is HookEvent.PRE_LLM_CALL:
        count = len(data["messages"]) if isinstance(data.get("messages"), list) else 0
        return {"kind": "agent_turn", "raw": f"model call over {count} messages"}
    return _tool_record(event, data)


def _tool_record(event: HookEvent, data: dict[str, Any]) -> dict[str, Any]:
    tool = str(data.get("tool_name", ""))
    given = data.get("tool_input")
    arguments: dict[str, Any] = given if isinstance(given, dict) else {}
    raw = json.dumps(data.get("tool_response", data.get("error", "")))
    if tool in _SHELL_TOOLS:
        command = str(arguments.get("command", ""))
        return {
            "kind": "command",
            "raw": raw,
            "command": command,
            "exit_code": _exit_code(data.get("tool_response"), event),
        }
    path = arguments.get("file_path") or arguments.get("path")
    files = [path] if isinstance(path, str) else []
    if tool in _EDIT_TOOLS:
        return {"kind": "edit", "raw": raw, "files": files}
    if tool == "Read":
        return {"kind": "read", "raw": raw, "files": files}
    return {"kind": "tool_result", "raw": raw, "files": files}


def _exit_code(response: Any, event: HookEvent) -> int | None:
    """What the harness reported; a failure with no code is 1, a success is never assumed 0."""
    if isinstance(response, dict):
        for key in ("exit_code", "exitCode"):
            if isinstance(response.get(key), int):
                return int(response[key])
    return 1 if event is HookEvent.POST_TOOL_USE_FAILURE else None


def _worded(event: HookEvent, notes: list[str], style: NoteStyle) -> str:
    if event is HookEvent.POST_TOOL_USE and style is NoteStyle.FINDING:
        notes = [f"Finding: {note}" for note in notes]
    return "\n".join(notes)


def _inline_context(event: HookEvent, text: str) -> str:
    output = {"hookEventName": event.value, "additionalContext": text}
    return json.dumps({"hookSpecificOutput": output})
