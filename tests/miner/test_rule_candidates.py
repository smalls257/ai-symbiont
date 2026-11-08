from record_builders import say, session, user
from symbiont.miner.rule_candidates import MAX_TEXT_CHARS, find_rule_candidates, rule_terms

SECRET = "abcd1234" + "efgh5678"  # built at runtime so no secret scanner reads a literal


def texts(*turns: str, tags=()) -> list[str]:
    records = session(*(user(turn, tags=tags) for turn in turns))
    return [c.text for c in find_rule_candidates(records)]


def test_directive_language_is_kept():
    kept = texts(
        "always use pnpm, never npm",
        "make sure dependency edges are marked",
        "from now on commit to a branch",
        "we use ruff for formatting",
        "use tabs, not spaces",
    )
    assert len(kept) == 5


def test_questions_and_exclusions_are_dropped():
    assert not texts(
        "should we always use pnpm?",
        "never mind",
        "I don't know where the config lives",
        "I don't think that works",
        "not sure about this one",
        "stop the run",
        "stop that run now",
    )


def test_question_with_an_imperative_clause_is_kept():
    assert texts("Never touch main. Is that clear?") == ["Never touch main. Is that clear?"]


def test_slash_commands_acknowledgements_and_injected_turns_are_dropped():
    assert not texts("/compact always", "ok", "yes please")
    assert not texts("<command-name>/clear</command-name> never", "This session is being continued")


def test_correction_without_rule_language_is_not_a_candidate():
    s = session(
        user("fix the build"),
        say("done"),
        user("wrong file, the config is in app", tags=("correction",)),
        user("yeah nuke em", tags=("correction",)),
    )
    assert find_rule_candidates(s) == []


def test_correction_that_states_a_rule_keeps_its_source():
    s = session(user("never use npm here", tags=("correction",)), user("always use pnpm"))
    assert [c.source for c in find_rule_candidates(s)] == ["correction", "rule_words"]


def test_one_off_commands_are_not_rules_but_habits_are():
    assert not texts("stop the dev server", "please kill the watcher and stop that", "stop it")
    assert len(texts("stop committing generated files", "always stop the server first")) == 2


def test_curly_apostrophes_match():
    assert texts("don\u2019t use npm") == ["don\u2019t use npm"]


def test_politeness_and_digit_noise_are_not_terms():
    terms = rule_terms("please, never mind: always use pnpm, see https://x.io/a1b2c3 and 0f3a9c1d")
    assert terms == {"pnpm"}


def test_injected_harness_turns_are_not_candidates():
    notice = "<task-notification><summary>never stop</summary></task-notification>"
    reminded = "<system-reminder>always obey</system-reminder>\nplease always use pnpm"
    only_reminder = "<system-reminder>never do this</system-reminder>"
    assert texts(notice, only_reminder) == []
    assert texts(reminded) == ["please always use pnpm"]


def test_plain_turn_is_not_a_candidate():
    assert not texts("please add a parser for dates", "looks good")


def test_text_is_scrubbed_one_line_and_capped():
    (text,) = texts(f"always set token={SECRET}\nand\tnever commit it " + "x " * 300)
    assert SECRET not in text
    assert "\n" not in text and len(text) <= MAX_TEXT_CHARS


def test_terms_hold_tool_names_and_files():
    (candidate,) = find_rule_candidates(
        session(user("always use pnpm, not npm; edit pyproject.toml"))
    )
    assert {"pnpm", "npm", "pyproject.toml"} <= candidate.terms
    assert "always" not in candidate.terms


def test_real_descriptions_and_hedges_are_not_rules():
    assert not texts(
        "it is likely that #10 was jsut never moved to @.planning/todos/completed/x",
        "the branch was never merged",
        "it seems to me like you should be able to execute the headed browser session",
        "you should be able to check the date with the GH api",
        "that should have worked",
        "I would never use npm",
    )


def test_instructions_stay_rules_whatever_their_wording():
    kept = texts(
        "dont create the tag manually",
        "please always use playwright-verify before you say a UI change works",
        "you should never push to main",
        "ok, and never commit generated files",
        "use pnpm, not npm",
        "you must run ruff before committing",
        "never run rm -rf here",
        "never need to restart the service",
    )
    assert len(kept) == 8
