"""Plug scored run (prereg/2026-10-29-l2l-a2.md): prepare rows and probes, then score and decide.

Usage: uv run python scripts/routea/plug_run.py prepare --work W
Usage: uv run python scripts/routea/plug_run.py score --work W --out results/l2l-a2.json

`prepare` refuses a plan whose counts differ from the prereg's table. `score` prints every row
(floors, references, a2, controls) and applies the frozen decision rule; a missing answer file
raises. The driver `plug_run.sh` trains, answers and ranks between the two stages.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parent / "aidev"))  # appended: routea's `lessons` must win

from l2l_quick import read_lessons  # noqa: E402
from lessons import Lesson  # noqa: E402
from plug import abstains, confabulates  # noqa: E402
from questions import Asks, lessons_prompt, training_messages  # noqa: E402
from score_habits import score as keyword_habits  # noqa: E402
from scoring import score, vocabulary  # noqa: E402
from warm_start import (  # noqa: E402
    _jsonl,
    _read_jsonl,
    answerer_provenance,
    paired_gain,
    probes,
    ranked_rate,
)

BUDGETS = (5, 10)
PRIMARY_BUDGET = 5
MIN_GAIN = 0.05  # `better` needs at least this mean gain (prereg, decision rule)
CONFAB_MEAN_BAR = 0.10  # a2's confabulation at 5 lessons: mean at most this (prereg, control)
CONFAB_UPPER_BAR = 0.20  # ... and the interval's upper bound below this
VALID_ROWS = 8
# The prereg's scored-repo table; `prepare` refuses a plan that differs.
SCORED = {
    "NCAS-CMS/cfdm": 10,
    "OSeMOSYS/otoole": 13,
    "ShawHahnLab/igseq": 11,
    "Unidata/MetPy": 19,
    "einsteinpy/einsteinpy": 12,
    "googleapis/python-spanner": 17,
    "googleapis/python-storage": 13,
    "hylang/hy": 17,
    "marcosschroh/dataclasses-avroschema": 12,
    "marshmallow-code/webargs": 10,
    "pennmem/cmlreaders": 29,
    "scipp/plopp": 18,
    "zopefoundation/zope.component": 19,
}
META_REPOS = 71
META_ROWS = 1469
META_DROPPED = 333  # rows over 1,300 characters dropped from meta-train (prereg)
SHARED_KEY_LESSONS = 5  # scored lessons whose failure key recurs in meta-train (prereg)
# Rows of the prereg's table: (name, label, lessons in the prompt).
ROWS = (
    ("floor_plain", "floor", "none"),
    ("floor_a2", "floor", "none"),
    ("a1", "reference", "own"),
    ("per_repo", "reference", "none"),
    ("a2", "under_test", "own"),
    ("a2_wrong", "control", "wrong"),
    ("a1_wrong", "control", "wrong"),
)


class PlanMismatchError(ValueError):
    """The plan differs from the prereg's table; names the difference."""


def check_plan(plan: dict) -> None:
    """Raise PlanMismatchError unless the plan reproduces the prereg's counts and pairing."""
    names = sorted(SCORED)
    pairing = {repo: names[(i + 1) % len(names)] for i, repo in enumerate(names)}
    expected = {
        "test_repos": SCORED,
        "control_of": pairing,
        "meta_train_repo_count": META_REPOS,
        "meta_train_rows": META_ROWS,
        "meta_rows_dropped_too_long": META_DROPPED,
        "shared_key_lessons": SHARED_KEY_LESSONS,
    }
    found = {
        "test_repos": plan["test_repos"],
        "control_of": plan["control_of"],
        "meta_train_repo_count": len(plan["meta_train_repos"]),
        "meta_train_rows": plan["meta_train_rows"],
        "meta_rows_dropped_too_long": plan["meta_rows_dropped_too_long"],
        "shared_key_lessons": len(plan["shared_key_lesson_ids"]),
    }
    differs = sorted(key for key in expected if found[key] != expected[key])
    if differs:
        raise PlanMismatchError(f"plan differs from the prereg in: {differs}")


