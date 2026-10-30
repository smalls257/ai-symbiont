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
