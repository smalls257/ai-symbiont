"""Episode records: each played move becomes one vizdoom Record a meta-trainer can read."""

import io
import json

import pytest

from room_world import two_rooms_with_a_pillar
from symbiont.act1.env_text import GameStateView, Layout
from symbiont.act1.episode_records import PROVENANCE, Episode, EpisodeEnd, episode_records
from symbiont.act1.rooms import RoomFinder
from symbiont.act1.steplog import MoveKind, MoveRun
from symbiont.records.schema import Kind, dump_jsonl, load_jsonl

ROOMS = RoomFinder(two_rooms_with_a_pillar())
EPISODE = Episode("MAP03", "random", 7)
IN_ROOM_0 = (10.0, 10.0)
IN_ROOM_1 = (150.0, 50.0)


def view(position, angle=90.0, health=80.0, ammo=20.0, keys=()):
    return GameStateView(
        health=health,
        ammo=ammo,
        position=position,
        angle_deg=angle,
        objects=(),
        doors=(),
        keys_held=tuple(keys),
        layout=Layout(True, True, True, False),
        exits=(),
        closed_sectors=frozenset(),
    )


def move(decision, before, after, label="walk to BlueCard", outcome="arrived"):
    return MoveRun(decision, label, MoveKind.WALK, outcome, 12, before, after)


def two_moves():
    return [
        move(0, view(IN_ROOM_0), view(IN_ROOM_1, angle=181.6, health=70.0, keys=("blue",))),
        move(1, view(IN_ROOM_1), view(IN_ROOM_0), label="walk to exit"),
    ]


def test_each_run_becomes_one_command_record_named_by_level_policy_and_seed():
    records = episode_records(EPISODE, two_moves(), ROOMS, EpisodeEnd.DIED)
    assert [r.step for r in records] == [0, 1]
    assert [r.command for r in records] == ["walk to BlueCard", "walk to exit"]
    for record in records:
        assert record.kind is Kind.COMMAND
        assert record.harness == "vizdoom"
        assert record.project == "freedoom2"
        assert record.session_id == "MAP03-random-s7"
        assert record.task_id is None
        assert record.exit_code is None


def test_raw_carries_position_room_action_and_outcome():
    first = json.loads(episode_records(EPISODE, two_moves(), ROOMS, EpisodeEnd.DIED)[0].raw)
    assert first == {
        "level": "MAP03",
        "policy": "random",
        "seed": 7,
        "decision": 0,
        "position_before": [10, 10],
        "position_after": [150, 50],
        "room_before": 0,
        "room_after": 1,
        "angle": 182,
        "health": 70.0,
        "ammo": 20.0,
        "keys_held": ["blue"],
        "tics": 12,
        "outcome": "arrived",
        "ended": None,
        "health_before": 80,
        "ammo_before": 20,
    }


def test_tags_carry_the_policy_then_the_pains():
    records = episode_records(EPISODE, two_moves(), ROOMS, EpisodeEnd.DIED)
    assert records[0].tags == ("policy:random",)
    assert records[1].tags == ("policy:random", "pain:room_reentered")


def test_a_run_that_ended_the_episode_still_becomes_a_record():
    ended = move(0, view(IN_ROOM_0, angle=45.0), None, outcome="episode over")
    (record,) = episode_records(EPISODE, [ended], ROOMS, EpisodeEnd.EXITED)
    facts = json.loads(record.raw)
    assert facts["position_after"] is None
    assert facts["room_after"] is None
    assert facts["angle"] == 45
    assert record.tags == ("policy:random",)


def test_records_roundtrip_through_jsonl():
    records = episode_records(EPISODE, two_moves(), ROOMS, EpisodeEnd.DIED)
    buffer = io.StringIO()
    dump_jsonl(records, buffer)
    buffer.seek(0)
    assert list(load_jsonl(buffer)) == records


def test_records_are_spark_safe_selfplay():
    (record,) = episode_records(EPISODE, two_moves()[:1], ROOMS, EpisodeEnd.DIED)
    assert record.provenance == PROVENANCE
    assert PROVENANCE.spark_safe is True
    assert PROVENANCE.license == "BSD-3-Clause"


def test_the_last_record_says_how_the_episode_ended_and_earlier_ones_say_null():
    records = episode_records(EPISODE, two_moves(), ROOMS, EpisodeEnd.DIED)
    assert [json.loads(r.raw)["ended"] for r in records] == [None, "died"]


@pytest.mark.parametrize("ending", list(EpisodeEnd))
def test_every_ending_roundtrips_through_raw(ending):
    (record,) = episode_records(EPISODE, two_moves()[:1], ROOMS, ending)
    assert json.loads(record.raw)["ended"] == ending.value


def test_the_endings_are_the_four_named_values():
    assert {e.value for e in EpisodeEnd} == {"died", "exited", "timed_out", "decision_cap"}


def test_values_before_the_move_are_ints_so_a_pickup_can_be_derived():
    run = move(0, view(IN_ROOM_0, health=40.4, ammo=3.6), view(IN_ROOM_0, health=65.0, ammo=3.6))
    facts = json.loads(episode_records(EPISODE, [run], ROOMS, EpisodeEnd.EXITED)[0].raw)
    assert facts["health_before"] == 40
    assert facts["ammo_before"] == 4
    assert isinstance(facts["health_before"], int)
    assert isinstance(facts["ammo_before"], int)
    assert facts["health"] > facts["health_before"]


def test_an_angle_just_under_a_full_turn_wraps_to_zero():
    run = move(0, view(IN_ROOM_0, angle=359.6), view(IN_ROOM_0, angle=359.6))
    facts = json.loads(episode_records(EPISODE, [run], ROOMS, EpisodeEnd.EXITED)[0].raw)
    assert facts["angle"] == 0
