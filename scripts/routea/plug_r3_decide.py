"""Plug round 3's frozen decision rule (prereg/2026-10-29-plug-judge.md): H1 against the thresholded
ranker, the safety, habits and new-lesson gates, the minimum detectable effect and the claim.

Pure: per-repo rates in, decisions out. A ranker with no safe point makes H1 read
`no safe comparator`, never a win over silence; the claim sentence always prints the
always-answering ranker's pick, precision and wrong pick beside the judge's.
"""

import math
import random
from collections.abc import Sequence

from plug_r2_select import better, mde
from warm_start import paired_gain

SAFE_SILENCE, SAFE_SILENCE_LOW = 0.80, 0.60  # H2: point, and the interval's lower bound
SAFE_WRONG, SAFE_WRONG_HIGH = 0.05, 0.10  # H2: point, and the interval's upper bound
HABITS_BAR = 0.90  # H3, the owner's bar on the seed mean
NEW_GAP, NEW_GAP_LOW = -0.05, -0.10  # H4: new minus seen pick, point and lower bound
UNDERPOWERED_MDE = 0.10
RESAMPLES, SEED = 10_000, 0


def safety_gate(cells: dict[str, dict]) -> dict:
    """H2 on per-repo rates: silence and wrong pick, each on its point and its interval."""
    silence = paired_gain([c["silence"] for c in cells.values()])
    wrong = paired_gain([c["wrong_pick"] for c in cells.values()])
    passes = (
        silence["mean_gain"] >= SAFE_SILENCE
        and silence["ci95_low"] > SAFE_SILENCE_LOW
        and wrong["mean_gain"] <= SAFE_WRONG
        and wrong["ci95_high"] <= SAFE_WRONG_HIGH
    )
    return {"passes": passes, "silence": silence, "wrong_pick": wrong}


def wilson(rate: float, questions: int) -> list[float]:
    """The 95% Wilson interval of a rate over a number of questions."""
    z2 = 1.96**2
    center = (rate + z2 / (2 * questions)) / (1 + z2 / questions)
    half = math.sqrt(z2 * rate * (1 - rate) / questions + z2 * z2 / (4 * questions**2)) / (
        1 + z2 / questions
    )
    return [round(center - half, 4), round(center + half, 4)]


def habits_gate(judge_rate: float, untrained_rate: float, questions: int) -> dict:
    """H3: the judge adapter's seed-mean habits score against the bar, the untrained beside."""
    return {
        "passes": judge_rate >= HABITS_BAR,
        "judge": round(judge_rate, 4),
        "judge_wilson95": wilson(judge_rate, questions),
        "untrained_1b": round(untrained_rate, 4),
    }


def gap_interval(new: Sequence[float], seen: Sequence[float]) -> dict:
    """Mean of `new` minus mean of `seen`, with a percentile bootstrap that resamples each
    group's repos on its own (the groups are different repos, so nothing pairs them)."""
    rng = random.Random(SEED)
    draws = sorted(
        sum(rng.choices(new, k=len(new))) / len(new)
        - sum(rng.choices(seen, k=len(seen))) / len(seen)
        for _ in range(RESAMPLES)
    )
    gap = sum(new) / len(new) - sum(seen) / len(seen)
    low, high = draws[int(0.025 * RESAMPLES)], draws[int(0.975 * RESAMPLES) - 1]
    return {"gap": round(gap, 4), "ci95_low": round(low, 4), "ci95_high": round(high, 4)}


def new_lesson_gate(new: dict[str, dict], seen: dict[str, dict]) -> dict:
    """H4: per-repo pick on new (scored) lessons minus on seen (meta-train, unseen wording)."""
    found = gap_interval([c["pick"] for c in new.values()], [c["pick"] for c in seen.values()])
    return {"passes": found["gap"] >= NEW_GAP and found["ci95_low"] >= NEW_GAP_LOW, **found}


def h1(judge: dict[str, dict], ranker: dict[str, dict] | None) -> dict:
    """Judge minus thresholded ranker on per-repo pick; `no safe comparator` without a ranker."""
    if ranker is None:
        return {"decision": "no safe comparator"}
    return better([judge[repo]["pick"] - ranker[repo]["pick"] for repo in sorted(judge)])


def versus_alone(judge: dict[str, dict], alone: dict[str, dict]) -> dict:
    """Secondary: judge minus the always-answering ranker, pick and precision, paired by repo;
    precision pairs only the repos where the judge answered at least once."""
    repos = sorted(judge)
    spoke = [r for r in repos if judge[r]["answered"]]
    return {
        "pick": paired_gain([judge[r]["pick"] - alone[r]["pick"] for r in repos]),
        "precision": paired_gain([judge[r]["precision"] - alone[r]["precision"] for r in spoke])
        if spoke
        else {"repos": 0, "status": "the judge answered nothing"},
    }


def power(gains: Sequence[float], validation_items: float, scored_items: float) -> dict:
    """Round 2's MDE on validation gains (s in-sample, so optimistic) and the underpowered flag."""
    found = mde(gains, validation_items, scored_items)
    return {**found, "underpowered": found["mde"] > UNDERPOWERED_MDE}


def failed_gates(gates: dict[str, dict]) -> list[str]:
    """The names of the gates that did not pass, in a fixed order."""
    return [name for name in ("safety", "habits", "new lessons") if not gates[name]["passes"]]


def beside(means: dict[str, dict]) -> str:
    """The judge's pick, precision and wrong pick, then the always-answering ranker's three."""
    keys = ("pick", "precision", "wrong_pick")
    judge, alone = (
        ", ".join("n/a" if means[row][k] is None else f"{means[row][k]:.2f}" for k in keys)
        for row in ("judge", "ranker_alone")
    )
    return f"pick, precision, wrong pick {judge} (ranker alone {alone})"


def claim(first: dict, gates: dict[str, dict], means: dict[str, dict]) -> str:
    """The claim sentence for H1 and the gates, in the prereg's fixed words (at most 260 chars)."""
    numbers = f"the judge's {beside(means)}"
    failed = failed_gates(gates)
    if first["decision"] == "no safe comparator":
        return f"the ranker could not be made silent at these limits; {numbers}"
    if first["decision"] == "better" and not failed:
        return (
            f"on situations built from each lesson's own record, on 40 unseen repos, {numbers}; "
            f"thresholded ranker picks {means['ranker_threshold']['pick']:.2f}; "
            f"silent in {means['judge']['silence']:.2f} with no applicable lesson"
        )
    if first["decision"] == "better":
        names = " and ".join(failed)
        return f"the judge beat the thresholded ranker but failed the {names} gate; {numbers}"
    return (
        f"the judge did not beat the thresholded ranker ({first['decision']}, gain "
        f"{first['mean_gain']:+.2f}, interval {first['ci95_low']:+.2f} to "
        f"{first['ci95_high']:+.2f}); {numbers}"
    )
