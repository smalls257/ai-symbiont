from symbiont.miner.failure_program import failing_program


def test_subcommand_programs_carry_their_subcommand():
    assert failing_program("git add a.py") == "git add"
    assert failing_program("gh pr checks 3") == "gh pr"


def test_other_programs_stay_bare():
    assert failing_program("pytest -q") == "pytest"


def test_no_subcommand_gives_the_program():
    assert failing_program("git --version") == "git"


def test_a_script_is_named_after_its_last_working_line():
    assert failing_program("git status --short\ngit add a.ts") == "git add"
    assert failing_program("echo == ; git commit -m x") == "git commit"
    assert failing_program("cd /repo; for f in a b; do cat $f; done") == "cat"
    assert failing_program("npm test; echo done") == "npm test"


def test_a_chain_and_a_pipeline_keep_their_first_working_command():
    assert failing_program("git add a && git commit -m x") == "git add"
    assert failing_program("pnpm test 2>&1 | tail -5") == "pnpm test"


def test_script_runners_name_the_script():
    assert failing_program("npm run test") == "npm run test"
    assert failing_program("uv run pytest") == "uv run pytest"
