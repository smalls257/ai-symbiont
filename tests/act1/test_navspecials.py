import pytest

from symbiont.act1.map_index import DOOR_SPECIALS, EXIT_SPECIALS
from symbiont.act1.navspecials import (
    SPECIALS,
    Effect,
    Trigger,
    UnknownSpecialError,
    special_named,
)


def test_every_vanilla_number_from_1_to_141_is_listed_so_none_reads_as_a_wall_by_accident():
    assert [n for n in range(1, 142) if n not in SPECIALS] == []


def test_an_unlisted_special_raises_instead_of_being_guessed():
    with pytest.raises(UnknownSpecialError, match="special 9999"):
        special_named(9999)


def test_the_map_indexs_doors_and_exits_agree_with_the_table():
    for number in DOOR_SPECIALS:
        assert special_named(number).trigger == Trigger.MANUAL
    for number, secret in EXIT_SPECIALS.items():
        wanted = Effect.SECRET_EXIT if secret else Effect.EXIT
        assert special_named(number).effect == wanted


def test_keyed_switch_doors_name_their_color():
    assert special_named(133).key == "blue" and special_named(135).key == "red"
    assert special_named(137).key == "yellow"


def test_walk_and_use_lifts_are_both_lifts():
    assert special_named(88).effect == special_named(62).effect == Effect.LIFT
    assert special_named(88).trigger == Trigger.WALK and special_named(62).trigger == Trigger.USE


def test_what_the_planner_cannot_follow_says_why():
    stairs = special_named(8)
    assert stairs.effect == Effect.UNMODELED and "stairs" in stairs.note
