"""Written lessons, verdicts and judged candidates persist per project."""

import pytest

from symbiont.miner.lesson_context import AuthoredLesson, LessonKind, Review, Severity, Verdict
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery


def test_authored_lessons_round_trip_and_replace_by_id(tmp_path):
    store = Store.open(tmp_path / "s.db")
    first = AuthoredLesson(
        "a1", "Money is integer cents.", LessonKind.RULE, ("src/money.py",), "notes", Severity.HIGH
    )
    store.curation.add_authored("demo", first)
    store.curation.add_authored(
        "demo", AuthoredLesson("a1", "Money is integer cents, rounded once.", LessonKind.RULE)
    )
    store.curation.add_authored("other", AuthoredLesson("b1", "x", LessonKind.FRICTION))

    (kept,) = Store.open(tmp_path / "s.db").curation.authored("demo")

    assert kept.text.endswith("rounded once.") and kept.kind is LessonKind.RULE


def test_reviews_and_decided_candidates_are_kept_per_project(tmp_path):
    store = Store.open(tmp_path / "s.db")
    store.curation.save_review(
        "demo", "s:1:failed_command", Review(Verdict.NOISE, "", "Flaky test")
    )
    store.curation.decide("demo", ["s:2", "s:3"])
    store.curation.decide("demo", ["s:2"])

    assert store.curation.reviews("demo")["s:1:failed_command"].verdict is Verdict.NOISE
    assert store.curation.reviews("other") == {}
    assert store.curation.decided("demo") == {"s:2", "s:3"}
