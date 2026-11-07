"""The session page's detail: lanes, messages with their neighbors, failures, scrubbing.

Failures guarded against: Leaky Narrative (a credential reaching the page in a message, a command
or an error) and Silent Fallback (a long session cut with no word of how much was left out).
"""

from dataclasses import replace

from record_builders import edit, run, say, session, user
from symbiont.miner.session_detail import session_detail

PASSWORD_URL = "https://dev:" + "hunter2hunter2" + "@example.com/repo.git"
BEARER = "Bearer " + "abcdefghij0123456789klmnop"


def stamped(records, first="2026-03-04T10:00:00+00:00", last="2026-03-04T10:42:00+00:00"):
    records = [replace(r, project="demo") for r in records]
    return [replace(records[0], ts=first), *records[1:-1], replace(records[-1], ts=last)]


def story():
    return session(
        user("please fix the parser"),
        run("cd /repo && pytest tests/test_parser.py -q", 1, "E   AssertionError: no parse"),
        edit("/home/dev/demo/src/parser.py"),
        edit("/tmp/notes.md"),
        say("trying again"),
        user("no, use the other helper"),
        run("pytest tests/test_parser.py -q", 0, "1 passed"),
    )


def test_lanes_and_counts_of_a_small_session():
    detail = session_detail(stamped(story())).as_json()

    assert [lane for _, lane, _ in detail["steps"]] == [
        "you", "failed", "edit", "scratch", "you", "passed",
    ]  # fmt: skip
    assert detail["counts"] == {
        "steps": 6, "failed": 1, "edits": 1, "scratch": 1, "messages": 2, "passed": 1,
    }  # fmt: skip
    assert detail["total"] == detail["shown"] == 6
    assert detail["date"] == "2026-03-04" and detail["minutes"] == 42


def test_a_message_carries_the_actions_before_and_after_it():
    messages = session_detail(stamped(story())).as_json()["messages"]

    assert messages[0]["before"] is None and messages[0]["then"].startswith("pytest")
    assert messages[1]["text"] == "no, use the other helper"
    assert messages[1]["before"].endswith("notes.md") and messages[1]["then"].startswith("pytest")


def test_a_failed_command_shows_its_working_segment_and_the_tools_complaint():
    (failure,) = session_detail(stamped(story())).as_json()["failed"]

    assert failure == {
        "step": 1,
        "command": "pytest tests/test_parser.py -q",
        "error": "AssertionError: no parse",
    }


def test_session_detail_scrubs_secrets():
    steps = session(
        user(f"clone {PASSWORD_URL} and send {BEARER}"),
        run(f"git clone {PASSWORD_URL}", 1, f"fatal: could not read from {BEARER}"),
    )

    shown = str(session_detail(steps).as_json())

    for secret in ("hunter2hunter2", "abcdefghij0123456789klmnop"):
        assert secret not in shown
    assert "[secret]" in shown


def test_session_detail_caps_steps():
    steps = session(*[run(f"ls dir{n}", 0) for n in range(2000)])

    detail = session_detail(steps).as_json()

    assert detail["shown"] == len(detail["steps"]) == 600 and detail["total"] == 2000
    assert detail["counts"]["steps"] == 2000


def test_the_cap_keeps_the_stretch_with_the_failures():
    quiet = [run("ls", 0)] * 900
    bad = [run("make", 1, "error: boom")] * 50
    detail = session_detail(session(*quiet, *bad, *quiet), max_steps=100).as_json()

    assert len(detail["failed"]) == 50 and detail["total"] == 1850


def test_minutes_and_date_are_null_without_timestamps():
    detail = session_detail(story()).as_json()

    assert detail["minutes"] is None and detail["date"] is None


def test_message_text_is_one_line_of_at_most_300_characters():
    long = "word\n" * 200
    (message,) = session_detail(session(user(long))).as_json()["messages"]

    assert "\n" not in message["text"] and len(message["text"]) == 300


def test_a_malformed_or_impossible_timestamp_means_no_minutes_not_a_crash():
    steps = session(user("a"), user("b"))
    steps = [replace(steps[0], ts="2026-02-30T10:00:00Z"), replace(steps[1], ts="yesterday")]

    assert session_detail(steps).as_json()["minutes"] is None


def test_minutes_span_mixed_zone_and_naive_stamps():
    steps = session(user("a"), user("b"))
    steps = [
        replace(steps[0], ts="2026-03-04T10:00:00"),
        replace(steps[1], ts="2026-03-04T11:30:00Z"),
    ]

    assert session_detail(steps).as_json()["minutes"] == 90
