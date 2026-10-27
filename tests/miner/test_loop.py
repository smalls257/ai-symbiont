"""A loop is the agent going round in circles: the same command, or the same
view of the same lines, repeated close together with nothing learned (the
same result each time) and nothing changed in between."""

from record_builders import edit, run, say, session, view
from symbiont.miner.painpoint import Signal
from symbiont.miner.signals.loop import find_loops

PYTEST = "cd /workspace/repo && python -m pytest tests/test_tokens.py -q"
FAILED = "FAILED tests/test_tokens.py::test_x - KeyError\n1 failed in 0.31s"
PARSER = "sqlglot/parser.py"


def test_same_command_3x_same_result_is_loop():
    s = session(run(PYTEST, 1, FAILED), run(PYTEST, 1, FAILED), run(PYTEST, 1, FAILED))
    (pain,) = find_loops(s)
    assert pain.signature.signal == Signal.LOOP
    assert pain.signature.key == ("command", PYTEST)
    assert pain.step == 2
    assert pain.record_refs == (("s1", 0), ("s1", 1), ("s1", 2))


def test_two_repeats_is_not_loop():
    assert find_loops(session(run(PYTEST, 1, FAILED), run(PYTEST, 1, FAILED))) == []


def test_same_command_with_a_different_result_is_not_loop():
    s = session(
        run(PYTEST, 1, FAILED),
        run(PYTEST, 1, "FAILED tests/test_tokens.py::test_y"),
        run(PYTEST, 1, FAILED),
    )
    assert find_loops(s) == []


def test_same_command_with_a_different_exit_code_is_not_loop():
    s = session(run(PYTEST, 1, FAILED), run(PYTEST, 2, FAILED), run(PYTEST, 1, FAILED))
    assert find_loops(s) == []


def test_timings_in_output_do_not_make_results_differ():
    outputs = [FAILED, FAILED.replace("0.31s", "0.29s"), FAILED.replace("0.31s", "1.02s")]
    assert len(find_loops(session(*[run(PYTEST, 1, o) for o in outputs]))) == 1


def test_different_python_c_bodies_are_not_a_loop():
    s = session(
        run("python -c \"import sqlglot; print(sqlglot.transpile('SELECT 1'))\"", 0, "x"),
        run("python -c \"import sqlglot; print(sqlglot.parse_one('SELECT 1'))\"", 0, "x"),
        run('python -c "from sqlglot import exp; print(exp.Cast)"', 0, "x"),
    )
    assert find_loops(s) == []


def test_different_sed_ranges_of_one_file_are_not_a_loop():
    s = session(*[run(f"sed -n {a},{a + 40}p {PARSER}", 0, "x") for a in (100, 140, 180)])
    assert find_loops(s) == []


def test_different_grep_patterns_on_one_file_are_not_a_loop():
    s = session(
        *[
            run(f"grep -n {pat} {PARSER}", 0, "x")
            for pat in ("_parse_cast", "TRY_CAST", "def _parse_id")
        ]
    )
    assert find_loops(s) == []


def test_heredoc_scripts_with_different_bodies_are_not_a_loop():
    s = session(*[run(f"python - <<'EOF'\nprint({n})\nEOF", 0, "x") for n in (1, 2, 3)])
    assert find_loops(s) == []


def test_temp_paths_and_spacing_do_not_make_commands_differ():
    s = session(
        run("pytest /tmp/tmpa1b2/test_x.py  -q", 1, FAILED),
        run("pytest /tmp/tmpzz99/test_x.py -q", 1, FAILED),
        run("pytest /tmp/tmp0000/test_x.py -q ", 1, FAILED),
    )
    assert len(find_loops(s)) == 1


def test_repeats_far_apart_are_not_a_loop():
    filler = [say(f"thinking {i}") for i in range(12)]
    s = session(
        run(PYTEST, 1, FAILED), *filler, run(PYTEST, 1, FAILED), *filler, run(PYTEST, 1, FAILED)
    )
    assert find_loops(s) == []


def test_window_is_tunable():
    s = session(
        run(PYTEST, 1, FAILED),
        say("a"),
        say("b"),
        run(PYTEST, 1, FAILED),
        say("c"),
        run(PYTEST, 1, FAILED),
    )
    assert find_loops(s, window=2) == []
    assert len(find_loops(s, window=3)) == 1


def test_rerun_after_an_edit_is_progress_not_loop():
    s = session(
        run(PYTEST, 1, FAILED),
        edit("sqlglot/tokens.py"),
        run(PYTEST, 1, FAILED),
        run(PYTEST, 1, FAILED),
    )
    assert find_loops(s) == []


def test_rejected_edit_does_not_break_a_loop():
    s = session(
        run(PYTEST, 1, FAILED),
        edit("sqlglot/tokens.py", exit_code=1),
        run(PYTEST, 1, FAILED),
        run(PYTEST, 1, FAILED),
    )
    assert len(find_loops(s)) == 1


def test_same_view_3x_without_edit_is_loop():
    s = session(
        view(PARSER, (120, 160)),
        edit("sqlglot/generator.py"),
        view(PARSER, (120, 160)),
        run("ls"),
        view(PARSER, (120, 160)),
    )
    (pain,) = find_loops(s)
    assert pain.signature.key == ("read", PARSER, "120-160")
    assert pain.record_refs == (("s1", 0), ("s1", 2), ("s1", 4))


def test_whole_file_view_key_says_so():
    (pain,) = find_loops(session(view(PARSER), view(PARSER), view(PARSER)))
    assert pain.signature.key == ("read", PARSER, "whole file")


def test_paging_through_a_file_is_not_a_loop():
    s = session(
        view(PARSER, (1, 100)), view(PARSER, (100, 200)), view(PARSER, (200, 300)), view(PARSER)
    )
    assert find_loops(s) == []


def test_failed_views_are_not_counted():
    s = session(view(PARSER, exit_code=1), view(PARSER, exit_code=1), view(PARSER, exit_code=1))
    assert find_loops(s) == []


def test_editing_the_file_resets_its_reads():
    s = session(view(PARSER), view(PARSER), edit(PARSER), view(PARSER))
    assert find_loops(s) == []


def test_long_streak_is_one_pain_point():
    (pain,) = find_loops(session(*[run(PYTEST, 1, FAILED) for _ in range(6)]))
    assert pain.step == 2


def test_min_repeats_is_tunable():
    assert (
        len(find_loops(session(run(PYTEST, 1, FAILED), run(PYTEST, 1, FAILED)), min_repeats=2)) == 1
    )


def test_very_long_command_key_is_shortened_readably():
    long = 'python -c "' + "x = 1; " * 40 + '"'
    (pain,) = find_loops(session(*[run(long, 0, "ok") for _ in range(3)]))
    shown = pain.signature.key[1]
    assert len(shown) <= 120 and shown.endswith("...") and shown.startswith("python -c")


def test_long_commands_sharing_a_prefix_are_different_commands():
    prefix = 'python -c "' + "x = 1; " * 40
    s = session(*[run(prefix + f'print({n})"', 0, "ok") for n in (1, 2, 3)])
    assert find_loops(s) == []
