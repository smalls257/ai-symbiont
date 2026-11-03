"""Harness hooks: forward one hook event to /observe and hand the notes back as context.

An offline service must be audible, not an empty note that reads as "nothing to warn
about", so offline prints a visible note and exits 0: the harness is never blocked.
"""

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from symbiont.delivery.recall import ServiceOfflineError, ServiceReplyError, call_service
from symbiont.records.output_failure import exit_code_with_output

DATASET_PREFIX = "live-"
LIVE_LICENSE = "local-session"


class HookEvent(StrEnum):
    """The harness events the hooks understand (day-1 G2 for Muse Code; Claude Code's docs)."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_LLM_CALL = "PreLLMCall"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    STOP = "Stop"


class NoteStyle(StrEnum):
    """How a PostToolUse note is worded: plain prose, or a finding in the tool result's voice."""

    PLAIN = "plain"
    FINDING = "finding"


class NoteVisibility(StrEnum):
    """Who reads a note: the model alone, or the developer on screen as well."""

    MODEL_ONLY = "model-only"
    ALSO_DEVELOPER = "also-developer"


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
    visibility: NoteVisibility = NoteVisibility.ALSO_DEVELOPER


class HookInputError(ValueError):
    """The harness sent hook input the hook cannot use; the message names the field."""


# PreLLMCall additionalContext was not seen in messages on echo (G2); it only observes.
# PostToolUseFailure additionalContext reaches the model on Muse Code too (measured in a session
# log: a developer-role context block).
_SPEAKING_EVERYWHERE = frozenset(
    {
        HookEvent.SESSION_START,
        HookEvent.USER_PROMPT_SUBMIT,
        HookEvent.POST_TOOL_USE,
        HookEvent.POST_TOOL_USE_FAILURE,
    }
)
CLAUDE_CODE = "claude_code"
MUSE_CODE = "muse_code"
AUTO = "auto"
# Muse Code sets this for every plugin hook it runs (measured with `muse plugins hook test`);
# Claude Code does not, so one plugin bundle can tell its two hosts apart without an argument.
MUSE_MARKER = "MUSE_PLUGIN_ROOT"
# Muse Code names its tools in snake_case (measured from live hook payloads: `bash`, `read_file`).
_EDIT_TOOLS = frozenset(
    {"Edit", "Write", "MultiEdit", "NotebookEdit", "edit_file", "write_file", "apply_patch"}
)
_SHELL_TOOLS = frozenset({"Bash", "shell", "bash", "exec_command"})
_READ_TOOLS = frozenset({"Read", "read_file"})


def resolve_harness(chosen: str, environ: Mapping[str, str]) -> str:
    """The harness a hook runs under: `auto` reads the host's environment, else as given."""
    if chosen != AUTO:
        return chosen
    return MUSE_CODE if MUSE_MARKER in environ else CLAUDE_CODE


def speaking_events(harness: str) -> frozenset[HookEvent]:
    """The events whose notes this harness takes as inline context (both do, as measured)."""
    return _SPEAKING_EVERYWHERE


def offline_note(reason: object) -> str:
    """The visible line that stands in for notes when the service cannot be reached."""
    return f"symbiont offline: {reason}"


ServiceCall = Callable[[str, dict[str, object], int], dict[str, Any]]


def run_hook(
    event: HookEvent, stdin_text: str, settings: HookSettings, call: ServiceCall | None = None
) -> HookResult:
    """What to print; raises HookInputError for unusable input.

    `call` is how the service is reached (default: as is); the plugin passes one that starts a
    down service.
    """
    data = parsed_input(stdin_text)
    body = observe_body(event, data, settings.harness, settings.fallback_project)
    try:
        reply = (call or call_service)("/observe", body, settings.port)
    except ServiceOfflineError as offline:
        note = offline_note(offline)
        if event in speaking_events(settings.harness):
            return HookResult(context=_inline_context(event, note, shown_to=note))
        return HookResult(warning=note)
    notes = reply.get("notes")
    if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
        raise ServiceReplyError("the local service sent notes that are not a list of sentences")
    told = _announcements(reply, dashboard_url(settings.port, body["payload"]["record"]["project"]))
    worded = _worded(event, notes, settings.style)
    text = "\n".join(filter(None, [worded, *told]))
    if not text or event not in speaking_events(settings.harness):
        return HookResult()
    shown_notes = [worded] if settings.visibility is NoteVisibility.ALSO_DEVELOPER else []
    seen = [*filter(None, shown_notes), *told]
    return HookResult(context=_inline_context(event, text, shown_to="\n".join(seen)))


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


