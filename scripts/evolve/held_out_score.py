"""Score the held-out test: pure over per-case numbers, no engine, no files.

The verdict words and the sentence are built here from the intervals, so a tie reads as a tie, and
a set with too few cases where a lesson fired says "underpowered" instead of a quiet "better". Fires
are counted by the same would-fire rule in every arm; the no-lesson arm's fires are decisions where
a lesson would have appeared.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import held_out_cases
import score_final

from symbiont.act1.game_fitness import Case

BOOTSTRAP_SEED = 20261101
MIN_GAIN = 0.08  # [hypothesis] whole-game fitness a "one move per reply" win must reach
NEEDED_WITH_FIRE = 84  # cases with a fire the old-cutoff (0.969) check said the primary needs
UNDERPOWERED_BELOW = 126  # 1.5 times the need: under this a set is called underpowered in words


@dataclass(frozen=True)
class Fired:
    """One game's outcome at its would-fire decisions.

    `first_*` is the first would-fire decision, reached with identical prompts in every arm; the
    unprefixed fields average all of them. A progress of None means no route reading, never 0.
    """

    decisions: int
    first_mistakes: float
    first_progress: float | None
    mistakes: float
    progress: float | None
    no_progress: int

    @staticmethod
    def of(summary: Mapping[str, float | None]) -> "Fired":
        """From fired_outcomes' summary of one game."""
        return Fired(
            int(summary["fired"] or 0), float(summary["first_mistakes"] or 0),
            summary["first_progress"], float(summary["mistakes"] or 0), summary["progress"],
            int(summary["no_progress"] or 0),
        )  # fmt: skip


FiredByCase = Mapping[Case, Fired | None]
FIRST = ("first_mistakes", "first_progress")
ALL = ("mistakes", "progress")


def _both_fired(first: FiredByCase, second: FiredByCase) -> list[Case]:
    """Cases where both arms had at least one would-fire decision."""
    return [case for case in first if first[case] is not None and second.get(case) is not None]


def _paired_measure(
    lessons: FiredByCase, none: FiredByCase, shared: list[Case], field: str
) -> dict[str, Any]:
    """One measure over cases both arms read; mistakes are negated, so higher is better."""
    direction = -1.0 if "mistakes" in field else 1.0
    usable = [
        case for case in shared
        if getattr(lessons[case], field) is not None and getattr(none[case], field) is not None
    ]  # fmt: skip
    if len(usable) < 2:
        return {"cases": len(usable)}
    return score_final.compare(
        {case: direction * getattr(lessons[case], field) for case in usable},
        {case: direction * getattr(none[case], field) for case in usable},
        BOOTSTRAP_SEED,
    )


def at_fires(
    lessons: FiredByCase, none: FiredByCase, cases: set[Case], fields: tuple[str, str]
) -> dict[str, dict[str, Any]]:
    """Mistakes and progress for the named fields, lessons against none, with-fire cases only."""
    shared = [case for case in _both_fired(lessons, none) if case in cases]
    if len(shared) < 2:
        return {}
    return {
        "mistakes": _paired_measure(lessons, none, shared, fields[0]),
        "progress": _paired_measure(lessons, none, shared, fields[1]),
    }


def whole_game(
    first: Mapping[Case, float], second: Mapping[Case, float], cases: set[Case]
) -> dict[str, Any]:
    """Fitness difference over the cases both arms played, first minus second."""
    shared = {c for c in first if c in second and c in cases}
    return score_final.compare(
        {c: first[c] for c in shared}, {c: second[c] for c in shared}, BOOTSTRAP_SEED
    )


def _word(measures: Mapping[str, Mapping[str, Any]], name: str) -> str:
    """The word of one measure; a measure without enough cases reads as a tie."""
    return measures.get(name, {}).get("word", "tie")


def lessons_verdict(measures: Mapping[str, Mapping[str, Any]], with_fire: int) -> str:
    """C1: supported only if mistakes read better and progress does not read worse."""
    if not measures or with_fire < UNDERPOWERED_BELOW:
        return "underpowered"
    mistakes, progress = _word(measures, "mistakes"), _word(measures, "progress")
    if mistakes == "worse" or progress == "worse":
        return "worse"
    return "supported" if mistakes == "better" else "tie"


def one_move_verdict(claim: Mapping[str, Any]) -> str:
    """C2: `supported` needs better and a mean of MIN_GAIN; a smaller better says so."""
    if claim["word"] == "better":
        return "supported" if claim["mean_difference"] >= MIN_GAIN else "better but small"
    return claim["word"]


def no_progress_counts(fired: Mapping[held_out_cases.Arm, FiredByCase], cases: set[Case]) -> dict:
    """Fires without a route reading, per arm: dropped from progress, never scored as 0."""
    return {
        arm.value: sum(g.no_progress for c, g in by_case.items() if g is not None and c in cases)
        for arm, by_case in fired.items()
    }


def analyze_set(
    cases: set[Case],
    fitness: Mapping[held_out_cases.Arm, Mapping[Case, float]],
    fired: Mapping[held_out_cases.Arm, FiredByCase],
) -> dict[str, Any]:
    """Both claims on one map set, plus the descriptive comparisons."""
    if not cases:
        return {"cases": 0, "verdict": "no cases played"}
    arm = held_out_cases.Arm
    lessons, none = fired[arm.LESSONS], fired[arm.NONE]
    first = at_fires(lessons, none, cases, FIRST)
    with_fire = len([c for c in _both_fired(lessons, none) if c in cases])
    one_move = whole_game(fitness[arm.ONE_MOVE], fitness[arm.NONE], cases)
    return {
        "cases": len(cases),
        "cases_with_fire_in_both_arms": with_fire,
        "fires_without_progress_reading": no_progress_counts(fired, cases),
        "C1_lessons_at_first_fire": {"verdict": lessons_verdict(first, with_fire), **first},
        "C2_one_move_whole_game": {"verdict": one_move_verdict(one_move), **one_move},
        "secondary_lessons_all_fires": at_fires(lessons, none, cases, ALL),
        "secondary_lessons_whole_game": whole_game(fitness[arm.LESSONS], fitness[arm.NONE], cases),
    }


def analyze(
    all_cases: set[Case],
    fitness: Mapping[held_out_cases.Arm, Mapping[Case, float]],
    fired: Mapping[held_out_cases.Arm, FiredByCase],
) -> dict[str, Any]:
    """The generated set (decides the headline) and the Freedoom set (reported apart)."""
    by_set = {
        which.value: {c for c in all_cases if held_out_cases.map_set_of(c.level) == which}
        for which in held_out_cases.MapSet
    }
    sets = {name: analyze_set(cases, fitness, fired) for name, cases in by_set.items()}
    return {"sets": sets, "result": verdict_sentence(sets["generated"])}


def verdict_sentence(primary: Mapping[str, Any]) -> str:
    """The only sentence the pitch may use for the situational lessons, built from the numbers."""
    if not primary["cases"]:
        return "No generated-map cases were scored."
    c1, c2 = primary["C1_lessons_at_first_fire"], primary["C2_one_move_whole_game"]
    with_fire = primary["cases_with_fire_in_both_arms"]
    note = (
        f" (underpowered: {with_fire} cases with a fire, fewer than {UNDERPOWERED_BELOW})"
        if c1["verdict"] == "underpowered"
        else f" ({with_fire} cases with a fire)"
    )
    lessons = (
        f"Situational lessons at the first decision where one would fire: {c1['verdict']}{note}."
    )
    one_move = f"One move per reply, whole game, against no lesson: {c2['verdict']}."
    return f"{lessons} {one_move}"
