"""Score the card test: paired differences, two intervals, one decision word, one sentence.

Pure over per-case fitness. A claim reads `better` only when the map interval AND the case
interval both have a low end above 0, `worse` only when both high ends are below 0, else `tie`.
C1 supports the card only when it reads better with a mean difference of at least 0.10. The
sentence is built here so no one writes the headline by hand.
"""

import random
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

import script_paths

script_paths.add_script_dirs()

from symbiont.act1 import duel  # noqa: E402 - needs the sibling path added above
from symbiont.act1.game_fitness import Case  # noqa: E402

BOOTSTRAP_SEED = 20261029
MIN_GAIN = 0.10  # [hypothesis] the smallest mean difference C1 may call support
SMALL_BAND = 0.05  # a tie with a mean from here up to MIN_GAIN is "no measurable gain at this size"
COMPARISONS = (("C1", "mined", "none"), ("C2", "mined", "strong"), ("C3", "strong", "none"))
FORBIDDEN_WORDS = ("evolved", "self-improving", "learned from its own mistakes", "recursive")
Z_LOW, Z_HIGH = 0.025, 0.975


class UnpairedCasesError(ValueError):
    """The arms did not play the same cases: a pair is missing."""


def case_interval(diffs: Sequence[float], seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    """95% percentile bootstrap of the mean difference, resampling single cases."""
    rng = random.Random(seed)
    draws = duel.BOOTSTRAP_DRAWS
    means = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(draws))
    return means[int(Z_LOW * draws)], means[int(Z_HIGH * draws) - 1]


def decision_word(map_interval: tuple[float, float], case_interval_: tuple[float, float]) -> str:
    """better / worse only if both intervals agree, else tie."""
    if map_interval[0] > 0 and case_interval_[0] > 0:
        return "better"
    if map_interval[1] < 0 and case_interval_[1] < 0:
        return "worse"
    return "tie"


def compare(
    first: Mapping[Case, float], second: Mapping[Case, float], seed: int = BOOTSTRAP_SEED
) -> dict[str, Any]:
    """One paired comparison over the cases both arms have."""
    if set(first) != set(second):
        raise UnpairedCasesError("the two arms do not hold the same cases")
    groups: dict[str, list[float]] = {}
    for case in first:
        groups.setdefault(case.level, []).append(first[case] - second[case])
    diffs = [value for values in groups.values() for value in values]
    by_map = duel.paired_interval(groups, seed)
    by_case = case_interval(diffs, seed)
    return {
        "cases": len(diffs),
        "mean_difference": statistics.fmean(diffs),
        "map_interval": list(by_map),
        "case_interval": list(by_case),
        "word": decision_word(by_map, by_case),
        "per_map": {level: statistics.fmean(values) for level, values in sorted(groups.items())},
    }


def analyze(scores: Mapping[str, Mapping[Case, float]]) -> dict[str, Any]:
    """The three comparisons, the C1 bar and the sentence. `scores[arm][case]` is fitness."""
    claims = {name: compare(scores[a], scores[b]) for name, a, b in COMPARISONS}
    c1 = claims["C1"]
    claims["C1"]["supports_the_card"] = c1["word"] == "better" and c1["mean_difference"] >= MIN_GAIN
    return {"claims": claims, "result": verdict_sentence(claims)}


def _range(interval: Sequence[float]) -> str:
    """An interval in words."""
    return f"{interval[0]:.2f} to {interval[1]:.2f}"


def verdict_sentence(claims: Mapping[str, Mapping[str, Any]]) -> str:
    """The only sentence the pitch may use for this test, built from the numbers."""
    c1, c3 = claims["C1"], claims["C3"]
    mean = c1["mean_difference"]
    both = f"map interval {_range(c1['map_interval'])}, case interval {_range(c1['case_interval'])}"
    if c1["supports_the_card"]:
        return (
            f"A two-lesson card whose checks are the miner's own texts for the two most common "
            f"mistakes raised Muse Spark's fitness by {mean:.2f} ({both}) on 7 Freedoom maps no "
            f"model or card had played, against {c3['mean_difference']:.2f} for a hand-written "
            f"card."
        )
    if c1["word"] == "worse":
        return f"The mined card scored below no card on 7 held-out maps ({mean:.2f}; {both})."
    sentence = f"A mined card did not measurably beat no card at this size ({mean:.2f}; {both})."
    if c1["word"] == "tie" and SMALL_BAND <= mean < MIN_GAIN:
        sentence += " No measurable gain at this size."
    return sentence
