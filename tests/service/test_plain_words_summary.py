"""The owner's example, as a fixture: a rule summary is short and plain, with no quote or code."""

from dataclasses import replace

from record_builders import edit, run, session, user
from symbiont.core.notes import render_lesson, title_of
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_chain, sessions_of
from symbiont.miner.painpoint import Signal, Signature
from symbiont.service.candidate_summary import SUMMARY_CHARS, rule_summary

ASKED = (
    "Im looking through the code, and think that the identity controller should not be "
    "responsible for passing in the list of allowed domains. this is a leaky implementation"
)
PATH = "apps/api/src/auth/controllers/identity.controller.ts"
ADDED = "+    host: this.configService.get('REDIS_HOST', 'localhost'),\n"
TEST = "pnpm api:generate"


def owners_session():
    return session(
        user(ASKED),
        run(TEST, 1, f"{PATH}(10,5)\nTSError: Unable to compile TypeScript"),
        *[edit(PATH, diff=ADDED) for _ in range(6)],
        run("pnpm api:generate 2>&1 | tail -5", 0, "ok"),
    )


def lesson_of(records):
    return lessons_from(mine_chain(sessions_of(records), {}), records, frozenset())[0]


def test_the_owners_summary_is_two_short_plain_sentences():
    summary = rule_summary(lesson_of(owners_session()))
    assert len(summary) <= SUMMARY_CHARS
    assert "You asked" not in summary and "`" not in summary and "REDIS_HOST" not in summary
    assert "apps/api" not in summary and "identity.controller.ts" in summary


def test_a_note_for_a_six_edit_fix_is_short_and_still_names_the_file():
    lesson = lesson_of(owners_session())
    note = render_lesson(lesson).split("Check:")[0]
    resolved = note.split("Last time: ")[1]
    assert len(resolved) <= 200 and "identity.controller.ts" in resolved


def test_a_correction_title_prefers_the_group_name_else_quotes_a_short_slice():
    said = "keep amounts in integer cents because floats drift when you add them up later"
    sig = Signature(Signal.CORRECTION, ("-", said))
    assert title_of(sig, "Money as cents") == "Money as cents"
    title = title_of(sig)
    assert (
        title.startswith('You corrected the agent: "keep amounts') and "were corrected" not in title
    )
    assert len(title) <= len('You corrected the agent: ""') + 60


def test_other_titles_stay_what_happened():
    sig = Signature(Signal.REWORKED_EDIT, ("a.py",))
    assert title_of(sig) == "your edits to `a.py` were redone"


def test_a_slash_only_or_acknowledgment_turn_is_not_a_correction():
    from symbiont.miner.signals.correction import find_corrections

    turns = session(
        user("/compact", tags=("correction",)), user("ok", tags=("rejection",)),
        user("no, keep amounts in integer cents please", tags=("correction",)),
    )  # fmt: skip
    found = find_corrections(turns)
    assert [pain.step for pain in found] == [2]
    assert replace(turns[0]).raw == "/compact"
