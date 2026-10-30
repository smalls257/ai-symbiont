"""Plug round 4's nightly arm on the scored repositories, against the fair reference.

Usage: uv run python scripts/routea/plug_r4_nightly_arm.py STAGE --scale S ...  (fit, pins, decide)
Usage: fit: --work --combo --out; pins: --adapters --selection --idle --out
Usage: decide: --primary --adapters-r3 --selection-r3 --pins0 --scores --adapters --selection
Usage:   --idle --gpins --out

One adapter per scored repository, read at one strength fixed on validation, judged against
the round 3 judge with the same agree rule. A repository with no adapter reads the general judge.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_r3_run import load_items  # noqa: E402
from plug_r4_combine import FOLDS, candidates, decide, two_d_rules  # noqa: E402
from plug_r4_combo import joined_scores, merged_candidates  # noqa: E402
from plug_r4_general_arm import read_general  # noqa: E402
from plug_r4_matched import fit_at, inner_target  # noqa: E402
from plug_r4_scored import PinMismatchError, check, claim, read_scores, sha256_of, summarize  # noqa: E402
from plug_situation import item_from  # noqa: E402
from warm_start import _read_jsonl  # noqa: E402


def fit_nightly(work: Path, combo: Path, scale: str) -> dict:
    """The arm's agree-rule point from validation, on the chosen strength's scores."""
    items, repo_of = load_items(work, "scored")
    scores = joined_scores(combo / "scores-habits10", scale)
    cands = merged_candidates(items, candidates(items, scores))
    target = inner_target(items, repo_of, cands, list(range(FOLDS)))
    point = fit_at(items, cands, target)
    if point is None:
        raise PinMismatchError("no safe agree-rule point for the nightly arm on validation")
    return {"target": target, "rule": point[0], "threshold": point[1], "scale": scale}


def adapters_hash(adapters: Path, scale_dir: str) -> str:
    """One hash over every repository's adapter weights (sorted by name)."""
    parts = [
        f"{p.parent.name}:{sha256_of(p)}"
        for p in sorted(adapters.glob("*/adapter_model.safetensors"))
    ]
    if not parts:
        raise PinMismatchError(f"no adapters under {adapters} ({scale_dir})")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


AMENDMENT_KEYS = frozenset(
    {"amendment", "nightly_adapters", "nightly_adapter_count", "nightly_idle_repos"}
)
WRONG_BOUND_FOR_CLAIM = 0.05  # the nightly arm's wrong-pick upper bound a "better" needs


def freeze_pins(selection: Path, scale: str) -> dict:
    """What the freeze fixes: the nightly selection file and the read strength."""
    return {"nightly_selection": sha256_of(selection), "nightly_scale": scale}


def amendment_pins(adapters: Path, idle: Path, date: str) -> dict:
    """What a dated amendment may add, and only this: the adapter set, its count, the idle list."""
    return {
        "amendment": date,
        "nightly_adapters": adapters_hash(adapters, "amendment"),
        "nightly_adapter_count": len(list(adapters.glob("*/adapter_model.safetensors"))),
        "nightly_idle_repos": sha256_of(idle),
    }


def nightly_reading(summary: dict) -> dict:
    """The nightly arm's reading: "better" needs the coverage-difference interval above zero
    (the base reading) AND the arm's wrong-pick upper bound at most 0.05; otherwise the numbers
    are reported side by side with no claim."""
    raw = summary["reading"]
    claim_ok = raw == "better" and summary["wrong_bound_rule"] <= WRONG_BOUND_FOR_CLAIM
    return {
        **summary,
        "reading_coverage_only": raw,
        "reading": "better" if claim_ok else "no claim",
    }


def arm_scores(directory: Path, scale: str, idle: set[str], general: dict, repo_of: dict) -> dict:
    """Each query's P(yes): its repository's adapter, or the general judge if it has none. A
    repository that is neither idle nor scored raises."""
    scores = {}
    for repo in sorted(set(repo_of.values())):
        slug = repo.replace("/", "__")
        path = directory / slug / f"s{scale}" / "scores.jsonl"
        if repo in idle:
            continue
        if not path.exists():
            raise PinMismatchError(f"missing nightly scores for {repo}")
        scores |= {r["question_id"]: r["p_yes"] for r in _read_jsonl(path)}
    for key, value in general.items():
        scores.setdefault(key, value)
    return scores


def run_decide(args: argparse.Namespace) -> dict:
    """Check every pin, then the nightly arm against the fair reference."""
    check(args.primary, args.adapters_r3, args.selection_r3, args.pins0)
    frozen, amended = (json.loads(p.read_text()) for p in (args.fpins, args.apins))
    if set(amended) != AMENDMENT_KEYS:
        raise PinMismatchError(f"an amendment may add only {sorted(AMENDMENT_KEYS)}")
    if freeze_pins(args.selection, args.scale) != frozen:
        raise PinMismatchError("nightly selection or strength differ from the freeze pins")
    now = amendment_pins(args.adapters, args.idle, amended["amendment"])
    if now != amended:
        raise PinMismatchError("nightly adapters or idle list differ from the amendment pins")
    records = _read_jsonl(args.primary / "primary-items.jsonl")
    items = [item_from(r) for r in records]
    repo_of = {r["question_id"]: r["repo"] for r in records}
    queries = args.primary / "primary-queries.jsonl"
    ref_sel, sel = (json.loads(p.read_text()) for p in (args.selection_r3, args.selection))
    r3 = merged_candidates(items, candidates(items, read_scores(args.scores, queries)))
    general = read_general(args.scores, queries)
    idle = set(json.loads(args.idle.read_text()))
    night = arm_scores(args.adapters.parent / "scores-habits10", args.scale, idle, general, repo_of)
    cands = merged_candidates(items, candidates(items, night))
    reference = decide(items, r3, two_d_rules()[ref_sel["rule"]], ref_sel["threshold"])
    rule_of = two_d_rules()[sel["rule"]]
    arm = decide(items, cands, rule_of, sel["threshold"])
    found = summarize(items, repo_of, reference, arm, decide(items, cands, rule_of, 0.0))
    if sel["rule"] == "idf>=0.0":  # the rule has no ranker cut, so a ranker-only row means nothing
        found["ranker_at_same_cut_no_judge"] = "not applicable"
    found = nightly_reading(found)
    arm = "the nightly per-repository judge with the agree rule"
    return {**found, "claim": claim(found, arm, "the fair reference")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    flags = {
        "fit": ("work", "combo", "out"),
        "freeze-pins": ("selection", "out"),
        "amendment-pins": ("adapters", "idle", "out"),
        "decide": (
            "primary",
            "adapters-r3",
            "selection-r3",
            "pins0",
            "scores",
            "adapters",
            "selection",
            "idle",
            "fpins",
            "apins",
            "out",
        ),
    }
    for name, names in flags.items():
        sub = stages.add_parser(name)
        sub.add_argument("--scale", default="1")
        sub.add_argument("--date", default="")
        for flag in names:
            sub.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "fit":
        result = fit_nightly(args.work, args.combo, args.scale)
    elif args.stage == "freeze-pins":
        result = freeze_pins(args.selection, args.scale)
    elif args.stage == "amendment-pins":
        result = amendment_pins(args.adapters, args.idle, args.date)
    else:
        result = run_decide(args)
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
