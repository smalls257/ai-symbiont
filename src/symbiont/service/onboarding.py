"""What the first sessions of a repository say to the developer and to the session's model.

Before an answer: what symbiont does and how to answer. After yes: one question (what should
symbiont pay attention to?), the dashboard link, and a request to review what rules found. The
session's own model does the reading and writing through the curation tools; symbiont calls none.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from symbiont.miner.lesson_context import AuthoredLesson, LessonContext
from symbiont.service.nightly import NightlyJudges
from symbiont.store.repos import Announced, RepoRegistry

SESSION_START = "SessionStart"
DASHBOARD_TOKEN = "{dashboard}"
ONBOARDING = (
    "symbiont is installed but not switched on for this repository. It reads your coding-agent "
    "history to warn you about mistakes you have made before, and everything stays on this "
    "computer. Until you answer, nothing from this repository is stored. "
    "To switch it on, run `symbiont repo allow`; to also learn from this repository's past "
    "Claude Code and Muse Code sessions, run `symbiont repo mine` afterwards; it opens the "
    "dashboard so you can watch it learn. "
    "If you also want it to find your past corrections, the model running this session will "
    "read short excerpts of past messages from this same tool's history, and nothing leaves "
    "this computer. To keep it off here, run `symbiont repo decline`."
)
NIGHTLY_LIVE = (
    "symbiont finished its first night of learning from this repository's history. From now on "
    "it checks a note against what it learned here before showing it."
)
FOCUS_QUESTION = (
    "Anything symbiont should pay attention to in this repository? Any notes, reports or lessons "
    "you already keep? Ask the developer, in your own words. Then call symbiont_set_focus with "
    "their answer, and symbiont_add_lessons for each rule or lesson they state or that you read "
    "from what they point you to. You may also call symbiont_correction_candidates to look for "
    "past messages where they corrected the agent."
)
DASHBOARD_LINK = f"symbiont's dashboard for this repository: {DASHBOARD_TOKEN}"


def _no_contexts(project: str) -> Mapping[str, LessonContext]:
    """No developer words."""
    return {}


def _no_written(project: str) -> list[AuthoredLesson]:
    """No written lessons."""
    return []


def _none(project: str) -> int:
    """Zero."""
    return 0


@dataclass(frozen=True)
class Lookups:
    """What the gate reads from the store: words, written lessons and counts, by repository."""

    contexts: Callable[[str], Mapping[str, LessonContext]] = _no_contexts
    written: Callable[[str], list[AuthoredLesson]] = _no_written
    pending_reviews: Callable[[str], int] = _none
    lesson_count: Callable[[str], int] = _none


@dataclass
class Announcements:
    """The notes a repository that said yes gets at session start, each until it is done."""

    registry: RepoRegistry
    lookups: Lookups
    nightly: NightlyJudges | None = None
    shown: set[str] = field(default_factory=set)

    def at_session_start(self, project: str) -> tuple[str, ...]:
        """The lines for this session start: nightly news once, the question, the link, reviews."""
        lines = [*self._nightly(project), *self._question(project), *self._link(project)]
        waiting = self.lookups.pending_reviews(project)
        if waiting and self.registry.focus(project) is not None:
            lines.append(_review_request(waiting))
        return tuple(lines)

    def _nightly(self, project: str) -> list[str]:
        """The one-time news that nightly training is live."""
        if self.nightly is None or not self.nightly.has_record(project):
            return []
        if self.registry.was_announced(project, Announced.NIGHTLY_LIVE):
            return []
        self.registry.announce(project, Announced.NIGHTLY_LIVE)
        return [NIGHTLY_LIVE]

    def _question(self, project: str) -> list[str]:
        """The up-front question, once per repository.

        Every headless session carried it otherwise and nudged the model into memory-shaped
        lesson writes after the repository was already onboarded (live sympy preflight).
        """
        if self.registry.focus(project) is not None or self.registry.was_announced(
            project, Announced.FOCUS_QUESTION
        ):
            return []
        self.registry.announce(project, Announced.FOCUS_QUESTION)
        return [FOCUS_QUESTION]

    def _link(self, project: str) -> list[str]:
        """The dashboard link, once the repository has lessons."""
        if self.registry.was_announced(
            project, Announced.DASHBOARD_LINK
        ) or not self.lookups.lesson_count(project):
            return []
        self.registry.announce(project, Announced.DASHBOARD_LINK)
        return [DASHBOARD_LINK]


def _review_request(waiting: int) -> str:
    """Ask the session's model to judge the pain points rules found."""
    return (
        f"{waiting} pain points found by rules are waiting for your judgment. Call "
        "symbiont_review_candidates, judge each as a mistake, expected or noise in plain words, "
        "then call symbiont_save_reviews."
    )
