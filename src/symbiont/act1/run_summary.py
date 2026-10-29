"""The publishable summary of one Evolve run: counts, ids and labels, never card text (pure).

The progress page and the results files read this and nothing else, so a lesson's words cannot
leak through them. Each point names its generation, its arm and a label saying whether it came
from a dry run, an exploratory run on training levels, or a scored run.
"""

import statistics
from typing import Any

from symbiont.act1.card_genome import Card
from symbiont.act1.evolution import RunRecord
from symbiont.act1.lexicase import FitnessTable
from symbiont.act1.lineage import Arm, Lineage

SCHEMA = "evolve-run-v1"
ARM_ROLES = {
    Arm.EVOLVED: "under test",
    Arm.NO_SELECTION: "reference (equal compute)",
}


def _card_mean(table: FitnessTable, card_id: str) -> float:
    """A card's mean fitness over the table's kept cases."""
    return statistics.fmean(table.scores[(card_id, case)] for case in table.cases)


def _generation_points(arm: Arm, tables: list[FitnessTable]) -> list[dict[str, Any]]:
    """One point per generation for one arm: mean and best card mean, kept and dropped cases."""
    points = []
    for generation, table in enumerate(tables):
        means = [_card_mean(table, card_id) for card_id in table.cards]
        points.append(
            {
                "generation": generation,
                "arm": arm.value,
                "role": ARM_ROLES[arm],
                "mean_fitness": statistics.fmean(means),
                "best_fitness": max(means),
                "cases_kept": len(table.cases),
                "cases_dropped_ungraded": len(table.dropped_cases),
            }
        )
    return points


def _floor(record: RunRecord) -> dict[str, Any] | None:
    """The empty card's generation-0 mean: the no-card floor, if the empty card played."""
    empty = Card.of([]).card_id
    first = record.tables.get(Arm.EVOLVED, [None])[0]
    if first is None or empty not in first.cards:
        return None
    return {"role": "floor", "card": "no card", "mean_fitness": _card_mean(first, empty)}


def summary_of(record: RunRecord, label: str, claim: str, spend: dict[str, Any]) -> dict[str, Any]:
    """The run's counts, ids and labels. `claim` is 'exploratory' or 'scored'.

    `spend` is the run's ledger snapshot (calls, dollars, source), copied and never made up.
    """
    noise = record.noise
    lineage = Lineage()
    lineage.births = list(record.births)
    return {
        "schema": SCHEMA,
        "label": label,
        "claim": claim,
        "spend": dict(spend),
        "noise": None
        if noise is None
        else {
            "verdict": noise.verdict.value,
            "within_variance": noise.within_variance,
            "between_variance": noise.between_variance,
            "standard_error": noise.standard_error,
            "selection_games": noise.selection_games,
            "games_per_mean": noise.games_per_mean,
            "pairs_used": noise.pairs_used,
            "true_between_variance": noise.true_between_variance,
            "games_needed": noise.games_needed,
            "games_per_case": record.games_per_case,
        },
        "curves": [
            p for arm, tables in record.tables.items() for p in _generation_points(arm, tables)
        ],
        "floor": _floor(record),
        "validation": [
            {"generation": g, "training_mean": t, "validation_mean": v, "gap": t - v}
            for g, t, v in record.gaps
        ],
        "unroutable_spots": sum(g.result.unroutable_spots for g in record.games),
        "stop_reason": record.stop_reason,
        "last_played": record.last_played,
        "last_good": record.last_good,
        "picks": {arm.value: card_id for arm, card_id in record.picks.items()},
        "births": lineage.publishable()["births"],
        "archive": {arm.value: archive.to_json() for arm, archive in record.archives.items()},
    }
