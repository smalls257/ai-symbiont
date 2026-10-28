"""The results document of the reasoning-strength gate: counts, ids and labels only (pure).

Violation prevented: Leaky Narrative at the repo boundary. Replies and prompts stay in the local
workdir; this file holds per-item 0/1 strings, token counts, seconds, scored labels and the
verdict, in the row shape `check_results.py` expects (fixed-low and fixed-high are references).
"""

import statistics
from collections import Counter
from typing import Any

from gate_verdict import ItemOutcome, decide

PREREG = "prereg/2026-10-28-reasoning-strength-gate.md"
RULE = (
    "GO if low is within 10 points of high overall, low uses at most 50% of high's tokens "
    "(median of per-item ratios), and at least 25% of items differ; else NO-GO."
)
CAVEATS = (
    "Freedoom items are warped states, not a played episode; one Glimmer slot was shared "
    "with a calibration run, so wall-clock is noisy.",
    "Thirty items cannot resolve small differences; the verdict is a go/no-go screen, "
    "not an estimate of the effect.",
    "Coding score is the same-file (and function, when known) match of the first command, "
    "not a test result.",
)


def _flags(outcomes: list[ItemOutcome], arm: str) -> str:
    return "".join("1" if getattr(o, f"{arm}_ok") else "0" for o in outcomes)


def _row(outcomes: list[ItemOutcome], arm: str, role: str) -> dict[str, Any]:
    tokens = [getattr(o, f"{arm}_tokens") for o in outcomes]
    seconds = [getattr(o, f"{arm}_seconds") for o in outcomes]
    wins = sum(getattr(o, f"{arm}_ok") for o in outcomes)
    return {
        "arm": f"fixed_{arm}", "role": role, "split": "all", "n": len(outcomes),
        "successes": wins, "success_rate": wins / len(outcomes),
        "median_completion_tokens": statistics.median(tokens),
        "total_completion_tokens": sum(tokens),
        "median_seconds": round(statistics.median(seconds), 1),
        "total_seconds": round(sum(seconds), 1),
        "per_item": _flags(outcomes, arm),
    }  # fmt: skip


def _hindsight_row(outcomes: list[ItemOutcome]) -> dict[str, Any]:
    """Ceiling: with hindsight pick low when it succeeds, else high when it does."""
    chosen = [(o.low_ok, o.low_tokens, o.low_seconds) if o.low_ok or not o.high_ok
              else (True, o.high_tokens, o.high_seconds) for o in outcomes]  # fmt: skip
    wins = sum(ok for ok, _, _ in chosen)
    return {
        "arm": "hindsight_chooser", "role": "ceiling", "split": "all", "n": len(outcomes),
        "successes": wins, "success_rate": wins / len(outcomes),
        "median_completion_tokens": statistics.median(t for _, t, _ in chosen),
        "total_completion_tokens": sum(t for _, t, _ in chosen),
        "total_seconds": round(sum(s for _, _, s in chosen), 1),
    }  # fmt: skip


def _label_counts(scored: list[tuple[ItemOutcome, dict[str, str], bool, bool]]) -> dict[str, Any]:
    return {
        arm: dict(Counter(labels[arm] for _, labels, _, _ in scored)) for arm in ("low", "high")
    }


def _by_domain(outcomes: list[ItemOutcome]) -> dict[str, Any]:
    result = {}
    for domain in sorted({o.domain for o in outcomes}):
        part = [o for o in outcomes if o.domain == domain]
        result[domain] = {
            "n": len(part),
            "low_success": sum(o.low_ok for o in part) / len(part),
            "high_success": sum(o.high_ok for o in part) / len(part),
        }
    return result


def build_results(
    scored: list[tuple[ItemOutcome, dict[str, str], bool, bool]], run_mode: str
) -> dict[str, Any]:
    """The whole results document from scored items; `run_mode` is 'smoke' or 'full'."""
    outcomes = [outcome for outcome, _, _, _ in scored]
    return {
        "run_mode": run_mode,
        "prereg": PREREG,
        "model": "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M",
        "item_ids": [o.item_id for o in outcomes],
        "rows": [
            _row(outcomes, "low", "reference"),
            _row(outcomes, "high", "reference"),
            _hindsight_row(outcomes),
        ],
        "by_domain": _by_domain(outcomes),
        "labels": _label_counts(scored),
        "coding_same_file_only": {
            "low": sum(low for _, _, low, _ in scored),
            "high": sum(high for _, _, _, high in scored),
        },
        "decision": decide(outcomes),
        "rule": RULE,
        "caveats": list(CAVEATS),
    }
