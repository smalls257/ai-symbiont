"""The repository gate: what the service may do for a repository, by what the developer said.

A repository nobody answered for is not observed, and its first session says once what symbiont
does and how to answer. The gate also keeps a silenced kind of trouble silent, lets the
exact-repeat rule speak once per lesson per session, and makes the nightly announcement once.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.core.repeat import RepeatNote, repeat_note
from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import Signature
from symbiont.records.schema import Record
from symbiont.service.nightly import NightlyJudges
from symbiont.store.repos import RepoRegistry, RepoStance

SESSION_START = "SessionStart"
ONBOARDING = (
    "symbiont is installed but not switched on for this repository. It reads your coding-agent "
    "history to warn you about mistakes you have made before, and everything stays on this "
    "computer. Until you answer, nothing from this repository is stored. "
    "To switch it on, run `symbiont repo allow`; to also learn from this repository's past "
    "Claude Code and Muse Code sessions, run `symbiont repo mine` afterwards. "
    "To keep it off here, run `symbiont repo decline`."
)
NIGHTLY_LIVE = (
    "symbiont finished its first night of learning from this repository's history. From now on "
    "it checks a note against what it learned here before showing it."
)


@dataclass(frozen=True)
class Door:
    """Whether the service may observe, and what to tell the developer directly either way."""

    may_observe: bool
    announce: tuple[str, ...] = ()


class RepoGate:
    """Decides, per repository, what the service may do; state lives in the registry file.

    Without a registry every repository is open and nothing is silenced.
    """

    def __init__(
        self, registry: RepoRegistry | None = None, nightly: NightlyJudges | None = None
    ) -> None:
        """Read answers from `registry`; `nightly` says when a repository's first night is done."""
        self.registry = registry
        self._nightly = nightly
        self._said: set[tuple[str, Signature]] = set()

    def door(self, project: str, event: str) -> Door:
        """Open for a repository that said yes; otherwise closed, asking once at session start."""
        if self.registry is None:
            return Door(may_observe=True)
        stance = self.registry.stance(project)
        if stance is RepoStance.GIVEN:
            return Door(may_observe=True, announce=self._nightly_news(project, event))
        asked_now = stance is None and event == SESSION_START
        return Door(may_observe=False, announce=(ONBOARDING,) if asked_now else ())

    def silenced(self, project: str, trouble: Signature | None) -> bool:
        """Whether the developer muted this kind of trouble in this repository."""
        if trouble is None or self.registry is None:
            return False
        return (trouble.signal.value, *trouble.key) in self.registry.muted(project)

    def repeat(
        self, session_id: str, record: Record, earlier: Sequence[Record], lessons: Sequence[Lesson]
    ) -> RepeatNote | None:
        """The exact-repeat note for `record`, unless muted or already said in this session."""
        found = repeat_note(record, earlier, lessons) if self.registry else None
        if found is None or self.silenced(record.project, found.lesson.pain_point.signature):
            return None
        signature = found.lesson.pain_point.signature
        if (session_id, signature) in self._said:
            return None
        self._said.add((session_id, signature))
        return found

    def status(self, project: str, lessons: Sequence[Lesson]) -> dict[str, object]:
        """What `/symbiont status` shows: the answer, the lesson count, silenced kinds, nightly."""
        stance = self.registry.stance(project) if self.registry else RepoStance.GIVEN
        return {
            "project": project,
            "repo": "unasked" if stance is None else stance.value,
            "lessons": len(lessons),
            "muted": len(self.registry.muted(project)) if self.registry else 0,
            "nightly": self._nightly is not None and self._nightly.has_record(project),
        }

    def _nightly_news(self, project: str, event: str) -> tuple[str, ...]:
        """The one-time announcement that the repository's nightly training is live."""
        if self._nightly is None or self.registry is None or event != SESSION_START:
            return ()
        if not self._nightly.has_record(project) or self.registry.nightly_announced(project):
            return ()
        self.registry.announce_nightly(project)
        return (NIGHTLY_LIVE,)
