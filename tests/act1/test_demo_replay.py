"""demo-replay-v1 from two played episodes: counters come from pain tags, totals from the steps."""

import json

import pytest

from symbiont.act1.demo_replay import ArmEpisode, ReplayError, ReplayTask, demo_replay
from symbiont.act1.episode import Decision
from symbiont.act1.episode_records import PROVENANCE
from symbiont.records.schema import Kind, Record

TASK = ReplayTask("MAP03", 2, "synthetic", "hypothesis")


def record(step, decision, move, pains=(), ended=None, room=1):
    facts = {"decision": decision, "room_before": room, "room_after": room, "ended": ended}
    return Record(
        harness="vizdoom",
        project="freedoom2",
        session_id="MAP03-x-s2",
        step=step,
        kind=Kind.COMMAND,
        raw=json.dumps(facts),
        provenance=PROVENANCE,
        command=f"scripted {move}",
        tags=tuple(f"pain:{pain}" for pain in pains),
    )


def decision(index, outcomes, status="ok", tokens=(700, 40), seconds=30.0):
    return Decision(
        index, "view", "reply", status, None, "stop", 0, tuple(outcomes), seconds, *tokens
    )


def plain_episode():
    """Two wasted open_door() in one room: the second is a repeat; then the decision cap."""
    decisions = [
        decision(0, ["scripted open_door() -> no door in reach"]),
        decision(1, ["scripted open_door() -> no door in reach", "scripted turn(90) -> turned"]),
        decision(2, [], status="invalid", tokens=(650, 1500)),
    ]
    records = [
        record(0, 0, "open_door()", ["wasted_move"]),
        record(1, 1, "open_door()", ["wasted_move"]),
        record(2, 1, "turn(90)", ended="decision_cap"),
    ]
    return ArmEpisode("plain", "Glimmer", "glimmer", None, decisions, records)


def personal_episode():
    decisions = [decision(0, ["scripted go_to(exit) -> arrived at exit"])]
    records = [record(0, 0, "go_to(exit)", ended="exited")]
    return ArmEpisode("personal", "Glimmer + adapter", "glimmer", "freedoom", decisions, records)


def test_steps_carry_the_tagged_mistakes_and_the_totals_add_up():
    plain, personal = demo_replay(TASK, plain_episode(), personal_episode())["runs"]
    assert [s["mistake_tag"] for s in plain["steps"]] == ["new", "repeated", "none"]
    assert [s["outcome"] for s in plain["steps"]] == ["failed", "failed", "failed"]
    assert plain["steps"][1]["action"] == "scripted open_door(), scripted turn(90)"
    assert plain["steps"][2]["action"] == "reply invalid: no move played"
    totals = plain["totals"]
    assert (totals["repeated_mistakes"], totals["new_mistakes"], totals["wasted_steps"]) == (
        1,
        1,
        2,
    )
    assert (totals["tokens_in"], totals["tokens_out"], totals["wall_s"]) == (2050, 1580, 90.0)
    assert totals["result"] == "not solved" and totals["steps"] == 3
    assert personal["totals"]["result"] == "solved"
    assert personal["steps"][0]["outcome"] == "solved"


def test_roles_adapters_and_the_absence_of_notes_follow_the_demo_contract():
    document = demo_replay(TASK, plain_episode(), personal_episode())
    assert document["schema"] == "demo-replay-v1" and document["status"] == "hypothesis"
    plain, personal = document["runs"]
    assert (plain["role"], plain["adapter"]) == ("floor", None)
    assert (personal["role"], personal["adapter"]) == ("under test", "freedoom")
    for run in (plain, personal):
        assert [s["step"] for s in run["steps"]] == list(range(1, len(run["steps"]) + 1))
        assert all(s["note"] is s["classifier"] is s["picker"] is None for s in run["steps"])


def test_an_action_label_is_cut_to_twelve_words():
    long_moves = [f"scripted walk_to(a b c {n}) -> arrived" for n in range(3)]
    episode = ArmEpisode("plain", "G", "g", None, [decision(0, long_moves)], [record(0, 0, "x")])
    run = demo_replay(TASK, episode, personal_episode())["runs"][0]
    assert len(run["steps"][0]["action"].split()) == 12


def test_a_plain_run_with_an_adapter_or_a_bad_tag_is_refused():
    with_adapter = ArmEpisode(**{**plain_episode().__dict__, "adapter": "freedoom"})
    with pytest.raises(ReplayError, match="floor"):
        demo_replay(TASK, with_adapter, personal_episode())
    with pytest.raises(ReplayError, match="status"):
        demo_replay(ReplayTask("MAP03", 2, "s", "probably"), plain_episode(), personal_episode())
    with pytest.raises(ReplayError, match="plain then personal"):
        demo_replay(TASK, personal_episode(), plain_episode())
