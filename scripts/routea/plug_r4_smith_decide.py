"""Code-fix lessons study: pins, and the frozen decision on the SWE-smith items.

Usage: uv run python scripts/routea/plug_r4_smith_decide.py pins --items I --adapters A \\
Usage:   --selections S... --out F
Usage: uv run python scripts/routea/plug_r4_smith_decide.py check --items I --adapters A \\
Usage:   --selections S... --pins F
Usage: uv run python scripts/routea/plug_r4_smith_decide.py decide --items I --adapters A \\
Usage:   --selections S3 SN --pins F --scores D --nightly N --out R

Arms as in round 4: judge alone at its frozen 0.99, the agree rule, and the nightly arm, with
round 4's fixed thresholds. Clusters are tasks (two repositories cannot be clustered). The
nightly arm is "better" than the agree rule only if its coverage-difference interval is above
zero with a gain of at least 0.05 AND the exact Clopper-Pearson upper bound of its wrong picks
over all items is below 0.05; otherwise the numbers are reported with no claim.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_r4_bounds import clopper_pearson_upper  # noqa: E402
from plug_r4_combine import candidates, decide, judge_top, two_d_rules  # noqa: E402
from plug_r4_combo import merged_candidates  # noqa: E402
from plug_r4_scored import (  # noqa: E402
    FROZEN_JUDGE_THRESHOLD,
    SHORTLIST,
    PinMismatchError,
    adapter_hashes,
    read_scores,
    sha256_of,
    summarize,
)
from plug_situation import item_from  # noqa: E402
from warm_start import _read_jsonl  # noqa: E402

FILES = ("primary-items.jsonl", "primary-queries.jsonl", "primary-negatives.txt")
WRONG_BAR = 0.05  # the round 4 bar, fixed before any scoring


def current_pins(items: Path, adapters: Path, selections: list[Path]) -> dict:
    """Hashes of the item files, the round 3 adapters and the selection files."""
    return {
        "files": {name: sha256_of(items / name) for name in FILES},
        "adapters": adapter_hashes(adapters),
        "selections": [sha256_of(path) for path in selections],
        "items": len(_read_jsonl(items / "primary-items.jsonl")),
        "judge_threshold": FROZEN_JUDGE_THRESHOLD,
    }


def check(items: Path, adapters: Path, selections: list[Path], pins: Path) -> dict:
    """The current pins, or PinMismatchError naming what differs."""
    now = current_pins(items, adapters, selections)
    frozen = json.loads(pins.read_text())
    differing = sorted(key for key in frozen if frozen[key] != now.get(key))
    if differing:
        raise PinMismatchError(f"differs from the frozen pins: {differing}")
    return now


def nightly_scores(directory: Path, repos: list[str]) -> dict[str, float]:
    """P(yes) per query from each repository's nightly adapter; a missing repository raises."""
    scores = {}
    for repo in repos:
        path = directory / repo.replace("/", "__") / "s1" / "scores.jsonl"
        if not path.exists():
            raise PinMismatchError(f"missing nightly scores for {repo}")
        scores |= {r["question_id"]: r["p_yes"] for r in _read_jsonl(path)}
    return scores


def run_decide(args: argparse.Namespace) -> dict:
    """Check the pins, then the three arms against each other."""
    check(args.items, args.adapters, args.selections, args.pins)
    records = _read_jsonl(args.items / "primary-items.jsonl")
    items = [item_from(r) for r in records]
    cluster = {r["question_id"]: r["task"] for r in records}
    repos = sorted({r["repo"] for r in records})
    sel3, seln = (json.loads(p.read_text()) for p in args.selections)
    r3 = merged_candidates(
        items, candidates(items, read_scores(args.scores, args.items / "primary-queries.jsonl"))
    )
    night = merged_candidates(items, candidates(items, nightly_scores(args.nightly, repos)))
    alone = decide(items, r3, judge_top(SHORTLIST), FROZEN_JUDGE_THRESHOLD)
    agree = decide(items, r3, two_d_rules()[sel3["rule"]], sel3["threshold"])
    arm = decide(items, night, two_d_rules()[seln["rule"]], seln["threshold"])
    found = {
        "agree_vs_judge_alone": summarize(items, cluster, alone, agree, agree),
        "nightly_vs_agree": summarize(items, cluster, agree, arm, arm),
    }
    nightly = found["nightly_vs_agree"]
    wrong = round(nightly["rule"]["wrong_pick"] * len(items))
    nightly["wrong_exact_upper"] = round(clopper_pearson_upper(wrong, len(items)), 4)
    ok = nightly["reading"] == "better" and nightly["wrong_exact_upper"] < WRONG_BAR
    nightly["claim_reading"] = "better" if ok else "no claim"
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("pins", "check", "decide"))
    for flag in ("items", "adapters", "pins", "scores", "nightly", "out"):
        parser.add_argument(f"--{flag}", type=Path)
    parser.add_argument("--selections", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    if args.stage == "pins":
        result = current_pins(args.items, args.adapters, args.selections)
    elif args.stage == "check":
        result = check(args.items, args.adapters, args.selections, args.pins)
    else:
        result = run_decide(args)
    if args.out:
        args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result)[:600])


if __name__ == "__main__":
    main()
