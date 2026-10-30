"""Plug round 4 decisive validation number: coverage at a matched wrong-pick rate.

Usage: uv run python scripts/routea/plug_r4_matched.py --work R3 --r4 R4 --combo C --out F

For each scorer (the fair reference, the nightly combo at strengths 0.5 and 1.0) the two-threshold
rule is fitted at a stricter in-sample wrong-pick target on four repo folds and read on the fifth.
The target is itself chosen by an inner repo-fold CV on the four training folds (nested), as the
largest-pick target whose inner CV wrong pick is at most 0.05, so no outer fold picks its own
target. Reported: pooled outer pick, wrong, silence, and the pick given up against target 0.05.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_judge import Choice, outcome_rates  # noqa: E402
from plug_judge_cli import GRID, seed_mean_scores  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_r4_combine import FOLDS, candidates, decide, fold_of, two_d_rules  # noqa: E402
from plug_r4_combo import joined_scores, merged_candidates  # noqa: E402

TARGETS = (0.02, 0.03, 0.04, 0.05)  # in-sample wrong-pick targets tried
LIMIT = 0.05  # the outcome limit on cross-validated wrong pick
SILENCE = 0.80


def fit_at(items, cands, target: float):
    """The (rule, threshold) with the highest pick on these items at wrong <= target, or None."""
    best, best_pick = None, -1.0
    for name, rule in two_d_rules().items():
        for threshold in GRID:
            rates = outcome_rates(items, decide(items, cands, rule, threshold))
            allowed = rates["silence"] >= SILENCE and rates["wrong_pick"] <= target
            if allowed and rates["pick"] > best_pick:
                best, best_pick = (name, threshold), rates["pick"]
    return best


def folded(items, repo_of, cands, target: float, parts: list[int]) -> list[Choice]:
    """Choices of each fold in `parts`, fitted on the other folds of `parts` at `target`."""
    choices = []
    for held in parts:
        train = [
            i
            for i in items
            if fold_of(repo_of[i.item_id]) in parts and fold_of(repo_of[i.item_id]) != held
        ]
        test = [i for i in items if fold_of(repo_of[i.item_id]) == held]
        point = fit_at(train, cands, target)
        if point is None:
            choices += [Choice(i.item_id, None, 0.0) for i in test]
        else:
            choices += decide(test, cands, two_d_rules()[point[0]], point[1])
    return choices


def inner_target(items, repo_of, cands, parts: list[int]) -> float:
    """The target with the best inner-CV pick among those with inner-CV wrong <= LIMIT."""
    chosen, best = TARGETS[0], -1.0
    seen = [i for i in items if fold_of(repo_of[i.item_id]) in parts]
    for target in TARGETS:
        rates = outcome_rates(seen, folded(seen, repo_of, cands, target, parts))
        if rates["wrong_pick"] <= LIMIT and rates["pick"] > best:
            chosen, best = target, rates["pick"]
    return chosen


def rounded(items, choices) -> dict:
    """Outcome rates of the choices, rounded."""
    return {k: round(v, 4) for k, v in outcome_rates(items, choices).items()}


def nested(items, repo_of, cands) -> dict:
    """Pooled outer-fold rates with a per-fold nested target, and the fixed-0.05 contrast."""
    outer, fixed = [], []
    for held in range(FOLDS):
        parts = [f for f in range(FOLDS) if f != held]
        target = inner_target(items, repo_of, cands, parts)
        train = [i for i in items if fold_of(repo_of[i.item_id]) != held]
        test = [i for i in items if fold_of(repo_of[i.item_id]) == held]
        for target_used, sink in ((target, outer), (0.05, fixed)):
            point = fit_at(train, cands, target_used)
            rule = two_d_rules()[point[0]] if point else None
            sink += (
                decide(test, cands, rule, point[1])
                if point
                else [Choice(i.item_id, None, 0.0) for i in test]
            )
    return {"nested_target": rounded(items, outer), "fixed_target_0.05": rounded(items, fixed)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--work", "--r4", "--combo", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    short, short_repo = load_items(args.work, "scored")
    rich, rich_repo = load_items(args.r4 / "rich", "scored")
    ref = seed_mean_scores([args.work / "scores" / f"scored-judge-s{s}.jsonl" for s in range(3)])
    found = {
        "reference_round3_judge": nested(
            short, short_repo, merged_candidates(short, candidates(short, ref))
        )
    }
    for scale in ("0.5", "1"):
        scores = joined_scores(args.combo / "scores-habits10", scale)
        cands = merged_candidates(rich, candidates(rich, scores))
        found[f"nightly_rich_scale_{scale}"] = nested(rich, rich_repo, cands)
    args.out.write_text(json.dumps(found, indent=1) + "\n")
    print(json.dumps(found, indent=1))


if __name__ == "__main__":
    main()
