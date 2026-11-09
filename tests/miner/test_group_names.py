"""Group names: a repeat is told apart without losing the part that tells it apart."""

from symbiont.miner.group_names import NAME_CHARS, distinct, shortened


def test_repeated_long_names_stay_distinct_within_the_name_limit():
    long = "You corrected the agent: " + "x" * 120
    names = distinct([shortened(long)] * 3, ["", "", ""])

    assert len(set(names)) == 3 and all(len(n) <= NAME_CHARS for n in names)
    assert names[1].endswith("(2)") and names[2].endswith("(3)")


def test_a_repeat_is_told_apart_by_its_place_when_it_has_one_and_unique_names_are_left_alone():
    names = distinct(["pytest failing", "pytest failing", "make failing"], ["api", "web", ""])

    assert names == ["pytest failing on api", "pytest failing on web", "make failing"]
