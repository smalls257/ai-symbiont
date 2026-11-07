from symbiont.miner.failure_program import failing_program


def test_subcommand_programs_carry_their_subcommand():
    assert failing_program("git add a.py") == "git add"
    assert failing_program("gh pr checks 3") == "gh pr"


def test_other_programs_stay_bare():
    assert failing_program("pytest -q") == "pytest"


def test_no_subcommand_gives_the_program():
    assert failing_program("git --version") == "git"
