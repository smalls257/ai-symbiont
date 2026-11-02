"""Plug round 4: exact binomial upper bounds for wrong-pick counts (a correction after scoring).

Usage: uv run python scripts/routea/plug_r4_bounds.py --results R... --out F

The pre-registered clustered bootstrap is degenerate at zero (all-zero data resamples to zero),
so beside it this reports the exact Clopper-Pearson 95% two-sided upper bound over items. Items
are treated as independent, so repository clustering would widen it. Verdicts do not change.
"""

import argparse
import json
from math import comb
from pathlib import Path

ALPHA = 0.05


def binomial_cdf(events: int, trials: int, rate: float) -> float:
    """The chance of at most `events` successes in `trials` draws at success probability `rate`."""
    return sum(comb(trials, i) * rate**i * (1 - rate) ** (trials - i) for i in range(events + 1))


def clopper_pearson_upper(events: int, trials: int, alpha: float = ALPHA) -> float:
    """The exact two-sided (1 - alpha) upper bound for `events` in `trials`, by bisection."""
    if events >= trials:
        return 1.0
    low, high = events / trials, 1.0
    for _ in range(60):
        mid = (low + high) / 2
        if binomial_cdf(events, trials, mid) > alpha / 2:
            low = mid
        else:
            high = mid
    return high


def wrong_count(rate: float, items: int) -> int:
    """The count behind a rounded pooled rate."""
    return round(rate * items)


def bounds_of(path: Path) -> dict:
    """Each arm's wrong count, the exact bound and the pre-registered bootstrap bound."""
    found = json.loads(path.read_text())
    total = found["items"]
    rows = {}
    for name, key in (("arm", "rule"), ("comparator", "judge_alone")):
        wrong = wrong_count(found[key]["wrong_pick"], total)
        rows[name] = {
            "wrong": wrong,
            "items": total,
            "exact_upper": round(clopper_pearson_upper(wrong, total), 4),
        }
    rows["arm"]["bootstrap_upper"] = found["wrong_bound_rule"]
    rows["arm"]["bootstrap_note"] = (
        "degenerate at zero" if rows["arm"]["wrong"] == 0 else "clustered"
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    document = {
        "status": "correction after scoring: the pre-registered bootstrap is degenerate at zero",
        "arms": {p.stem: bounds_of(p) for p in args.results},
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(json.dumps(document, indent=1))


if __name__ == "__main__":
    main()
