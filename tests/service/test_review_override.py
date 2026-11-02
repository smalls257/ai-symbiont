"""Keep or dismiss answers a reviewer's verdict and survives a reload.

Failure guarded against: a banner that returns on every page load, and a model verdict that
re-silences a lesson the developer already chose to keep.
"""

from dataclasses import replace
from datetime import date

import pytest

from record_builders import edit, run, session
from symbiont.miner.lesson_context import Review, ReviewOverride, Verdict
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.trained import lesson_id
from symbiont.service.context_route import save_context
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.effective_context import effective_contexts
from symbiont.service.request_shapes import BadRequestError
from symbiont.store.local import Store


def pytest_lessons():
    steps = session(
        run("pytest tests/test_refund.py -q", 1, "E   AssertionError: assert 1 == 2\n"),
        edit("src/refund.py"),
        run("pytest tests/test_refund.py -q", 0, "1 passed"),
    )
    steps = [replace(step, project="demo", session_id="s1") for step in steps]
    return lessons_from(mine_history(sessions_of(steps), {}), steps)


def rig(tmp_path):
    (lesson,) = pytest_lessons()
    store = Store.open(tmp_path / "s.db")
    store.save_mining("demo", [], [lesson], held_out_tasks=frozenset())
    store.curation.save_review("demo", lesson_id(lesson), Review(Verdict.NOISE))
    return store, lesson, lesson_id(lesson)


def answer(store, ident, choice):
    save_context(
        store,
        ident,
        {"text": "Matters.", "intentional": choice == "dismiss", "review_override": choice},
    )


def test_keep_leaves_the_lesson_active_and_is_stored(tmp_path):
    store, _, ident = rig(tmp_path)

    answer(store, ident, "keep")

    assert store.contexts.overrides("demo") == {ident: ReviewOverride.KEEP}
    assert not effective_contexts(store, "demo")[ident].intentional


def test_dismiss_silences_the_lesson_and_is_stored(tmp_path):
    store, _, ident = rig(tmp_path)

    answer(store, ident, "dismiss")

    assert store.contexts.overrides("demo") == {ident: ReviewOverride.DISMISS}
    assert effective_contexts(store, "demo")[ident].intentional


def test_the_answer_survives_reopening_the_store_and_resolves_the_banner(tmp_path):
    store, lesson, ident = rig(tmp_path)
    answer(store, ident, "keep")
    reopened = Store.open(tmp_path / "s.db")
    annotated = frozenset(reopened.contexts.all("demo")) - frozenset(
        reopened.contexts.overrides("demo")
    )
    view = RepoView(
        "demo",
        [lesson],
        effective_contexts(reopened, "demo"),
        {},
        reopened.curation.reviews("demo"),
        annotated=annotated,
    )

    snapshot = dashboard_snapshot(view, date(2026, 11, 2))

    assert snapshot["lessons"][0]["reviewConflict"] is None


def test_an_unknown_answer_is_refused(tmp_path):
    store, _, ident = rig(tmp_path)

    with pytest.raises(BadRequestError, match="keep or dismiss"):
        save_context(store, ident, {"text": "x", "review_override": "maybe"})
