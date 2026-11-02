"""The developer's words about a lesson persist, survive re-mining and stay per repository."""

import pytest

from symbiont.miner.lesson_context import LessonContext, Priority
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery


def test_words_are_saved_replaced_and_read_back_across_connections(tmp_path):
    store = Store.open(tmp_path / "s.db")
    store.contexts.save("s:1:failed_command", "demo", LessonContext("first"))
    store.contexts.save("s:1:failed_command", "demo", LessonContext("second", True, Priority.HIGH))

    again = Store.open(tmp_path / "s.db").contexts

    assert again.get("s:1:failed_command") == LessonContext("second", True, Priority.HIGH)
    assert again.get("nope") is None


def test_all_returns_only_the_projects_words(tmp_path):
    store = Store.open(tmp_path / "s.db")
    store.contexts.save("a", "demo", LessonContext("mine"))
    store.contexts.save("b", "other", LessonContext("theirs"))

    assert store.contexts.all("demo") == {"a": LessonContext("mine")}
