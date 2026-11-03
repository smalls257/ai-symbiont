"""The Stop hook: at the end of a session, ask the session's own model to reflect once.

A Stop hook that blocks makes the host run one more turn, and that turn ends in another Stop.
The service marks a session as asked before it answers, and the host's own `stop_hook_active`
flag is honored here as well, so the reflection turn can never ask again.
The service decides consent and whether there is anything to reflect on; this is a thin client.
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
    if data.get("stop_hook_active"):
        return HookResult()
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
    try:
        reply = (call or call_service)("/reflect", body, settings.port)
    except ServiceOfflineError as offline:
        return HookResult(context=json.dumps({"systemMessage": offline_note(offline)}))
    return HookResult(context=_reflection_request(reply))


def _reflection_request(reply: dict[str, Any]) -> str:
    """The host's stop-and-continue instruction for the service's question; empty for no ask."""
    question = reply.get("ask")
    if not isinstance(question, str):
        raise ServiceReplyError("the local service sent a reflection question that is not text")
    if not question:
        return ""
    return json.dumps({"decision": "block", "reason": question})
