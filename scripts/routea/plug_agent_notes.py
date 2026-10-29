"""PLUG-AGENT-1 notes: one situation per failed command, and each arm's way to pick its note.

A failed command (return code not 0) whose output names an error class becomes a situation in
round 3's wording; each distinct (failed, error) gets at most one note per run. The judge arm asks
a loopback judge service; a judge that does not answer raises, never an arm without notes.
"""

import json
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse

from lessons import ERROR_CLASS, Lesson, error_line, shown_command
from plug_judge import JUDGE_SYSTEM, pair_prompt, shortlist
from plug_r3 import ranker_choices
from plug_situation import Item, lexical_rank

from symbiont.miner.commands import normalise_command

SHORTLIST = 10  # interface spec: the judge scores the ranker's top 10
RAG_LESSONS = 3  # interface spec: basic retrieval shows the top 3, always
JUDGE_TIMEOUT_S = 300


class NoteArm(StrEnum):
    """PLUG-AGENT-1's arms: five runs per task (none twice, the second is the A/A noise floor)."""

    NONE = "none"
    NONE_REPEAT = "none2"
    RAG = "rag"
    RANKER = "ranker"
    JUDGE = "judge"


SILENT_ARMS = frozenset({NoteArm.NONE, NoteArm.NONE_REPEAT})


class JudgeDownError(RuntimeError):
    """The judge service did not answer: the run stops rather than going on without notes."""


@dataclass(frozen=True)
class Failure:
    """A failed command in round 3's fields."""

    failed: str
    error: str
    program: str
    file: str

    def situation(self, repo: str) -> str:
        """Round 3's situation wording (`plug_situation.situation_of`)."""
        return f"Ran `{self.failed}` in {repo} (file {self.file}). It failed: {self.error}"

    def key(self) -> tuple[str, str]:
        """(error class, program): the repeated-known-mistake key."""
        found = ERROR_CLASS.search(self.error)
        return (found.group(1) if found else "", self.program)


def failure_of(command: str, returncode: int | None, output: str) -> Failure | None:
    """The failure a command shows, or None when it passed or names no error class."""
    if returncode in (0, None):
        return None
    error = error_line(output)
    if error is None:
        return None
    failed = shown_command(command)
    program, target = normalise_command(failed)
    return Failure(failed, error, program, target)


Scorer = Callable[[list[dict[str, str]]], list[float]]


def judge_client(url: str) -> Scorer:
    """P(yes) per pair from the loopback judge; raises JudgeDownError on any failure."""
    if urlparse(url).hostname not in ("127.0.0.1", "localhost"):
        raise ValueError(f"the judge must be a loopback service, not {url}")

    def score(pairs: list[dict[str, str]]) -> list[float]:
        body = json.dumps({"pairs": pairs}).encode()
        request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=JUDGE_TIMEOUT_S) as reply:  # noqa: S310 loopback checked
                found = json.loads(reply.read())["p_yes"]
        except (OSError, ValueError, KeyError) as error:
            raise JudgeDownError(
                f"judge at {url} did not answer: {type(error).__name__}"
            ) from error
        if len(found) != len(pairs):
            raise JudgeDownError(f"judge returned {len(found)} scores for {len(pairs)} pairs")
        return [float(p) for p in found]

    return score


@dataclass
class NoteSource:
    """One run's notes: the arm, the task's store and thresholds, and what it showed when."""

    arm: NoteArm
    repo: str
    store: Sequence[Lesson]
    ranker_threshold: float
    judge_threshold: float
    judge: Scorer | None = None
    seen: set[tuple[str, str]] = field(default_factory=set)
    events: list[dict] = field(default_factory=list)

    def note_for(self, step: int, failure: Failure) -> str | None:
        """The note text for this failure, or None (silence, a repeat, or the none arm)."""
        if self.arm in SILENT_ARMS or (failure.failed, failure.error) in self.seen:
            return None
        self.seen.add((failure.failed, failure.error))
        item = Item(f"step{step}", failure.situation(self.repo), tuple(self.store), None)
        chosen, top = self._choose(item)
        self.events.append(
            {"step": step, "lessons": [lesson.lesson_id for lesson in chosen], "top": top}
        )
        return "\n".join(lesson.text() for lesson in chosen) or None

    def _choose(self, item: Item) -> tuple[list[Lesson], float | None]:
        if self.arm is NoteArm.RAG:
            return lexical_rank(item)[:RAG_LESSONS], None
        if self.arm is NoteArm.RANKER:
            (choice,) = ranker_choices([item], self.ranker_threshold)
            return _by_id(item, choice.lesson_id), choice.score
        return self._judged(item)

    def _judged(self, item: Item) -> tuple[list[Lesson], float | None]:
        if self.judge is None:
            raise JudgeDownError("the judge arm has no judge service")
        shortlisted = shortlist(item, SHORTLIST)
        pairs = [
            {"system": JUDGE_SYSTEM, "prompt": pair_prompt(item.situation, lesson)}
            for lesson in shortlisted
        ]
        scores = self.judge(pairs)
        best, lesson = max(zip(scores, shortlisted, strict=True), key=lambda pair: pair[0])
        return ([lesson] if best >= self.judge_threshold else []), best


def _by_id(item: Item, lesson_id: str | None) -> list[Lesson]:
    return [lesson for lesson in item.prompt_lessons if lesson.lesson_id == lesson_id]


def known_mistake(failure: Failure, store: Sequence[Lesson]) -> bool:
    """The failure's (error class, program) matches a lesson's; an empty part never matches."""
    error_class, program = failure.key()
    if not error_class or not program:
        return False
    return (error_class, program) in {(lesson.error_class, lesson.program) for lesson in store}
