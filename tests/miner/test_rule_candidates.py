from record_builders import say, session, user
from symbiont.miner.rule_candidates import MAX_TEXT_CHARS, find_rule_candidates

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


def test_corrections_are_candidates_even_without_directive_words():
    s = session(
        user("fix the build"),
        say("done"),
        user("wrong file, the config is in app", tags=("correction",)),
    )
    (candidate,) = find_rule_candidates(s)
    assert (candidate.step, candidate.source) == (2, "correction")


def test_directive_turn_that_is_also_a_correction_is_rule_words():
    s = session(user("never use npm here", tags=("correction",)))
    (candidate,) = find_rule_candidates(s)
    assert candidate.source == "rule_words"


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
