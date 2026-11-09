"""A session's digest is what a batched summarizer reads: asks, files, failures, the ending.

Failure guarded against: Paper Tiger (a digest of injected text and chat summarizes nothing) and
Silent Fallback (a session whose ending is missing cannot be told apart as done or stuck).
"""

from dataclasses import replace

from record_builders import edit, run, say, session, user
from symbiont.miner.session_digest import digest_of
from symbiont.miner.themes import Codebase
from symbiont.records.session_tags import title_tag

CODEBASE = Codebase(frozenset({"demo"}))


def stamped(records, ts="2026-03-04T10:00:00Z"):
    return [replace(records[0], ts=ts), *records[1:]]


def test_injected_text_and_chat_are_not_asks_and_a_plan_gives_its_heading_as_the_title():
    plan = "Implement the following plan:\n\n# Plan: Add refunds to billing\n\nSteps follow."
    steps = session(
        user("This session is being continued from a previous conversation that ran out"),
        user(plan),
        user("[Request interrupted by user]"),
        user("ok"),
        user("please make refunds go through the ledger service"),
        user("and add a test for partial refunds as well"),
        user("also rename the module to something nicer please"),
    )

    digest = digest_of(stamped(steps), CODEBASE)

    assert digest.title == "Add refunds to billing"
    assert digest.asks == (
        "please make refunds go through the ledger service",
        "and add a test for partial refunds as well",
    )
    assert digest.date == "2026-03-04" and digest.session_id == "s1"


def test_a_reader_title_wins_over_a_plan_heading():
    steps = session(
        user("Implement the following plan:\n# Plan: X y z", (title_tag("Fix refunds"),))
    )
    assert digest_of(steps, CODEBASE).title == "Fix refunds"


def test_files_are_repo_relative_most_edited_first_and_capped_at_five():
    edits = [edit("/home/dev/demo/src/a.py")] * 3 + [
        edit(f"/home/dev/demo/src/f{n}.py") for n in range(6)
    ]
    digest = digest_of(session(user("do a thing here please"), *edits), CODEBASE)

    assert digest.files[0] == "src/a.py" and len(digest.files) == 5
    assert all(not name.startswith("/") for name in digest.files)


def test_failed_commands_are_counted_and_capped_at_three():
    steps = session(
        user("fix the build please now"),
        *[run("pytest tests/x.py -q", 1)] * 2,
        run("npm run lint", 1),
        run("make all", 1),
        run("cargo build", 1),
        run("pytest tests/x.py -q", 0),
    )

    digest = digest_of(steps, CODEBASE)

    assert digest.failed[0] == "pytest tests/x.py -q (x2)" and len(digest.failed) == 3


def test_corrections_are_the_tagged_turns_trimmed_and_the_ending_keeps_the_last_two_turns():
    long = "no " + "word " * 60
    steps = session(
        user("add refunds to the billing code"),
        say("done, refunds added"),
        user(long, ("correction",)),
        say("sorry, reverting " + "x" * 300),
        user("thanks, that works now"),
    )

    digest = digest_of(steps, CODEBASE)

    assert len(digest.corrections) == 1 and len(digest.corrections[0]) <= 140
    assert len(digest.last_turns) == 2
    assert digest.last_turns[-1] == "developer: thanks, that works now"
    assert digest.last_turns[0].startswith("agent: sorry") and len(digest.last_turns[0]) <= 160


def test_credentials_are_scrubbed_from_every_text_field():
    secret = "ghp_" + "a" * 36
    steps = session(user(f"deploy using token {secret} to the server now"), say(f"used {secret}"))

    digest = digest_of(steps, CODEBASE)

    assert secret not in repr(digest)
