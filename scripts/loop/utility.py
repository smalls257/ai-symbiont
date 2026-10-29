"""Lesson utility: did a lesson help where it applied? Keep, down-weight or drop it (pure).

Ablation (card in the prompt or not, same model and tasks) wins when there are enough pairs;
otherwise a difference in differences on the never-mined baseline half of training tasks (pass
gap applied vs not, trained vs untrained, averaged with the drop in mistake repeats). Only harm
confirmed by MIN_DROP_PAIRS pairs and a 95% bound drops a lesson for good; a weaker bad score
down-weights it, reversibly. Per-kind means set the next round's harvest quotas.
"""

from __future__ import annotations

import hashlib
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

MIN_EXPOSURES = 3  # applicable attempts needed on each side before a lesson is judged at all
MIN_ABLATION_PAIRS = 3  # with/without pairs needed before the ablation overrides observation
PROBATION_ROUNDS = 2  # trained rounds a lesson may stay unjudged or neutral at full weight
HARM_BELOW = -0.10  # a score this low down-weights, reversibly; it never drops on its own
# A permanent drop needs at least this many with/without pairs (all rounds pooled) and a 95%
# upper bound on the mean difference below zero: 3 pairs once dropped a lesson that helps.
MIN_DROP_PAIRS = 8
Z_95 = 1.96
KEEP_ABOVE = 0.05  # a score this high earns full weight
BASELINE_EVERY = 2  # one training task in this many is judged, never mined
QUOTA_STEP = 0.5  # a kind's harvest quota moves by this share of the base per judged sign


class Mark(StrEnum):
    """How one lesson relates to one attempt."""

    NOT_APPLICABLE = "not applicable"  # the lesson's situation never arose
    AVOIDED = "avoided"  # the situation arose and the mistake did not happen
    REPEATED = "repeated"  # the situation arose and the mistake happened again


class Decision(StrEnum):
    """What the next round's training set does with a lesson."""

    KEEP = "keep"  # full weight
    PROBATION = "probation"  # full weight, not enough evidence yet
    DOWN_WEIGHT = "down-weight"  # card row only
    DROP = "drop"  # no rows, never harvested again


class Estimator(StrEnum):
    """Which evidence produced a score."""

    ABLATION = "ablation"
    OBSERVATIONAL = "observational"
    NONE = "none"


@dataclass(frozen=True)
class Exposure:
    """One lesson's mark on one graded training attempt."""

    lesson_id: str
    attempt_id: str
    task_id: str
    mark: Mark
    passed: bool
    trained: bool  # the attempting model's training set held this lesson


@dataclass(frozen=True)
class AblationPair:
    """The same model and task, with the lesson card in the prompt and without."""

    lesson_id: str
    task_id: str
    passed_with: bool
    passed_without: bool


@dataclass(frozen=True)
class LessonUtility:
    """One row of the per-lesson utility table: counts, rates, score and the decision."""

    lesson_id: str
    kind: str
    applied_trained: int
    applied_untrained: int
    repeat_before: float | None
    repeat_after: float | None
    pass_gap_lift: float | None
    ablation_pairs: int
    estimator: Estimator
    score: float | None
    decision: Decision


@dataclass(frozen=True)
class LessonRecord:
    """What the judge needs to know about a lesson besides its exposures."""

    lesson_id: str
    kind: str
    rounds_trained: int


def in_baseline(task_id: str) -> bool:
    """Whether a training task is in the judged, never-mined half (fixed by its id)."""
    return hashlib.sha256(task_id.encode()).digest()[0] % BASELINE_EVERY == 0


