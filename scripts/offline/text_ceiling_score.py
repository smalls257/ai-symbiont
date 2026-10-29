"""Score the T49 rows and apply the frozen bar of prereg/2026-10-28-text-ceiling.md.

The bar needs both a paired net-value gain of old-plus-text MLP over old-feature logistic (same
bootstrap draws) and a rise in ROC AUC: ranking a little better without earning notes is not
enough. Rows go through T47's `note_cost_report.report` with counters beside them.
"""

from typing import Any

import numpy as np
import run_repo_curve as rc

from symbiont.eval import selection as sel
from symbiont.eval.note_cost_ranking import ranking
from symbiont.eval.note_cost_report import NET, Arms, report
from symbiont.eval.note_cost_select import FOLDS

HEADLINE = "a_heads_up_gain_1"  # the option of T47's table, where the bar is read
KEPT_OPTIONS = rc.KEPT_OPTIONS
REFERENCE = "logistic old"
CANDIDATE = "MLP old+text"
ROLES = {
    "logistic old": "reference",
    "MLP old": "reference",
    "logistic old+text": "under test",
    "MLP old+text": "under test",
}
MIN_NET_GAIN = 0.03  # prereg bar: net value per 100 steps
MIN_AUC_GAIN = 0.03  # prereg bar: ROC AUC
FAIL_HEADLINE = "the step text does not raise the ceiling enough to justify more learner tuning"
PASS_HEADLINE = "the step text raises the ceiling past the pre-registered bar"
SLOT_KEY = 0.0  # the classifier slot is keyed by a penalty; one fit per row here


def verdict(gap: dict[str, Any], auc_gain: float) -> dict[str, Any]:
    """PASS or FAIL under the frozen bar, with each of its three parts."""
    parts = {
        "net_gain_at_least_0.03": bool(gap["value"] >= MIN_NET_GAIN),
        "net_gain_ci95_low_above_0": bool(gap["ci95_low"] is not None and gap["ci95_low"] > 0),
        "auc_gain_at_least_0.03": bool(auc_gain >= MIN_AUC_GAIN),
    }
    passed = all(parts.values())
    return {
        "verdict": "PASS" if passed else "FAIL",
        "result": PASS_HEADLINE if passed else FAIL_HEADLINE,
        "bar_parts": parts,
        "net_gain": gap,
        "auc_gain": auc_gain,
    }


def ranks(seeds: dict[int, dict[str, list[float]]]) -> dict[str, float]:
    """Seed-averaged ROC AUC and precision in the riskiest 1% of scoring steps."""
    followed = np.concatenate([np.concatenate(rc.COLUMNS[r]["followed"]) for r in rc.SCORING])
    found = [
        ranking(np.concatenate([risks[r] for r in rc.SCORING]), followed)
        for risks in seeds.values()
    ]
    return {
        "roc_auc": float(np.mean([f["roc_auc"] for f in found])),
        "precision_top_1pct": float(np.mean([f["precision_top_0.01"] for f in found])),
        "base_rate": found[0]["base_rate"],
    }


def score_row(job: tuple[str, dict[int, dict], dict, dict]) -> dict[str, Any]:
    """Option A rows of one learner, its gap to the reference and counters, and its ranking."""
    name, seeds, counters, reference = job
    traces = {s: rc.traces_of(r) for s, r in seeds.items()}
    body = report(
        Arms(
            counters=rc.traces_of(counters),
            fly=traces,
            dense={s: {0.0: t} for s, t in traces.items()},
            logistic={fold: {SLOT_KEY: rc.traces_of(reference)} for fold in range(FOLDS)},
        ),
        seed=sel.SEED,
    )
    return {
        "name": name,
        "rows": _rows_of(name, body["rows"]),
        "differences": _gaps_of(name, body["differences"]),
        "ranking": ranks(seeds),
    }


def _rows_of(name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [r for r in rows if r["option"] in KEPT_OPTIONS]
    found = [{**r, "arm": name, "role": ROLES[name]} for r in kept if r["arm"] == "fly"]
    return found + [r for r in kept if r["arm"] == "counters"]


def _gaps_of(name: str, differences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    renamed = {
        "fly minus counters": f"{name} minus counters",
        "fly minus logistic": f"{name} minus {REFERENCE}",
    }
    return [
        {**d, "what": renamed[d["what"]]}
        for d in differences
        if d["option"] in KEPT_OPTIONS and d["what"] in renamed
    ]


def table_line(row: dict[str, Any], ranked: dict[str, float]) -> str:
    """One line of the headline table: net value, interval, precision, AUC, top-1% precision."""
    net, prec = row["metrics"][NET], row["metrics"]["precision"]["value"]
    return (
        f"{row['arm']} | {row['role']} | {_shown(net['value'], 3)} "
        f"[{_shown(net['ci95_low'], 3)}, {_shown(net['ci95_high'], 3)}] | prec {_shown(prec, 2)} "
        f"| AUC {_shown(ranked['roc_auc'], 3)} "
        f"| top 1% prec {_shown(ranked['precision_top_1pct'], 2)}"
    )


def _shown(value: float | None, places: int) -> str:
    """A metric for the log table; an undefined metric (no notes, one class) reads n/a."""
    return "n/a" if value is None else f"{value:.{places}f}"


def headline_gap(scored: list[dict[str, Any]]) -> dict[str, Any]:
    """The candidate's paired net-value gap to the reference at the headline option."""
    found = [
        d
        for s in scored
        for d in s["differences"]
        if d["option"] == HEADLINE and d["what"] == f"{CANDIDATE} minus {REFERENCE}"
    ]
    if len(found) != 1:
        raise ValueError(f"expected one {CANDIDATE} gap at {HEADLINE}, found {len(found)}")
    return found[0]
