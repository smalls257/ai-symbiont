"""A developer's correction is a house rule: it is heard and outranks an older contradicting lesson.

Failures guarded against: Paper Tiger (a correction stored but never delivered, or outvoted by a
reflection written before it) and Silent Fallback (a lesson dropped with no trace of why).
"""

import pytest

from symbiont.core.house_rules import (
    MAX_STANDING,
    retired_by_corrections,
    standing_corrections,
    standing_sentence,
)
from symbiont.core.rule_relevance import MAX_NOTE_CHARS, Rule, rules_of
from symbiont.miner.lesson_context import AppliesTo, AuthoredLesson, LessonKind, Priority, Severity

REFLECTION = (
    "Parcel labels are priced from the stored zone table (zones.cached), never from the live "
    "carrier quote, so a label total is stable when it is reprinted."
)
CORRECTION = "Price a parcel label from the live carrier quote, not from the stored zone table."


def written(ident, text, kind, **extra):
    return AuthoredLesson(ident, text, kind, **extra)


def rules(*items):
    return rules_of([], {}, list(items))


def test_a_reflection_written_before_a_correction_on_the_same_subject_is_retired():
    both = rules(
        written("refl", REFLECTION, LessonKind.RULE, source_label="from reflection"),
        written("fix", CORRECTION, LessonKind.CORRECTION),
    )

    retired = retired_by_corrections(both)

    assert set(retired) == {"refl"}
    assert retired["refl"].newer == "fix"
    assert "stored zone table" in retired["refl"].older_excerpt
    assert retired["refl"].newer_excerpt.startswith("Price a parcel label")


def test_a_reflection_written_after_the_correction_was_made_with_it_in_view_and_stays():
    both = rules(
        written("fix", CORRECTION, LessonKind.CORRECTION),
        written("refl", REFLECTION, LessonKind.RULE),
    )

    assert retired_by_corrections(both) == {}


def test_a_reflection_about_another_subject_is_not_retired():
    other = "Label printing retries twice when the spooler answers busy; do not add a third."
    both = rules(
        written("other", other, LessonKind.RULE),
        written("fix", CORRECTION, LessonKind.CORRECTION),
    )

    assert retired_by_corrections(both) == {}


def test_a_correction_is_never_retired_by_a_later_correction_that_shares_its_words():
    both = rules(
        written("first", CORRECTION, LessonKind.CORRECTION),
        written(
            "second",
            "A parcel label total from the live carrier quote rounds up.",
            LessonKind.CORRECTION,
        ),
    )

    assert retired_by_corrections(both) == {}


def test_the_writers_term_tags_count_toward_the_subject():
    tagged = written(
        "refl",
        "Keep the cached table for each lookup.",
        LessonKind.RULE,
        applies=AppliesTo(terms=("carrier_quote",)),
    )
    fix = written("fix", "Never skip the carrier_quote lookup.", LessonKind.CORRECTION)

    assert set(retired_by_corrections(rules(tagged, fix))) == {"refl"}


def corrections(count, **first):
    items = [
        written(f"c{n}", f"House rule number {n} about parcel weight.", LessonKind.CORRECTION)
        for n in range(count)
    ]
    return rules(*items)


def test_standing_corrections_are_the_most_recent_up_to_the_cap():
    said = standing_corrections(corrections(5), frozenset())

    assert [rule.ident for rule in said] == ["c4", "c3", "c2"]
    assert len(said) == MAX_STANDING


def test_a_high_priority_correction_comes_before_newer_normal_ones():
    items = [
        written(
            "old", "Always weigh the box twice.", LessonKind.CORRECTION, severity=Severity.HIGH
        ),
        written("new", "Tape seams are billed per roll.", LessonKind.CORRECTION),
    ]

    assert [rule.ident for rule in standing_corrections(rules(*items), frozenset())] == [
        "old",
        "new",
    ]
    assert rules(*items)[0].words.priority is Priority.HIGH


def test_only_corrections_stand_and_left_out_ones_do_not():
    mixed = rules(
        written("note", "Reprints reuse the old total.", LessonKind.RULE),
        written("a", "Round weights up to the next gram.", LessonKind.CORRECTION),
        written("b", "Never ship on a Sunday.", LessonKind.CORRECTION),
    )

    assert [r.ident for r in standing_corrections(mixed, frozenset({"b"}))] == ["a"]


