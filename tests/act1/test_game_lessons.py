"""Game lessons: what happened, how it was resolved and the check, in the game's own words."""

import json
import re

import pytest

from symbiont.act1.episode_records import PROVENANCE
from symbiont.act1.game_lessons import (
    GameLesson,
    LessonSourceError,
    lessons_from_episode,
    lessons_from_history,
)
from symbiont.act1.game_pains import GamePain
from symbiont.records.schema import Kind, Record

SESSION = "MAP03-glimmer_plain-s1"


def step(index, move, outcome, rooms, pains=(), *, angle=90, keys=(), ended=None, session=SESSION):
    """One synthetic game record; `rooms` is (room before, room after)."""
    facts = {
        "level": session.split("-")[0],
        "decision": index,
        "outcome": outcome,
        "room_before": rooms[0],
        "room_after": rooms[1],
        "angle": angle,
        "keys_held": list(keys),
        "ended": ended,
    }
    return Record(
        harness="vizdoom",
        project="freedoom2",
        session_id=session,
        step=index,
        kind=Kind.COMMAND,
        raw=json.dumps(facts),
        provenance=PROVENANCE,
        command=f"scripted {move}",
        tags=("policy:glimmer_plain", *(f"pain:{pain}" for pain in pains)),
    )


def wall_bumps_then_door():
    """Three bumps into the north wall of the start room, then go_to(door) leads out."""
    bumps = [
        step(i, "walk_to(exit)", "blocked by a wall on the way to exit", (40, 40), ["wall_bump"])
        for i in range(3)
    ]
    return [*bumps, step(3, "go_to(door)", "arrived at door", (40, 41))]


def test_three_wall_bumps_become_one_lesson_with_the_move_that_got_out():
    (lesson,) = lessons_from_episode(wall_bumps_then_door()).lessons
    assert lesson.pain is GamePain.WALL_BUMP and lesson.repeats == 3 and lesson.level == "MAP03"
    assert lesson.what_happened == (
        "`walk_to(exit)` walked into a wall 3 times in the start room, heading north."
    )
    assert lesson.how_resolved == "`go_to(door)` took you into the second room you entered."
    assert (lesson.session_id, lesson.resolved_at) == (SESSION, 3)
    assert "Layout line" in lesson.check and "go_to" in lesson.check


def test_the_card_reads_what_happened_how_resolved_and_the_check_in_order():
    card = lessons_from_episode(wall_bumps_then_door()).lessons[0].card()
    parts = ("What happened: ", "How it was resolved: ", "The check to run: ")
    assert [card.index(part) for part in parts] == sorted(card.index(part) for part in parts)


def test_no_coordinates_sector_numbers_or_tag_names_reach_the_text():
    records = wall_bumps_then_door()
    for lesson in lessons_from_episode(records).lessons:
        text = lesson.card()
        assert "40" not in text and "41" not in text
        assert "wall_bump" not in text and "pain:" not in text
        assert not re.search(r"\(\s*-?\d+\s*,", text)


def test_a_mistake_nothing_later_fixed_is_counted_never_given_a_made_up_resolution():
    records = [
        step(0, "open_door()", "no door in reach", (5, 5), ["wasted_move"]),
        step(1, "open_door()", "no door in reach", (5, 5), ["wasted_move"], ended="decision_cap"),
    ]
    harvest = lessons_from_episode(records)
    assert harvest.lessons == ()
    assert harvest.unresolved == {"wasted_move": 1}
    assert harvest.mistakes == {"wasted_move": 2}


def test_a_turn_that_drifts_into_another_room_is_not_the_resolution():
    records = [
        step(0, "open_door()", "no door in reach", (5, 5), ["wasted_move"]),
        step(1, "turn(90)", "turned 90 degrees", (5, 6)),
        step(2, "go_to(key)", "arrived at BlueCard", (6, 7), keys=["BlueCard"]),
    ]
    (lesson,) = lessons_from_episode(records).lessons
    assert lesson.how_resolved == "`go_to(key)` picked up the BlueCard key."


