"""A fix reads as one short plain phrase: file names and one command, never code or paths."""

from record_builders import edit, run
from symbiont.miner.fix_words import PHRASE_CHARS, edit_clause, fix_phrase

SPEC = "src/vault/republish.service.spec.ts"


def test_many_edits_to_one_file_name_it_once_by_its_base_name():
    steps = [edit(SPEC, diff="+const secret = 1\n"), edit(SPEC), edit(SPEC)]
    phrase = fix_phrase(steps)
    assert phrase == "edited republish.service.spec.ts"
    assert "const" not in phrase and "src/" not in phrase and "`" not in phrase


def test_two_files_are_named_and_three_or_more_say_how_many_more():
    two = [edit("a/vault.controller.spec.ts"), edit("a/vault.service.ts")]
    assert fix_phrase(two) == "edited vault.controller.spec.ts and vault.service.ts"
    five = [edit(f"pkg/f{n}.ts") for n in range(5)]
    assert fix_phrase(five) == "edited 5 files (f0.ts, f1.ts and 3 more)"


def test_read_only_and_plumbing_commands_are_dropped():
    steps = [run("cat a.py"), run("cd app && ls -la"), run("git status"), edit("a.py")]
    assert fix_phrase(steps) == "edited a.py"


def test_the_last_real_command_is_named_by_program_and_subcommand():
    steps = [run("pip install -r reqs.txt"), run("npm install --save left-pad src/very/long/arg")]
    assert fix_phrase(steps) == "ran npm install"


def test_rerunning_the_failed_program_reads_as_a_rerun_after_the_edit():
    steps = [edit(SPEC), run("pnpm exec vitest run src/x.spec.ts")]
    assert (
        fix_phrase(steps, "pnpm exec") == "edited republish.service.spec.ts, then re-ran pnpm exec"
    )


def test_an_install_beats_the_rerun_when_nothing_was_edited():
    steps = [run("pip install pyyaml"), run("pytest tests/ -q")]
    assert fix_phrase(steps, "pytest") == "ran pip install"


def test_the_phrase_order_follows_what_happened():
    steps = [run("npm install"), edit("a.ts")]
    assert fix_phrase(steps) == "ran npm install, then edited a.ts"


def test_the_phrase_is_capped_even_for_long_names():
    steps = [edit(f"d/{'x' * 60}{n}.ts") for n in range(3)] + [run("pnpm exec vitest")]
    assert len(fix_phrase(steps, "pnpm exec")) <= PHRASE_CHARS


def test_steps_that_were_all_read_only_still_say_something_was_done():
    assert fix_phrase([run("ls")]) == "ran another command"


def test_no_steps_is_no_phrase():
    assert fix_phrase([]) == ""


def test_the_edit_part_can_be_read_back_from_a_phrase():
    assert edit_clause("edited a.ts and b.ts, then re-ran pnpm exec") == "a.ts and b.ts"
    assert edit_clause("ran npm install") == ""
