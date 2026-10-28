"""The local store: the hold-out and Spark guards raise, never filter quietly."""

from dataclasses import replace

import pytest

from record_builders import PUBLIC, edit, run, session, user
from symbiont.miner.painpoint import Signal
from symbiont.records.holdout import (
    HoldOutViolationError,
    UnrecognisedTaskIdError,
    normalise_task_id,
)
from symbiont.records.schema import Provenance
from symbiont.store.local import SparkPrivacyViolationError, Store, StoreConflictError

pytestmark = pytest.mark.periphery

PROJECT = "tobymao/sqlglot"
SWE_CHAT = Provenance(dataset="SWE-chat", license="ODC-BY", spark_safe=False)
NO_HOLD_OUT: frozenset[str] = frozenset()


def _task(records, task_id, session_id="s1", provenance=PUBLIC):
    return [
        replace(r, task_id=task_id, session_id=session_id, provenance=provenance) for r in records
    ]


def _failing_session(task_id="tobymao__sqlglot-1000", session_id="s1", provenance=PUBLIC):
    return _task(
        session(
            user("fix it"),
            run("pytest tests/test_parser.py", 1, "AssertionError"),
            edit("sqlglot/parser.py"),
        ),
        task_id,
        session_id,
        provenance,
    )


@pytest.fixture
def store(tmp_path):
    return Store.open(tmp_path / "store.sqlite")


def test_records_roundtrip_by_session_in_step_order(store):
    records = _failing_session()
    assert store.add_records(reversed(records), held_out_tasks=NO_HOLD_OUT) == 3
    assert store.sessions(PROJECT) == [records]


def test_store_reopens_from_disk(tmp_path):
    Store.open(tmp_path / "s.sqlite").add_records(_failing_session(), held_out_tasks=NO_HOLD_OUT)
    assert Store.open(tmp_path / "s.sqlite").sessions(PROJECT) == [_failing_session()]


def test_holdout_task_raises(store):
    held_out = frozenset({"tobymao__sqlglot-2000"})
    records = _failing_session() + _failing_session("tobymao__sqlglot-2000", "s2")
    with pytest.raises(HoldOutViolationError, match="tobymao__sqlglot-2000"):
        store.add_records(records, held_out_tasks=held_out)
    assert store.sessions(PROJECT) == []  # nothing from the batch was written


def test_holdout_matches_across_dataset_id_formats(store):
    held_out = frozenset({"tobymao/sqlglot#2000"})
    with pytest.raises(HoldOutViolationError):
        store.add_records(_failing_session("tobymao__sqlglot-2000"), held_out_tasks=held_out)


def test_holdout_set_must_be_stated(store):
    with pytest.raises(TypeError):
        store.add_records(_failing_session())


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("tobymao__sqlglot-1234", "tobymao/sqlglot#1234"),
        ("tobymao/sqlglot#1234", "tobymao/sqlglot#1234"),
        ("getmoto__moto-1234", "getmoto/moto#1234"),
        ("Owner__repo-name-77", "owner/repo-name#77"),
    ],
)
def test_normalise_task_id(given, expected):
    assert normalise_task_id(given) == expected


def test_readding_the_same_records_adds_nothing(store):
    store.add_records(_failing_session(), held_out_tasks=NO_HOLD_OUT)
    assert store.add_records(_failing_session(), held_out_tasks=NO_HOLD_OUT) == 0


def test_different_record_under_an_existing_key_raises(store):
    store.add_records(_failing_session(), held_out_tasks=NO_HOLD_OUT)
    changed = [replace(r, raw=r.raw + " (edited)") for r in _failing_session()]
    with pytest.raises(StoreConflictError, match="s1"):
        store.add_records(changed, held_out_tasks=NO_HOLD_OUT)


def test_mine_stores_pain_points(store):
    store.add_records(_failing_session(), held_out_tasks=NO_HOLD_OUT)
    assert store.mine(PROJECT, references={}) == 1
    (pain,) = store.pain_points(PROJECT)
    assert pain.signature.signal == Signal.FAILED_COMMAND
    assert store.records_for(pain.record_refs) == [_failing_session()[1]]


def test_mine_idempotent(store):
    store.add_records(_failing_session(), held_out_tasks=NO_HOLD_OUT)
    store.mine(PROJECT, references={})
    first = store.pain_points(PROJECT)
    store.mine(PROJECT, references={})
    assert store.pain_points(PROJECT) == first


def test_records_for_unknown_ref_raises(store):
    with pytest.raises(LookupError, match="nope"):
        store.records_for((("nope", 0),))


def test_spark_view_reads_public_records(store):
    store.add_records(_failing_session(), held_out_tasks=NO_HOLD_OUT)
    store.mine(PROJECT, references={})
    view = store.spark_view()
    assert view.sessions(PROJECT) == [_failing_session()]
    assert len(view.pain_points(PROJECT)) == 1