def test_wasted_move_lessons_quote_the_scripts_reason_and_pick_the_matching_check():
    records = [
        step(0, "go_to(door)", "enemy in the way: Zombieman at 230", (5, 5), ["wasted_move"]),
        step(1, "go_to(exit)", "arrived at exit", (5, 9), ended="exited"),
    ]
    (lesson,) = lessons_from_episode(records).lessons
    assert lesson.what_happened == (
        '`go_to(door)` changed nothing once in the start room: the script said "enemy in the way".'
    )
    assert lesson.how_resolved == "`go_to(exit)` reached the exit and ended the level."
    assert lesson.check.startswith("When go_to stops for an enemy in the way, shoot_nearest()")


def test_a_reason_that_carries_numbers_is_left_out_rather_than_dumped():
    records = [
        step(0, "go_to(door)", "stuck at 120, 40", (5, 5), ["wasted_move"]),
        step(1, "open_door()", "opened", (5, 5)),
    ]
    (lesson,) = lessons_from_episode(records).lessons
    assert lesson.what_happened == "`go_to(door)` changed nothing once in the start room."
    assert lesson.how_resolved == "`open_door()` opened a door."


def test_reentered_and_rechecked_rooms_name_the_room_by_entry_order():
    records = [
        step(0, "go_to(door)", "arrived at door", (1, 2)),
        step(1, "go_to(door)", "arrived at door", (2, 1), ["room_reentered"]),
        step(2, "turn(90)", "turned 90 degrees", (1, 1), ["room_rechecked"]),
        step(3, "go_to(exit)", "arrived at exit", (1, 3)),
    ]
    lessons = {lesson.pain: lesson for lesson in lessons_from_episode(records).lessons}
    assert lessons[GamePain.ROOM_REENTERED].what_happened == (
        "You went back into the start room once after leaving it."
    )
    assert lessons[GamePain.ROOM_RECHECKED].what_happened == (
        "You turned to look around the start room once and saw nothing new."
    )
    assert lessons[GamePain.ROOM_REENTERED].how_resolved == (
        "`go_to(exit)` took you into the third room you entered."
    )


def test_history_merges_episodes_and_their_counters():
    other = [
        step(
            0, "shoot_nearest()", "no enemy visible", (8, 8), ["wasted_move"], session="MAP05-x-s2"
        ),
        step(1, "go_to(exit)", "arrived", (8, 9), session="MAP05-x-s2"),
    ]
    harvest = lessons_from_history([*wall_bumps_then_door(), *other])
    assert [lesson.level for lesson in harvest.lessons] == ["MAP03", "MAP05"]
    assert harvest.mistakes == {"wall_bump": 3, "wasted_move": 1}
    assert all(isinstance(lesson, GameLesson) for lesson in harvest.lessons)


def test_a_record_from_another_harness_or_episode_or_order_is_refused():
    coding = Record(
        harness="openhands",
        project="p",
        session_id=SESSION,
        step=0,
        kind=Kind.COMMAND,
        raw="{}",
        provenance=PROVENANCE,
    )
    with pytest.raises(LessonSourceError, match="not a game record"):
        lessons_from_episode([coding])
    mixed = [step(0, "turn(90)", "turned", (1, 1)), step(1, "turn(90)", "t", (1, 1), session="b")]
    with pytest.raises(LessonSourceError, match="two episodes"):
        lessons_from_episode(mixed)
    with pytest.raises(LessonSourceError, match="out of order"):
        lessons_from_episode([step(1, "turn(90)", "turned", (1, 1))])
    with pytest.raises(LessonSourceError, match="no records"):
        lessons_from_episode([])


def test_a_record_missing_its_facts_names_the_step():
    broken = step(0, "turn(90)", "turned", (1, 1))
    broken = Record(**{**broken.__dict__, "raw": json.dumps({"outcome": "x"})})
    with pytest.raises(LessonSourceError, match="step 0"):
        lessons_from_episode([broken])


def test_a_wasted_move_with_no_known_check_raises():
    records = [
        step(0, "dance()", "nothing", (1, 1), ["wasted_move"]),
        step(1, "go_to(exit)", "arrived", (1, 2)),
    ]
    with pytest.raises(LessonSourceError, match="no check"):
        lessons_from_episode(records)
