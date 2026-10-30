"""Plug round 4 free check: where do wrong picks land, by who learned the chosen lesson?

Usage: uv run python scripts/routea/plug_r4_slice.py --work R3 --r4 R4 --combo C --out F

Reference = round 3's 3-seed judge with the two-threshold rule; arm = the combo's nightly
adapters at strengths 0.5 and 1.0 with the same rule. Both are read by repo-fold cross-validation,
twins merged. A wrong pick is split by the chosen lesson: the repo's own (the nightly adapter
trained on it), a base-training lesson (round 3's meta-train), or another scored repo's (nobody
trained on it). Rates are over all items. No training, no GPU.
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
from plug_r4_combine import candidates, cv_choices  # noqa: E402
from plug_r4_combo import joined_scores, merged_candidates  # noqa: E402

FORM = "two_d_threshold"


def owners(work: Path, items, repo_of: dict) -> tuple[dict, set]:
    """lesson id -> repo for scored lessons, and the set of base-training lesson ids."""
    own = {i.applies.lesson_id: repo_of[i.item_id] for i in items if i.applies}
    trained, _ = load_items(work, "trained")
    return own, {i.applies.lesson_id for i in trained if i.applies}


def classify(items, choices, repo_of, own: dict, base: set) -> dict:
    """Rates over all items: right, and wrong picks split by who learned the chosen lesson."""
    by_item = {c.item_id: c for c in choices}
    counts = {"right": 0, "wrong_repo_own": 0, "wrong_base_trained": 0, "wrong_other_repo": 0}
    for item in items:
        chosen = by_item[item.item_id].lesson_id
        if chosen is None:
            continue
        if item.applies is not None and chosen == item.applies.lesson_id:
            counts["right"] += 1
        elif own.get(chosen) == repo_of[item.item_id]:
            counts["wrong_repo_own"] += 1
        elif chosen in base:
            counts["wrong_base_trained"] += 1
        else:
            counts["wrong_other_repo"] += 1
    return {key: round(value / len(items), 4) for key, value in counts.items()}


def row(items, repo_of, scores, own, base) -> dict:
    """One scorer's cross-validated two-threshold choices, classified."""
    cands = merged_candidates(items, candidates(items, scores))
    return classify(items, cv_choices(items, repo_of, cands, FORM), repo_of, own, base)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--work", "--r4", "--combo", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    short, short_repo = load_items(args.work, "scored")
    rich, rich_repo = load_items(args.r4 / "rich", "scored")
    own, base = owners(args.work, short, short_repo)
    ref = seed_mean_scores([args.work / "scores" / f"scored-judge-s{s}.jsonl" for s in range(3)])
    found = {"reference_round3_judge_two_threshold": row(short, short_repo, ref, own, base)}
    for scale in ("0.5", "1"):
        scores = joined_scores(args.combo / "scores-habits10", scale)
        found[f"nightly_rich_scale_{scale}"] = row(rich, rich_repo, scores, own, base)
    args.out.write_text(json.dumps(found, indent=1) + "\n")
    print(json.dumps(found, indent=1))


if __name__ == "__main__":
    main()
