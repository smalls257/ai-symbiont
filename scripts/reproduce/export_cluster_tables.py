"""Maintainer tool: write the per-cluster counts that let anyone rerun the headline bootstraps.

The study's statistic needs five counts per cluster and arm. This derives them from the saved
model scores with the study's own decision code; only counts and ids are written.
Needs the study's local artifacts, which are not in the repository.
Usage: uv run python scripts/reproduce/export_cluster_tables.py --plug-primary DIR --out FILE
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "routea"))

from plug_r4_combine import candidates, decide, judge_top, two_d_rules  # noqa: E402
from plug_r4_combo import merged_candidates  # noqa: E402
from plug_r4_primary_stats import repo_table  # noqa: E402
from plug_r4_scored import FROZEN_JUDGE_THRESHOLD, SHORTLIST, read_scores  # noqa: E402
from plug_r4_smith_decide import nightly_scores  # noqa: E402
from plug_situation import item_from  # noqa: E402
from warm_start import _read_jsonl  # noqa: E402

RESULTS = ROOT / "results"
COLUMNS = ["positives", "right", "items", "wrong", "answered"]


def table_of(items, cluster_of: dict, choices) -> dict[str, list[int]]:
    """Cluster -> [positives, right, items, wrong, answered] for one arm."""
    table = repo_table(items, cluster_of, choices)
    columns = [table.positives, table.right, table.items, table.wrong, table.answered]
    return {
        name: [int(column[index]) for column in columns] for index, name in enumerate(table.repos)
    }


def plug_primary(primary: Path, scores_dir: Path) -> dict:
    """Round 4 primary: judge alone and the agree rule, clustered by repository."""
    records = _read_jsonl(primary / "primary-items.jsonl")
    items = [item_from(r) for r in records]
    cluster_of = {r["question_id"]: r["repo"] for r in records}
    scores = read_scores(scores_dir, primary / "primary-queries.jsonl")
    chosen = json.loads((RESULTS / "plug-r4-selection.json").read_text())
    cands = merged_candidates(items, candidates(items, scores))
    alone = decide(items, cands, judge_top(SHORTLIST), FROZEN_JUDGE_THRESHOLD)
    agree = decide(items, cands, two_d_rules()[chosen["rule"]], chosen["threshold"])
    return {
        "cluster": "repository",
        "arms": {
            "judge_alone": table_of(items, cluster_of, alone),
            "agree_rule": table_of(items, cluster_of, agree),
        },
    }


def code_fix(items_dir: Path, scores_dir: Path, nightly_dir: Path) -> dict:
    """Code-fix study: judge alone, agree rule and nightly arm, clustered by task."""
    records = _read_jsonl(items_dir / "primary-items.jsonl")
    items = [item_from(r) for r in records]
    cluster_of = {r["question_id"]: r["task"] for r in records}
    repos = sorted({r["repo"] for r in records})
    base = read_scores(scores_dir, items_dir / "primary-queries.jsonl")
    plain = merged_candidates(items, candidates(items, base))
    night = merged_candidates(items, candidates(items, nightly_scores(nightly_dir, repos)))
    rules = [
        json.loads((RESULTS / name).read_text())
        for name in ("plug-r4-selection.json", "plug-r4-selection-nightly.json")
    ]
    alone = decide(items, plain, judge_top(SHORTLIST), FROZEN_JUDGE_THRESHOLD)
    agree = decide(items, plain, two_d_rules()[rules[0]["rule"]], rules[0]["threshold"])
    arm = decide(items, night, two_d_rules()[rules[1]["rule"]], rules[1]["threshold"])
    return {
        "cluster": "task",
        "arms": {
            "judge_alone": table_of(items, cluster_of, alone),
            "agree_rule": table_of(items, cluster_of, agree),
            "nightly": table_of(items, cluster_of, arm),
        },
    }


def main() -> None:
    """Write results/repro-cluster-tables.json (or --out)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("plug-primary", "plug-scores", "smith-items", "smith-scores", "smith-nightly"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    document = {
        "columns": COLUMNS,
        "note": "counts per cluster and arm; the study's bootstrap reruns on these",
        "plug-r4-primary": plug_primary(args.plug_primary, args.plug_scores),
        "code-fix": code_fix(args.smith_items, args.smith_scores, args.smith_nightly),
    }
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    sys.stdout.write(f"wrote {args.out}\n")


if __name__ == "__main__":
    main()