def slug(repo: str) -> str:
    """A repo name as a directory name."""
    return repo.replace("/", "__")


def prepare(work: Path) -> dict:
    """Training rows, contexts and probes per scored repo and budget; returns counts."""
    plan = json.loads((work / "plan.json").read_text())
    check_plan(plan)
    counts = {}
    for repo, control in sorted(plan["control_of"].items()):
        own = read_lessons(work / "lessons" / f"{slug(repo)}.jsonl")
        wrong = read_lessons(work / "lessons" / f"{slug(control)}.jsonl")
        for budget in BUDGETS:
            folder = work / "repos" / slug(repo) / str(budget)
            rows = [row for lesson in own[:budget] for row in training_messages(lesson)]
            _jsonl(folder / "train" / "train.jsonl", rows)
            _jsonl(folder / "train" / "valid.jsonl", rows[:VALID_ROWS])
            (folder / "right.txt").write_text(lessons_prompt(own[:budget]))
            (folder / "wrong.txt").write_text(lessons_prompt(wrong[:budget]))
            _jsonl(folder / "probes.jsonl", probes(own[:budget]))
        counts[repo] = {"lessons": len(own), "control": control}
    return counts


def recall_cell(asked: Sequence[dict], answers: dict[str, str], lessons: Sequence[Lesson]) -> dict:
    """Reworded and verbatim recall, and the invented-detail rate, for one row on one repo."""
    by_id = {lesson.lesson_id: lesson for lesson in lessons}
    known = vocabulary(lessons)
    tallies = {"paraphrased": [0, 0], "verbatim": [0, 0]}
    invented = 0
    for probe in asked:
        verdict = score(
            answers[probe["question_id"]], by_id[probe["lesson_id"]], Asks(probe["asks"]), known
        )
        tallies[probe["wording"]][0] += verdict.hit
        tallies[probe["wording"]][1] += 1
        invented += bool(verdict.invented)
    return {
        "reworded": tallies["paraphrased"][0] / tallies["paraphrased"][1],
        "verbatim": tallies["verbatim"][0] / tallies["verbatim"][1],
        "invented": invented / len(asked),
    }


def prompt_rates(asked: Sequence[dict], answers: dict[str, str], own, wrong) -> dict:
    """Confabulation and abstention over the reworded probes."""
    texts = [answers[p["question_id"]] for p in asked if p["wording"] == "paraphrased"]
    return {
        "confabulation": sum(confabulates(t, own, wrong) for t in texts) / len(texts),
        "abstention": sum(abstains(t) for t in texts) / len(texts),
    }


def decide(gains: Sequence[float]) -> dict:
    """better, tie or worse for per-repo gains, by the prereg's rule."""
    interval = paired_gain(gains)
    if interval["ci95_low"] > 0 and interval["mean_gain"] >= MIN_GAIN:
        word = "better"
    elif interval["ci95_high"] < 0:
        word = "worse"
    else:
        word = "tie"
    return {"decision": word, **interval}


def confabulation_control(a2_rates: Sequence[float], a1_rates: Sequence[float]) -> dict:
    """The control: a1 minus a2 not worse, and a2's rate under the absolute bars."""
    relative = decide([a1 - a2 for a1, a2 in zip(a1_rates, a2_rates, strict=True)])
    absolute = paired_gain(list(a2_rates))
    passes = (
        relative["decision"] != "worse"
        and absolute["mean_gain"] <= CONFAB_MEAN_BAR
        and absolute["ci95_high"] < CONFAB_UPPER_BAR
    )
    return {"passes": passes, "a1_minus_a2": relative, "a2_rate": absolute}


def _answers(path: Path) -> dict[str, str]:
    return {row["question_id"]: row["answer"] for row in _read_jsonl(path)}


