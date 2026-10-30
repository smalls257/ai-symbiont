"""Plug round 4's floors: a RAG-style similarity cutoff with no judge, and the untrained 1B judge.

Usage: uv run python scripts/routea/plug_r4_floors.py fit --work R3 --out F
Usage: uv run python scripts/routea/plug_r4_floors.py decide --primary D --adapters A \\
Usage:   --selection-r3 S --pins P --scores D --floors F --fpins FP --untrained U --out R

Why: "training beats retrieval" needs the two floors on the same primary items. The RAG floor
answers the ranker's top lesson when its similarity reaches a cut; the untrained floor is the
same judge prompt with no adapter under the agree rule. Cuts are fitted on validation only
(nested repo-fold CV at wrong <= 0.05). Each floor is read against the agree rule and the judge.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_judge_cli import seed_mean_scores  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_r4_combine import FOLDS, candidates, decide, judge_top, two_d_rules  # noqa: E402
from plug_r4_combo import merged_candidates  # noqa: E402
from plug_r4_matched import fit_at, inner_target  # noqa: E402
from plug_r4_scored import (  # noqa: E402
    FROZEN_JUDGE_THRESHOLD,
    SHORTLIST,
    PinMismatchError,
    check,
    read_scores,
    sha256_of,
    summarize,
)
from plug_situation import item_from  # noqa: E402
from warm_start import _read_jsonl  # noqa: E402


def fitted(items, repo_of, cands) -> dict:
    """The agree-rule point on these shortlists: nested-CV stricter target, then the fit."""
    target = inner_target(items, repo_of, cands, list(range(FOLDS)))
    point = fit_at(items, cands, target)
    if point is None:
        raise PinMismatchError("no safe floor point on validation")
    return {"target": target, "rule": point[0], "threshold": point[1]}


def always_yes(items, scores_like) -> dict:
    """Scores of 1.0 for every pair: the similarity cut alone decides (no judge)."""
    return {key: 1.0 for key in scores_like}


def fit_floors(work: Path) -> dict:
    """Both floors' points from round 3's scored repositories (validation here)."""
    items, repo_of = load_items(work, "scored")
    untrained = seed_mean_scores([work / "scores" / "scored-untrained.jsonl"])
    rag = merged_candidates(items, candidates(items, always_yes(items, untrained)))
    return {
        "rag_floor": fitted(items, repo_of, rag),
        "untrained_1b": fitted(
            items, repo_of, merged_candidates(items, candidates(items, untrained))
        ),
    }


def read_untrained(path: Path, queries: Path) -> dict[str, float]:
    """The untrained judge's P(yes) on exactly the primary queries; anything else raises."""
    scores = seed_mean_scores([path])
    wanted = {json.loads(x)["question_id"] for x in queries.read_text().splitlines()}
    if set(scores) != wanted or any(not 0.0 <= v <= 1.0 for v in scores.values()):
        raise PinMismatchError("untrained scores do not cover exactly the primary queries")
    return scores


def run_decide(args: argparse.Namespace) -> dict:
    """Check the primary pins, then each floor against the agree rule and the judge alone."""
    check(args.primary, args.adapters, args.selection_r3, args.pins)
    if {"floors_selection": sha256_of(args.floors)} != json.loads(args.fpins.read_text()):
        raise PinMismatchError("the floors selection differs from its pins")
    records = _read_jsonl(args.primary / "primary-items.jsonl")
    items = [item_from(r) for r in records]
    repo_of = {r["question_id"]: r["repo"] for r in records}
    queries = args.primary / "primary-queries.jsonl"
    ref_sel = json.loads(args.selection_r3.read_text())
    floors = json.loads(args.floors.read_text())
    r3 = merged_candidates(items, candidates(items, read_scores(args.scores, queries)))
    unt = read_untrained(args.untrained, queries)
    base = {
        "agree_rule": decide(items, r3, two_d_rules()[ref_sel["rule"]], ref_sel["threshold"]),
        "judge_alone": decide(items, r3, judge_top(SHORTLIST), FROZEN_JUDGE_THRESHOLD),
    }
    cands = {
        "rag_floor": merged_candidates(items, candidates(items, always_yes(items, unt))),
        "untrained_1b": merged_candidates(items, candidates(items, unt)),
    }
    found = {}
    for name, sel in floors.items():
        floor = decide(items, cands[name], two_d_rules()[sel["rule"]], sel["threshold"])
        for against, comparator in base.items():
            found[f"{name}_vs_{against}"] = summarize(items, repo_of, comparator, floor, floor)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    flags = {
        "fit": ("work", "out"),
        "decide": (
            "primary",
            "adapters",
            "selection-r3",
            "pins",
            "scores",
            "floors",
            "fpins",
            "untrained",
            "out",
        ),
    }
    for name, names in flags.items():
        sub = stages.add_parser(name)
        for flag in names:
            sub.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    result = fit_floors(args.work) if args.stage == "fit" else run_decide(args)
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1)[:1500])


if __name__ == "__main__":
    main()
