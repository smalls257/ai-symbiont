"""Lessons carry their own quote, resolution and privacy flag, so no record needs keeping.

Hand-written records only.
"""

from dataclasses import replace

import pytest

from record_builders import edit, run, say, session, user
from symbiont.miner.lessons import (
    QUOTE_CHARS,
    Coverage,
    excerpt,
    lessons_from,
    resolution_coverage,
)
from symbiont.miner.mine import mine_chain, mine_history, sessions_of
from symbiont.miner.painpoint import Signal
from symbiont.miner.turns_before import CONTEXT_CHARS
from symbiont.records.schema import Provenance, Record

PRIVATE = Provenance(dataset="SWE-chat", license="ODC-BY", remote_safe=False)
TEST = "pytest tests/test_parser.py -q"
BROKE = "E   ModuleNotFoundError: No module named 'yaml'\n1 error"


def fixed_by_install():
    return session(
        user("make the parser tests pass"),
        run(TEST, 1, BROKE),
        run("pip install pyyaml"),
        run(TEST, 0, "3 passed"),
    )


def never_fixed():
    return [replace(r, session_id="s2") for r in session(run(TEST, 1, BROKE))]


def lessons_of(records):
    return lessons_from(mine_chain(sessions_of(records), {}), records, frozenset())


def test_a_lesson_quotes_what_happened_and_names_what_fixed_it():
    (lesson,) = lessons_of(fixed_by_install())
    assert lesson.quote.startswith(f"$ {TEST}\n") and "No module named 'yaml'" in lesson.quote
    assert lesson.resolution == ("ran pip install",)
    assert lesson.fix_commands == ("pip install pyyaml", TEST)
    assert lesson.unresolved_because is None
    assert lesson.sources == (("s1", 1), ("s1", 2), ("s1", 3), ("s1", 0))  # then the asked turn
    assert lesson.remote_safe


def test_an_unresolved_lesson_says_why():
    (lesson,) = lessons_of(never_fixed())
    assert lesson.resolution == ()
    assert "no later command" in (lesson.unresolved_because or "")


def test_the_quote_is_bounded_and_keeps_the_end_of_command_output():
    long_output = "noise\n" * 500 + "E   ImportError: cannot import name 'Foo'"
    (lesson,) = lessons_of(session(run(TEST, 1, long_output)))
    assert len(lesson.quote) <= QUOTE_CHARS
    assert lesson.quote.endswith("cannot import name 'Foo'")


def test_excerpt_of_prose_keeps_the_start_within_the_limit():
    text = excerpt(user("please stop " * 100), 50)
    assert len(text) <= 50 and text.startswith("please stop")


def test_the_privacy_flag_is_false_when_any_record_used_is_private():
    records = fixed_by_install()
    records[2] = replace(records[2], provenance=PRIVATE)  # only the install step is private
    (lesson,) = lessons_of(records)
    assert lesson.remote_safe is False


def test_a_missing_cited_record_raises_rather_than_quoting_nothing():
    records = fixed_by_install()
    pains = mine_chain([records], {})
    with pytest.raises(LookupError, match="s1:1"):
        lessons_from(pains, [r for r in records if r.step != 1], frozenset())


def test_coverage_counts_resolved_lessons_per_signal_and_lists_every_signal():
    records = fixed_by_install() + never_fixed()
    coverage = resolution_coverage(lessons_of(records))
    assert coverage[Signal.FAILED_COMMAND] == Coverage(resolved=1, total=2)
    assert coverage[Signal.LOOP] == Coverage(resolved=0, total=0)
    assert set(coverage) == set(Signal)


def test_an_edit_step_names_the_file_and_never_the_code_it_added():
    added = "+install_requires=['pyyaml']\n"
    failure = f"{BROKE}\nhint: check setup.py"
    records = session(run(TEST, 1, failure), edit("setup.py", diff=added), run(TEST, 0, "ok"))
    (lesson,) = lessons_of(records)
    assert lesson.resolution == ("edited setup.py, then re-ran pytest",)


def test_an_unrelated_edit_is_worded_as_alongside_not_as_the_fix():
    records = session(
        run(TEST, 1, BROKE),
        edit("docs/notes.md"),
        run("pip install pyyaml"),
        run(TEST, 0, "ok"),
    )
    (lesson,) = lessons_of(records)
    assert lesson.resolution == ("ran pip install",)
    assert lesson.changed_alongside == ("edited notes.md",)


