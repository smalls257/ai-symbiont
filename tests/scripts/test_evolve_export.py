"""The progress export: control arm and floor are mandatory, every point is labeled, no text."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from evolve_world import run

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import export_progress  # noqa: E402 - needs the scripts path added above

from symbiont.act1.run_summary import summary_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.periphery
SPEND = {"calls": 3, "dollars": 0.001, "source": "ledger"}


@pytest.fixture(scope="module")
def record():
    return run(generations=3)


def summary(record, label="dry run, fake player", claim="exploratory"):
    return summary_of(record, label, claim, SPEND)


def test_export_without_the_control_arm_raises(record):
    broken = summary(record)
    broken["curves"] = [p for p in broken["curves"] if p["arm"] != "no_selection"]
    with pytest.raises(export_progress.MissingControlArmError, match="no_selection"):
        export_progress.export(broken)


def test_export_with_arms_covering_different_generations_raises(record):
    broken = summary(record)
    broken["curves"] = [
        p for p in broken["curves"] if not (p["arm"] == "no_selection" and p["generation"] == 3)
    ]
    with pytest.raises(export_progress.MissingControlArmError, match="same generations"):
        export_progress.export(broken)


def test_export_without_the_floor_raises(record):
    broken = summary(record)
    broken["floor"] = None
    with pytest.raises(export_progress.MissingFloorError):
        export_progress.export(broken)


def test_an_unlabeled_claim_raises(record):
    with pytest.raises(export_progress.UnlabeledRunError):
        export_progress.export(summary(record, claim="proven"))


def test_every_curve_point_names_its_generation_arm_and_label(record):
    document = export_progress.export(summary(record))
    assert document["dry_run"] is True and document["label"] == "dry run, fake player"
    for point in document["curves"] + document["validation"] + [document["floor"]]:
        assert point["label"] == "exploratory"
    assert all({"generation", "arm"} <= set(p) for p in document["curves"])
    assert document["spend"] == SPEND


def test_the_family_tree_of_the_pick_reaches_a_seed(record):
    document = export_progress.export(summary(record))
    tree = document["family_tree"]
    assert tree[0]["card_id"] == document["picks"]["evolved"]
    ids = {node["card_id"] for node in tree}
    assert all(parent in ids for node in tree for parent in node["parents"])
    assert any(node["operator"] == "seed" and node["generation"] == 0 for node in tree)


def test_the_published_json_passes_the_results_content_gate_and_holds_no_card_text(
    record, tmp_path
):
    document = export_progress.export(summary(record))
    target = tmp_path / "dashboard" / "sample" / "evolve-dry-run.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(document))
    gate = ROOT / "scripts" / "gates" / "check_results_content.py"
    done = subprocess.run(
        [sys.executable, str(gate), str(target)], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr
    for card in record.cards.values():
        for lesson in card.lessons:
            assert lesson.instead not in target.read_text()


def test_main_writes_the_page_json_and_a_private_local_copy_of_the_cards(record, tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary(record)))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"games": {}, "cards": {"abc": "1. What went wrong: x."}}))
    out, cards = tmp_path / "out.json", tmp_path / "cards.local.json"
    args = ["--summary", str(summary_path), "--out", str(out), "--state", str(state)]
    assert export_progress.main([*args, "--cards-out", str(cards)]) == 0
    assert json.loads(out.read_text())["schema"] == export_progress.SCHEMA
    assert json.loads(cards.read_text()) == {"abc": "1. What went wrong: x."}
    assert cards.stat().st_mode & 0o077 == 0


def test_the_summary_is_not_mutated_by_the_export(record):
    original = summary(record)
    snapshot = copy.deepcopy(original)
    export_progress.export(original)
    assert original == snapshot


def test_a_card_found_again_later_does_not_make_the_family_tree_cycle():
    def birth(card, generation, operator, parents):
        return {"card_id": card, "generation": generation, "operator": operator,
                "parents": parents, "rejection": None}  # fmt: skip

    births = [birth("b", 1, "add", ["a"]), birth("a", 5, "delete", ["b"])]
    tree = export_progress.family_tree(births, "b")
    assert [(n["card_id"], n["operator"]) for n in tree] == [("b", "add"), ("a", "seed")]


def test_a_summary_without_a_ledger_snapshot_is_refused_not_given_a_made_up_spend(record):
    broken = summary(record)
    del broken["spend"]
    with pytest.raises(export_progress.MissingSpendError):
        export_progress.export(broken)