def repo_cells(work: Path, repo: str, control: str, budget: int) -> dict[str, dict]:
    """Every row's measures on one repo at one budget."""
    folder = work / "repos" / slug(repo) / str(budget)
    own = read_lessons(work / "lessons" / f"{slug(repo)}.jsonl")[:budget]
    wrong = read_lessons(work / "lessons" / f"{slug(control)}.jsonl")[:budget]
    asked = _read_jsonl(folder / "probes.jsonl")
    cells = {}
    for name, _, lessons_in_prompt in ROWS:
        answers = _answers(work / "answers" / name / f"{slug(repo)}-{budget}.jsonl")
        cell = recall_cell(asked, answers, own)
        rates = prompt_rates(asked, answers, own, wrong)
        # Abstention for every row: under wrong lessons it is wanted, elsewhere it is false.
        cell["abstention"] = rates["abstention"]
        if lessons_in_prompt == "wrong":
            cell["confabulation"] = rates["confabulation"]
        cells[name] = cell
    return cells


def all_cells(work: Path) -> dict[tuple[str, int], dict[str, dict]]:
    """(repo, budget) -> row -> measures, over the 13 scored repos."""
    plan = json.loads((work / "plan.json").read_text())
    check_plan(plan)
    return {
        (repo, budget): repo_cells(work, repo, control, budget)
        for repo, control in sorted(plan["control_of"].items())
        for budget in BUDGETS
    }


def row_means(cells: dict[tuple[str, int], dict[str, dict]]) -> list[dict]:
    """Each row's mean measures over repos, per budget, with its label."""
    rows = []
    for budget in BUDGETS:
        at = [by_row for (_, b), by_row in sorted(cells.items()) if b == budget]
        for name, label, lessons_in_prompt in ROWS:
            row = {
                "row": name,
                "label": label,
                "lessons_in_prompt": lessons_in_prompt,
                "budget": budget,
            }
            for measure in at[0][name]:
                interval = paired_gain([by_row[name][measure] for by_row in at])
                row[measure] = interval["mean_gain"]
                row[f"{measure}_ci95"] = [interval["ci95_low"], interval["ci95_high"]]
            rows.append(row)
    return rows


def decisions(cells: dict[tuple[str, int], dict[str, dict]]) -> dict:
    """H1, the secondaries and the confabulation control, by the frozen rule."""

    def gains(budget: int, left: str, right: str, measure: str = "reworded") -> list[float]:
        at = [by_row for (_, b), by_row in sorted(cells.items()) if b == budget]
        return [by_row[left][measure] - by_row[right][measure] for by_row in at]

    def rates(budget: int, name: str) -> list[float]:
        return [r[name]["confabulation"] for (_, b), r in sorted(cells.items()) if b == budget]

    h1 = decide(gains(PRIMARY_BUDGET, "a2", "a1"))
    control = confabulation_control(
        rates(PRIMARY_BUDGET, "a2_wrong"), rates(PRIMARY_BUDGET, "a1_wrong")
    )
    versus_adapter = decide(gains(PRIMARY_BUDGET, "a2", "per_repo"))
    works = (
        h1["decision"] == "better" and control["passes"] and versus_adapter["decision"] != "worse"
    )
    return {
        "h1_a2_vs_a1_at_5": h1,
        "a2_vs_a1_at_10": decide(gains(10, "a2", "a1")),
        "a2_vs_per_repo_at_5": versus_adapter,
        "a2_vs_per_repo_at_10": decide(gains(10, "a2", "per_repo")),
        "confabulation_control_at_5": control,
        "confabulation_control_at_10": confabulation_control(
            rates(10, "a2_wrong"), rates(10, "a1_wrong")
        ),
        "plug_and_play_works": works,
    }


