"""Exploratory, after round 3's scored run: lessons added after training against trained lessons,
with the frozen round-3 adapters and thresholds, beside the ranker. No retraining, no new answers.

Usage: uv run python scripts/routea/plug_r3_after.py --work B --out F

New: the 40 scored repos' items (every lesson added after the judge was frozen, situations never
seen). Trained: the 60 meta-train repos' items under the seen-set wording (lessons the judge
trained on, in a wording no training row used). Both read the scores `plug_r3.sh scored` wrote.
"""

import argparse
import json
import sys
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_judge import outcome_rates  # noqa: E402
from plug_judge_cli import seed_mean_scores  # noqa: E402
from plug_r3 import per_repo, ranker_choices  # noqa: E402
from plug_r3_run import judged, load_items  # noqa: E402
from plug_r4_combine import without_twins  # noqa: E402
from warm_start import paired_gain  # noqa: E402

SETS = {  # label: bundle split; the last needs `plug_r3_trained.py` and one more GPU pass
    "new": "scored",
    "trained": "seen",
    "trained_own_wording": "trained",
}
SEEDS = (0, 1, 2)


def arm_rates(items: list, repo_of: dict, choose) -> dict:
    """Item-pooled rates and per-repo pick with a bootstrap interval over repos."""
    choices = choose()
    cells = per_repo(items, choices, repo_of)
    return {
        **{key: round(value, 4) for key, value in outcome_rates(items, choices).items()},
        "per_repo_pick": paired_gain([cell["pick"] for cell in cells.values()]),
    }


def one_set(work: Path, split: str, thresholds: dict, select=list) -> dict:
    """The judge, thresholded ranker and ranker alone on one split's items."""
    items, repo_of = load_items(work, split)
    items = select(items)  # round 4 passes `without_twins` to drop items with a twin lesson
    scores = seed_mean_scores([work / "scores" / f"{split}-judge-s{seed}.jsonl" for seed in SEEDS])
    arms = {
        "judge": partial(judged, items, scores, thresholds["judge"]),
        "ranker_threshold": partial(ranker_choices, items, thresholds["ranker_threshold"]),
        "ranker_alone": partial(ranker_choices, items, float("-inf")),
    }
    return {
        "repos": len(set(repo_of.values())),
        "items": len(items),
        **{arm: arm_rates(items, repo_of, choose) for arm, choose in arms.items()},
    }


def scored_set(work: Path, split: str, thresholds: dict, select) -> dict:
    """`one_set`, or a plain status if that split's judge scores are not there yet."""
    if not (work / "scores" / f"{split}-judge-s0.jsonl").exists():
        return {"status": f"not scored yet: no {split}-judge-s0.jsonl"}
    return one_set(work, split, thresholds, select)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--twin-free", action="store_true", help="drop items with a twin lesson")
    args = parser.parse_args()
    thresholds = json.loads((args.work / "selection.json").read_text())["thresholds"]
    document = {
        "status": "exploratory, after the frozen round-3 scored run, no prereg",
        "source": "round-3 adapters judge-s0 to s2 at amendment 1's thresholds",
        **{
            label: scored_set(
                args.work, split, thresholds, without_twins if args.twin_free else list
            )
            for label, split in SETS.items()
        },
        "twin_free": args.twin_free,
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(json.dumps(document, indent=1))


if __name__ == "__main__":
    main()
