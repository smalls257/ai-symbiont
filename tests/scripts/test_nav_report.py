"""Navigation report: reasons become short kinds; held-out levels are never marked as walked."""

import json
import sys
from pathlib import Path

from wad_builder import sample_wad

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import nav_report  # noqa: E402 - needs the scripts path added above

WALKED = {"level": "MAP01", "reached_exit": True, "decisions": 1, "last_outcomes": ["x"]}


def test_a_blocker_reason_becomes_one_short_kind():
    assert nav_report.blocker_kind("beyond that is a 72-unit climb") == "climb"
    assert nav_report.blocker_kind("beyond that is only 40 units of headroom") == "headroom"
    assert nav_report.blocker_kind("locked door: needs blue key") == "locked_door"
    assert nav_report.blocker_kind("beyond that is the edge of the map (no sector there)") == "void"
    assert nav_report.blocker_kind("something nobody wrote a kind for") == "other"


def test_the_way_a_walk_ended_becomes_one_short_kind():
    assert nav_report.walk_kind("go_to(exit) -> stuck at 1,2 at waypoint 3 of 4") == "stuck"
    assert nav_report.walk_kind("go_to(exit) -> out of tic budget (2500)") == "tic_budget"
    assert nav_report.walk_kind("go_to(exit) -> reached exit, but the level did not end") == (
        "level_not_ended"
    )


def test_a_training_level_with_a_walk_reports_it_and_a_held_out_level_never_does():
    wad = sample_wad()
    training = nav_report.level_row(wad, "MAP01", {"MAP01": WALKED})
    assert training["split"] == "training" and training["walk"] == "exit_reached"
    held_out_wad = wad.replace(b"MAP01\0\0\0", b"MAP04\0\0\0")
    held_out = nav_report.level_row(held_out_wad, "MAP04", {"MAP04": {**WALKED, "level": "MAP04"}})
    assert held_out["split"] == "held_out" and held_out["walk"] == "not_played"


def test_walks_are_read_back_from_the_verifier_files(tmp_path):
    (tmp_path / "MAP01.jsonl").write_text(json.dumps(WALKED) + "\n")
    assert nav_report.read_walks(tmp_path) == {"MAP01": WALKED}
