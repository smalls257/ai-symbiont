"""Episode records: each played move becomes one vizdoom Record a meta-trainer can read."""

import io
import json

from room_world import two_rooms_with_a_pillar
from symbiont.act1.env_text import GameStateView, Layout
from symbiont.act1.episode_records import PROVENANCE, Episode, episode_records
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
    records = episode_records(EPISODE, two_moves(), ROOMS)
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
    first = json.loads(episode_records(EPISODE, two_moves(), ROOMS)[0].raw)
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
    }


def test_tags_carry_the_policy_then_the_pains():
    records = episode_records(EPISODE, two_moves(), ROOMS)
    assert records[0].tags == ("policy:random",)
    assert records[1].tags == ("policy:random", "pain:room_reentered")


def test_a_run_that_ended_the_episode_still_becomes_a_record():
    ended = move(0, view(IN_ROOM_0, angle=45.0), None, outcome="episode over")
    (record,) = episode_records(EPISODE, [ended], ROOMS)
    facts = json.loads(record.raw)
    assert facts["position_after"] is None
    assert facts["room_after"] is None
    assert facts["angle"] == 45
    assert record.tags == ("policy:random",)


def test_records_roundtrip_through_jsonl():
    records = episode_records(EPISODE, two_moves(), ROOMS)
    buffer = io.StringIO()
    dump_jsonl(records, buffer)
    buffer.seek(0)
    assert list(load_jsonl(buffer)) == records


def test_records_are_spark_safe_selfplay():
    (record,) = episode_records(EPISODE, two_moves()[:1], ROOMS)
    assert record.provenance == PROVENANCE
    assert PROVENANCE.spark_safe is True
    assert PROVENANCE.license == "BSD-3-Clause"