def test_spark_view_raises_on_private_record(store):
    private = _failing_session(session_id="chat-1", provenance=SWE_CHAT)
    store.add_records(_failing_session() + private, held_out_tasks=NO_HOLD_OUT)
    store.mine(PROJECT, references={})
    view = store.spark_view()
    with pytest.raises(SparkPrivacyViolationError, match="SWE-chat"):
        view.records_for((("chat-1", 1),))
    with pytest.raises(SparkPrivacyViolationError):
        view.sessions(PROJECT)
    with pytest.raises(SparkPrivacyViolationError):
        view.pain_points(PROJECT)
    assert view.records_for((("s1", 1),)) == [_failing_session()[1]]


def test_spark_view_is_read_only(store):
    view = store.spark_view()
    assert not hasattr(view, "add_records")
    assert not hasattr(view, "mine")


def test_unparseable_task_id_is_refused_not_matched_against_nothing():
    with pytest.raises(UnrecognisedTaskIdError, match="sqlglot-4001"):
        normalise_task_id("sqlglot-4001")


def test_held_out_id_that_does_not_parse_raises(store):
    """A typo in the hold-out set would otherwise guard nothing."""
    with pytest.raises(UnrecognisedTaskIdError, match="sqlglot-4001"):
        store.add_records(_failing_session(), held_out_tasks=frozenset({"sqlglot-4001"}))
    assert store.sessions(PROJECT) == []


def test_record_task_id_that_does_not_parse_raises_under_a_hold_out(store):
    """`sqlglot-2000` could be the held-out tobymao__sqlglot-2000 spelled another way."""
    with pytest.raises(UnrecognisedTaskIdError, match="sqlglot-2000"):
        store.add_records(
            _failing_session("sqlglot-2000"), held_out_tasks=frozenset({"tobymao__sqlglot-1"})
        )


def test_record_task_id_is_free_form_when_nothing_is_held_out(store):
    assert store.add_records(_failing_session("my-own-task"), held_out_tasks=NO_HOLD_OUT) == 3


def test_ref_lookups_use_an_index(store):
    """records_for is called per pain point; a full scan per ref does not scale."""
    plan = store._db.execute(
        "EXPLAIN QUERY PLAN SELECT body FROM records WHERE session_id=? AND step=?", ("s1", 0)
    ).fetchall()
    assert "USING INDEX" in str(plan) or "USING COVERING INDEX" in str(plan)


def test_spark_view_pain_points_checks_privacy_in_one_query(store):
    private = _failing_session(session_id="chat-1", provenance=SWE_CHAT)
    many = [r for i in range(20) for r in _failing_session(f"tobymao__sqlglot-{i}", f"s{i}")]
    store.add_records(many + private, held_out_tasks=NO_HOLD_OUT)
    store.mine(PROJECT, references={})
    queries = []
    store._db.set_trace_callback(queries.append)
    with pytest.raises(SparkPrivacyViolationError, match="SWE-chat"):
        store.spark_view().pain_points(PROJECT)
    assert len(queries) <= 3


def _edit_session(session_id, old, new, ts):
    from record_builders import replace_text

    return [
        replace(r, session_id=session_id, ts=ts, task_id=None)
        for r in session(replace_text("sqlglot/parser.py", old, new))
    ]


def _rework(store):
    return [p for p in store.pain_points(PROJECT) if p.signature.signal == Signal.REWORKED_EDIT]


def test_mine_finds_rework_across_timed_sessions_in_time_order(store):
    """A developer's sessions on one repo form a chain, ordered by when they ran
    (here the later session sorts first by id)."""
    earlier = _edit_session("b-monday", "x = 1", "x = compute_offset(node)", "2026-10-26T09:00:00Z")
    later = _edit_session("a-tuesday", "x = compute_offset(node)", "x = 2", "2026-10-27T09:00:00Z")
    store.add_records(later + earlier, held_out_tasks=NO_HOLD_OUT)
    store.mine(PROJECT, references={})
    (pain,) = _rework(store)
    assert (pain.session_id, pain.record_refs) == ("a-tuesday", (("b-monday", 0), ("a-tuesday", 0)))


def test_untimed_sessions_are_mined_alone(store):
    """Published trajectories are parallel attempts with no order; chaining them
    would make every attempt look like it reworked the others."""
    first = _edit_session("t1", "x = 1", "x = compute_offset(node)", None)
    second = _edit_session("t2", "x = compute_offset(node)", "x = 2", None)
    store.add_records(first + second, held_out_tasks=NO_HOLD_OUT)
    store.mine(PROJECT, references={})
    assert _rework(store) == []
