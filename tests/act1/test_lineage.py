"""Lineage: where every card came from, recorded when it is born."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from symbiont.act1.generality import Rejection
from symbiont.act1.lineage import (
    Arm,
    Birth,
    Lineage,
    LineageError,
    Operator,
    UnknownCardError,
    birth_from_json,
    birth_to_json,
)

ROOT = Path(__file__).resolve().parents[2]


def birth(card_id, operator, parents=(), generation=0, rejection=None, arm=Arm.EVOLVED):
    return Birth(card_id, generation, arm, operator, tuple(parents), "fake", rejection)


def family():
    lineage = Lineage()
    lineage.add(birth("seed1", Operator.SEED_HISTORY))
    lineage.add(birth("seed2", Operator.SEED_SPARK))
    lineage.add(birth("kid1", Operator.REWRITE, ["seed1"], 1))
    lineage.add(birth("cross", Operator.CROSSOVER, ["kid1", "seed2"], 2))
    return lineage


def test_a_crossover_has_two_parents_others_one_and_seeds_none():
    lineage = Lineage()
    lineage.add(birth("seed1", Operator.SEED_EMPTY))
    lineage.add(birth("seed2", Operator.SEED_HISTORY))
    with pytest.raises(LineageError, match="crossover"):
        lineage.add(birth("x", Operator.CROSSOVER, ["seed1"], 1))
    with pytest.raises(LineageError, match="rewrite"):
        lineage.add(birth("y", Operator.REWRITE, ["seed1", "seed2"], 1))
    with pytest.raises(LineageError, match="seed_spark"):
        lineage.add(birth("z", Operator.SEED_SPARK, ["seed1"]))
    with pytest.raises(LineageError, match="rewrite"):
        lineage.add(birth("w", Operator.REWRITE, [], 1))


def test_ancestors_walk_back_to_generation_zero():
    ancestry = family().ancestors("cross")
    assert [b.card_id for b in ancestry] == ["cross", "kid1", "seed2", "seed1"]
    assert ancestry[-1].generation == 0


def test_ancestors_of_an_unknown_card_raise():
    with pytest.raises(UnknownCardError, match="nope"):
        family().ancestors("nope")


def test_a_rejected_child_is_recorded_with_its_label_and_cannot_be_a_parent():
    lineage = family()
    lineage.add(birth("bad", Operator.ADD, ["seed1"], 1, Rejection.MAP_NAME))
    assert lineage.publishable()["births"][-1]["rejection"] == "map_name"
    with pytest.raises(LineageError, match="bad"):
        lineage.add(birth("grandkid", Operator.REWRITE, ["bad"], 2))
    with pytest.raises(UnknownCardError):
        lineage.ancestors("bad")


def test_a_parent_that_was_never_born_raises():
    with pytest.raises(LineageError, match="ghost"):
        Lineage().add(birth("kid", Operator.REWRITE, ["ghost"], 1))


def test_an_elite_carried_forward_keeps_its_original_ancestry():
    lineage = family()
    lineage.add(birth("kid1", Operator.ELITE, ["kid1"], 2))
    assert [b.card_id for b in lineage.ancestors("kid1")] == ["kid1", "seed1"]


def test_publishable_holds_ids_generations_operators_and_labels_only():
    document = family().publishable()
    assert document["births"][3] == {
        "card_id": "cross",
        "generation": 2,
        "arm": "evolved",
        "operator": "crossover",
        "parents": ["kid1", "seed2"],
        "author": "fake",
        "rejection": None,
    }


@pytest.mark.periphery
def test_publishable_passes_the_results_content_gate(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    target = results / "evolve-lineage.json"
    target.write_text(json.dumps(family().publishable()))
    gate = ROOT / "scripts" / "gates" / "check_results_content.py"
    done = subprocess.run(
        [sys.executable, str(gate), str(target)], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_birth_survives_the_json_round_trip_including_a_rejection():
    rejected = birth("bad", Operator.ADD, ["seed1"], 1, Rejection.MAP_NAME)
    assert birth_from_json(birth_to_json(rejected)) == rejected
    plain = birth("kid", Operator.CROSSOVER, ["a", "b"], 2)
    assert birth_from_json(birth_to_json(plain)) == plain