def sensitivity(work: Path, cells: dict[tuple[str, int], dict[str, dict]]) -> dict:
    """H1 with the probes of lessons whose failure key recurs in meta-train removed."""
    plan = json.loads((work / "plan.json").read_text())
    shared = set(plan["shared_key_lesson_ids"])
    gains = []
    for repo in sorted(plan["control_of"]):
        folder = work / "repos" / slug(repo) / str(PRIMARY_BUDGET)
        asked = [p for p in _read_jsonl(folder / "probes.jsonl") if p["lesson_id"] not in shared]
        own = read_lessons(work / "lessons" / f"{slug(repo)}.jsonl")[:PRIMARY_BUDGET]
        recall = {
            name: recall_cell(
                asked, _answers(work / "answers" / name / f"{slug(repo)}-5.jsonl"), own
            )
            for name in ("a1", "a2")
        }
        gains.append(recall["a2"]["reworded"] - recall["a1"]["reworded"])
    return {
        "label": "H1 without shared-key lessons, never decides",
        "shared_lessons": len(shared),
        **decide(gains),
    }


def habits(work: Path) -> dict:
    """Ranked-choice habits (primary) and keyword habits (secondary) per model."""
    questions = _read_jsonl(work / "habit_questions.jsonl")
    found = {}
    for path in sorted((work / "ranked").glob("*.jsonl")):
        name = path.stem
        keyword = keyword_habits(questions, _answers(work / "habit_answers" / f"{name}.jsonl"))
        found[name] = {"ranked": round(ranked_rate(path), 4), "keyword": keyword["hit_rate"]}
    return found


def verdict_sentence(found: dict, rows: list[dict], habit_rates: dict) -> str:
    """The report's sentence, fixed by the prereg's wording, built from the decisions."""
    at5 = {row["row"]: row for row in rows if row["budget"] == PRIMARY_BUDGET}
    h1 = found["h1_a2_vs_a1_at_5"]
    if found["plug_and_play_works"]:
        parts = [
            f"recalls {at5['a2']['reworded']:.2f} of the reworded probes with 5 lessons in the "
            f"prompt on 13 unseen repos, against {at5['a1']['reworded']:.2f} for the plain model, "
            "without per-repo training"
        ]
    else:
        parts = [
            "a meta-trained reader did not measurably beat the plain model at this size "
            f"(a2 minus a1 {h1['mean_gain']:+.2f}, "
            f"interval {h1['ci95_low']:+.2f} to {h1['ci95_high']:+.2f})"
        ]
    if h1["decision"] == "better" and not found["confabulation_control_at_5"]["passes"]:
        parts.append("recalls more and confabulates more")
    if h1["decision"] == "better" and habit_rates["a2"]["ranked"] < habit_rates["plain"]["ranked"]:
        parts.append("recalls more and keeps fewer habits")
    return "; ".join(parts)


def score_run(work: Path, provenance: dict) -> dict:
    """The results document of the scored run."""
    cells = all_cells(work)
    plan = json.loads((work / "plan.json").read_text())
    rows, found, habit_rates = row_means(cells), decisions(cells), habits(work)
    return {
        **provenance,
        **answerer_provenance(work),
        "status": "scored under prereg/2026-10-29-l2l-a2.md",
        "scored_repos": plan["test_repos"],
        "meta_train_repos": plan["meta_train_repos"],
        "meta_train_rows": plan["meta_train_rows"],
        "control_of": plan["control_of"],
        "meta_rows_dropped_too_long": plan["meta_rows_dropped_too_long"],
        "shared_key_lessons": len(plan["shared_key_lesson_ids"]),
        "a2_adapter_sha256": (work / "adapters" / "a2" / "sha256.txt").read_text().strip(),
        "rows": rows,
        "decisions": found,
        "result": verdict_sentence(found, rows, habit_rates),
        "sensitivity": sensitivity(work, cells),
        "habits": habit_rates,
    }


def main() -> None:
    """`prepare` before training; `score` after the driver has answered every row."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("prepare", "score"))
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.stage == "prepare":
        print(json.dumps(prepare(args.work), indent=1))
        return
    provenance = json.loads((args.work / "provenance.json").read_text())
    text = json.dumps(score_run(args.work, provenance), indent=1, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
