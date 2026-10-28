"""Which lessons the sqlglot adapter learns, and which of the 11 pilot tasks each one serves.

Tier 1 lessons come from the task's own earlier solved run ("same bug, second run"). Tier 2 tasks'
own runs give none: the claim is that an earlier task's lesson solves them. An upstream fix that
changes an evaluation task's construct after that task was filed carries its future, so it is
dropped. Every drop is counted by reason. Pure: evidence and curated text in, lessons out.
"""

import dataclasses
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlglot_habits import habits
from sqlglot_lessons import (
    Lesson,
    LessonSource,
    Link,
    TaskEvidence,
    curated,
    own_failure,
    own_solve,
    pair,
)

_ID = "tobymao__sqlglot-"
# pilot-dispatch.md: Tier 1 is in band at a 50-step cap, Tier 2 failed 2 of 2 at a 75-step cap.
TIER1 = tuple(f"{_ID}{n}" for n in (1379, 1944, 1309, 2443, 2095, 2529, 2658))
TIER2 = tuple(f"{_ID}{n}" for n in (910, 3339, 3426, 3885))
EVAL_TASKS = TIER1 + TIER2


class Drop(StrEnum):
    """Why an attempted task gives no lesson."""

    NO_PLACE = "no-fix-place"  # no solved or gold patch resolves to a python construct
    TIER2_OWN = "tier2-own-runs"  # a Tier 2 task's own runs would void the capability claim
    LATER_SAME_PLACE = "later-fix-of-eval-construct"  # upstream fix from an eval task's future


@dataclass(frozen=True)
class Selection:
    """The chosen lessons and the count of every task left out, by reason."""

    lessons: list[Lesson]
    drops: Counter[Drop]


def number(task: str) -> str:
    """`tobymao__sqlglot-1944` as `1944`."""
    return task.removeprefix(_ID)


def later_same_place(evidence: TaskEvidence, evals: Sequence[TaskEvidence]) -> str | None:
    """The evaluation task whose gold construct this later upstream fix also changes, if any."""
    mine = set(evidence.gold_places)
    for other in evals:
        if other.created < evidence.created and mine & set(other.gold_places):
            return other.task
    return None


def lesson_for(
    evidence: TaskEvidence, parts: Mapping | None, evals: Sequence[TaskEvidence]
) -> Lesson | Drop:
    """The task's lesson, or why it has none."""
    if evidence.task in TIER2:
        return Drop.TIER2_OWN
    if parts is not None:
        return curated(evidence, f"own-{number(evidence.task)}", parts)
    if any(run.resolved for run in evidence.runs):
        if not (evidence.solved_places or evidence.gold_places):
            return Drop.NO_PLACE
        return own_solve(evidence, f"own-{number(evidence.task)}")
    if not evidence.gold_places:
        return Drop.NO_PLACE
    if later_same_place(evidence, evals):
        return Drop.LATER_SAME_PLACE
    return own_failure(evidence, f"fail-{number(evidence.task)}")


def _pair_lessons(found: Mapping[str, Lesson], curated_text: Mapping[str, Mapping]) -> list[Lesson]:
    made = []
    for target, parts in curated_text.items():
        if parts.get("link") != Link.PAIR_LESSON:
            continue
        sources = [found[task] for task in parts["from_tasks"]]
        runs = [run for lesson in sources for run in lesson.runs]
        made.append(pair(target, f"pair-{number(target)}", parts, runs))
    return made


def _with_pair_sources(lesson: Lesson, curated_text: Mapping[str, Mapping]) -> Lesson:
    targets = [
        (target, Link.PAIR_SOURCE)
        for target, parts in curated_text.items()
        if parts.get("link") == Link.PAIR_LESSON and lesson.task in parts["from_tasks"]
    ]
    return dataclasses.replace(lesson, links=lesson.links + tuple(targets)) if targets else lesson


def select(evidence: Mapping[str, TaskEvidence], curated_text: Mapping[str, Mapping]) -> Selection:
    """Task lessons, pair lessons and repo habits, with every left-out task counted."""
    evals = [evidence[task] for task in EVAL_TASKS if task in evidence]
    drops: Counter[Drop] = Counter()
    found: dict[str, Lesson] = {}
    for task in sorted(evidence, key=lambda name: int(number(name))):
        same_task = curated_text.get(task)
        parts = same_task if same_task and same_task["link"] == Link.SAME_TASK else None
        made = lesson_for(evidence[task], parts, evals)
        if isinstance(made, Drop):
            drops[made] += 1
        else:
            found[task] = _with_pair_sources(made, curated_text)
    all_runs = [run for item in evidence.values() for run in item.runs]
    lessons = [*found.values(), *_pair_lessons(found, curated_text), *habits(all_runs)]
    return Selection(lessons, drops)


def own_history(lessons: Sequence[Lesson]) -> list[Lesson]:
    """Lessons whose resolution is Glimmer's own: no upstream-fix lessons."""
    return [lesson for lesson in lessons if lesson.source != LessonSource.OWN_FAILURE]
