"""The Stop hook: at the end of a session, ask the session's own model to reflect once.

The service marks a session as asked before it answers, and the host's `stop_hook_active` flag
is honored too, so the reflection turn never asks again; that Stop still reports to the service,
which logs whether a lesson was saved. The service decides; this is a thin client.
"""

import json
from pathlib import Path
from typing import Any

from symbiont.delivery.hooks import (
    HookInputError,
    HookResult,
    HookSettings,
    ServiceCall,
    offline_note,
    parsed_input,
)
from symbiont.delivery.recall import ServiceOfflineError, ServiceReplyError, call_service


def run_stop(
    stdin_text: str, settings: HookSettings, call: ServiceCall | None = None
) -> HookResult:
    """What to print at Stop: a block asking for one reflection turn, or nothing."""
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
    reflection_turn = bool(data.get("stop_hook_active"))
    route = "/reflect/finished" if reflection_turn else "/reflect"
    try:
        reply = (call or call_service)(route, body, settings.port)
    except ServiceOfflineError as offline:
        return HookResult(context=json.dumps({"systemMessage": offline_note(offline)}))
    if reflection_turn:
        return HookResult()
    return HookResult(context=_reflection_request(reply))


def _reflection_request(reply: dict[str, Any]) -> str:
    """The host's stop-and-continue instruction for the service's question; empty for no ask."""
    question = reply.get("ask")
    if not isinstance(question, str):
        raise ServiceReplyError("the local service sent a reflection question that is not text")
    if not question:
        return ""
    return json.dumps({"decision": "block", "reason": question})
