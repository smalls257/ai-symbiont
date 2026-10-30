"""Plug round 4's general-judge arm: the judge trained on mined real repeats, with the agree rule.

Usage: uv run python scripts/routea/plug_r4_general_arm.py STAGE ...  (fit, pins, decide)
Usage: fit: --work --scores --out; pins: --model --selection --out
Usage: decide: --primary --adapters --selection-r3 --pins --scores --model --selection --gpins --out

Its weights and validation-fitted point are pinned; it is judged against the round 3 judge alone
at the frozen 0.99.
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
    claim,
    read_scores,
    sha256_of,
    summarize,
)
from plug_situation import item_from  # noqa: E402


def fit_general(work: Path, scores_file: Path) -> dict:
    """The arm's agree-rule point from validation: nested-CV stricter target, then the fit."""
    items, repo_of = load_items(work, "scored")
    scores = seed_mean_scores([scores_file])
    cands = merged_candidates(items, candidates(items, scores))
    target = inner_target(items, repo_of, cands, list(range(FOLDS)))
    point = fit_at(items, cands, target)
    if point is None:
        raise PinMismatchError("no safe agree-rule point for the general judge on validation")
    return {"target": target, "rule": point[0], "threshold": point[1]}


def general_pins(model: Path, selection: Path) -> dict:
    """The arm's weight hash and selection hash."""
    return {
        "general_model": sha256_of(model / "model.safetensors"),
        "general_selection": sha256_of(selection),
    }


def read_general(directory: Path, queries: Path) -> dict[str, float]:
    """The general judge's P(yes) per primary query; missing or partial files raise."""
    path = directory / "primary-general.jsonl"
    if not path.exists():
        raise PinMismatchError("missing primary-general.jsonl")
    scores = seed_mean_scores([path])
    wanted = {json.loads(x)["question_id"] for x in queries.read_text().splitlines()}
    if set(scores) != wanted or any(not 0.0 <= v <= 1.0 for v in scores.values()):
        raise PinMismatchError("general scores do not cover exactly the primary queries")
    return scores


def run_decide(args: argparse.Namespace) -> dict:
    """Check both pin sets, then the arm against the round 3 judge alone."""
    check(args.primary, args.adapters, args.selection_r3, args.pins)
    if general_pins(args.model, args.selection) != json.loads(args.gpins.read_text()):
        raise PinMismatchError("general model or selection differs from its pins")
    records = [
        json.loads(x) for x in (args.primary / "primary-items.jsonl").read_text().splitlines()
    ]
    items = [item_from(r) for r in records]
    repo_of = {r["question_id"]: r["repo"] for r in records}
    queries = args.primary / "primary-queries.jsonl"
    r3 = merged_candidates(items, candidates(items, read_scores(args.scores, queries)))
    gen = merged_candidates(items, candidates(items, read_general(args.scores, queries)))
    selection = json.loads(args.selection.read_text())
    rule_of = two_d_rules()[selection["rule"]]
    alone = decide(items, r3, judge_top(SHORTLIST), FROZEN_JUDGE_THRESHOLD)
    rule = decide(items, gen, rule_of, selection["threshold"])
    found = summarize(items, repo_of, alone, rule, decide(items, gen, rule_of, 0.0))
    arm = "the judge trained on mined real repeats with the ranker agreeing"
    return {**found, "claim": claim(found, arm, "the round 3 judge alone")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    flags = {
        "fit": ("work", "scores", "out"),
        "pins": ("model", "selection", "out"),
        "decide": (
            "primary",
            "adapters",
            "selection-r3",
            "pins",
            "scores",
            "model",
            "selection",
            "gpins",
            "out",
        ),
    }
    for name, names in flags.items():
        sub = stages.add_parser(name)
        for flag in names:
            sub.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "fit":
        result = fit_general(args.work, args.scores)
    elif args.stage == "pins":
        result = general_pins(args.model, args.selection)
    else:
        result = run_decide(args)
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
