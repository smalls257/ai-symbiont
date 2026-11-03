"""The reflection ledger: a session is asked once, across processes; a bad file raises."""

import pytest

from symbiont.store.reflections import (
    KEPT_PER_PROJECT,
    ReflectionLedger,
    ReflectionLedgerError,
)

pytestmark = pytest.mark.periphery


def test_an_asked_session_is_remembered_across_instances_and_per_repository(tmp_path):
    ReflectionLedger(tmp_path).mark_asked("demo", "s1")

    again = ReflectionLedger(tmp_path)

    assert again.asked("demo", "s1")
    assert not again.asked("demo", "s2") and not again.asked("other", "s1")


def test_only_the_newest_sessions_are_kept(tmp_path):
    ledger = ReflectionLedger(tmp_path)
    for number in range(KEPT_PER_PROJECT + 5):
        ledger.mark_asked("demo", f"s{number}")

    assert not ledger.asked("demo", "s0")
    assert ledger.asked("demo", f"s{KEPT_PER_PROJECT + 4}")


def test_a_malformed_ledger_raises_naming_the_file(tmp_path):
    (tmp_path / "reflections.json").write_text("[1, 2]")

    with pytest.raises(ReflectionLedgerError, match="reflections.json"):
        ReflectionLedger(tmp_path).asked("demo", "s1")
