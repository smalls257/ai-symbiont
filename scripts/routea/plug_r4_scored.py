"""Plug round 4's scored runner: pins, the validation fit, and the primary decision.

Usage: uv run python scripts/routea/plug_r4_scored.py STAGE ...   (pins, fit, check, decide)
Usage: STAGE flags: pins/check take --primary --adapters --selection and --out/--pins;
Usage: fit takes --work --out; decide adds --scores to check's flags and --out.

Why: a run that quietly differs from the one frozen (a smaller item set, another adapter, a
re-fitted threshold, a missing score read as silence) is not the pre-registered run, so every
mismatch raises. `check` compares the primary files, negative-id list, adapters and selection with
the pins; `decide` re-checks, then reads three seeds' scores, judge alone at its frozen 0.99
threshold against the agree rule, and prints the claim.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_judge_cli import seed_mean_scores  # noqa: E402
from plug_r3_run import load_items  # noqa: E402
from plug_r4_combine import FOLDS, candidates, decide, judge_top, two_d_rules  # noqa: E402
from plug_r4_combo import merged_candidates  # noqa: E402
from plug_r4_matched import fit_at, inner_target  # noqa: E402
from plug_r4_power import icc  # noqa: E402
from plug_r4_primary import PRIMARY_POSITIVES, PRIMARY_REPOS, SHORTLIST  # noqa: E402
from plug_r4_primary_stats import (  # noqa: E402
    bootstrap,
    coverage,
    pooled_rates,
    repo_table,
    safety,
    verdict,
)

FROZEN_JUDGE_THRESHOLD = 0.99  # amendment 1, applied as deployed, never refit
SEEDS = (0, 1, 2)
PIN_FILES = ("primary-items.jsonl", "primary-queries.jsonl", "primary-negatives.txt")


class PinMismatchError(RuntimeError):
    """A file, count or setting differs from the frozen pins."""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapter_hashes(adapters: Path) -> dict[str, str]:
    """The three round 3 adapters' weight hashes; a missing adapter raises."""
    return {
        f"judge-s{s}": sha256_of(adapters / f"judge-s{s}" / "adapter_model.safetensors")
        for s in SEEDS
    }


def current_pins(primary: Path, adapters: Path, selection: Path) -> dict:
    """What the files on disk say now."""
    manifest = json.loads((primary / "primary-manifest.json").read_text())
    return {
        "positives": manifest["positives"],
        "positive_repos": manifest["positive_repos"],
        "negatives": manifest["negatives"],
        "files": {name: sha256_of(primary / name) for name in PIN_FILES},
        "adapters": adapter_hashes(adapters),
        "selection": sha256_of(selection),
        "judge_threshold": FROZEN_JUDGE_THRESHOLD,
    }


def check(primary: Path, adapters: Path, selection: Path, pins: Path) -> dict:
    """The current pins, or PinMismatchError naming every field that differs."""
    now, frozen = current_pins(primary, adapters, selection), json.loads(pins.read_text())
    if (now["positives"], now["positive_repos"]) != (PRIMARY_POSITIVES, PRIMARY_REPOS):
        raise PinMismatchError(f"n = {now['positives']} in {now['positive_repos']} repos")
    differing = sorted(key for key in frozen if frozen[key] != now.get(key))
    if differing:
        raise PinMismatchError(f"differs from the frozen pins: {differing}")
    return now


def validation_inputs(work: Path):
    """Round 3's scored repositories (validation here): items, repos, merged shortlists."""
    items, repo_of = load_items(work, "scored")
    scores = seed_mean_scores([work / "scores" / f"scored-judge-s{s}.jsonl" for s in SEEDS])
    return items, repo_of, merged_candidates(items, candidates(items, scores))


def fit(work: Path) -> dict:
    """The agree rule's cut and threshold: the in-sample target whose nested-CV wrong pick is at
    most 0.05 with the best pick, then the point fitted at that target on all validation repos."""
    items, repo_of, cands = validation_inputs(work)
    target = inner_target(items, repo_of, cands, list(range(FOLDS)))
    point = fit_at(items, cands, target)
    if point is None:
        raise PinMismatchError("no safe agree-rule point on validation at any target")
    return {
        "target": target,
        "rule": point[0],
        "threshold": point[1],
        "validation_repos": len(set(repo_of.values())),
    }


def read_scores(directory: Path, queries: Path) -> dict[str, float]:
    """Three seeds' mean P(yes) per query; a missing, extra, non-finite or out-of-range score
    raises rather than reading as silence."""
    paths = [directory / f"primary-judge-s{s}.jsonl" for s in SEEDS]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise PinMismatchError(f"missing score files: {missing}")
    scores = seed_mean_scores(paths)
    wanted = {json.loads(line)["question_id"] for line in queries.read_text().splitlines()}
    if set(scores) != wanted:
        raise PinMismatchError("score files do not cover exactly the primary queries")
    if any(not math.isfinite(v) or not 0.0 <= v <= 1.0 for v in scores.values()):
        raise PinMismatchError("a score is not a probability")
    return scores


