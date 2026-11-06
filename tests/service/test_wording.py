"""Counts read as English: one session, two sessions."""

from symbiont.service.wording import counted


def test_a_count_of_one_is_singular_and_every_other_count_is_plural():
    assert counted(1, "session") == "1 session"
    assert counted(0, "session") == "0 sessions"
    assert counted(2, "lesson") == "2 lessons"
