"""The exact-repeat rule: the same normalized failure, fixed before, is told how.

Failure guarded against: a Paper Tiger (silent for weeks) and its opposite, a note that scolds a
planned TDD red.
"""

from dataclasses import replace

from record_builders import edit, run, session
from symbiont.core.repeat import repeat_note
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of

ASSERTION = "FAILED tests/test_parser.py::test_new - assert 1 == 2\nE   assert 1 == 2"
IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse' from 'app.parser'"


def stored_lessons(*steps):
    records = session(*steps)
    return lessons_from(mine_history(sessions_of(records), {}), records, frozenset())


def fixed_import_error():
    return stored_lessons(
        run("pytest tests/test_parser.py", 1, IMPORT),
        edit("app/parser.py", diff="-a\n+def parse(text):\n"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )


def live_failure(command, output, exit_code=1, step=40, session_id="live"):
    failed = run(command, exit_code, output)
    return replace(failed, step=step, session_id=session_id)


def test_the_same_command_failing_the_same_way_is_told_how_it_was_fixed():
    failed = live_failure("pytest -q tests/test_parser.py::test_x", IMPORT)

    note = repeat_note(failed, [], fixed_import_error())

    assert note is not None
    assert "Last time" in note.sentence
    assert "`pytest tests/test_parser.py` failed with ImportError" in note.sentence
    assert "edited parser.py, then re-ran pytest" in note.sentence
    assert "def parse(text)" not in note.sentence and "app/parser.py" not in note.sentence


def test_a_different_error_is_not_a_repeat():
    failed = live_failure("pytest tests/test_parser.py", "TypeError: bad operand")

    assert repeat_note(failed, [], fixed_import_error()) is None


def test_a_failure_that_was_never_fixed_makes_no_note():
    unfixed = stored_lessons(run("pytest tests/test_parser.py", 1, IMPORT))
    failed = live_failure("pytest tests/test_parser.py", IMPORT)

    assert repeat_note(failed, [], unfixed) is None


def test_a_passing_command_makes_no_note():
    passed = live_failure("pytest tests/test_parser.py", "1 passed", exit_code=0)

    assert repeat_note(passed, [], fixed_import_error()) is None


def test_a_planned_failure_in_a_test_written_this_session_makes_no_note():
    written = [
        replace(edit("tests/test_parser.py"), step=38, session_id="live"),
        replace(edit("app/lexer.py"), step=39, session_id="live"),
    ]
    failed = live_failure("pytest tests/test_parser.py", IMPORT)

    assert repeat_note(failed, written, fixed_import_error()) is None


def test_the_same_failure_without_a_test_written_this_session_is_a_repeat():
    earlier = [replace(edit("app/lexer.py"), step=39, session_id="live")]
    failed = live_failure("pytest tests/test_parser.py", IMPORT)

    assert repeat_note(failed, earlier, fixed_import_error()) is not None


def test_a_different_assertion_in_the_same_command_is_not_a_repeat():
    lessons = stored_lessons(
        run("pytest tests/test_parser.py", 1, 'File "app/parser.py"\nE   assert 3 == 4'),
        edit("app/parser.py", diff="-a\n+b\n"),
        run("pytest tests/test_parser.py", 0, "1 passed"),
    )
    same = live_failure("pytest tests/test_parser.py", 'File "app/parser.py"\nE   assert 8 == 9')
    other = live_failure("pytest tests/test_parser.py", 'File "app/parser.py"\nE   assert x is y')

    assert repeat_note(same, [], lessons) is not None
    assert repeat_note(other, [], lessons) is None


def test_a_pass_is_never_a_failure_now():
    from symbiont.core.repeat import failed_now

    assert not failed_now(run("pytest", 0, "ok"))
    assert not failed_now(run("pytest", None, "unknown"))
    assert failed_now(run("pytest", 2, "boom"))


def test_the_developers_words_lead_the_note():
    from symbiont.miner.lesson_context import LessonContext
    from symbiont.miner.trained import lesson_id

    (lesson,) = fixed_import_error()
    failed = live_failure("pytest tests/test_parser.py", IMPORT)
    words = {lesson_id(lesson): LessonContext("Parser imports must stay lazy.")}

    note = repeat_note(failed, [], [lesson], words)

    assert note.sentence.startswith("[symbiont] In this repo: Parser imports must stay lazy. Last")
    assert "failed with ImportError" in note.sentence


def test_an_intentional_failure_stays_silent():
    from symbiont.miner.lesson_context import LessonContext
    from symbiont.miner.trained import lesson_id

    (lesson,) = fixed_import_error()
    failed = live_failure("pytest tests/test_parser.py", IMPORT)
    words = {lesson_id(lesson): LessonContext("on purpose", intentional=True)}

    assert repeat_note(failed, [], [lesson], words) is None


def test_a_lesson_without_a_fix_speaks_only_if_the_developer_added_words():
    from symbiont.miner.lesson_context import LessonContext
    from symbiont.miner.trained import lesson_id

    (lesson,) = stored_lessons(run("pytest tests/test_parser.py", 1, IMPORT))
    failed = live_failure("pytest tests/test_parser.py", IMPORT)
    words = {lesson_id(lesson): LessonContext("Known flake in CI.")}

    assert repeat_note(failed, [], [lesson]) is None
    assert "no fix was found" in repeat_note(failed, [], [lesson], words).sentence