def is_single_fix(item) -> bool:
    """A negative, or a positive whose (command, error) key only one lesson in its prompt has."""
    if item.applies is None:
        return True
    key = (item.applies.failed, item.applies.error)
    return sum((x.failed, x.error) == key for x in item.prompt_lessons) == 1


def wrong_flags_by_repo(items, repo_of, choices) -> dict:
    """Repo -> 0/1 flags of a wrong answer on each of its items (for the ICC)."""
    flags: dict[str, list[int]] = {}
    for item, choice in zip(items, choices, strict=True):
        right = item.applies is not None and choice.lesson_id == item.applies.lesson_id
        flags.setdefault(repo_of[item.item_id], []).append(
            int(choice.lesson_id is not None and not right)
        )
    return flags


def primary_decision(items, repo_of, scores, selection: dict) -> dict:
    """Judge alone at 0.99 against the agree rule on these scores."""
    cands = merged_candidates(items, candidates(items, scores))
    alone = decide(items, cands, judge_top(SHORTLIST), FROZEN_JUDGE_THRESHOLD)
    rule_of = two_d_rules()[selection["rule"]]
    rule = decide(items, cands, rule_of, selection["threshold"])
    return summarize(items, repo_of, alone, rule, decide(items, cands, rule_of, 0.0))


def summarize(items, repo_of, alone, rule, ranker) -> dict:
    """Rates, interval, verdicts, ICC and strict row of an arm (`rule`) against the comparator
    (`alone`); `ranker` is the same rule's cut with no judge."""
    t_rule, t_alone = repo_table(items, repo_of, rule), repo_table(items, repo_of, alone)
    boot = bootstrap(t_rule, t_alone)
    gain = coverage(t_rule) - coverage(t_alone)
    keep = [i for i, item in enumerate(items) if is_single_fix(item)]
    strict = [
        repo_table([items[i] for i in keep], repo_of, [choices[i] for i in keep])
        for choices in (rule, alone)
    ]
    return {
        "coverage_rule": round(coverage(t_rule), 4),
        "coverage_judge_alone": round(coverage(t_alone), 4),
        "gain": round(gain, 4),
        "gain_interval": [round(boot["gain_low"], 4), round(boot["gain_high"], 4)],
        "reading": verdict(gain, boot["gain_low"], boot["gain_high"]),
        "rule": pooled_rates(t_rule),
        "judge_alone": pooled_rates(t_alone),
        "ranker_at_same_cut_no_judge": {
            "coverage": round(coverage(repo_table(items, repo_of, ranker)), 4),
            **pooled_rates(repo_table(items, repo_of, ranker)),
        },
        "wrong_bound_rule": round(boot["wrong_high"], 4),
        "safety": safety(pooled_rates(t_rule)["wrong_pick"], boot["wrong_high"]),
        "strict_single_fix": {
            "rule": round(coverage(strict[0]), 4),
            "judge_alone": round(coverage(strict[1]), 4),
        },
        "wrong_pick_icc": round(icc(wrong_flags_by_repo(items, repo_of, rule)), 4),
    }


def claim(found: dict) -> str:
    """The claim sentence, built from the numbers; it always carries the judge alone."""
    return (
        f"On {PRIMARY_POSITIVES} real later recurrences in {PRIMARY_REPOS} repositories, small "
        f"trained judge + ranker agreement covers {found['coverage_rule']} against "
        f"{found['coverage_judge_alone']} for the judge alone (gain {found['gain']}, interval "
        f"{found['gain_interval']}, reading {found['reading']}); wrong pick "
        f"{found['rule']['wrong_pick']} against {found['judge_alone']['wrong_pick']}, "
        f"{found['safety']}."
    )


def run_decide(args: argparse.Namespace) -> dict:
    """Check the pins, then decide."""
    check(args.primary, args.adapters, args.selection, args.pins)
    records = [
        json.loads(x) for x in (args.primary / "primary-items.jsonl").read_text().splitlines()
    ]
    from plug_situation import item_from  # noqa: PLC0415

    items = [item_from(r) for r in records]
    repo_of = {r["question_id"]: r["repo"] for r in records}
    scores = read_scores(args.scores, args.primary / "primary-queries.jsonl")
    found = primary_decision(items, repo_of, scores, json.loads(args.selection.read_text()))
    return {**found, "claim": claim(found)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    for name, flags in {
        "pins": ("primary", "adapters", "selection", "out"),
        "fit": ("work", "out"),
        "check": ("primary", "adapters", "selection", "pins"),
        "decide": ("primary", "adapters", "scores", "selection", "pins", "out"),
    }.items():
        sub = stages.add_parser(name)
        for flag in flags:
            sub.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "pins":
        result = current_pins(args.primary, args.adapters, args.selection)
    elif args.stage == "fit":
        result = fit(args.work)
    elif args.stage == "check":
        result = check(args.primary, args.adapters, args.selection, args.pins)
    else:
        result = run_decide(args)
    if hasattr(args, "out"):
        args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
