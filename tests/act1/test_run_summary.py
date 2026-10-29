"""The run summary holds counts, ids and labels only, and names the floor and the control arm."""

import json

from evolve_world import run
from symbiont.act1.card_genome import Card
from symbiont.act1.lineage import Arm
from symbiont.act1.run_summary import SCHEMA, summary_of

SPEND = {"calls": 0, "dollars": 0.0, "source": "ledger"}


def summary(**kwargs):
    return summary_of(run(**kwargs), "dry run, fake player", "exploratory", SPEND)


def test_every_curve_point_names_its_generation_arm_role_and_the_run_names_its_label():
    doc = summary()
    assert doc["schema"] == SCHEMA and doc["label"] == "dry run, fake player"
    assert doc["claim"] == "exploratory"
    arms = {p["arm"] for p in doc["curves"]}
    assert arms == {"evolved", "no_selection"}
    assert all({"generation", "arm", "role", "mean_fitness"} <= set(p) for p in doc["curves"])
    assert {p["role"] for p in doc["curves"]} == {"under test", "reference (equal compute)"}
    assert len([p for p in doc["curves"] if p["arm"] == "evolved"]) == 4


def test_the_floor_is_the_empty_cards_generation_zero_mean():
    doc = summary()
    assert doc["floor"]["role"] == "floor" and isinstance(doc["floor"]["mean_fitness"], float)


def test_validation_gap_points_and_picks_are_present():
    doc = summary()
    assert len(doc["validation"]) == 3
    assert all(
        abs(v["gap"] - (v["training_mean"] - v["validation_mean"])) < 1e-12
        for v in doc["validation"]
    )
    assert set(doc["picks"]) == {"evolved", "no_selection"}


def test_no_lesson_text_reaches_the_summary():
    record = run()
    text = json.dumps(summary_of(record, "dry run", "exploratory", SPEND))
    for card in record.cards.values():
        for lesson in card.lessons:
            assert lesson.instead not in text and lesson.went_wrong not in text
    assert record.picks[Arm.EVOLVED] in text  # ids are fine


def test_a_run_without_the_empty_card_has_no_floor():
    record = run()
    first = record.tables[Arm.EVOLVED][0]
    record.tables[Arm.EVOLVED][0] = type(first)(
        tuple(c for c in first.cards if c != Card.of([]).card_id),
        first.cases,
        first.scores,
        first.dropped_cases,
    )
    assert summary_of(record, "x", "exploratory", SPEND)["floor"] is None


def test_the_spend_is_the_ledgers_snapshot_copied_into_the_summary():
    snapshot = {"calls": 12, "dollars": 0.004, "source": "ledger"}
    doc = summary_of(run(), "exploratory run", "exploratory", snapshot)
    assert doc["spend"] == snapshot and doc["spend"] is not snapshot


def test_the_summary_counts_the_spots_the_nav_could_not_route():
    assert summary()["unroutable_spots"] == 0