def test_history_chains_timed_sessions_and_mines_untimed_ones_alone():
    monday = [replace(r, session_id="mon", ts="2026-10-26T09:00:00") for r in never_fixed()]
    tuesday = [replace(r, session_id="tue", ts="2026-10-27T09:00:00") for r in never_fixed()]
    found = mine_history(sessions_of(tuesday + monday + never_fixed()), {})
    assert [p.session_id for p in found] == ["mon", "tue", "s2"]


def test_a_lesson_with_unrelated_changes_pickles_without_any_record():
    import pickle

    records = session(run(TEST, 1, BROKE), edit("docs/changelog.md"), run(TEST, 0, "ok"))
    (lesson,) = lessons_of(records)
    assert "never names" in (lesson.unresolved_because or "")
    assert lesson.changed_alongside
    revived = pickle.loads(pickle.dumps(lesson))
    assert not any(isinstance(v, Record) for v in vars(revived).values())
    assert b"Record" not in pickle.dumps(lesson).replace(b"PainPoint", b"")


def asked_then_failed(user_text="make the parser tests pass", agent_text="I will install pyyaml"):
    return session(
        user(user_text),
        say(agent_text),
        run(TEST, 1, BROKE),
        run("pip install pyyaml"),
        run(TEST, 0, "3 passed"),
    )


def test_a_lesson_keeps_what_the_user_asked_and_what_the_agent_meant_before_the_failure():
    records = asked_then_failed("x" * 400)

    (lesson,) = lessons_of(records)

    assert lesson.asked.startswith("xxx") and len(lesson.asked) == CONTEXT_CHARS
    assert lesson.agent_intent == "I will install pyyaml"
    assert (lesson.pain_point.session_id, 0) in lesson.sources


def test_a_lesson_with_no_turn_before_the_failure_has_empty_context():
    (lesson,) = lessons_of(
        session(run(TEST, 1, BROKE), run("pip install pyyaml"), run(TEST, 0, "ok"))
    )

    assert (lesson.asked, lesson.agent_intent) == ("", "")


def test_a_private_turn_quoted_as_context_makes_the_lesson_private():
    records = asked_then_failed()
    records[0] = replace(records[0], provenance=PRIVATE)  # only the user's request is private

    (lesson,) = lessons_of(records)

    assert lesson.remote_safe is False and lesson.private_datasets == ("SWE-chat",)


def test_the_context_cap_matches_a_correction_candidates_turn_cap():
    from symbiont.core.correction_candidates import MAX_TURN_CHARS

    assert CONTEXT_CHARS == MAX_TURN_CHARS


def test_lessons_from_marks_a_target_created_in_the_session():
    """Failure guarded against: a script the agent wrote itself passing as the project's own."""
    made = replace(edit("/workspace/x/repro.py"), tags=("created",))
    records = session(made, run("python ./repro.py", 1, "TypeError: x"), run("python repro.py", 0))
    (lesson,) = lessons_of(records)
    assert lesson.target_created is True


def test_a_target_created_only_after_the_failure_is_not_marked():
    made = replace(edit("repro.py"), tags=("created",))
    records = session(run("python repro.py", 1, "TypeError: x"), made, run("python repro.py", 0))
    (lesson,) = lessons_of(records)
    assert lesson.target_created is False


def _failed_on(target_command, made_path, tags=("created",)):
    made = replace(edit(made_path), tags=tags)
    records = session(made, run(target_command, 1, "TypeError: x"), run(target_command, 0))
    (lesson,) = lessons_of(records)
    return lesson


def test_a_temporary_file_of_the_same_name_is_not_the_projects_script():
    """Failure guarded against: a scratch `/tmp/manage.py` hiding the project's `manage.py`."""
    assert _failed_on("python manage.py", "/tmp/manage.py").target_created is False


def test_a_created_repo_path_matches_the_same_repo_path():
    assert _failed_on("python src/run.py", "src/run.py").target_created is True


def test_a_created_repo_path_is_not_another_directorys_file_of_that_name():
    assert _failed_on("python lib/run.py", "src/run.py").target_created is False


def test_a_refused_create_made_no_file():
    """Failure guarded against: a create the harness refused counting as the agent's own script."""
    assert _failed_on("python repro.py", "repro.py", ("created", "refused")).target_created is False
