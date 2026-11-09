"""A store mined before the known-fix rule never speaks until it is mined again.

Failure guarded against: a pre-branch store keeps delivering reworked-edit notes and notes for
failures that only "passed" when re-run, because the rule that drops them runs at mining time.
"""

import logging
from dataclasses import replace

import pytest

from record_builders import edit, run, session
from symbiont.core.counters import Counters
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.screen import ScreenRules
from symbiont.service.app import Service, ServiceParts
from symbiont.service.events import EventLog
from symbiont.service.stale_lessons import StaleLessons
from symbiont.store.held_back import MiningOutcome
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"


def lesson_of(steps):
    (found,) = lessons_from(mine_history(sessions_of(steps), {}), steps, frozenset({"demo"}))
    return found


def fixed_by_edit():
    return lesson_of(
        session(
            run("pytest tests/test_parser.py", 1, IMPORT),
            edit("app/parser.py", diff="-a\n+def parse(text):\n"),
            run("pytest tests/test_parser.py", 0, "1 passed"),
        )
    )


def only_re_run():
    """A failure that passed on a second run with nothing changed: no fix was shown."""
    taught = fixed_by_edit()
    signature = Signature(Signal.FAILED_COMMAND, ("make", "lint", "exit 2"))
    return replace(
        taught,
        fix=None,
        resolution=("ran `make lint` again",),
        pain_point=replace(taught.pain_point, signature=signature),
    )


def reworked():
    taught = fixed_by_edit()
    signature = Signature(Signal.REWORKED_EDIT, ("app/parser.py",))
    return replace(taught, fix=None, pain_point=replace(taught.pain_point, signature=signature))


def in_session(found, session_id):
    pain = replace(found.pain_point, session_id=session_id)
    return replace(found, pain_point=pain, sources=((session_id, 1),))


def taught_twice():
    """A fix shown in two sessions: what the screen keeps at the default min_sessions."""
    return [in_session(fixed_by_edit(), "s1"), in_session(fixed_by_edit(), "s2")]


def older_store(tmp_path, lessons):
    """A store mined before the known-fix rule: it never recorded the min_sessions it used."""
    store = Store.open(tmp_path / "store.db")
    store.mined.save("demo", [], MiningOutcome(list(lessons)), held_out_tasks=frozenset())
    return store


def keeper_of(store):
    return StaleLessons(store, ScreenRules)


def test_reworked_edits_and_failures_with_no_shown_fix_are_not_delivered(tmp_path, caplog):
    taught = taught_twice()
    store = older_store(tmp_path, [reworked(), only_re_run(), *taught])

    with caplog.at_level(logging.WARNING):
        delivered = keeper_of(store).deliverable(store, "demo")

    assert delivered == taught
    assert "symbiont repo mine" in caplog.text


def test_a_sibling_without_its_own_fix_is_not_delivered_even_when_its_group_shows_one(tmp_path):
    taught = taught_twice()
    sibling = replace(taught[0], fix=None, resolution=("ran `pip install pyyaml`",))
    store = older_store(tmp_path, [*taught, in_session(sibling, "s3")])

    assert keeper_of(store).deliverable(store, "demo") == taught


def test_a_fix_shown_in_one_session_is_not_delivered_by_an_older_store(tmp_path):
    store = older_store(tmp_path, [fixed_by_edit()])
    assert keeper_of(store).deliverable(store, "demo") == []


def test_a_store_mined_with_min_sessions_one_delivers_a_single_session_fix(tmp_path):
    store = Store.open(tmp_path / "store.db")
    outcome = MiningOutcome([fixed_by_edit()], min_sessions=1)
    store.mined.save("demo", [], outcome, held_out_tasks=frozenset())
    assert keeper_of(store).deliverable(store, "demo") == [fixed_by_edit()]


def test_the_stale_store_is_logged_once_per_process_not_once_per_call(tmp_path, caplog):
    store = older_store(tmp_path, [reworked(), only_re_run()])
    keeper = keeper_of(store)

    with caplog.at_level(logging.WARNING):
        keeper.deliverable(store, "demo")
        keeper.deliverable(store, "demo")

    assert caplog.text.count("symbiont repo mine") == 1


def test_a_store_with_only_taught_lessons_logs_nothing(tmp_path, caplog):
    taught = taught_twice()
    store = older_store(tmp_path, taught)
    with caplog.at_level(logging.WARNING):
        assert keeper_of(store).deliverable(store, "demo") == taught
    assert caplog.text == ""


def test_recall_over_a_store_holding_only_stale_lessons_has_nothing_to_say(tmp_path):
    store = Store.open(tmp_path / "store.db")
    store.mined.save(
        "demo", [], MiningOutcome([reworked(), only_re_run()]), held_out_tasks=frozenset()
    )
    service = Service(ServiceParts(store, Counters(), EventLog(tmp_path / "run", "counters")))

    reply = service.respond("/recall", {"project": "demo", "question": "ImportError parser"})

    assert reply.status == 200 and "parse" not in reply.body["answer"]
    assert reply.body["records"] == []
