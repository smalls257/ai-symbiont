"""Export a run's summary to the progress page's JSON: counts, ids and labels, never card text.

The exporter refuses a run that lacks the no-selection arm or the no-card floor: an evolved curve
drawn alone proves nothing. Card text stays in the run directory; an optional local copy for the
owner's screen goes to a gitignored path.

Usage: export_progress.py --summary RUN/summary.json --out dashboard/sample/evolve-dry-run.json
       [--state RUN/state.json --cards-out data/evolve-cards.local.json]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA = "evolve-progress-v1"
REQUIRED_ARMS = ("evolved", "no_selection")
LABELS = ("exploratory", "scored")


class MissingControlArmError(ValueError):
    """The run has no curve for the no-selection arm (or one of the arms has no points)."""


class MissingFloorError(ValueError):
    """The run has no no-card floor."""


class UnlabeledRunError(ValueError):
    """The run's claim is neither exploratory nor scored."""


def _require_arms(curves: list[dict[str, Any]]) -> None:
    """Raises MissingControlArmError unless both arms have a point in every generation drawn."""
    generations = {
        arm: {p["generation"] for p in curves if p["arm"] == arm} for arm in REQUIRED_ARMS
    }
    for arm in REQUIRED_ARMS:
        if not generations[arm]:
            raise MissingControlArmError(f"no curve points for the {arm} arm")
    if generations["evolved"] != generations["no_selection"]:
        raise MissingControlArmError("the arms do not cover the same generations")


def _earliest_birth(
    births: list[dict[str, Any]], card_id: str, before: float
) -> dict[str, Any] | None:
    """The first accepted, non-elite birth of the card in a generation earlier than `before`."""
    found = [
        b for b in births
        if b["card_id"] == card_id and b["rejection"] is None and b["operator"] != "elite"
        and b["generation"] < before
    ]  # fmt: skip
    return found[0] if found else None


def family_tree(births: list[dict[str, Any]], card_id: str) -> list[dict[str, Any]]:
    """The card's ancestors, nearest first. A parent is always from an earlier generation than its
    child, so a card written again later (a re-found seed) cannot make a cycle; a card with no
    earlier birth is a generation 0 seed.
    """
    tree: list[dict[str, Any]] = []
    queue: list[tuple[str, float]] = [(card_id, float("inf"))]
    while queue:
        current, before = queue.pop(0)
        if any(node["card_id"] == current for node in tree):
            continue
        born = _earliest_birth(births, current, before)
        if born is None:
            tree.append({"card_id": current, "generation": 0, "operator": "seed", "parents": []})
            continue
        tree.append({k: born[k] for k in ("card_id", "generation", "operator", "parents")})
        queue.extend((parent, born["generation"]) for parent in born["parents"])
    return tree


def export(summary: dict[str, Any]) -> dict[str, Any]:
    """The page's document. Raises for a missing control arm, floor or label."""
    claim = summary["claim"]
    if claim not in LABELS:
        raise UnlabeledRunError(f"claim {claim!r} is not one of {LABELS}")
    _require_arms(summary["curves"])
    if summary["floor"] is None:
        raise MissingFloorError("the run has no no-card floor (the empty card did not play)")
    curves = [{**point, "label": claim} for point in summary["curves"]]
    ungraded = [
        {
            "generation": p["generation"],
            "arm": p["arm"],
            "dropped_cases": p["cases_dropped_ungraded"],
            "kept_cases": p["cases_kept"],
        }
        for p in summary["curves"]
    ]
    pick = summary["picks"].get("evolved")
    return {
        "schema": SCHEMA,
        "label": summary["label"],
        "claim": claim,
        "dry_run": summary["label"].startswith("dry run"),
        "curves": curves,
        "floor": {**summary["floor"], "label": claim},
        "validation": [{**v, "label": claim} for v in summary["validation"]],
        "ungraded": ungraded,
        "noise": summary["noise"],
        "stop_reason": summary["stop_reason"],
        "spend": {"calls": 0, "label": "no Spark calls in a dry run"},
        "picks": summary["picks"],
        "family_tree": family_tree(summary["births"], pick) if pick else [],
    }


def main(argv: list[str] | None = None) -> int:
    """Write the page JSON, and the owner's local card copy if asked."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--cards-out", type=Path)
    args = parser.parse_args(argv)
    document = export(json.loads(args.summary.read_text()))
    args.out.write_text(json.dumps(document, indent=1) + "\n")
    if args.state and args.cards_out:
        cards = json.loads(args.state.read_text())["cards"]
        args.cards_out.write_text(json.dumps(cards, indent=1))
        args.cards_out.chmod(0o600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
