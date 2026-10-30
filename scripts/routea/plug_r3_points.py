"""Exploratory, validation repos only: two operating points of the 1B judge's precision-coverage
curve on the 5 held-out validation repos (the upper half by name hash, as in the exploration).

Usage: uv run python scripts/routea/plug_r3_points.py --items V --judge S0 S1 S2 --out F

Each point is the lowest grid threshold meeting its limit on those repos' own curve, so it reads
the curve and is not a transfer test. Intervals: a bootstrap over the 5 repos, and a Wilson
interval over the applicable situations.
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
from plug_judge_cli import GRID, seed_mean_scores  # noqa: E402
from plug_r3 import per_repo  # noqa: E402
from plug_r3_decide import wilson  # noqa: E402
from plug_r3_run import judged  # noqa: E402
from plug_round2 import name_hash  # noqa: E402
from plug_situation import item_from  # noqa: E402
from warm_start import _read_jsonl, paired_gain  # noqa: E402

LIMITS = {  # point name: the limit its threshold must meet on the held-out repos
    "wrong_pick_at_most_0.05": lambda rates: rates["wrong_pick"] <= 0.05,
    "silence_at_least_0.90": lambda rates: rates["silence"] >= 0.90,
}


def held_out(path: Path) -> tuple[list, dict[str, str]]:
    """The validation items of the upper half of repos by name hash, and each item's repo."""
    records = _read_jsonl(path)
    repos = sorted({r["repo"] for r in records}, key=name_hash)
    held = set(repos[len(repos) // 2 :])
    kept = [r for r in records if r["repo"] in held]
    return [item_from(r) for r in kept], {r["question_id"]: r["repo"] for r in kept}


def point(items: list, repo_of: dict, choose, accept) -> dict:
    """The lowest grid threshold meeting `accept`, its rates and their intervals."""
    for threshold in sorted(GRID):
        choices = choose(threshold)
        rates = outcome_rates(items, choices)
        if accept(rates):
            cells = per_repo(items, choices, repo_of)
            applicable = sum(item.applies is not None for item in items)
            return {
                "threshold": threshold,
                **{key: round(value, 4) for key, value in rates.items()},
                "applicable_items": applicable,
                "coverage_wilson95": wilson(rates["coverage"], applicable),
                "pick_wilson95": wilson(rates["pick"], applicable),
                "repo_bootstrap95": {
                    m: paired_gain([c[m] for c in cells.values()])
                    for m in ("coverage", "pick", "precision", "wrong_pick", "silence")
                },
            }
    return {"threshold": None, "status": "no grid point meets the limit"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--judge", type=Path, nargs=3, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    items, repo_of = held_out(args.items)
    choose = partial(judged, items, seed_mean_scores(args.judge))
    document = {
        "status": "exploratory, validation repos only, no prereg",
        "source": "judge 1B of the round-3 exploration (618 rows, no rewordings or habits)",
        "held_out_repos": len(set(repo_of.values())),
        "held_out_items": len(items),
        **{name: point(items, repo_of, choose, accept) for name, accept in LIMITS.items()},
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    print(json.dumps(document, indent=1))


if __name__ == "__main__":
    main()
