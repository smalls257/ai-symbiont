"""Session-end reflection: ask the session's own model what it learned, once, in a consented repo.

symbiont makes no model call. Every refusal to ask carries its reason, and every decision and
outcome is an event: a model may read the question and end its turn without calling the tool,
and that must not look like "never asked".
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from symbiont.service.events import Call, EventLog
from symbiont.service.repo_gate import RepoGate
from symbiont.service.request_shapes import BadRequestError, require_keys
from symbiont.store.reflections import ReflectionLedger
from symbiont.store.repos import RepoRegistry, RepoStance

REFLECTION_LABEL = "from reflection"
REFLECT_KEYS = frozenset({"project", "session_id", "harness"})
STOP_HOOK = "Stop"
REFLECTION_QUESTION = (
    "This is symbiont's end-of-session reflection. It is for you to answer from the work you "
    "just did, not a question for the developer: do not ask them anything. "
    "In one or two plain sentences each, what non-obvious thing about this "
    "repository would you tell a teammate before they work on this area next time? Name the "
    "files or areas, and list in applies_to the terms (identifiers, error words) and areas "
    "(directories or modules) a later task would mention when this lesson matters. "
    "Only things that were not obvious from the docs. If there is nothing, "
    "answer 'nothing' and call no tool. Otherwise call symbiont_add_lessons once, with one item "
    f'per thing: {{text_in_plain_words, kind: "rule" (what to do) or "mistake" (a trap), files, '
    f'source_label: "{REFLECTION_LABEL}", applies_to: {{terms, areas}}}}. Then end your reply '
    "with one short line saying what you saved."
)


@dataclass(frozen=True)
class ReflectionSensors:
    """Where the desk's decisions are logged and how it counts lessons the model has saved."""

    events: EventLog
    # Reflection-labeled lessons a project holds; a rise across the turn means the model answered.
    saved_so_far: Callable[[str], int]


class ReflectionDesk:
    """Decides whether a finishing session is asked to reflect; the guard survives restarts."""

    def __init__(
        self,
        registry: RepoRegistry | None,
        ledger: ReflectionLedger,
        gate: RepoGate,
        sensors: ReflectionSensors,
    ) -> None:
        """Consent from `registry`, once-only from `ledger`, work seen by `gate`.

        Every decision and outcome goes to the sensors' event log; their lesson count tells
        whether the model answered.
        """
        self._registry = registry
        self._ledger = ledger
        self._gate = gate
        self._events = sensors.events
        self._saved_so_far = sensors.saved_so_far
        self._count_at_ask: dict[tuple[str, str], int] = {}

    def ask(self, request: dict[str, Any]) -> dict[str, Any]:
        """`{"ask": question}`, or `{"ask": "", "why_not": reason}`; marks the session as asked."""
        project, session_id = _identified(request)
        reply = self._decide(project, session_id)
        saved = self._saved_so_far(project)
        if reply["ask"]:
            self._count_at_ask[(project, session_id)] = saved
        fields = {"asked": bool(reply["ask"]), "why_not": reply.get("why_not", ""), "saved": saved}
        self._events.append_reflection(Call("reflect", STOP_HOOK, project), "decision", fields)
        return reply

    def finished(self, request: dict[str, Any]) -> dict[str, Any]:
        """Record how the reflection turn ended: lessons saved by it, or none (`saved` 0).

        `saved` is null when the service restarted after the ask, so the baseline is gone.
        """
        project, session_id = _identified(request)
        before = self._count_at_ask.pop((project, session_id), None)
        now = self._saved_so_far(project)
        saved = None if before is None else now - before
        self._events.append_reflection(
            Call("reflect/finished", STOP_HOOK, project), "outcome", {"saved": saved}
        )
        return {"saved": saved}

    def _decide(self, project: str, session_id: str) -> dict[str, Any]:
        """The reply for one Stop: the question, or the reason there is none."""
        registry = self._registry
        if registry is None:
            return _declined("no repository registry, so there is no consent to rest on")
        if registry.stance(project) is not RepoStance.GIVEN:
            return _declined(f"symbiont is not switched on for {project}")
        if self._ledger.asked(project, session_id):
            return _declined("this session was already asked to reflect")
        if not self._gate.reached_milestone(session_id):
            return _declined("no edit followed by a passing check yet, so no milestone")
        self._ledger.mark_asked(project, session_id)
        return {"ask": REFLECTION_QUESTION}


def _identified(request: dict[str, Any]) -> tuple[str, str]:
    """The project and session a reflection call is about; anything else is a bad request."""
    require_keys(request, REFLECT_KEYS, REFLECT_KEYS)
    project, session_id = request["project"], request["session_id"]
    if not (isinstance(project, str) and isinstance(session_id, str) and session_id):
        raise BadRequestError("project and session_id must be text")
    return project, session_id


def _declined(reason: str) -> dict[str, Any]:
    """The reply for a session that is not asked; the reason keeps silence from looking broken."""
    return {"ask": "", "why_not": reason}