def parsed_input(stdin_text: str) -> dict[str, Any]:
    """The hook's stdin as a JSON object; anything else raises HookInputError."""
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
    """The record the service stores for one hook event."""
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
    """The kind and raw text of a record, by event."""
    if event is HookEvent.USER_PROMPT_SUBMIT:
        return {"kind": "user_turn", "raw": str(data.get("prompt", ""))}
    if event is HookEvent.SESSION_START:
        return {"kind": "user_turn", "raw": f"session started ({data.get('source', 'startup')})"}
    if event is HookEvent.PRE_LLM_CALL:
        count = len(data["messages"]) if isinstance(data.get("messages"), list) else 0
        return {"kind": "agent_turn", "raw": f"model call over {count} messages"}
    return _tool_record(event, data)


def _tool_record(event: HookEvent, data: dict[str, Any]) -> dict[str, Any]:
    """A tool-call record; shell tools carry the command and its exit status."""
    tool = str(data.get("tool_name", ""))
    given = data.get("tool_input")
    arguments: dict[str, Any] = given if isinstance(given, dict) else {}
    given_response = data.get("tool_response")
    printed = _decoded_object(data.get("error") if given_response is None else given_response)
    raw = _output_text(printed if printed is not None else "")
    if tool in _SHELL_TOOLS:
        command = str(arguments.get("command", ""))
        return {
            "kind": "command",
            "raw": raw,
            "command": command,
            "exit_code": exit_code_with_output(command, raw, _exit_code(printed, event)),
        }
    path = arguments.get("file_path") or arguments.get("path")
    files = [path] if isinstance(path, str) else []
    if tool in _EDIT_TOOLS:
        return {"kind": "edit", "raw": raw, "files": files}
    if tool in _READ_TOOLS:
        return {"kind": "read", "raw": raw, "files": files}
    return {"kind": "tool_result", "raw": raw, "files": files}


def _decoded_object(response: Any) -> Any:
    """Muse Code sends shell results as JSON text (exit_code, output); open it, else keep text."""
    if not isinstance(response, str):
        return response
    try:
        opened = json.loads(response)
    except ValueError:
        return response
    return opened if isinstance(opened, dict) else response


def _output_text(response: Any) -> str:
    """What the tool printed, as the text a person would read.

    JSON-encoding it would write every newline as two characters glued to the next word, so the
    miner would never see an error class that starts a line.
    """
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        printed = [
            response[k] for k in ("stdout", "stderr", "output") if isinstance(response.get(k), str)
        ]
        if printed:
            return "\n".join(part for part in printed if part)
    return json.dumps(response)


def _exit_code(response: Any, event: HookEvent) -> int | None:
    """What the harness reported; a failure with no code is 1, a success is never assumed 0."""
    if isinstance(response, dict):
        for key in ("exit_code", "exitCode"):
            if isinstance(response.get(key), int):
                return int(response[key])
    return 1 if event is HookEvent.POST_TOOL_USE_FAILURE else None


def dashboard_url(port: int, project: str) -> str:
    """Where the local dashboard for `project` is served."""
    safe = "".join(
        char
        if char.isascii() and (char.isalnum() or char in "-._~")
        else "".join(f"%{b:02X}" for b in char.encode())
        for char in project
    )
    return f"http://127.0.0.1:{port}/dashboard?project={safe}"


def _announcements(reply: dict[str, Any], dashboard: str) -> list[str]:
    """What the service wants the developer to read directly, with the dashboard link filled in."""
    told = reply.get("announce", [])
    if not isinstance(told, list) or not all(isinstance(line, str) for line in told):
        raise ServiceReplyError("the local service sent an announcement that is not sentences")
    return [line.replace("{dashboard}", dashboard) for line in told]


def _worded(event: HookEvent, notes: list[str], style: NoteStyle) -> str:
    """Join notes into the hook's output text; post-tool notes may be prefixed `Finding:`."""
    if event is HookEvent.POST_TOOL_USE and style is NoteStyle.FINDING:
        notes = [f"Finding: {note}" for note in notes]
    return "\n".join(notes)


def _inline_context(event: HookEvent, text: str, shown_to: str = "") -> str:
    """Context for the model; `shown_to` also goes to the developer as a system message."""
    output = {"hookEventName": event.value, "additionalContext": text}
    reply: dict[str, Any] = {"hookSpecificOutput": output}
    if shown_to:
        reply["systemMessage"] = shown_to
    return json.dumps(reply)
