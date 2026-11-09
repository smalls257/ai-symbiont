from symbiont.miner.commands import normalise_command


def test_program_and_first_path():
    assert normalise_command("pytest tests/test_parser.py -x") == ("pytest", "tests/test_parser.py")


def test_python_module_is_the_program():
    assert normalise_command("python -m pytest tests/dialects/test_duckdb.py -q") == (
        "pytest",
        "tests/dialects/test_duckdb.py",
    )


def test_cd_prefix_and_pipes_are_skipped():
    cmd = (
        "cd /workspace/tobymao__sqlglot__unknown && "
        "python -m pytest tests/test_tokens.py -v 2>&1 | tail -30"
    )
    assert normalise_command(cmd) == ("pytest", "tests/test_tokens.py")


def test_normalise_strips_tmp_paths_and_numbers():
    cmd = (
        "timeout 120 pytest /tmp/tmpk3j2x9/test_scratch.py -n 4 "
        "tests/test_parser.py::TestParser::test_union:88"
    )
    assert normalise_command(cmd) == ("pytest", "tests/test_parser.py")


def test_no_path_is_marked_with_dash():
    assert normalise_command('python -c "import sqlglot; print(sqlglot.__version__)"') == (
        "python",
        "-",
    )


def test_sed_range_is_not_a_path():
    assert normalise_command("sed -n 120,140p sqlglot/parser.py") == ("sed", "sqlglot/parser.py")


def test_program_path_reduced_to_name():
    assert normalise_command("/opt/conda/envs/testbed/bin/python reproduce.py") == (
        "python",
        "reproduce.py",
    )


def test_unbalanced_quote_in_heredoc_body_still_keys_on_first_line():
    cmd = "cat > notes.py << 'EOF'\nprint(\"don't\")\nEOF"
    assert normalise_command(cmd) == ("cat", "notes.py")


def test_status_program_follows_shell_rules():
    from symbiont.miner.commands import status_program

    assert status_program("pytest -q; grep -c ok log.txt") == "grep"
    assert status_program("python a.py || grep x b.py") == "grep"
    assert status_program("cd repo && export X=1 && rg foo") == "rg"
    assert status_program("pytest && grep ok log.txt") is None
    assert status_program("grep -l x *.py | xargs wc -l") == "xargs"
    assert status_program("") is None


# --- keys: what a failed command is counted as ------------------------------------------

from record_builders import run, session  # noqa: E402
from symbiont.miner.failure_keys import is_bare_exit  # noqa: E402
from symbiont.miner.signals.failed_command import find_failed_commands  # noqa: E402


def key_of(command, exit_code=1, output=""):
    (pain,) = find_failed_commands(session(run(command, exit_code, output)))
    return pain.signature.key


def test_cd_and_env_prefixes_do_not_hide_the_program():
    assert key_of(
        "cd /repo && PYTHONPATH=src DEBUG=1 pytest tests/test_x.py", 1, "E   assert 1"
    ) == (
        "pytest",
        "tests/test_x.py",
        "assert <n>",
    )


def test_a_heredoc_script_keys_by_interpreter_and_error_class():
    script = "cd /repo && python3 - <<'EOF'\nimport sqlglot\nsqlglot.nothing()\nEOF"
    output = "Traceback\nAttributeError: module 'sqlglot' has no attribute 'nothing'"
    assert key_of(script, 1, output) == ("python", "<inline>", "AttributeError")
    assert key_of("python -c 'import nope'", 1, "ModuleNotFoundError: x") == (
        "python",
        "<inline>",
        "ModuleNotFoundError",
    )


def test_pytest_exit_5_reads_as_no_tests_collected():
    assert key_of("python -m pytest tests/test_x.py", 5, "no tests ran")[-1] == "no tests collected"
    assert key_of("pytest tests/nope.py", 4, "ERROR: file not found")[-1] == (
        "usage error or bad path"
    )


def test_a_bare_exit_code_marks_the_failure_not_comparable():
    broke = key_of("make lint", 2, "make: *** [lint] Error 2")[-1]
    assert broke == "exit 2" and is_bare_exit(broke)
    assert not is_bare_exit("no tests collected") and not is_bare_exit("ImportError")


def test_an_interrupt_is_not_a_failed_command():
    records = session(run("C-c", 130, ""), run("C-c", 1, "^C"), run("sleep 60", 130, "^C"))
    assert find_failed_commands(records) == []
