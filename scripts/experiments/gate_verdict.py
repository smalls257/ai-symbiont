"""The go/no-go decision rule for reasoning strength."""

import statistics
from dataclasses import dataclass

MAX_SUCCESS_GAP = 0.10  # low within 10 points of high overall
MAX_MEDIAN_TOKEN_RATIO = 0.50  # low uses at most half of high's tokens, median over items
MIN_DIFFERING_SHARE = 0.25  # at least a quarter of the items must make the arms differ
RATIO_BAND = 2.0  # an item's cost ratio differs when it is >2x above or below the median ratio


@dataclass(frozen=True)
class ItemOutcome:
    """Both arms on one item."""

    item_id: str
    domain: str  # freedoom | coding
    low_ok: bool
    high_ok: bool
    low_tokens: int
    high_tokens: int
    low_seconds: float
    high_seconds: float


def token_ratio(outcome: ItemOutcome) -> float:
    """Low's completion tokens over high's; zero tokens from high means the request failed."""
    if outcome.high_tokens <= 0 or outcome.low_tokens <= 0:
        raise ValueError(f"{outcome.item_id}: an arm reported no completion tokens")
    return outcome.low_tokens / outcome.high_tokens


def differs(outcome: ItemOutcome, median_ratio: float) -> bool:
    """Low fails where high succeeds, or this item's cost ratio is >2x off the median ratio."""
    if outcome.high_ok and not outcome.low_ok:
        return True
    ratio = token_ratio(outcome)
    return ratio > RATIO_BAND * median_ratio or ratio < median_ratio / RATIO_BAND


def decide(outcomes: list[ItemOutcome]) -> dict[str, object]:
    """Apply the three-part rule to every item pooled; returns the numbers and GO or NO-GO."""
    if not outcomes:
        raise ValueError("no items to decide on")
    count = len(outcomes)
    low_rate = sum(o.low_ok for o in outcomes) / count
    high_rate = sum(o.high_ok for o in outcomes) / count
    ratios = [token_ratio(o) for o in outcomes]
    median_ratio = statistics.median(ratios)
    differing = sum(differs(o, median_ratio) for o in outcomes)
    holds = {
        "success_within_10_points": high_rate - low_rate <= MAX_SUCCESS_GAP + 1e-9,
        "median_token_ratio_at_most_half": median_ratio <= MAX_MEDIAN_TOKEN_RATIO,
        "quarter_of_items_differ": differing / count >= MIN_DIFFERING_SHARE,
    }
    return {
        "items": count,
        "low_success": low_rate,
        "high_success": high_rate,
        "median_token_ratio": median_ratio,
        "items_differing": differing,
        "conditions": holds,
        "verdict": "GO" if all(holds.values()) else "NO-GO",
    }
