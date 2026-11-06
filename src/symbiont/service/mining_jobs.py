"""Mining as a tracked job: the service runs it in the background and answers how far it got.

A mining run over hundreds of logs used to be silent. Now every run has a state the terminal and
the dashboard both read (`running`, `done`, `failed`), and a failure keeps its reason instead of
leaving an empty dashboard. The job holds counts and short titles only, never log text beyond the
one-line description of a kind of trouble.
"""

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from symbiont.core.notes import happened
from symbiont.miner.lessons import Lesson
from symbiont.store.held_back import MiningOutcome

log = logging.getLogger("symbiont.service")
RECENT_TITLES = 8
TITLE_CHARS = 90


class NoMiningJobError(LookupError):
    """A progress question about a project whose mining never ran in this service."""


class MiningState(StrEnum):
    """Where a mining job is."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class MiningProgress:
    """What a poller sees: counts so far, the newest kinds of trouble, and why it failed."""

    state: MiningState
    sessions_read: int = 0
    sessions_total: int = 0
    pain_points: int = 0
    fixes_paired: int = 0
    lessons: int = 0
    recent: tuple[str, ...] = ()
    error: str | None = None
    # Groups held back per reason (`HoldReason` value -> count) once the run is done.
    held_back: Mapping[str, int] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        """The route's answer."""
        return {
            "state": self.state.value,
            "sessions_read": self.sessions_read,
            "sessions_total": self.sessions_total,
            "pain_points": self.pain_points,
            "fixes_paired": self.fixes_paired,
            "lessons": self.lessons,
            "recent": list(self.recent),
            "error": self.error,
            "held_back": dict(self.held_back),
        }


# A job body: it calls the given function after each log with that log's preview lessons and
# returns the final outcome (kept lessons and what was held back); it raises when it cannot finish.
MiningWork = Callable[[Callable[[list[Lesson]], None]], MiningOutcome]
Finished = Callable[[MiningProgress], None]


def tally(lessons: list[Lesson], state: MiningState, read: int, total: int) -> MiningProgress:
    """The counts for `lessons`: distinct kinds of trouble, fixes found, lessons, newest titles."""
    titles = tuple(_title(lesson) for lesson in lessons)
    return MiningProgress(
        state,
        read,
        total,
        pain_points=len({lesson.pain_point.signature for lesson in lessons}),
        fixes_paired=sum(1 for lesson in lessons if lesson.resolution),
        lessons=len(lessons),
        recent=tuple(dict.fromkeys(reversed(titles)))[:RECENT_TITLES],
    )


def _title(lesson: Lesson) -> str:
    """One short line naming the trouble, in the dashboard's own words."""
    line = happened(lesson.pain_point.signature)
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1] + "…"


class MiningJobs:
    """One background job per project; progress is kept in memory for the dashboard to poll."""

    def __init__(self) -> None:
        """Start with no jobs."""
        self._lock = threading.Lock()
        self._progress: dict[str, MiningProgress] = {}
        self._threads: dict[str, threading.Thread] = {}

    def progress(self, project: str) -> MiningProgress | None:
        """The latest progress of `project`'s job, or None when none has run since the start."""
        with self._lock:
            return self._progress.get(project)

    def start(self, project: str, total: int, work: MiningWork, finished: Finished) -> bool:
        """Run `work` in the background; False, starting nothing, when `project` is mining now."""
        with self._lock:
            current = self._progress.get(project)
            if current is not None and current.state is MiningState.RUNNING:
                return False
            self._progress[project] = MiningProgress(MiningState.RUNNING, 0, total)
            thread = threading.Thread(
                target=self._run, args=(project, total, work, finished), daemon=True
            )
            self._threads[project] = thread
        thread.start()
        return True

    def wait(self, project: str, timeout_s: float) -> None:
        """Block until `project`'s job ends; for tests and shutdown."""
        thread = self._threads.get(project)
        if thread is not None:
            thread.join(timeout_s)

    def _run(self, project: str, total: int, work: MiningWork, finished: Finished) -> None:
        """The job thread: preview after each log, then the final counts or the failure."""
        previews: list[Lesson] = []

        def after_log(preview: list[Lesson]) -> None:
            """Fold one log's lessons into the running preview and publish it."""
            previews.extend(preview)
            with self._lock:
                read = self._progress[project].sessions_read + 1
            self._publish(project, tally(previews, MiningState.RUNNING, read, total))

        try:
            outcome = work(after_log)
            end = replace(
                tally(outcome.kept, MiningState.DONE, total, total),
                held_back={reason.value: count for reason, count in outcome.held.items()},
            )
        except Exception as failed:  # a thread must report any failure, not die quietly
            log.exception("mining %s failed", project)
            with self._lock:
                last = self._progress[project]
            end = replace(last, state=MiningState.FAILED, error=_reason(failed))
        self._publish(project, end)
        finished(end)

    def _publish(self, project: str, progress: MiningProgress) -> None:
        """Make `progress` what pollers see."""
        with self._lock:
            self._progress[project] = progress


def _reason(failed: Exception) -> str:
    """Why a job failed, in a sentence a person can act on."""
    return str(failed) or f"{type(failed).__name__}; see the service log"
