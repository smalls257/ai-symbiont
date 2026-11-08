"""Standing rules: candidates out, the model's confirmed rules in.

The developer's own messages that may state a rule go to their session model, which merges
the ones that say the same thing and drops questions and one-off requests. symbiont makes no
model call. Dataset history is refused and barred harnesses are left out, as for session
candidates, so no candidate is a silent filter of private text.
"""

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from symbiont.miner.stated_rule import Ref, StatedRule, StatedRuleError, stated_rule_from
from symbiont.service.curation_routes import CurationRoutes, items_of, running_harness
from symbiont.service.request_shapes import BadRequestError
from symbiont.service.rule_candidates import CandidateLike, offered, waiting_candidates
from symbiont.service.summary_routes import SummaryRoutes
from symbiont.store.local import Store

RULES_RESEND = (
    "Expected per rule: rule (one line, at most 120 characters, an instruction in plain words), "
    "scope (repo|area), area (a path, when scope is area), refs [[session_id, step]] from the "
    "candidates, dropped [[session_id, step]] of candidates that are not rules. Fix it and "
    "resend the SAME rules."
)


class RuleRoutes:
    """Rule candidates out, confirmed rules in. Each method is one route."""

    def __init__(
        self,
        curation: CurationRoutes,
        summaries: SummaryRoutes,
        store: Store,
        mined_candidates: Callable[[str], Sequence[CandidateLike]],
    ) -> None:
        """Share the consent gate and readable-history rule; `mined_candidates(project)` reads."""
        self._curation = curation
        self._summaries = summaries
        self._store = store
        self._mined = mined_candidates

    def routes(self) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        """The route names the service exposes, each taking a request and returning a body."""
        return {"rules/candidates": self.rule_candidates, "rules/save": self.save_rules}

    def rule_candidates(self, request: dict[str, Any]) -> dict[str, Any]:
        """Up to 80 uncovered candidates; dataset history is refused."""
        project = self._curation.allowed_project(request, {"project", "running_in"})
        waiting, blocked = self._waiting(project, request)
        started = {f.session_id: f.started for f in self._store.mined.session_facts(project)}
        shown, remaining = offered(waiting, started)
        return {"candidates": shown, "remaining": remaining, "not_shown": blocked}

    def save_rules(self, request: dict[str, Any]) -> dict[str, Any]:
        """Keep the rules; an unknown ref or a malformed rule refuses the whole call."""
        project = self._curation.allowed_project(request, {"project", "running_in", "rules"})
        items = items_of(request.get("rules"), "rules")
        try:
            parsed = [stated_rule_from(item) for item in items]
            rules, dropped = [rule for rule, _ in parsed], [r for _, d in parsed for r in d]
            self._require_offered(project, request, rules, dropped)
        except (StatedRuleError, BadRequestError) as error:
            raise BadRequestError(f"{error}. {RULES_RESEND}") from error
        self._store.review.rules.save(project, rules, dropped, date.today())
        return {"saved": len(rules), "dropped": len(set(dropped))}

    def _waiting(
        self, project: str, request: dict[str, Any]
    ) -> tuple[list[CandidateLike], list[str]]:
        withheld = self._summaries.withheld_datasets(project)
        if withheld:
            raise BadRequestError("; ".join(withheld))
        sessions, blocked = self._summaries.readable_sessions(project, running_harness(request))
        readable = frozenset(s[0].session_id for s in sessions)
        covered = self._store.review.rules.covered(project)
        return waiting_candidates(self._mined(project), readable, covered), blocked

    def _require_offered(
        self, project: str, request: dict[str, Any], rules: list[StatedRule], dropped: list[Ref]
    ) -> None:
        waiting, _ = self._waiting(project, request)
        known = {(c.session_id, c.step) for c in waiting}
        used = [ref for rule in rules for ref in rule.refs] + dropped
        unknown = sorted({ref for ref in used if ref not in known})
        if unknown:
            raise BadRequestError(
                "no candidate " + ", ".join(f"[{sid!r}, {step}]" for sid, step in unknown)
            )
        keys = [rule.key for rule in rules]
        repeated = sorted({k for k in keys if keys.count(k) > 1})
        if repeated:
            raise BadRequestError(f"more than one rule for {', '.join(repeated)}")
