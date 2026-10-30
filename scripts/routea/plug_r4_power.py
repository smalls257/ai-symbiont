"""Plug round 4 power numbers measured on validation: the paired per-repo SD of the agree rule's
pick gain over the round 3 judge alone, the intraclass correlation of wrong picks, and the MDE.

Usage: uv run python scripts/routea/plug_r4_power.py --work R3 --out F

The rule is read by nested repo-fold CV, the judge alone at its frozen threshold, twins merged.
MDE = (1.96 + 0.84) * SD / sqrt(n); the SD is scaled from validation's pick items per repo
to the scored set's (251 / 89).
"""

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_judge_cli import seed_mean_scores  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_r4_combine import candidates, decide, judge_top  # noqa: E402
from plug_r4_combo import merged_candidates  # noqa: E402
from plug_r4_matched import nested_choices, rounded  # noqa: E402

SCORED_PICKS, SCORED_REPOS = 251, 89
FROZEN_THRESHOLD = (
    0.99  # amendment 1: the 3-seed judge's threshold, applied as deployed, never refit
)
SHORTLIST = 10
Z_ALPHA_POWER = 1.96 + 0.84


def per_repo_pick(items, repo_of, choices) -> dict:
    """Repo -> right picks over its pick items."""
    by_item = {c.item_id: c.lesson_id for c in choices}
    hits: dict[str, list[int]] = {}
    for item in items:
        if item.applies is not None:
            hits.setdefault(repo_of[item.item_id], []).append(
                int(by_item[item.item_id] == item.applies.lesson_id)
            )
    return {repo: sum(v) / len(v) for repo, v in hits.items()}


def wrong_flags(items, repo_of, choices) -> dict:
    """Repo -> 0/1 wrong-answer flags over all its items (negatives included)."""
    by_item = {c.item_id: c.lesson_id for c in choices}
    flags: dict[str, list[int]] = {}
    for item in items:
        chosen = by_item[item.item_id]
        right = item.applies is not None and chosen == item.applies.lesson_id
        flags.setdefault(repo_of[item.item_id], []).append(int(chosen is not None and not right))
    return flags


def icc(groups: dict) -> float:
    """One-way ANOVA intraclass correlation of 0/1 flags grouped by repo."""
    values = [x for g in groups.values() for x in g]
    total, repos = len(values), len(groups)
    mean = sum(values) / total
    between = sum(len(g) * (sum(g) / len(g) - mean) ** 2 for g in groups.values()) / (repos - 1)
    within = sum((x - sum(g) / len(g)) ** 2 for g in groups.values() for x in g) / (total - repos)
    size = (total - sum(len(g) ** 2 for g in groups.values()) / total) / (repos - 1)
    spread = between + (size - 1) * within
    return max(0.0, (between - within) / spread) if spread else 0.0  # no wrong picks: no clustering


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    items, repo_of = load_items(args.work, "scored")
    scores = seed_mean_scores([args.work / "scores" / f"scored-judge-s{s}.jsonl" for s in range(3)])
    cands = merged_candidates(items, candidates(items, scores))
    rule, _ = nested_choices(items, repo_of, cands)
    alone = decide(items, cands, judge_top(SHORTLIST), FROZEN_THRESHOLD)
    with_rule, without = per_repo_pick(items, repo_of, rule), per_repo_pick(items, repo_of, alone)
    diffs = [with_rule[r] - without[r] for r in with_rule]
    mean = sum(diffs) / len(diffs)
    sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1))
    picks_per_repo = sum(1 for i in items if i.applies) / len(with_rule)
    sd_scored = sd * math.sqrt(picks_per_repo / (SCORED_PICKS / SCORED_REPOS))
    found = {
        "validation_repos": len(with_rule),
        "per_repo_mean_coverage_rule": round(sum(with_rule.values()) / len(with_rule), 4),
        "per_repo_mean_coverage_judge_alone": round(sum(without.values()) / len(without), 4),
        "pooled_rule": rounded(items, rule),
        "pooled_judge_alone": rounded(items, alone),
        "mean_gain_rule_over_judge_alone": round(mean, 4),
        "paired_sd_per_repo": round(sd, 4),
        "paired_sd_scaled_to_scored": round(sd_scored, 4),
        "mde_89_repos": round(Z_ALPHA_POWER * sd_scored / math.sqrt(SCORED_REPOS), 4),
        "wrong_pick_icc": round(icc(wrong_flags(items, repo_of, rule)), 4),
    }
    args.out.write_text(json.dumps(found, indent=1) + "\n")
    print(json.dumps(found, indent=1))


if __name__ == "__main__":
    main()
