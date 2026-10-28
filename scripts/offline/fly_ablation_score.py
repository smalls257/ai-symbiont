"""Score the T47 ablation's risks: option A rows, paired differences, ranking, refit times.

Violation prevented: **Paper Tiger**. Every arm is scored by the same `note_cost_report.report`
as T46, in the fly's slot, with the counters run as the reference beside it and the batch
classifier (R1) in its own slot, so each arm's gap to both is paired on the same bootstrap
draws. A row without the counters row beside it is never written.
"""

from typing import Any

import numpy as np
import run_repo_curve as rc
import run_selection as g6

from symbiont.eval import selection as sel
from symbiont.eval.note_cost_ranking import ranking
from symbiont.eval.note_cost_report import NET, Arms, report
from symbiont.eval.note_cost_select import FOLDS

KEPT_OPTIONS = rc.KEPT_OPTIONS
HEADLINE = "a_heads_up_gain_1"
L2 = 100.0
REGIMES = ("R1", "R2")
BATCH_ONLY_R1 = {"counters"}


def learner_runs(
    found: dict, part: dict[str, Any], n_repos: int
) -> dict[tuple[str, str], dict[int, dict]]:
    """(learner, regime) -> seed -> risks per scoring repository, at N training repositories."""
    runs: dict[tuple[str, str], dict[int, dict]] = {}
    for regime in REGIMES:
        for arm in part["arms"]:
            runs[(arm, regime)] = {
                s: found[("online", (arm, s, n_repos))][regime] for s in sel.WIRING_SEEDS
            }
        runs[("logistic regression", regime)] = {0: found[("logistic", n_repos)][regime]}
        if part["mlp"]:
            runs[("MLP ceiling probe", regime)] = {
                s: found[("mlp", (s, n_repos))][regime] for s in sel.WIRING_SEEDS
            }
    runs[("counters", "R1")] = {0: found[("counters", n_repos)]["R1"]}
    return runs


def _score_one(job: tuple[str, str, int, dict[int, dict], dict, dict]) -> dict[str, Any]:
    learner, regime, n_repos, seeds, counters, logistic = job
    traces = {s: rc.traces_of(r) for s, r in seeds.items()}
    arms = Arms(
        counters=rc.traces_of(counters),
        fly=traces,
        dense={s: {0.0: t} for s, t in traces.items()},
        logistic={fold: {L2: rc.traces_of(logistic)} for fold in range(FOLDS)},
    )
    body = report(arms, seed=sel.SEED)
    keep = {"learner": learner, "regime": regime, "train_repos": n_repos}
    rows = [
        {**keep, **r, "arm": learner}
        for r in body["rows"]
        if r["arm"] == "fly" and r["option"] in KEPT_OPTIONS
    ]
    refs = [
        {**r, "regime": "R1", "train_repos": n_repos}
        for r in body["rows"]
        if r["arm"] in ("counters", "logistic")
    ]
    gaps = [
        {**keep, **d, "what": d["what"].replace("fly", learner)}
        for d in body["differences"]
        if d["option"] in KEPT_OPTIONS and d["what"] in ("fly minus counters", "fly minus logistic")
    ]
    return {"rows": rows, "references": refs, "differences": gaps, "auc": _auc(seeds)}


def _auc(seeds: dict[int, dict]) -> float:
    followed = np.concatenate([np.concatenate(rc.COLUMNS[r]["followed"]) for r in rc.SCORING])
    found = [
        ranking(np.concatenate([risks[r] for r in rc.SCORING]), followed)["roc_auc"]
        for risks in seeds.values()
    ]
    return float(np.mean(found))


def _refit_name(kind: str, key: Any) -> str:
    if kind == "online":
        return f"{key[0]} n={key[2]}"
    if kind == "logistic":
        return f"logistic regression n={key}"
    return f"MLP ceiling probe n={key[1]}"


def refit_times(found: dict) -> dict[str, dict[str, float]]:
    """Wall seconds per R2 refit, pooled over seeds and repositories, per learner."""
    pooled: dict[str, list[float]] = {}
    for (kind, key), result in found.items():
        if "refit_s" in result:
            pooled.setdefault(_refit_name(kind, key), []).extend(result["refit_s"])
    return {
        name: {
            "refits": len(t),
            "mean_s": float(np.mean(t)),
            "p95_s": float(np.quantile(t, 0.95)),
            "max_s": float(np.max(t)),
        }
        for name, t in pooled.items()
        if t
    }


def scored(found: dict, part: dict[str, Any], workers: int) -> dict[str, Any]:
    """Rows, differences, AUC and refit times of every (learner, regime, N) of the part."""
    jobs = []
    for n in part["n"]:
        counters, logistic = found[("counters", n)]["R1"], found[("logistic", n)]["R1"]
        for (learner, regime), seeds in learner_runs(found, part, n).items():
            jobs.append((learner, regime, n, seeds, counters, logistic))
    results = g6.pool_map(_score_one, jobs, workers)
    rows = [r for res in results for r in res["rows"]]
    references = {
        (r["arm"], r["option"], r["train_repos"]): r for res in results for r in res["references"]
    }
    auc = {f"{j[0]} {j[1]} n={j[2]}": res["auc"] for j, res in zip(jobs, results, strict=True)}
    return {
        "headline_option": HEADLINE,
        "rows": rows,
        "reference_rows": list(references.values()),
        "differences": [d for res in results for d in res["differences"]],
        "roc_auc": auc,
        "refit_wall_time": refit_times(found),
        "table_rows": table_lines(rows),
    }


def table_lines(rows: list[dict[str, Any]]) -> list[str]:
    """One line per (learner, regime) at 80 repositories, headline option only (at most 40)."""
    lines = []
    for row in rows:
        if row["option"] != HEADLINE or row["train_repos"] != 80:
            continue
        net, prec = row["metrics"][NET], row["metrics"]["precision"]["value"]
        notes = row["metrics"]["notes_per_100_steps"]["value"]
        shown = "n/a" if prec is None else f"{prec:.2f}"
        interval = f"[{net['ci95_low']:.3f}, {net['ci95_high']:.3f}]"
        lines.append(
            f"{row['learner']} | {row['regime']} | {net['value']:.3f} {interval}"
            f" | prec {shown} | notes/100 {notes:.2f}"
        )
    return lines[:40]
