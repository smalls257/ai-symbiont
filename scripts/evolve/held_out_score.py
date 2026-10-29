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
NEEDED_WITH_FIRE = 84  # cases with a fire the exploratory noise says the primary needs [measured]
SHOWN = ("better", "worse", "tie")


@dataclass(frozen=True)
class Fired:
    """One game's outcome at its would-fire decisions: how many, mistakes each, route progress."""

    decisions: int
    mistakes: float
    progress: float

    @staticmethod
    def of(summary: Mapping[str, float]) -> "Fired":
        """From fired_outcomes' summary of one game."""
        return Fired(int(summary["fired"]), summary["mistakes"], summary["progress"])


FiredByCase = Mapping[Case, Fired | None]


def _both_fired(first: FiredByCase, second: FiredByCase) -> list[Case]:
    """Cases where both arms had at least one would-fire decision."""
    return [case for case in first if first[case] is not None and second.get(case) is not None]


def at_fires(
    lessons: FiredByCase, none: FiredByCase, cases: set[Case]
) -> dict[str, dict[str, Any]]:
    """Mistakes (fewer is better) and progress over the next 3 decisions, lessons against none."""
    shared = [case for case in _both_fired(lessons, none) if case in cases]
    if len(shared) < 2:
        return {}
    sign = {"mistakes": -1.0, "progress": 1.0}
    out = {}
    for measure, direction in sign.items():
        out[measure] = score_final.compare(
            {case: direction * getattr(lessons[case], measure) for case in shared},
            {case: direction * getattr(none[case], measure) for case in shared},
            BOOTSTRAP_SEED,
        )
    return out


def whole_game(
    first: Mapping[Case, float], second: Mapping[Case, float], cases: set[Case]
) -> dict[str, Any]:
    """Fitness difference over the cases both arms played, first minus second."""
    shared = {c for c in first if c in second and c in cases}
    return score_final.compare(
        {c: first[c] for c in shared}, {c: second[c] for c in shared}, BOOTSTRAP_SEED
    )


def lessons_verdict(measures: Mapping[str, Mapping[str, Any]], with_fire: int) -> str:
    """C1: supported only if mistakes read better and progress does not read worse."""
    if not measures or with_fire < NEEDED_WITH_FIRE:
        return "underpowered"
    if measures["mistakes"]["word"] == "better" and measures["progress"]["word"] != "worse":
        return "supported"
    if measures["mistakes"]["word"] == "worse" or measures["progress"]["word"] == "worse":
        return "worse"
    return "tie"


def one_move_verdict(claim: Mapping[str, Any]) -> str:
    """C2: supported only if the word is better and the mean reaches MIN_GAIN."""
    if claim["word"] == "better" and claim["mean_difference"] >= MIN_GAIN:
        return "supported"
    return claim["word"] if claim["word"] == "worse" else "tie"


def analyze_set(
    cases: set[Case],
    fitness: Mapping[held_out_cases.Arm, Mapping[Case, float]],
    fired: Mapping[held_out_cases.Arm, FiredByCase],
) -> dict[str, Any]:
    """Both claims on one map set, plus the descriptive comparisons."""
    if not cases:
        return {"cases": 0, "verdict": "no cases played"}
    arm = held_out_cases.Arm
    measures = at_fires(fired[arm.LESSONS], fired[arm.NONE], cases)
    with_fire = len([c for c in _both_fired(fired[arm.LESSONS], fired[arm.NONE]) if c in cases])
    one_move = whole_game(fitness[arm.ONE_MOVE], fitness[arm.NONE], cases)
    return {
        "cases": len(cases),
        "cases_with_fire_in_both_arms": with_fire,
        "C1_lessons_at_fires": {"verdict": lessons_verdict(measures, with_fire), **measures},
        "C2_one_move_whole_game": {"verdict": one_move_verdict(one_move), **one_move},
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
    c1, c2 = primary["C1_lessons_at_fires"], primary["C2_one_move_whole_game"]
    with_fire = primary["cases_with_fire_in_both_arms"]
    lessons = (
        f"Situational lessons at the decisions where one would fire: {c1['verdict']} "
        f"({with_fire} cases with a fire)."
    )
    one_move = f"One move per reply, whole game, against no lesson: {c2['verdict']}."
    return f"{lessons} {one_move}"