def _rate(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _pass_gap(exposures: Sequence[Exposure]) -> float | None:
    """Pass rate where the lesson applied minus where it did not; None if a side is too thin."""
    applied = [e.passed for e in exposures if e.mark is not Mark.NOT_APPLICABLE]
    other = [e.passed for e in exposures if e.mark is Mark.NOT_APPLICABLE]
    if len(applied) < MIN_EXPOSURES or len(other) < MIN_EXPOSURES:
        return None
    return sum(applied) / len(applied) - sum(other) / len(other)


def _repeat_rate(exposures: Sequence[Exposure]) -> float | None:
    applied = [e.mark is Mark.REPEATED for e in exposures if e.mark is not Mark.NOT_APPLICABLE]
    return _rate(applied) if len(applied) >= MIN_EXPOSURES else None


def _observational(trained: Sequence[Exposure], untrained: Sequence[Exposure]) -> list[float]:
    """The available observational components: pass-gap lift and repeat-rate drop."""
    parts = []
    lift = _lift(trained, untrained)
    if lift is not None:
        parts.append(lift)
    after, before = _repeat_rate(trained), _repeat_rate(untrained)
    if after is not None and before is not None:
        parts.append(before - after)
    return parts


def harm_confirmed(pairs: Sequence[AblationPair]) -> bool:
    """MIN_DROP_PAIRS or more pairs whose 95% upper bound on with-minus-without is below zero."""
    if len(pairs) < MIN_DROP_PAIRS:
        return False
    gaps = [p.passed_with - p.passed_without for p in pairs]
    bound = Z_95 * statistics.stdev(gaps) / len(gaps) ** 0.5
    return statistics.fmean(gaps) + bound < 0


def decide(score: float | None, rounds_trained: int, *, confirmed_harm: bool) -> Decision:
    """DROP only on confirmed harm; a bad score down-weights; neutral gets probation first."""
    if confirmed_harm:
        return Decision.DROP
    if score is not None and score <= HARM_BELOW:
        return Decision.DOWN_WEIGHT
    if score is not None and score >= KEEP_ABOVE:
        return Decision.KEEP
    return Decision.PROBATION if rounds_trained < PROBATION_ROUNDS else Decision.DOWN_WEIGHT


def _score(parts: Sequence[float], pairs: Sequence[AblationPair]) -> tuple[Estimator, float | None]:
    """The ablation score when there are enough pairs, else the observational mean, else none."""
    if len(pairs) >= MIN_ABLATION_PAIRS:
        return Estimator.ABLATION, statistics.fmean(p.passed_with - p.passed_without for p in pairs)
    if parts:
        return Estimator.OBSERVATIONAL, statistics.fmean(parts)
    return Estimator.NONE, None


def _lift(trained: Sequence[Exposure], untrained: Sequence[Exposure]) -> float | None:
    after, before = _pass_gap(trained), _pass_gap(untrained)
    return None if after is None or before is None else after - before


def _applied(exposures: Sequence[Exposure]) -> int:
    return sum(e.mark is not Mark.NOT_APPLICABLE for e in exposures)


def judge_lesson(
    lesson: LessonRecord, exposures: Sequence[Exposure], pairs: Sequence[AblationPair]
) -> LessonUtility:
    """Score one lesson and decide its weight, on baseline-half exposures and pairs only."""
    judged = [e for e in exposures if in_baseline(e.task_id)]
    pairs = [p for p in pairs if in_baseline(p.task_id)]
    trained = [e for e in judged if e.trained]
    untrained = [e for e in judged if not e.trained]
    estimator, score = _score(_observational(trained, untrained), pairs)
    return LessonUtility(
        lesson_id=lesson.lesson_id,
        kind=lesson.kind,
        applied_trained=_applied(trained),
        applied_untrained=_applied(untrained),
        repeat_before=_repeat_rate(untrained),
        repeat_after=_repeat_rate(trained),
        pass_gap_lift=_lift(trained, untrained),
        ablation_pairs=len(pairs),
        estimator=estimator,
        score=score,
        decision=decide(score, lesson.rounds_trained, confirmed_harm=harm_confirmed(pairs)),
    )


def judge_lessons(
    lessons: Iterable[LessonRecord],
    exposures: Iterable[Exposure],
    pairs: Iterable[AblationPair] = (),
) -> list[LessonUtility]:
    """The utility table, one row per lesson, in lesson order."""
    by_lesson: dict[str, list[Exposure]] = defaultdict(list)
    for exposure in exposures:
        by_lesson[exposure.lesson_id].append(exposure)
    pairs_by: dict[str, list[AblationPair]] = defaultdict(list)
    for pair in pairs:
        pairs_by[pair.lesson_id].append(pair)
    return [
        judge_lesson(lesson, by_lesson[lesson.lesson_id], pairs_by[lesson.lesson_id])
        for lesson in lessons
    ]


def kind_scores(table: Sequence[LessonUtility]) -> dict[str, float]:
    """Mean score per harvest kind, over judged lessons only."""
    by_kind: dict[str, list[float]] = defaultdict(list)
    for row in table:
        if row.score is not None:
            by_kind[row.kind].append(row.score)
    return {kind: statistics.fmean(scores) for kind, scores in sorted(by_kind.items())}


def harvest_quotas(scores: Mapping[str, float], kinds: Iterable[str], base: int) -> dict[str, int]:
    """New lessons each kind may add next round: more for kinds that help, fewer for harm.

    An unjudged kind keeps the base quota; a helpful kind gets base * (1 + QUOTA_STEP), a harmful
    one base * (1 - QUOTA_STEP), never below one so a rule can still earn its way back.
    """
    quotas = {}
    for kind in sorted(set(kinds)):
        score = scores.get(kind)
        step = 0 if score is None or abs(score) < KEEP_ABOVE else (1 if score > 0 else -1)
        quotas[kind] = max(1, round(base * (1 + QUOTA_STEP * step)))
    return quotas
