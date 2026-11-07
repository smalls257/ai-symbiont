"""A failure told in three lines a new teammate can follow: working on, what broke, how it ended."""

from dataclasses import replace

from record_builders import edit, run, session, user
from story_builders import ADDED, ASKED, GOAL, OUTPUT, PATH, owners_lesson
from symbiont.miner.added_line import ADDED_CHARS, telling_added_line
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_chain, sessions_of
from symbiont.miner.painpoint import Signal, Signature
from symbiont.miner.story import (
    BROKE_CHARS,
    ENDED_CHARS,
    WORKING_ON_CHARS,
    specific_error_line,
    story_of,
)


def test_the_owners_example_reads_as_three_specific_lines():
    story = story_of(owners_lesson(), GOAL)
    assert story.working_on == GOAL
    assert story.broke == (
        "`pnpm api:generate` failed to compile — `identity.controller.ts:47`: "
        "'configService' is declared but its value is never read (TS6138)"
    )
    assert story.ended == (
        "fixed by editing identity.controller.ts (added "
        "`host: this.configService.get('REDIS_HOST', 'localhost')`), "
        "then `pnpm api:generate` passed"
    )


def test_without_a_goal_the_first_sentence_of_the_request_leads():
    working = story_of(owners_lesson()).working_on
    assert working.startswith("Im looking through the code") and len(working) <= WORKING_ON_CHARS
    assert story_of(replace(owners_lesson(), asked=""), "").working_on == ""


def test_the_error_picker_skips_runner_boilerplate_and_prefers_a_location_and_code():
    lines = [
        "ELIFECYCLE Command failed with exit code 1.",
        "ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL api@ generate: exit 1",
        "⨯ Unable to compile TypeScript:",
        "src/a.ts(3,1): error TS2304: Cannot find name 'x'.",
        "Error: something vague",
    ]
    assert specific_error_line(lines).startswith("src/a.ts(3,1): error TS2304")
    assert specific_error_line(["ELIFECYCLE Command failed", "Exit status 1", "$ pnpm x"]) == ""


def test_a_failure_with_no_message_says_the_exit_not_a_guess():
    lesson = owners_lesson()
    pain = replace(
        lesson.pain_point, signature=Signature(Signal.FAILED_COMMAND, ("pnpm", "-", "exit 1"))
    )
    bare = replace(
        lesson, pain_point=pain, error_lines=(), quote="$ pnpm api:generate\nExit status 1"
    )
    assert story_of(bare).broke == "`pnpm api:generate` failed (exit 1)"


def test_a_plain_error_line_gets_a_short_path():
    lesson = replace(
        owners_lesson(),
        quote="$ pytest\n",
        error_lines=(
            "File \"/srv/build/app/parser.py\", line 4: NameError: name 'np' is not defined",
        ),
    )
    assert "parser.py" in story_of(lesson).broke and "/srv/build" not in story_of(lesson).broke


def test_one_telling_line_is_picked_not_a_brace_or_an_import():
    edits = [
        edit("a.ts", diff="+++ b/a.ts\n+import x from 'y'\n+}\n+  const total = price * qty;\n"),
    ]
    assert telling_added_line(edits) == "const total = price * qty"
    assert telling_added_line([edit("a.ts", diff="+}\n")]) == "}"
    assert len(telling_added_line([edit("a.ts", diff="+" + "word " * 40)])) <= ADDED_CHARS


def test_several_files_are_named_with_how_many_more():
    records = session(
        run(
            "pnpm test",
            1,
            "a.ts(1,1): error TS1005: oops\n" + " ".join(f"src/f{n}.ts" for n in range(5)),
        ),
        *[edit(f"src/f{n}.ts", diff=f"+let a{n} = 1\n") for n in range(5)],
        run("pnpm test", 0, "ok"),
    )
    (lesson,) = lessons_from(mine_chain(sessions_of(records), {}), records, frozenset())
    assert "editing 5 files (f0.ts, f1.ts and 3 more)" in story_of(lesson).ended


def test_a_setup_fix_a_corrected_command_and_no_fix_each_have_their_own_ending():
    base = owners_lesson()
    setup = replace(
        base, resolution=("ran pip install",), fix_commands=("pip install x",), fix=None
    )
    named = story_of(setup, setup="pip install x")
    assert named.ended == "fixed the setup: ran `pip install x`, then it passed"
    assert story_of(setup).ended.startswith("fixed by running `pip install x`")
    from symbiont.miner.fixes import FixKind

    corrected = replace(setup, fix=FixKind.CORRECTED_COMMAND, fix_commands=("pytest -k a",))
    assert story_of(corrected).ended == "ran it correctly: `pytest -k a`"
    none = replace(base, resolution=(), unresolved_because="nothing changed in between")
    assert story_of(none).ended == "no fix was shown: nothing changed in between"


