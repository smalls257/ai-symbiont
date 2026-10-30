"""Plug round 3's scored stage (prereg/2026-10-29-plug-judge.md): every row, H1, the gates, the
secondaries and the claim sentence, at the thresholds `plug_r3_run.py fit` wrote.

Usage: uv run python scripts/routea/plug_r3_score.py --work B --judge S0 S1 S2 --seen E0 E1 E2
Usage:   --untrained U --plain-answers A --habits H0 H1 H2 --untrained-habits UH --out F

It raises if the judge had no safe point on validation, or if any input file is missing.
"""

import argparse
import json
import sys
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug import lesson_key  # noqa: E402
from plug_judge import Choice  # noqa: E402
from plug_judge_cli import _answers, seed_mean_scores  # noqa: E402
from plug_r3 import per_repo, ranker_choices, source_of, subset_rates, wrong_from  # noqa: E402
from plug_r3_decide import (  # noqa: E402
    claim,
    h1,
    habits_gate,
    new_lesson_gate,
    safety_gate,
    versus_alone,
)
from plug_r3_run import judged, load_items  # noqa: E402
from plug_situation import Item, item_from  # noqa: E402
from plug_v2conf import named_lesson  # noqa: E402
from warm_start import _read_jsonl  # noqa: E402

ROLES = {  # the prereg's rows table
    "judge": "under_test",
    "ranker_threshold": "reference",
    "ranker_alone": "reference",
    "untrained_1b": "floor",
    "plain_1b": "floor",
}
MEASURES = ("pick", "silence", "wrong_pick", "coverage")


def row_cells(args: argparse.Namespace, thresholds: dict) -> dict[str, dict]:
    """Per-repo rates of every row that has a threshold (or needs none)."""
    items, repo_of = load_items(args.work, "scored")
    picks = {
        "judge": partial(judged, items, seed_mean_scores(args.judge)),
        "ranker_threshold": partial(ranker_choices, items),
        "untrained_1b": partial(judged, items, seed_mean_scores([args.untrained])),
    }
    cells = {
        row: per_repo(items, pick(thresholds[row]), repo_of)
        for row, pick in picks.items()
        if thresholds[row] is not None
    }
    cells["ranker_alone"] = per_repo(items, ranker_choices(items, float("-inf")), repo_of)
    top5 = [item_from(r) for r in _read_jsonl(args.work / "scored-top5.jsonl")]
    answers = _answers(args.plain_answers)
    plain = [judged_note(item, answers[item.item_id]) for item in top5]
    cells["plain_1b"] = per_repo(top5, plain, repo_of)
    return cells


def judged_note(item: Item, answer: str) -> Choice:
    """The plain model's answer as a choice: the lesson its note names, or silence."""
    return Choice(item.item_id, named_lesson(item, answer), 0.0)


def mean_rates(cells: dict[str, dict]) -> dict[str, dict]:
    """Each row's per-repo mean of every measure (each repo weighs the same), except precision:
    right over answered, pooled over items, and None if the row answered nothing."""
    found = {}
    for row, repos in cells.items():
        found[row] = {m: round(sum(c[m] for c in repos.values()) / len(repos), 4) for m in MEASURES}
        answered = sum(c["answered"] for c in repos.values())
        right = sum(c["precision"] * c["answered"] for c in repos.values())
        found[row]["precision"] = round(right / answered, 4) if answered else None
    return found


def seed_safety(args: argparse.Namespace, seed_thresholds: list) -> list[dict]:
    """Each seed alone at its own validation threshold: its H2, flagged if it fails."""
    items, repo_of = load_items(args.work, "scored")
    found = []
    for seed, (path, threshold) in enumerate(zip(args.judge, seed_thresholds, strict=True)):
        if threshold is None:
            found.append({"seed": seed, "passes": False, "status": "no safe point on validation"})
            continue
        choices = judged(items, seed_mean_scores([path]), threshold)
        found.append(
            {"seed": seed, "threshold": threshold, **safety_gate(per_repo(items, choices, repo_of))}
        )
    return found


def novelty(args: argparse.Namespace, threshold: float) -> dict:
    """Secondaries on new lessons: rates on lessons whose failure key never occurs in meta-train,
    the share of wrong picks that chose a meta-train lesson, and the seen set's per-repo rates."""
    meta = json.loads((args.work / "meta.json").read_text())
    keys = {(kind, tuple(tokens)) for kind, tokens in meta["keys"]}
    items, _ = load_items(args.work, "scored")
    choices = judged(items, seed_mean_scores(args.judge), threshold)
    source = source_of([i.applies for i in items if i.applies is not None])
    seen, seen_repo = load_items(args.work, "seen")
    return {
        "new_key_lessons": subset_rates(
            items, choices, lambda item: lesson_key(source(item)) not in keys
        ),
        "wrong_picks_of_meta_lessons": wrong_from(items, choices, set(meta["lesson_ids"])),
        "seen_cells": per_repo(
            seen, judged(seen, seed_mean_scores(args.seen), threshold), seen_repo
        ),
    }


def habit_rate(path: Path) -> tuple[float, int]:
    """Hit rate and question count of one `rank_habits_torch.py` output."""
    rows = _read_jsonl(path)
    return sum(row["hit"] for row in rows) / len(rows), len(rows)


def score(args: argparse.Namespace) -> dict:
    """The scored document: rows, per-repo rows, decisions, secondaries and the claim."""
    selection = json.loads((args.work / "selection.json").read_text())
    thresholds = selection["thresholds"]
    if thresholds["judge"] is None:
        raise ValueError("the judge had no safe point on validation, so there is no scored run")
    cells = row_cells(args, thresholds)
    means = mean_rates(cells)
    found = novelty(args, thresholds["judge"])
    rates = [habit_rate(path) for path in args.habits]
    untrained, questions = habit_rate(args.untrained_habits)
    gates = {
        "safety": safety_gate(cells["judge"]),
        "habits": habits_gate(sum(r for r, _ in rates) / len(rates), untrained, questions),
        "new lessons": new_lesson_gate(cells["judge"], found.pop("seen_cells")),
    }
    first = h1(cells["judge"], cells.get("ranker_threshold"))
    return {
        **json.loads((args.work / "provenance.json").read_text()),
        "thresholds": thresholds,
        "rows": [{"arm": row, "role": ROLES[row], **means[row]} for row in cells],
        "per_repo_rows": [
            {"arm": row, "repo": r, **c} for row in cells for r, c in cells[row].items()
        ],
        "h1": first,
        "gates": gates,
        "secondary": {
            "versus_ranker_alone": versus_alone(cells["judge"], cells["ranker_alone"]),
            "per_seed_safety": seed_safety(args, selection["judge_seed_thresholds"]),
            **found,
        },
        "result": claim(first, gates, means),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--work", "--untrained", "--plain-answers", "--untrained-habits", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    for flag in ("--judge", "--seen", "--habits"):
        parser.add_argument(flag, type=Path, nargs=3, required=True)
    args = parser.parse_args()
    document = score(args)
    args.out.write_text(json.dumps(document, indent=1, sort_keys=True))
    print(document["result"])


if __name__ == "__main__":
    main()
