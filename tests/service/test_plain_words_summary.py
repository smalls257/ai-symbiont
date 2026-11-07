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


def test_a_fix_with_no_real_step_reads_as_no_fix_in_the_note_and_the_summary():
    fixed = lesson_of(owners_session())
    unfixed = replace(fixed, resolution=(), fix=None, unresolved_because="nothing changed")
    note, summary = render_lesson(unfixed), rule_summary(unfixed)
    assert "No fix was found" in note and "history shows no fix" in summary
    assert "ran another command" not in note + summary


def pooled(count):
    phrases = tuple(f"edited {'file' * 12}{n}.ts, then re-ran pnpm exec" for n in range(count))
    return replace(lesson_of(owners_session()), resolution=phrases)


def test_a_pooled_lesson_stays_short_in_the_note_the_card_and_the_summary():
    from symbiont.miner.incidents import incidents_from

    lesson = pooled(6)
    resolved = render_lesson(lesson).split("Last time: ")[1].split(" Check:")[0]
    assert len(resolved) <= 200 and "other fixes" in resolved
    assert len(rule_summary(lesson)) <= SUMMARY_CHARS
    recs = owners_session()
    (card,) = incidents_from([replace(lesson, fix=None)], {"s1": recs}, {"s1": recs})
    assert len(card.what_fixed_it) <= 200


def test_an_old_stored_row_reads_plain_on_the_note_and_the_card():
    import json
    from dataclasses import asdict

    from symbiont.miner.incidents import incidents_from
    from symbiont.store.lesson_rows import lesson_from_json

    old = asdict(lesson_of(owners_session()))
    del old["fix_commands"], old["fix_steps"]
    old["resolution"] = [
        f"edited `{PATH}` to add `host: this.configService.get('REDIS_HOST', 'localhost'),`",
        "ran `pnpm api:generate 2>&1 | tail -5`",
    ]
    lesson = lesson_from_json(json.dumps(old))
    note = render_lesson(lesson)
    assert "Last time: edited identity.controller.ts, then re-ran pnpm." in note
    assert "REDIS_HOST" not in note and "apps/api" not in note
    recs = owners_session()
    (card,) = incidents_from([lesson], {}, {"s1": recs})
    assert card.what_fixed_it == "Fixed by editing identity.controller.ts."


def test_short_real_corrections_stay_and_slash_commands_and_agreement_do_not():
    from symbiont.miner.signals.correction import find_corrections

    texts = ["use pnpm", "wrong file", "/compact", "/clear now", "ok", "thanks", "go on", ""]
    turns = session(*[user(text, tags=("correction",)) for text in texts])
    assert [pain.step for pain in find_corrections(turns)] == [0, 1]
