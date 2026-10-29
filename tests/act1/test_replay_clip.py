"""The replay's guards: it plays logged replies in order and refuses a game that drifted."""

import importlib.util
import sys
from pathlib import Path

import pytest

from symbiont.act1.episode import Decision

SCRIPTS = Path(__file__).parents[2] / "scripts" / "act1"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("replay_clip_under_test", SCRIPTS / "replay_clip.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def decision(index, observation, reply):
    return Decision(index, observation, reply, "ok", None, "stop", 0, (), 0.0)


def test_replies_come_back_in_logged_order_and_calls_are_counted():
    calls = []
    reply = module.logged_replies([decision(0, "see door", "go_to(door)")], calls)
    assert reply("Now: see door").text == "go_to(door)"
    assert calls == [0]


def test_a_changed_observation_is_drift_not_a_quiet_mismatch():
    reply = module.logged_replies([decision(0, "see door", "go_to(door)")], [])
    with pytest.raises(module.ReplayDriftError, match="observation differs"):
        reply("Now: see wall")


def test_asking_for_an_unlogged_decision_is_drift():
    calls = [0]
    reply = module.logged_replies([decision(0, "a", "x")], calls)
    with pytest.raises(module.ReplayDriftError, match="never logged"):
        reply("a")


def test_panel_labels_map_back_to_tag_names():
    assert module.pains_by_name({"wall bump": 2, "room re-entered": 0}) == {"wall_bump": 2}
