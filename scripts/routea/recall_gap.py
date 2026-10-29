"""Does the CUDA port reproduce the laptop's recall? Per-arm gaps against binomial noise.

Usage: uv run python scripts/routea/recall_gap.py --laptop L --cuda C --arms a3 a3_replay a2v ...
L and C are Plug a3 work dirs (`plug_a3.py plan` layout) holding repos/<slug>/answers/<arm>; the
repos present in C are compared, each through `plug_a3.repo_cells`, the scorer both machines use.

Greedy decoding on a different GPU stack and a retrained adapter can flip single answers, so a gap
counts only beyond two standard errors of the difference of two proportions at that measure's
question count (a 25-question measure moves 0.04 per answer). Prints counts and rates only.
"""

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parent / "aidev"))

SIGMAS = 2.0  # a two-sided 95% band on the difference of two proportions


def noise_band(rate_a: float, rate_b: float, questions: int) -> float:
    """Half-width of the band inside which two runs of one measure agree. Raises on zero questions.

    Uses the pooled rate; two runs that both score 0 or 1 have no spread to widen the band, so a
    flat 1/questions (one flipped answer) is the floor."""
    if questions < 1:
        raise ValueError("a measure with no questions has no noise band")
    pooled = (rate_a + rate_b) / 2
    spread = SIGMAS * math.sqrt(2 * pooled * (1 - pooled) / questions)
    return max(spread, 1 / questions)


def gap_row(measure: str, laptop: float, cuda: float, questions: int) -> dict:
    """One measure: both rates, their gap, the band and whether the gap sits inside it."""
    band = noise_band(laptop, cuda, questions)
    gap = cuda - laptop
    return {
        "measure": measure,
        "laptop": round(laptop, 4),
        "cuda": round(cuda, 4),
        "gap": round(gap, 4),
        "band": round(band, 4),
        "within_noise": abs(gap) <= band + 1e-9,
    }


def question_counts(folder: Path, habit_questions: int) -> dict[str, int]:
    """Paraphrased probe count per measure, from the repo's probe files."""

    def paraphrased(name: str) -> int:
        rows = [json.loads(line) for line in (folder / name).read_text().splitlines()]
        return sum(1 for row in rows if row["wording"] == "paraphrased")

    own, new = paraphrased("probes.jsonl"), paraphrased("probes-new.jsonl")
    return {
        "no_lessons": own,
        "lessons_in_prompt": own,
        "new_lessons": new,
        "wrong_lessons": own,
        "wrong_confabulation": own,
        "wrong_abstention": own,
        "habits_keyword": habit_questions,
        "habits_ranked": habit_questions,
    }


def compare(laptop: Path, cuda: Path, arms: list[str]) -> list[dict]:
    """Gap rows for every repo in `cuda` and every arm; raises if the laptop lacks a repo."""
    from plug_a3 import repo_cells  # noqa: PLC0415  (pulls the aidev lessons path)
    from warm_start import _read_jsonl  # noqa: PLC0415

    habits = _read_jsonl(cuda / "habit_questions.jsonl")
    rows = []
    for folder in sorted((cuda / "repos").iterdir()):
        counts = question_counts(folder, len(habits))
        for arm in arms:
            mine = repo_cells(folder, arm, habits)
            theirs = repo_cells(laptop / "repos" / folder.name, arm, habits)
            for measure, questions in counts.items():
                rows.append(
                    {"repo": folder.name, "arm": arm}
                    | gap_row(measure, theirs[measure], mine[measure], questions)
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--laptop", type=Path, required=True)
    parser.add_argument("--cuda", type=Path, required=True)
    parser.add_argument("--arms", nargs="+", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = compare(args.laptop, args.cuda, args.arms)
    text = json.dumps(rows, indent=1)
    if args.out:
        args.out.write_text(text + "\n")
    inside = sum(r["within_noise"] for r in rows)
    print(f"{inside} of {len(rows)} measure cells within noise")


if __name__ == "__main__":
    main()
