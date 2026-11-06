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


def test_reworked_edits_and_failures_with_no_shown_fix_are_not_delivered(caplog):
    taught = fixed_by_edit()
    keeper = StaleLessons()

    with caplog.at_level(logging.WARNING):
        delivered = keeper.deliverable([reworked(), only_re_run(), taught])

    assert delivered == [taught]
    assert "symbiont repo mine" in caplog.text


def test_a_sibling_without_its_own_fix_stays_when_its_group_shows_one():
    taught = fixed_by_edit()
    sibling = replace(taught, fix=None, resolution=("ran `pip install pyyaml`",))

    assert StaleLessons().deliverable([taught, sibling]) == [taught, sibling]


def test_the_stale_store_is_logged_once_per_process_not_once_per_call(caplog):
    keeper = StaleLessons()

    with caplog.at_level(logging.WARNING):
        keeper.deliverable([reworked()])
        keeper.deliverable([only_re_run()])

    assert caplog.text.count("symbiont repo mine") == 1


def test_a_store_with_only_taught_lessons_logs_nothing(caplog):
    with caplog.at_level(logging.WARNING):
        assert StaleLessons().deliverable([fixed_by_edit()]) == [fixed_by_edit()]
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