def test_the_standing_sentence_is_plain_prose_without_scores():
    said = standing_sentence(standing_corrections(corrections(2), frozenset()))

    assert said == (
        "[symbiont] House rules for this repo (from your corrections and PR reviews): "
        "House rule number 1 about parcel weight. House rule number 0 about parcel weight."
    )


def test_the_standing_sentence_drops_whole_rules_that_would_pass_the_cap():
    long_rule = "Pack fragile items with " + "foam, " * 82 + "and never stack them."
    items = [
        written("one", "Weigh every box twice.", LessonKind.CORRECTION),
        written("two", long_rule, LessonKind.CORRECTION),
    ]
    ranked = standing_corrections(rules(*items), frozenset())

    said = standing_sentence(ranked)

    assert ranked[0].ident == "two"
    assert len(said) <= MAX_NOTE_CHARS
    assert said.endswith("never stack them.")
    assert "Weigh every box" not in said


def test_one_correction_alone_longer_than_the_cap_is_cut_at_a_boundary():
    long_rule = ". ".join(f"Step {n} is to check the seal" for n in range(60))
    only = standing_corrections(rules(written("x", long_rule, LessonKind.CORRECTION)), frozenset())

    said = standing_sentence(only)

    assert said.endswith("...") and len(said) < MAX_NOTE_CHARS + 60


def test_nothing_to_say_is_an_error_not_an_empty_note():
    with pytest.raises(ValueError):
        standing_sentence([])


def test_mined_rules_have_no_kind_and_are_never_retired_or_standing():
    plain = Rule("m", rules(written("a", "x", LessonKind.RULE))[0].words, ())

    assert retired_by_corrections([plain]) == {}
    assert standing_corrections([plain], frozenset()) == []


PR = "https://github.com/acme/parcels/pull/412"
DUCKDB_RULING = "Do not copy properties inside a generator sub-method; generate copies once."


def test_a_review_ruling_saved_as_a_rule_stands_like_a_correction():
    ruling = written("pr", DUCKDB_RULING, LessonKind.RULE, source_url=PR)
    plain = written("plain", "Reprints reuse the old total.", LessonKind.RULE)

    said = standing_corrections(rules(plain, ruling), frozenset())

    assert [rule.ident for rule in said] == ["pr"]


def test_a_pr_linked_mistake_from_ci_is_not_a_house_rule():
    from_ci = written("ci", "The lint job failed.", LessonKind.MISTAKE, source_url=PR)

    assert standing_corrections(rules(from_ci), frozenset()) == []


def test_the_developers_own_corrections_come_before_pr_rulings_then_newest_first():
    items = [
        written("own-old", "Weigh every box twice.", LessonKind.CORRECTION),
        written("pr-old", "Seal cartons before labeling.", LessonKind.RULE, source_url=PR),
        written("own-new", "Tape seams are billed per roll.", LessonKind.CORRECTION),
        written("pr-new", DUCKDB_RULING, LessonKind.CORRECTION, source_url=PR),
        written("pr-newest", "Pallets ship on Mondays.", LessonKind.RULE, source_url=PR),
    ]

    said = standing_corrections(rules(*items), frozenset())

    assert [rule.ident for rule in said] == ["own-new", "own-old", "pr-newest"]


def test_a_later_user_correction_still_retires_an_older_review_ruling():
    items = [
        written("pr", REFLECTION, LessonKind.RULE, source_url=PR),
        written("fix", CORRECTION, LessonKind.CORRECTION),
    ]

    assert set(retired_by_corrections(rules(*items))) == {"pr"}


def test_a_pr_correction_does_not_retire_an_older_ruling_from_another_pull_request():
    other = "https://github.com/acme/parcels/pull/413"
    items = [
        written(
            "copy",
            "Do not copy label rows in the carrier sub-method.",
            LessonKind.RULE,
            source_url=PR,
        ),
        written(
            "guard",
            "Do not add a carrier null guard around label rows.",
            LessonKind.CORRECTION,
            source_url=other,
        ),
    ]

    assert retired_by_corrections(rules(*items)) == {}
