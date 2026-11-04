"""Per-repository nightly judges: the continuous loop's read side (plug round 4 nightly arm).

`<nightly-dir>/<project>/nightly.json` is written by `symbiont nightly` only after training exited
0: {"lessons_digest", "judge_url", "lesson_count", "trained_at", "backend"}. No record means no
first night yet and the agree rule applies (logged). A record for other lessons is stale and a
down server is offline; both raise (503) rather than silently change the rule.
"""

import hashlib
import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from symbiont.egress.client import Transport
from symbiont.miner.lessons import Lesson
from symbiont.miner.twins import merge_twins
from symbiont.service.judge_model import JudgeModel, JudgeOfflineError
from symbiont.service.judge_start import JudgeStart, Running, judge_start_from_json

log = logging.getLogger(__name__)
RECORD = "nightly.json"


class NightlyStaleError(JudgeOfflineError):
    """The repository's nightly adapter was trained on other lessons than the store holds now."""


def lessons_digest(lessons: Sequence[Lesson]) -> str:
    """A stable hash of which pain points the lessons come from (order-independent)."""
    refs = sorted(
        f"{ref[0]}:{ref[1]}" for lesson in lessons for ref in lesson.pain_point.record_refs
    )
    return hashlib.sha256("\n".join(refs).encode()).hexdigest()


class NightlyState(StrEnum):
    """Where a repository's nightly training stands, as `status` and the dashboard say it."""

    NEVER = "never"
    TRAINED = "trained"
    STALE = "stale"


@dataclass(frozen=True)
class NightlyReport:
    """The nightly state with what it rests on: how many lessons, trained when (ISO, UTC)."""

    state: NightlyState
    lessons: int | None = None
    trained_at: str | None = None
    # Why a record reads as stale when the lessons moved is obvious; an unreadable one is not.
    detail: str = ""

    def sentence(self) -> str:
        """The state in plain words for `symbiont status`."""
        if self.state is NightlyState.NEVER:
            return "checker not trained yet; run `symbiont nightly`"
        counted = "lessons" if self.lessons is None else f"{self.lessons} lessons"
        when = f" at {self.trained_at}" if self.trained_at else ""
        if self.state is NightlyState.TRAINED:
            return f"trained on {counted}{when}"
        reason = self.detail or "your lessons changed since"
        return f"stale: {reason}; last trained on {counted}{when} (run `symbiont nightly`)"


@dataclass(frozen=True)
class NightlyRecord:
    """What one successful night wrote: enough to tell later whether the lessons moved on."""

    lessons_digest: str
    judge_url: str
    lesson_count: int
    trained_at: str
    backend: str
    # How to start this repository's judge server again (`JudgeStart.as_json`); None on records
    # written before the service could revive it.
    judge_start: dict[str, object] | None = None


def write_record(root: Path, project: str, record: NightlyRecord) -> Path:
    """Write the project's record atomically, so a crash never leaves half a file.

    Call it only after training exited 0: a failed night must leave the older record, which then
    reads as stale. Returns the record's path.
    """
    target = root / project
    target.mkdir(parents=True, exist_ok=True)
    final = target / RECORD
    partial = target / (RECORD + ".partial")
    partial.write_text(json.dumps(asdict(record), indent=1) + "\n", encoding="utf-8")
    os.replace(partial, final)
    return final


def previous_judge_url(root: Path, project: str) -> str | None:
    """The judge URL of the project's last record, or None when it has none or it is unusable."""
    try:
        return str(json.loads((root / project / RECORD).read_text(encoding="utf-8"))["judge_url"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


@dataclass(frozen=True)
class NightlyJudges:
    """Where each repository's nightly record lives."""

    root: Path
    # None sends through urllib; tests pass a fake that never opens a socket.
    transport: Transport | None = None
    # Starts the judge server of a record again when a recall finds it down (None: only say so).
    revive: Callable[[JudgeStart, Path], Running] | None = None

    def has_record(self, project: str) -> bool:
        """Whether the project's first night has finished (its nightly record exists)."""
        return (self.root / project / RECORD).is_file()

    def report(self, project: str, lessons: Sequence[Lesson]) -> NightlyReport:
        """Never trained, trained on N lessons at T, or stale; reading it never raises."""
        path = self.root / project / RECORD
        if not path.is_file():
            return NightlyReport(NightlyState.NEVER)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            trained = record["lessons_digest"]
        except (OSError, ValueError, KeyError, TypeError) as unusable:
            return NightlyReport(NightlyState.STALE, detail=f"the record is unusable ({unusable})")
        count, when = record.get("lesson_count"), record.get("trained_at")
        state = (
            NightlyState.TRAINED
            if trained == lessons_digest(merge_twins(list(lessons)))
            else NightlyState.STALE
        )
        return NightlyReport(state, count if isinstance(count, int) else None, when)

    def start_for(self, project: str) -> JudgeStart | None:
        """How to start the project's judge server again, or None when its record does not say."""
        try:
            raw = json.loads((self.root / project / RECORD).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return judge_start_from_json(raw.get("judge_start")) if isinstance(raw, dict) else None

    def judge_for(self, project: str, lessons: Sequence[Lesson]) -> JudgeModel | None:
        """The project's nightly judge, or None before its first night (logged).

        Raises NightlyStaleError when the adapter was trained on other lessons, and
        JudgeOfflineError when the record is unreadable.
        """
        path = self.root / project / RECORD
        if not path.is_file():
            log.warning("recall for %s: no nightly adapter yet, using the agree rule", project)
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            trained, url = record["lessons_digest"], record["judge_url"]
        except (OSError, ValueError, KeyError, TypeError) as unusable:
            raise JudgeOfflineError(f"nightly record {path} is unusable: {unusable}") from unusable
        if trained != lessons_digest(lessons):
            raise NightlyStaleError(
                f"the nightly adapter for {project} is stale: run `symbiont nightly`"
            )
        return JudgeModel(url, self.transport)


@dataclass(frozen=True)
class RecallJudges:
    """The judges /recall may use: the three-seed first-night servers and the nightly records."""

    first_night: JudgeModel | None = None
    nightly: NightlyJudges | None = None
