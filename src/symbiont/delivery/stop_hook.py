"""The Stop hook: hold a finish while a check is red, else ask the model to reflect once.

`/stop/guard` is asked first and may hold the stop; only a stop it lets through reaches the
reflection ask. The service says whether this Stop ends the reflection turn (Muse Code sends
`stop_hook_active` on every Stop after a block, so the flag is forwarded, not trusted), and it
bounds the holds, so nothing loops.
"""

import json
from pathlib import Path
from typing import Any

from symbiont.delivery.headline import MAX_HEADLINE_CHARS
from symbiont.delivery.hooks import (
    HookInputError,
    HookResult,
    HookSettings,
    NoteVisibility,
    ServiceCall,
    offline_note,
    parsed_input,
)
from symbiont.delivery.recall import ServiceOfflineError, ServiceReplyError, call_service


def run_stop(
    stdin_text: str, settings: HookSettings, call: ServiceCall | None = None
) -> HookResult:
    """What to print at Stop: a block for a red check, a block asking to reflect, or nothing."""
    data = parsed_input(stdin_text)
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise HookInputError("hook input has no session_id")
    cwd = data.get("cwd")
    project = Path(cwd).name if isinstance(cwd, str) and cwd else settings.fallback_project
    body: dict[str, object] = {
        "project": project,
        "session_id": session_id,
        "harness": settings.harness,
    }
    active = bool(data.get("stop_hook_active"))
    send = call or call_service
    try:
        guard = send("/stop/guard", {**body, "stop_hook_active": active}, settings.port)
        held = _red_check_block(guard, settings)
        if held:
            return HookResult(context=held)
        reflection_turn = guard.get("reflecting") is True
        route = "/reflect/finished" if reflection_turn else "/reflect"
        reply = send(route, body, settings.port)
    except ServiceOfflineError as offline:
        return HookResult(context=json.dumps({"systemMessage": offline_note(offline)}))
    if reflection_turn:
        return HookResult()
    return HookResult(context=_reflection_request(reply))


def _red_check_block(guard: dict[str, Any], settings: HookSettings) -> str:
    """The host's stop-and-continue instruction for a red check; empty when the guard let go.

    The developer reads a one-line status as well unless the install is model-only.
    """
    reason = guard.get("block")
    if not isinstance(reason, str):
        raise ServiceReplyError("the local service sent a stop-guard reason that is not text")
    if not reason:
        return ""
    held: dict[str, Any] = {"decision": "block", "reason": reason}
    if settings.visibility is NoteVisibility.ALSO_DEVELOPER:
        held["systemMessage"] = _status_line(guard.get("check"))
    return json.dumps(held)


def _status_line(check: object) -> str:
    """One short line for the status bar: what is red, so the developer sees why the stop held."""
    name = check if isinstance(check, str) and check else "a check"
    return f"symbiont · the last run of `{name}` failed; holding the finish"[:MAX_HEADLINE_CHARS]


def _reflection_request(reply: dict[str, Any]) -> str:
    """The host's stop-and-continue instruction for the service's question; empty for no ask."""
    question = reply.get("ask")
    if not isinstance(question, str):
        raise ServiceReplyError("the local service sent a reflection question that is not text")
    if not question:
        return ""
    return json.dumps({"decision": "block", "reason": question})
