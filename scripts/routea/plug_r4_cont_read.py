"""Plug round 4 continuous training, readout: both arms against the fair reference.

Usage: uv run python scripts/routea/plug_r4_cont_read.py --work R3 --cont O --combo C \
Usage:   --spark S --out F

Arms: reference (round 3 judge + agree rule), the nightly judge at strengths 1 and 0.5, and a
retrained ranker with the judge frozen; nested repo-fold CV at wrong pick <= 0.05.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from dataclasses import replace  # noqa: E402

from plug_judge_cli import seed_mean_scores  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_r4_combine import candidates, fold_of, gradient_fit  # noqa: E402
from plug_r4_combo import habit_mean, joined_scores, merged_candidates  # noqa: E402
from plug_r4_eval import accepted  # noqa: E402
from plug_r4_matched import nested_choices, rounded  # noqa: E402
from plug_situation import lexical_rank, lexical_scores  # noqa: E402
from warm_start import _read_jsonl  # noqa: E402

SITUATION = re.compile(r"Ran `(.*)` in \S+ \(file (.*?)\)\. It failed: (.*)$", re.S)
RANKER_SCALE = 30.0  # logistic probability times this lands on the rule's 0 to 30 cut grid


def pair_features(situation: str, lesson, idf: float) -> list[float]:
    """The learned ranker's inputs for one (situation, lesson): its own IDF score and four exact
    agreements between the failure and the lesson."""
    found = SITUATION.match(situation)
    command, file, error = found.groups() if found else ("", "", "")
    return [
        idf,
        float(lesson.error_class in error),
        float(lesson.failed.split()[:1] == command.split()[:1]),
        float(lesson.file == file),
        float(lesson.error == error),
    ]


def fit_ranker(rows: list[tuple[list[float], int]]) -> np.ndarray:
    """Logistic weights (bias first) on the teacher-labeled pairs."""
    features = np.array([[1.0, *x] for x, _ in rows])
    return gradient_fit(features, np.array([y for _, y in rows], dtype=float))


def score_with(weights: np.ndarray, features: list[float]) -> float:
    """The ranker's score on the rule's 0 to 30 grid."""
    logit = float(weights @ np.array([1.0, *features]))
    return RANKER_SCALE / (1.0 + math.exp(-logit))


def pair_rows(pairs: list[dict], labels: dict, lessons: dict) -> list[tuple[str, list, int]]:
    """(repo, features, label) for every labeled pair whose lesson is known."""
    return [
        (
            p["repo"],
            pair_features(p["situation"], lessons[p["lesson_id"]], p["idf"]),
            int(labels[p["pair_id"]] == "yes"),
        )
        for p in pairs
        if p["pair_id"] in labels and p["lesson_id"] in lessons
    ]


def invented_rows(items, repo_of, invented: dict, per_lesson: int = 5) -> list:
    """(repo, features, label): the teacher's real-failure labels are all "no", so the ranker's
    positives come from Spark-invented situations of each lesson (its own lesson yes, two other
    shortlisted lessons no)."""
    rows = []
    for item in items:
        if item.applies is None:
            continue
        repo = repo_of[item.item_id]
        for situation in invented.get(item.applies.lesson_id, [])[:per_lesson]:
            idf = lexical_scores(replace(item, situation=situation))
            ranked = lexical_rank(replace(item, situation=situation))[:3]
            rows.append(
                (repo, pair_features(situation, item.applies, idf[item.applies.lesson_id]), 1)
            )
            rows.extend(
                (repo, pair_features(situation, other, idf[other.lesson_id]), 0)
                for other in ranked
                if other.lesson_id != item.applies.lesson_id
            )
    return rows


def retrained_cands(items, repo_of, cands, rows) -> dict:
    """Each shortlist re-ordered by a ranker trained on the other folds' labeled pairs."""
    weights = {}
    for fold in range(5):
        train = [(x, y) for repo, x, y in rows if fold_of(repo) != fold]
        weights[fold] = fit_ranker(train)
    by_id = {x.lesson_id: x for item in items for x in item.prompt_lessons}
    out = {}
    for item in items:
        idf = lexical_scores(item)
        fold_weights = weights[fold_of(repo_of[item.item_id])]
        scored = [
            (lid, p, score_with(fold_weights, pair_features(item.situation, by_id[lid], idf[lid])))
            for lid, p, _ in cands[item.item_id]
        ]
        out[item.item_id] = sorted(scored, key=lambda entry: (-entry[2], entry[0]))
    return out


def arm(items, repo_of, cands) -> dict:
    """Nested-CV outer rates of the agree rule over these shortlists."""
    outer, _ = nested_choices(items, repo_of, merged_candidates(items, cands))
    return rounded(items, outer)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--work", "--cont", "--combo", "--spark", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args()
    items, repo_of = load_items(args.work, "scored")
    r3 = seed_mean_scores([args.work / "scores" / f"scored-judge-s{s}.jsonl" for s in range(3)])
    base = candidates(items, r3)
    found = {"reference_round3_judge_agree_rule": arm(items, repo_of, base)}
    folder = args.combo / "scores-habits10"
    for scale in ("1", "0.5"):
        scores = joined_scores(folder, scale)
        found[f"continuous_judge_strength_{scale}"] = {
            **arm(items, repo_of, candidates(items, scores)),
            "habits_mean": habit_mean(folder, scale),
        }
    lessons = {x.lesson_id: x for i in items for x in i.prompt_lessons}
    labels = {
        r["pair_id"]: r["label"] for r in _read_jsonl(args.cont / "labels.jsonl") if "label" in r
    }
    invented = accepted(args.spark / "invent-val40.jsonl", "situations")
    rows = pair_rows(_read_jsonl(args.cont / "pairs.jsonl"), labels, lessons)
    rows += invented_rows(items, repo_of, invented)
    found["ranker_retrained_judge_frozen"] = arm(
        items, repo_of, retrained_cands(items, repo_of, base, rows)
    )
    found["labeled_pairs"] = len(rows)
    args.out.write_text(json.dumps(found, indent=1) + "\n")
    print(json.dumps(found, indent=1))


if __name__ == "__main__":
    main()