def test_every_line_is_bounded_and_scrubbed():
    token = "ghp_" + "a1b2c3d4e5" * 4
    lesson = replace(
        owners_lesson(),
        asked=f"deploy with {token} " + "word " * 80,
        fix_added=f"token = '{token}'",
    )
    story = story_of(lesson, "")
    assert len(story.working_on) <= WORKING_ON_CHARS
    assert len(story.broke) <= BROKE_CHARS and len(story.ended) <= ENDED_CHARS
    assert token not in " ".join([story.working_on, story.broke, story.ended])


def test_an_incident_card_carries_the_story_and_names_the_setup_as_typed():
    from symbiont.miner.incidents import incidents_from

    lesson = owners_lesson()
    records = session(
        user(ASKED),
        run("pnpm api:generate", 1, OUTPUT),
        edit(PATH, diff=ADDED),
        run("pnpm api:generate", 0, "done"),
    )
    (card,) = incidents_from([lesson], {}, {lesson.pain_point.session_id: records})
    assert card.broke.startswith("`pnpm api:generate` failed to compile")
    assert card.ended.startswith("fixed by editing identity.controller.ts")
    assert card.working_on.startswith("Im looking through the code")


def test_a_correction_card_quotes_the_developer_and_an_empty_one_quotes_nothing():
    from symbiont.miner.incident_corrections import SAID_CHARS, correction_card
    from symbiont.miner.painpoint import PainPoint

    long_said = "no, keep amounts in integer cents " * 10
    for text, expected_empty in ((long_said, False), ("/compact", True)):
        records = session(user(text, tags=("correction",)))
        pain = PainPoint(Signature(Signal.CORRECTION, ("-", "x")), "s1", 0, (("s1", 0),))
        (lesson,) = lessons_from([pain], records, frozenset())
        card = correction_card(lesson, records, "", frozenset())
        assert (card.broke == "") is expected_empty and len(card.broke) <= SAID_CHARS


def _session_with_setup():
    return session(
        user("make the build pass"),
        run("pnpm build", 1, "boom"),
        run("pip install foo"),
        run("ls"),
        run("pnpm build", 0, "ok"),
    )


def test_a_pooled_story_names_the_files_once_and_says_how_many_other_fixes():
    pooled = ("edited a.ts", "edited b.ts", "edited c.ts")
    ended = story_of(replace(owners_lesson(), resolution=pooled)).ended
    assert ended.count("other fixes") == 1 and ended.startswith("fixed by editing a.ts (added")


def test_the_command_named_as_the_fix_is_the_step_that_changed_things_not_the_rerun():
    records = _session_with_setup()
    (lesson,) = lessons_from(mine_chain(sessions_of(records), {}), records, frozenset())
    assert story_of(lesson).ended == "fixed by running `pip install foo`, then `pnpm build` passed"
    named = story_of(lesson, setup="pip install foo").ended
    assert named == "fixed the setup: ran `pip install foo`, then it passed"
    assert "pnpm build`," not in named


def test_the_real_message_line_is_shown_not_the_normalized_grouping_key():
    lock = "/".join(["", "Users", "pat", "Code", "cipher-box", ".git", "index.lock"])
    out = f"fatal: Unable to create '{lock}': File exists.\n\nAnother git process is running"
    records = session(run("git pull", 128, out), run("rm " + lock), run("git pull", 0, ""))
    (lesson,) = lessons_from(mine_chain(sessions_of(records), {}), records, frozenset())
    story = story_of(lesson, repo_names=frozenset({"cipher-box"}))
    assert "Unable to create '.git/index.lock': File exists." in story.broke
    assert "/Users" not in " ".join([story.broke, story.ended]) and "fatal:" not in story.broke


def test_a_deep_relative_path_in_an_error_shortens_to_its_file_name():
    lesson = replace(owners_lesson(), error_lines=(), quote="$ x\nError: cannot read a/b/c/d.json")
    assert "d.json" in story_of(lesson).broke and "a/b/c" not in story_of(lesson).broke


def test_the_chip_suggestion_is_the_clean_error_line_or_nothing():
    from symbiont.miner.story import error_summary

    assert error_summary(owners_lesson()).startswith("`identity.controller.ts:47`")
    assert error_summary(replace(owners_lesson(), error_lines=(), quote="$ x\nExit status 1")) == ""
