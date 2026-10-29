"""Plug round 2's selection on the validation repos, and the minimum detectable effect.

Usage: uv run python scripts/routea/plug_r2_select.py --work W --order V1 V2 ... --out F

The rule is the frozen prereg's: V1 replaces the floor only if its pick gain is `better` and it
passes the absolute abstention gate; a later variant replaces the current best only if its pick
gain is `better`, its silence is not 0.05 lower and its wrong pick not 0.02 higher. A tie keeps
the earlier variant. If V1 fails, the round stops.
"""

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

from plug_situation import item_from, rates  # noqa: E402
from warm_start import _read_jsonl, paired_gain  # noqa: E402

MIN_GAIN = 0.05
SILENCE_DROP = 0.05  # rule (b)
WRONG_RISE = 0.02  # rule (c)
GATE_SILENCE = 0.80  # H2: silence mean at least this
GATE_SILENCE_LOW = 0.60  # ... with the interval's lower bound above this
GATE_WRONG = 0.05  # ... and wrong pick at most this
SCORED_REPOS = 40
# Seed-to-seed spread of a 1B adapter is large (CUDA port report), so each variant trains with these
# seeds and every rule reads the per-repo mean over them.
SEEDS = (0, 1, 2)


def per_repo(work: Path, arm: str) -> dict[str, dict[str, float]]:
    """Rates per validation repo for one arm's answers."""
    by_repo: dict[str, list] = {}
    for record in _read_jsonl(work / "items.jsonl"):
        by_repo.setdefault(record["repo"], []).append(item_from(record))
    answers = {
        r["question_id"]: r["answer"] for r in _read_jsonl(work / "answers" / f"{arm}.jsonl")
    }
    return {repo: rates(items, answers) for repo, items in sorted(by_repo.items())}


def seed_mean(cells: Sequence[dict[str, dict[str, float]]]) -> dict[str, dict[str, float]]:
    """Per repo and measure, the mean over seeds' rates."""
    repos = sorted(cells[0])
    return {
        repo: {m: sum(c[repo][m] for c in cells) / len(cells) for m in cells[0][repo]}
        for repo in repos
    }


def per_repo_seeds(work: Path, arm: str) -> dict[str, dict[str, float]]:
    """Seed-mean rates of a trained arm from its answer files `<arm>-s<seed>.jsonl`."""
    return seed_mean([per_repo(work, f"{arm}-s{seed}") for seed in SEEDS])


def better(gains: Sequence[float]) -> dict:
    """The rule's words for a list of per-repo gains."""
    interval = paired_gain(gains)
    if interval["ci95_low"] > 0 and interval["mean_gain"] >= MIN_GAIN:
        word = "better"
    elif interval["ci95_high"] < 0:
        word = "worse"
    else:
        word = "tie"
    return {"decision": word, **interval}


def gate(cells: dict[str, dict[str, float]]) -> dict:
    """The absolute abstention gate (H2) on one arm's per-repo rates."""
    silence = paired_gain([c["silence"] for c in cells.values()])
    wrong = paired_gain([c["wrong_pick"] for c in cells.values()])
    passes = (
        silence["mean_gain"] >= GATE_SILENCE
        and silence["ci95_low"] > GATE_SILENCE_LOW
        and wrong["mean_gain"] <= GATE_WRONG
    )
    return {"passes": passes, "silence": silence, "wrong_pick": wrong}


def compare(new: dict, best: dict, *, against_floor: bool) -> dict:
    """Whether `new` replaces `best` by the frozen selection rule."""
    repos = sorted(new)
    pick = better([new[r]["pick"] - best[r]["pick"] for r in repos])
    if against_floor:
        checks = gate(new)
        replaces = pick["decision"] == "better" and checks["passes"]
        return {"replaces": replaces, "pick_gain": pick, "gate": checks}
    silence = sum(new[r]["silence"] - best[r]["silence"] for r in repos) / len(repos)
    wrong = sum(new[r]["wrong_pick"] - best[r]["wrong_pick"] for r in repos) / len(repos)
    replaces = pick["decision"] == "better" and silence >= -SILENCE_DROP and wrong <= WRONG_RISE
    return {
        "replaces": replaces,
        "pick_gain": pick,
        "silence_change": silence,
        "wrong_change": wrong,
    }


def select(cells: dict[str, dict], order: Sequence[str]) -> dict:
    """Walk the variants in order from the floor (`floor`); the round stops if V1 fails. `order`
    lists only the variants that ran; each must have cells."""
    best, steps = "floor", []
    for variant in order:
        step = compare(cells[variant], cells[best], against_floor=best == "floor")
        steps.append({"variant": variant, "against": best, **step})
        if step["replaces"]:
            best = variant
        elif best == "floor":
            break
    return {"selected": best, "steps": steps}


def mde(gains: Sequence[float], validation_items: float, scored_items: float) -> dict:
    """The prereg's minimum detectable effect from validation per-repo gains."""
    mean = sum(gains) / len(gains)
    spread = math.sqrt(sum((g - mean) ** 2 for g in gains) / (len(gains) - 1))
    scaled = spread * math.sqrt(validation_items / scored_items)
    half = 1.96 * scaled / math.sqrt(SCORED_REPOS)
    effect = max(MIN_GAIN, half) + 0.84 * scaled / math.sqrt(SCORED_REPOS)
    return {
        "sd_validation": round(spread, 4),
        "sd_scored": round(scaled, 4),
        "half_width": round(half, 4),
        "mde": round(effect, 4),
        "validation_gain": round(mean, 4),
        "expected_read": "tie" if mean < effect else "better",
    }


def main() -> None:
    """Score each arm on validation, apply the rule, and compute the MDE for the selected one."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True, help="validation top-5 work dir")
    parser.add_argument("--order", nargs="+", required=True)
    parser.add_argument(
        "--scored-items", type=float, required=True, help="mean pick items per scored repo"
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    arms = ["floor", *args.order]
    # Every listed arm needs answers: a missing file raises in per_repo, never reads as "not run".
    cells = {
        arm: per_repo(args.work, arm) if arm == "floor" else per_repo_seeds(args.work, arm)
        for arm in arms
    }
    result = select(cells, args.order)
    if result["selected"] != "floor":
        chosen, floor = cells[result["selected"]], cells["floor"]
        gains = [chosen[r]["pick"] - floor[r]["pick"] for r in sorted(chosen)]
        items = sum(1 for r in _read_jsonl(args.work / "items.jsonl") if r["applies"]) / len(chosen)
        result["mde"] = mde(gains, items, args.scored_items)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
