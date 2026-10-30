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
from plug_r4_scored import PinMismatchError, check, read_scores, sha256_of, summarize  # noqa: E402
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


def nightly_pins(adapters: Path, selection: Path, idle: Path, scale: str) -> dict:
    """The adapter set, the selection and the no-adapter list, hashed."""
    return {
        "nightly_adapters": adapters_hash(adapters, scale),
        "nightly_adapter_count": len(list(adapters.glob("*/adapter_model.safetensors"))),
        "nightly_selection": sha256_of(selection),
        "nightly_idle_repos": sha256_of(idle),
        "nightly_scale": scale,
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
    if nightly_pins(args.adapters, args.selection, args.idle, args.scale) != json.loads(
        args.gpins.read_text()
    ):
        raise PinMismatchError("nightly adapters, selection or idle list differ from the pins")
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
    return summarize(items, repo_of, reference, arm, decide(items, cands, rule_of, 0.0))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    flags = {
        "fit": ("work", "combo", "out"),
        "pins": ("adapters", "selection", "idle", "out"),
        "decide": (
            "primary",
            "adapters-r3",
            "selection-r3",
            "pins0",
            "scores",
            "adapters",
            "selection",
            "idle",
            "gpins",
            "out",
        ),
    }
    for name, names in flags.items():
        sub = stages.add_parser(name)
        sub.add_argument("--scale", default="1")
        for flag in names:
            sub.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "fit":
        result = fit_nightly(args.work, args.combo, args.scale)
    elif args.stage == "pins":
        result = nightly_pins(args.adapters, args.selection, args.idle, args.scale)
    else:
        result = run_decide(args)
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
