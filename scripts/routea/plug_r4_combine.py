"""Plug round 4, sixth single change: decide with the ranker's score and the judge's together.

Usage: uv run python scripts/routea/plug_r4_combine.py --work R3 --out F

Forms: the judge alone (round 3), the judge over the ranker's top k, a 2-D threshold on the
ranker's top lesson (its IDF score and its P(yes)), and a 2-feature logistic. Each is read at its
best safe point (wrong pick at most 0.05, silence at least 0.80) in-sample, and honestly by
repo-fold cross-validation: fitted on 4 folds of repos, read on the fifth. No new training.
"""

import argparse
import json
import math
import sys
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_judge import Choice, outcome_rates  # noqa: E402
from plug_judge_cli import GRID, seed_mean_scores  # noqa: E402
from plug_r3 import safe  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_situation import Item, lexical_rank, lexical_scores  # noqa: E402

FOLDS = 5
SHORTLIST = 10
IDF_GRID = tuple(step / 2 for step in range(61))  # ranker score 0 to 30 in steps of 0.5

Candidates = dict[str, list[tuple[str, float, float]]]  # item -> (lesson, P(yes), IDF), best first


def candidates(items: Sequence[Item], scores: dict[str, float]) -> Candidates:
    """Each item's shortlist in the ranker's order with the judge's P(yes) and the ranker score."""
    found = {}
    for item in items:
        idf = lexical_scores(item)
        ranked = lexical_rank(item)[:SHORTLIST]
        found[item.item_id] = [
            (x.lesson_id, scores[f"{item.item_id}::{x.lesson_id}"], idf[x.lesson_id])
            for x in ranked
        ]
    return found


Rule = Callable[[list[tuple[str, float, float]]], tuple[str | None, float]]


def judge_top(depth: int) -> Rule:
    """The best P(yes) among the ranker's top `depth`, with that P(yes) as the score."""

    def rule(shortlist):
        lesson, p_yes, _ = max(shortlist[:depth], key=lambda entry: entry[1])
        return lesson, p_yes

    return rule


def decide(items, cands: Candidates, rule: Rule, threshold: float) -> list[Choice]:
    """The rule's lesson per item where its score reaches the threshold, else silence."""
    found = []
    for item in items:
        lesson, score = rule(cands[item.item_id])
        found.append(Choice(item.item_id, lesson if score >= threshold else None, score))
    return found


def best_safe(
    items, cands, rules: dict[str, Rule], grid: Sequence[float]
) -> tuple[str, float] | None:
    """The (rule, threshold) with the highest pick among safe points on these items."""
    best, best_pick = None, -1.0
    for name, rule in rules.items():
        for threshold in grid:
            rates = outcome_rates(items, decide(items, cands, rule, threshold))
            if safe(rates) and rates["pick"] > best_pick:
                best, best_pick = (name, threshold), rates["pick"]
    return best


def two_d_rules() -> dict[str, Rule]:
    """The ranker's top lesson, scored 0 or 1 by whether its IDF score reaches each cut; the
    P(yes) threshold is applied after, so (cut, threshold) is a 2-D threshold."""

    def gated(cut: float) -> Rule:
        def rule(shortlist):
            lesson, p_yes, idf = shortlist[0]
            return lesson, p_yes if idf >= cut else -1.0

        return rule

    return {f"idf>={cut}": gated(cut) for cut in IDF_GRID}


def logit(probability: float) -> float:
    """Log-odds, clipped away from 0 and 1."""
    clipped = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(clipped / (1 - clipped))


def fitted_logistic(items, cands: Candidates) -> Rule:
    """A logistic over (judge log-odds, ranker score, 1 / rank) fitted on these items' pairs."""
    rows, labels = [], []
    for item in items:
        right = item.applies.lesson_id if item.applies else None
        for rank, (lesson, p_yes, idf) in enumerate(cands[item.item_id]):
            rows.append([logit(p_yes), idf / 10, 1 / (rank + 1), 1.0])
            labels.append(1.0 if lesson == right else 0.0)
    weights = gradient_fit(np.array(rows), np.array(labels))

    def rule(shortlist):
        scored = [
            (
                lesson,
                float(1 / (1 + np.exp(-np.dot(weights, [logit(p), idf / 10, 1 / (r + 1), 1.0])))),
            )
            for r, (lesson, p, idf) in enumerate(shortlist)
        ]
        return max(scored, key=lambda entry: entry[1])

    return rule


def gradient_fit(features: np.ndarray, labels: np.ndarray, steps: int = 3000) -> np.ndarray:
    """L2-regularized logistic regression by plain gradient descent."""
    weights = np.zeros(features.shape[1])
    for _ in range(steps):
        predicted = 1 / (1 + np.exp(-features @ weights))
        weights -= 0.5 * (features.T @ (predicted - labels) / len(labels) + 1e-3 * weights)
    return weights


def forms(train_items, cands) -> dict[str, tuple[dict[str, Rule], Sequence[float]]]:
    """Each form's rules and threshold grid (the logistic is fitted on train_items)."""
    return {
        "judge_alone": ({"judge": judge_top(SHORTLIST)}, GRID),
        **{f"judge_top{k}": ({f"top{k}": judge_top(k)}, GRID) for k in (1, 2, 3)},
        "two_d_threshold": (two_d_rules(), GRID),
        "logistic": ({"logistic": fitted_logistic(train_items, cands)}, GRID),
    }


def fold_of(repo: str) -> int:
    """A repository's cross-validation fold, by a stable hash of its name."""
    return zlib.crc32(repo.encode()) % FOLDS


def read_at(items, cands, rules, choice) -> dict:
    """Rates of one (rule, threshold) on items, or a status if no safe point was found."""
    if choice is None:
        return {"status": "no safe point"}
    name, threshold = choice
    rates = outcome_rates(items, decide(items, cands, rules[name], threshold))
    return {"rule": name, "threshold": threshold, **{k: round(v, 4) for k, v in rates.items()}}


def cross_validated(items, repo_of, cands, form: str) -> dict:
    """Pooled choices over the 5 folds, each fold read at the point fitted on the other four."""
    choices = []
    for fold in range(FOLDS):
        train = [i for i in items if fold_of(repo_of[i.item_id]) != fold]
        test = [i for i in items if fold_of(repo_of[i.item_id]) == fold]
        rules, grid = forms(train, cands)[form]
        point = best_safe(train, cands, rules, grid)
        if point is None:
            choices += [Choice(i.item_id, None, 0.0) for i in test]
            continue
        choices += decide(test, cands, rules[point[0]], point[1])
    rates = outcome_rates(items, choices)
    return {k: round(v, 4) for k, v in rates.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    items, repo_of = load_items(args.work, "scored")
    scores = seed_mean_scores([args.work / "scores" / f"scored-judge-s{s}.jsonl" for s in range(3)])
    cands = candidates(items, scores)
    found = {}
    for form, (rules, grid) in forms(items, cands).items():
        found[form] = {
            "in_sample": read_at(items, cands, rules, best_safe(items, cands, rules, grid)),
            "cross_validated": cross_validated(items, repo_of, cands, form),
        }
    document = {
        "status": "exploratory, round 3's 40 scored repos as validation, no training",
        **found,
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(json.dumps(found, indent=1))


if __name__ == "__main__":
    main()
