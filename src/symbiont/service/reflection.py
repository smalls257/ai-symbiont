"""Session-end reflection: ask the session's own model what it learned, once, in a consented repo.

symbiont only mines visible struggle, so a session that solved a hard task cleanly leaves nothing
behind and what the model understood is lost. This asks the model that did the work; symbiont
makes no model call. Every refusal to ask carries its reason, so an empty reply is never mistaken
for "nothing to reflect on".
"""

from typing import Any

from symbiont.service.repo_gate import RepoGate
from symbiont.service.request_shapes import BadRequestError, require_keys
from symbiont.store.reflections import ReflectionLedger
from symbiont.store.repos import RepoRegistry, RepoStance

REFLECTION_LABEL = "from reflection"
REFLECT_KEYS = frozenset({"project", "session_id", "harness"})
REFLECTION_QUESTION = (
    "This is symbiont's end-of-session reflection. It is for you to answer from the work you "
    "just did, not a question for the developer: do not ask them anything. "
    "In one or two plain sentences each, what non-obvious thing about this "
    "repository would you tell a teammate before they work on this area next time? Name the "
    "files or areas. Only things that were not obvious from the docs. If there is nothing, "
    "answer 'nothing' and call no tool. Otherwise call symbiont_add_lessons once, with one item "
    f'per thing: {{text_in_plain_words, kind: "rule" (what to do) or "mistake" (a trap), files, '
    f'source_label: "{REFLECTION_LABEL}", applies_to: {{terms, areas}}}}. Then end your reply '
    "with one short line saying what you saved."
)


class ReflectionDesk:
    """Decides whether a finishing session is asked to reflect; the guard survives restarts."""

    def __init__(
        self, registry: RepoRegistry | None, ledger: ReflectionLedger, gate: RepoGate
    ) -> None:
        """Consent from `registry`, the once-only guard from `ledger`, the work seen by `gate`."""
        self._registry = registry
        self._ledger = ledger
        self._gate = gate

    def ask(self, request: dict[str, Any]) -> dict[str, Any]:
        """`{"ask": question}`, or `{"ask": "", "why_not": reason}`; marks the session as asked."""
        require_keys(request, REFLECT_KEYS, REFLECT_KEYS)
        project, session_id = request["project"], request["session_id"]
        if not (isinstance(project, str) and isinstance(session_id, str) and session_id):
            raise BadRequestError("project and session_id must be text")
        registry = self._registry
        if registry is None:
            return _declined("no repository registry, so there is no consent to rest on")
        if registry.stance(project) is not RepoStance.GIVEN:
            return _declined(f"symbiont is not switched on for {project}")
        if self._ledger.asked(project, session_id):
            return _declined("this session was already asked to reflect")
        if not self._gate.edited_in(session_id):
            return _declined("this session changed no file, so there is nothing to reflect on")
        self._ledger.mark_asked(project, session_id)
        return {"ask": REFLECTION_QUESTION}


def _declined(reason: str) -> dict[str, Any]:
    """The reply for a session that is not asked; the reason keeps silence from looking broken."""
    return {"ask": "", "why_not": reason}
