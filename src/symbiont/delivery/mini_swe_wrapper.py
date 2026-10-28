"""Wraps a mini-SWE-agent environment so its observations carry the service's notes.

Composes any object with mini-SWE-agent's environment interface, `execute(action, cwd, *,
timeout) -> {"output", "returncode", ...}`; it never imports `minisweagent`. A service that is
down must be audible, so offline appends a visible note instead of nothing.

Everything the wrapper adds starts with NOTE_TAG on its own line, so the miner can skip our
own output instead of learning from it.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from symbiont.delivery.hooks import HookEvent, observe_body, offline_note
from symbiont.delivery.recall import (
    ServiceOfflineError,
    ServiceRefusedError,
    ServiceReplyError,
    call_service,
    recall_answer,
)

NOTE_TAG = "[symbiont]"
HARNESS = "mini_swe_agent"
RECALL_USAGE = 'usage: symbiont recall "<question>"'
_RECALL_COMMAND = re.compile(r"[ \t]*symbiont[ \t]+recall(?:[ \t]+(.*))?")
_SERVICE_FAILURES = (ServiceOfflineError, ServiceRefusedError, ServiceReplyError)


class WrapMode(StrEnum):
    """PLAIN is the floor arm: nothing appended, nothing intercepted."""

    PLAIN = "plain"
    NOTES = "notes"


@dataclass(frozen=True)
class WrapSettings:
    """One run's wiring: arm, service port, and the session and project the notes belong to."""

    mode: WrapMode
    port: int
    session_id: str
    project: str

    def __post_init__(self) -> None:
        """Normalize the arm to a WrapMode."""
        # A raw "plain" string must reach the floor arm, and a typo must raise, not run notes.
        object.__setattr__(self, "mode", WrapMode(self.mode))


def tagged(text: str) -> str:
    """`text` under the tag line, so readers can tell it is not the harness's own output."""
    return f"{NOTE_TAG}\n{text}"


def is_tagged(text: str) -> bool:
    """True when `text` contains a line the wrapper added."""
    return any(line.strip() == NOTE_TAG for line in text.splitlines())


def recall_question(command: str) -> str | None:
    """The question of a `symbiont recall ...` command, "" if it has none, None for any other."""
    found = _RECALL_COMMAND.fullmatch(command)
    if found is None:
        return None
    rest = (found.group(1) or "").strip()
    if _chains_commands(rest):
        return ""
    if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in "\"'":
        rest = rest[1:-1]
    return rest


def _chains_commands(text: str) -> bool:
    """True when `&&`, `||`, `;` or `|` appears outside quotes: the rest must not be dropped."""
    quote = ""
    for char in text:
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char in "&|;":
            return True
    return False


class NotedEnvironment:
    """The inner environment, plus notes on each observation and `symbiont recall` answered here."""

    def __init__(self, inner: Any, settings: WrapSettings) -> None:
        self._inner = inner
        self._settings = settings

    def __getattr__(self, name: str) -> Any:
        """Everything else (config, cleanup, template vars) is the inner environment's."""
        if name == "_inner":
            raise AttributeError(name)
        return getattr(self._inner, name)

    def serialize(self) -> dict[str, Any]:
        """The inner environment's record, plus which arm this run was."""
        record: dict[str, Any] = self._inner.serialize()
        wrap = {"mode": self._settings.mode.value, "harness": HARNESS}
        config = {**record.get("info", {}).get("config", {}), "symbiont_wrap": wrap}
        return {**record, "info": {**record.get("info", {}), "config": config}}

    def execute(
        self, action: dict[str, Any], cwd: str = "", *, timeout: int | None = None
    ) -> dict[str, Any]:
        """The inner result with notes appended.

        A Submitted raised inside passes through unobserved, so the final step is not mined.
        """
        command = str(action.get("command", ""))
        if self._settings.mode is WrapMode.PLAIN:
            plain: dict[str, Any] = self._inner.execute(action, cwd, timeout=timeout)
            return plain
        question = recall_question(command)
        if question is not None:
            return self._recall_result(question)
        result: dict[str, Any] = self._inner.execute(action, cwd, timeout=timeout)
        extra = self._notes_for(command, result)
        if extra:
            result = result | {"output": f"{result.get('output', '')}\n{tagged(extra)}"}
        return result

    def _recall_result(self, question: str) -> dict[str, Any]:
        if not question.strip():
            return _local_result(RECALL_USAGE, returncode=2)
        try:
            answer = recall_answer(question, self._settings.project, self._settings.port)
        except ServiceOfflineError as offline:
            return _local_result(offline_note(offline), returncode=0)
        except _SERVICE_FAILURES as failure:
            return _local_result(f"symbiont recall failed: {failure}", returncode=1)
        return _local_result(answer, returncode=0)

    def _notes_for(self, command: str, result: dict[str, Any]) -> str:
        data = {
            "session_id": self._settings.session_id,
            "cwd": self._settings.project,
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {
                "stdout": result.get("output", ""),
                "exit_code": result.get("returncode"),
            },
        }
        body = observe_body(HookEvent.POST_TOOL_USE, data, HARNESS, self._settings.project)
        try:
            notes = call_service("/observe", body, self._settings.port).get("notes")
        except ServiceOfflineError as offline:
            return offline_note(offline)
        except _SERVICE_FAILURES as failure:
            return f"symbiont notes unavailable: {failure}"
        if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
            return "symbiont notes unavailable: the service sent notes that are not sentences"
        return "\n".join(notes)


def _local_result(text: str, returncode: int) -> dict[str, Any]:
    return {"output": tagged(text), "returncode": returncode, "exception_info": ""}
