"""The scored T46 run's rules: choose on TRAIN, count TEST, bootstrap within repository, verdict.

prereg/2026-10-28-note-cost.md fixes every rule here. Settings are chosen on a repository's
TRAIN traces only and then counted on its TEST traces; the pooled interval resamples tasks
within each repository with the same draws for every row, so differences are paired. Pure.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

import numpy as np

from symbiont.eval.note_cost_options import Prepared, Stack, counts, shown
from symbiont.eval.note_cost_select import Option

N_BOOT = 2000


def pick_on_train(blocks: Sequence[Stack], option: Option) -> tuple[int, int]:
    """(block, setting) with the best TRAIN score; blocks are DenseNet rates or L2 strengths."""
    picks = [option.choose(block.counts) for block in blocks]
    best = max(range(len(blocks)), key=lambda index: (picks[index][1], -index))
    return best, picks[best][0]


def test_counts(test_arm: Prepared, stack: Stack, setting: int, option: Option) -> np.ndarray:
    """Per-task TEST counts at a setting chosen on TRAIN."""
    low, high = stack.settings[setting]
    return counts(test_arm, shown(test_arm, low, option.rule), high)


def stratified_draws(groups: Sequence[str], *, seed: int, n_boot: int = N_BOOT) -> np.ndarray:
    """How often each task is drawn per bootstrap sample, resampling within its group."""
    rng = np.random.default_rng(seed)
    labels = np.asarray(groups)
    draws = np.zeros((n_boot, len(labels)))
    for group in sorted(set(groups)):
        members = np.flatnonzero(labels == group)
        uniform = [1 / len(members)] * len(members)
        draws[:, members] = rng.multinomial(len(members), uniform, size=n_boot)
    return draws


class Verdict(StrEnum):
    """Who may speak live; NONE means recall-only plus encourage notes."""

    NONE = "none"
    COUNTERS = "counters"
    CLASSIFIER = "classifier"
    DENSE = "dense"
    FLY = "fly"


TIE_ORDER = (Verdict.COUNTERS, Verdict.CLASSIFIER, Verdict.DENSE, Verdict.FLY)


def verdict(
    benefit: Mapping[Verdict, Mapping[str, Any]],
    versus_counters: Mapping[Verdict, Mapping[str, Any]],
) -> Verdict:
    """The registered rule.

    1. A candidate earns notes if the lower bound of its pooled value is above 0.
    2. None earns: NONE. 3. Else the earner with the highest point estimate, ties by TIE_ORDER.
    4. If that is not counters and the lower bound of its paired difference from counters is
       not above 0: COUNTERS if counters earn, else NONE.
    """
    earners = [c for c in TIE_ORDER if benefit[c]["ci95_low"] > 0]
    if not earners:
        return Verdict.NONE
    best = max(earners, key=lambda who: (round(benefit[who]["value"], 12), -TIE_ORDER.index(who)))
    if best is Verdict.COUNTERS or versus_counters[best]["ci95_low"] > 0:
        return best
    return Verdict.COUNTERS if Verdict.COUNTERS in earners else Verdict.NONE


def consistent(per_repo_values: Sequence[float]) -> bool:
    """False when per-repository point estimates disagree in sign (a reported tag only)."""
    signs = {np.sign(v) for v in per_repo_values if v != 0}
    return len(signs) <= 1
