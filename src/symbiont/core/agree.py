"""The agree rule: speak only when a lexical ranker and a trained judge both pick the lesson.

Plug round 4's frozen rules (prereg/2026-10-29-plug-round4-DRAFT.md, results/plug-r4-selection*)
Pure: the judge is a callable passed in; no network here.
"""

import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from symbiont.core.notes import render_lesson
from symbiont.miner.lessons import Lesson


@dataclass(frozen=True)
class Bars:
    """The two cuts a rule frozen before scoring: ranker score and judge P(yes), both inclusive."""

    ranker_min_score: float
    judge_min_p_yes: float


# results/plug-r4-selection.json: rule "idf>=10.0", threshold 0.96 on the mean of three seeds.
AGREE = Bars(ranker_min_score=10.0, judge_min_p_yes=0.96)
# results/plug-r4-selection-nightly.json: rule "idf>=0.0" (no ranker cut), threshold 0.98.
NIGHTLY = Bars(ranker_min_score=0.0, judge_min_p_yes=0.98)
RANKER_MIN_SCORE = AGREE.ranker_min_score
JUDGE_MIN_P_YES = AGREE.judge_min_p_yes
JUDGE_SEEDS = 3
JUDGE_SYSTEM = (
    "You decide whether one stored lesson applies to what a coding agent is doing now. "
    "Answer yes or no."
)
_WORD = re.compile(r"[a-z0-9_]{2,}")


class Verdict(StrEnum):
    """Why the rule spoke or stayed silent; logged, never shown to the model."""

    AGREED = "agreed"
    RANKER_TOO_LOW = "ranker_too_low"
    JUDGE_TOO_LOW = "judge_too_low"
    NO_LESSONS = "no_lessons"


@dataclass(frozen=True)
class Agreement:
    """The rule's outcome: the lesson and its verbatim note when agreed, else neither."""

    verdict: Verdict
    lesson: Lesson | None
    note: str | None
    ranker_score: float
    judge_p_yes: float | None


JudgeScore = Callable[[str], float]  # judge prompt -> mean P(yes); raises when it cannot answer


def judge_prompt(question: str, lesson: Lesson) -> str:
    """The judge's question for a situation and one lesson (round 3's pair layout)."""
    return f"Situation:\n{question}\n\nLesson:\n{render_lesson(lesson)}\n\nDoes this lesson apply?"


def ranker_scores(question: str, lessons: Sequence[Lesson]) -> list[float]:
    """Each lesson's inverse-document-frequency overlap with the question, in lesson order."""
    docs = [_words(_lesson_text(lesson)) for lesson in lessons]
    frequency = Counter(word for doc in docs for word in doc)
    wanted = _words(question)
    return [sum(math.log(len(docs) / frequency[word]) for word in doc & wanted) for doc in docs]


def agree(
    question: str, lessons: Sequence[Lesson], judge: JudgeScore, bars: Bars = AGREE
) -> Agreement:
    """The ranker's top lesson if ranker and judge clear `bars`; a silent judge raises."""
    if not lessons:
        return Agreement(Verdict.NO_LESSONS, None, None, 0.0, None)
    scores = ranker_scores(question, lessons)
    best = max(range(len(lessons)), key=lambda index: (scores[index], -index))
    top, score = lessons[best], scores[best]
    if score < bars.ranker_min_score:
        return Agreement(Verdict.RANKER_TOO_LOW, None, None, score, None)
    p_yes = judge(judge_prompt(question, top))
    if p_yes < bars.judge_min_p_yes:
        return Agreement(Verdict.JUDGE_TOO_LOW, None, None, score, p_yes)
    return Agreement(Verdict.AGREED, top, render_lesson(top), score, p_yes)


def _lesson_text(lesson: Lesson) -> str:
    """What the ranker reads of a lesson: its trouble (command and error line) and its quote."""
    return " ".join([*lesson.pain_point.signature.key, lesson.quote])


def _words(text: str) -> set[str]:
    """Lowercase words of a text."""
    return set(_WORD.findall(text.lower()))
