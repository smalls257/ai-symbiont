"""Route B rows for the Freedoom adapter: Route B chat shape, play-time system turn, no held out."""

import pytest

from symbiont.act1.game_lessons import GameLesson
from symbiont.act1.game_pains import GamePain
from symbiont.act1.glimmer import REASONING_SYSTEM_MESSAGE
from symbiont.act1.lesson_rows import Situation, dataset_rows, select_lessons, training_rows
from symbiont.act1.levels import HeldOutLevelError

CHECK_A = "Before open_door(), check that the Doors line lists a closed door close by."
CHECK_B = "Before shoot_nearest(), check that the Visible line lists an enemy."


def lesson(number, repeats=1, check=CHECK_A, level="MAP03", what=None):
    return GameLesson(
        lesson_id=f"l{number}",
        session_id="MAP03-glimmer_plain-s1",
        level=level,
        resolved_at=number,
        pain=GamePain.WASTED_MOVE,
        repeats=repeats,
        what_happened=what or f"`open_door()` changed nothing {number} times in the start room.",
        how_resolved="`go_to(door)` opened a door.",
        check=check,
    )


def test_each_row_is_routeb_chat_shape_under_the_play_time_system_turn():
    rows = training_rows(lesson(1), Situation("the game prompt", "go_to(door)"))
    assert len(rows) == 3
    for row in rows:
        roles = [message["role"] for message in row["messages"]]
        assert roles == ["system", "user", "assistant"]
        assert row["messages"][0]["content"] == REASONING_SYSTEM_MESSAGE
    assert rows[0]["messages"][2]["content"] == lesson(1).card()
    assert rows[1]["messages"][2]["content"] == CHECK_A
    assert rows[2]["messages"][1:] == [
        {"role": "user", "content": "the game prompt"},
        {"role": "assistant", "content": "go_to(door)"},
    ]


def test_without_a_logged_decision_only_the_two_card_rows_are_written():
    assert len(training_rows(lesson(1), None)) == 2


def test_dataset_rows_join_the_situation_by_session_and_resolving_decision():
    situations = {("MAP03-glimmer_plain-s1", 2): Situation("prompt at 2", "turn(90)")}
    rows = dataset_rows([lesson(1), lesson(2)], situations)
    assert len(rows) == 5
    assert rows[-1]["messages"][1]["content"] == "prompt at 2"


def test_selection_takes_repeated_mistakes_first_and_caps_one_check():
    lessons = [lesson(1), lesson(2, repeats=3), lesson(3, check=CHECK_B), lesson(4, repeats=2)]
    chosen = select_lessons(lessons, count=3, per_check=2)
    assert [chosen_lesson.lesson_id for chosen_lesson in chosen] == ["l2", "l4", "l3"]


def test_selection_drops_a_card_it_already_holds():
    same = GameLesson(**{**lesson(1).__dict__, "lesson_id": "copy"})
    assert len(select_lessons([lesson(1), same], count=5, per_check=5)) == 1


def test_a_held_out_level_lesson_is_refused_never_skipped():
    with pytest.raises(HeldOutLevelError):
        select_lessons([lesson(1, level="MAP04")], count=5, per_check=5)
    with pytest.raises(HeldOutLevelError):
        training_rows(lesson(1, level="MAP08"), None)
