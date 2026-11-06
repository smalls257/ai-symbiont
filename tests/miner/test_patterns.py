"""The eight ways a session's struggle looks, each on a hand-built session."""

from record_builders import edit, replace_text, run, say, session
from symbiont.miner.patterns import HELP, StrugglePattern, patterns_of
from symbiont.miner.themes import Codebase

CODE = Codebase(frozenset({"app"}))
FAIL = "Traceback\nValueError: no"


def found(*records):
    return patterns_of(session(*records), CODE)


def test_a_clean_session_has_no_patterns():
    assert (
        found(run("pytest tests/test_a.py", 0), edit("app/a.py"), run("pytest tests/", 0)) == set()
    )


def test_tests_that_were_not_found_are_a_pattern():
    assert StrugglePattern.TESTS_NOT_FOUND in found(run("pytest tests/nope.py", 4, "usage"))
    assert StrugglePattern.TESTS_NOT_FOUND in found(run("pytest tests/x.py", 5, "no tests ran"))
    assert StrugglePattern.TESTS_NOT_FOUND not in found(run("pytest tests/x.py", 1, FAIL))


def test_three_failing_inline_scripts_are_trial_and_error():
    trial = [run(f"python -c 'print({n})'", 1, FAIL) for n in range(3)]
    assert StrugglePattern.INLINE_TRIAL in found(*trial)
    assert StrugglePattern.INLINE_TRIAL not in found(*trial[:2])


def test_eight_edits_outside_the_codebase_are_scratch_debugging():
    scratch = [edit(f"/tmp/repro_{n}.py") for n in range(8)]
    assert StrugglePattern.SCRATCH_DEBUG in found(*scratch)
    assert StrugglePattern.SCRATCH_DEBUG not in found(*scratch[:7])


def test_one_source_file_edited_five_times_is_thrash_but_a_test_file_is_not():
    thrash = [replace_text("app/parser.py", f"a{n}", f"b{n}") for n in range(5)]
    assert StrugglePattern.EDIT_THRASH in found(*thrash)
    tests = [replace_text("tests/test_parser.py", f"a{n}", f"b{n}") for n in range(5)]
    assert StrugglePattern.EDIT_THRASH not in found(*tests)
    assert StrugglePattern.EDIT_THRASH not in found(*thrash[:4])


def test_an_attribute_error_right_after_a_codebase_edit_is_the_wrong_api():
    err = "AttributeError: 'Parser' has no attribute 'go'"
    assert StrugglePattern.WRONG_API in found(edit("app/p.py"), run("pytest", 1, err))
    far = [say("thinking")] * 5
    assert StrugglePattern.WRONG_API not in found(edit("app/p.py"), *far, run("pytest", 1, err))
    assert StrugglePattern.WRONG_API not in found(edit("/tmp/x.py"), run("pytest", 1, err))


def test_five_failed_probes_are_looking_in_the_wrong_place():
    probes = [run(f"ls app/dir{n}", 2, "No such file") for n in range(5)]
    assert StrugglePattern.WRONG_PLACE in found(*probes)
    assert StrugglePattern.WRONG_PLACE not in found(*probes[:4])


def test_three_failures_that_passed_later_with_no_edit_are_rerunning():
    reruns = []
    for n in range(3):
        reruns += [run(f"pytest tests/t{n}.py", 1, FAIL), run(f"pytest tests/t{n}.py -x", 0)]
    assert StrugglePattern.RERUNNING in found(*reruns)
    fixed = [run("pytest tests/a.py", 1, FAIL), edit("app/a.py"), run("pytest tests/a.py", 0)]
    assert StrugglePattern.RERUNNING not in found(*fixed * 3)


def test_a_session_whose_last_test_run_failed_ended_failing():
    assert StrugglePattern.ENDED_FAILING in found(run("pytest", 0), run("pytest", 1, FAIL))
    assert StrugglePattern.ENDED_FAILING not in found(run("pytest", 1, FAIL), run("pytest", 0))


def test_every_pattern_has_plain_words_of_help():
    assert set(HELP) == set(StrugglePattern)
    assert HELP[StrugglePattern.TESTS_NOT_FOUND] == "lesson: where the tests live"
