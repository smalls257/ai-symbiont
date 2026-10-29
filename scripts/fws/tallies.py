"""Counts of the annotated traces and how the first-wrong-step label meets our mined trouble label.

A trace whose annotation lands on no step, a file that does not parse, a blamed message written
by another agent: each is a counted field here, never a trace dropped quietly or given a guessed
step. Pure: traces and labels come in as arguments.
"""

from collections import Counter
from collections.abc import Sequence

import numpy as np
from annotated import AnnotatedTrace, StepLabels


def split_counts(traces: Sequence[AnnotatedTrace]) -> dict[str, object]:
    """Traces, steps and placed annotations of one split."""
    firsts = [t.first_wrong for t in traces if t.first_wrong is not None]
    lengths = [len(t.records) for t in traces]
    return {
        "framework": traces[0].framework if traces else None,
        "task_kind": traces[0].task_kind.value if traces else None,
        "traces": len(traces),
        "steps": sum(lengths),
        "steps_per_trace_median": float(np.median(lengths)) if lengths else None,
        "annotated_wrong_steps": sum(len(t.error_steps) for t in traces),
        "annotations_on_no_step": sum(t.unplaced_errors for t in traces),
        "traces_with_first_wrong_step": len(firsts),
        "traces_without_first_wrong_step": len(traces) - len(firsts),
        "first_wrong_step_median": float(np.median(firsts)) if firsts else None,
        "first_wrong_share_of_trace_median": _median_share(traces),
    }


def _median_share(traces: Sequence[AnnotatedTrace]) -> float | None:
    """Median of first wrong step / last step: how early in a trace things go wrong."""
    shares = [
        t.first_wrong / (len(t.records) - 1)
        for t in traces
        if t.first_wrong is not None and len(t.records) > 1
    ]
    return round(float(np.median(shares)), 4) if shares else None


def label_counts(labels: Sequence[StepLabels]) -> dict[str, int]:
    """Positive steps of every label, summed over traces."""
    names = ("at_first_wrong", "first_wrong_ahead", "error_ahead", "mined_trouble_ahead")
    totals = {name: sum(int(getattr(one, name).sum()) for one in labels) for name in names}
    totals["mined_trouble_steps"] = sum(int(one.mined_trouble_here.sum()) for one in labels)
    totals["boundary_steps"] = sum(int(one.boundary.sum()) for one in labels)
    return {"steps": sum(len(one.boundary) for one in labels)} | totals


def agreement(labels: Sequence[StepLabels]) -> dict[str, object]:
    """Step-level confusion of mined trouble ahead against annotated wrong step ahead."""
    mined = np.concatenate([one.mined_trouble_ahead for one in labels]).astype(bool)
    annotated = np.concatenate([one.error_ahead for one in labels]).astype(bool)
    table = Counter(zip(mined.tolist(), annotated.tolist(), strict=True))
    both, mined_only = table[(True, True)], table[(True, False)]
    annotated_only, neither = table[(False, True)], table[(False, False)]
    return {
        "both": both,
        "mined_only": mined_only,
        "annotated_only": annotated_only,
        "neither": neither,
        "cohen_kappa": cohen_kappa(both, mined_only, annotated_only, neither),
    }


def cohen_kappa(both: int, first_only: int, second_only: int, neither: int) -> float | None:
    """Chance-corrected agreement of two yes/no labels; None when chance agreement is total."""
    total = both + first_only + second_only + neither
    if not total:
        return None
    observed = (both + neither) / total
    first_yes, second_yes = (both + first_only) / total, (both + second_only) / total
    chance = first_yes * second_yes + (1 - first_yes) * (1 - second_yes)
    return None if chance == 1 else round((observed - chance) / (1 - chance), 4)


def around_first_wrong(
    traces: Sequence[AnnotatedTrace], labels: Sequence[StepLabels], window: int
) -> dict[str, int]:
    """Does our miner see trouble at, before or within `window` steps after the first wrong step?"""
    tally: Counter[str] = Counter()
    for trace, one in zip(traces, labels, strict=True):
        first = trace.first_wrong
        if first is None:
            continue
        mined = np.flatnonzero(one.mined_trouble_here)
        tally["traces"] += 1
        tally["first_wrong_is_boundary"] += int(one.boundary[first])
        tally["mined_trouble_at_first_wrong"] += int(first in mined)
        tally["mined_trouble_before_first_wrong"] += int(bool((mined < first).any()))
        tally["mined_trouble_within_window_after"] += int(
            bool(((mined > first) & (mined <= first + window)).any())
        )
        tally["no_mined_trouble_in_trace"] += int(not len(mined))
    return dict(tally)
