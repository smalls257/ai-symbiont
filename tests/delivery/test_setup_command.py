"""`symbiont setup`: register the plugin in each harness found, naming every command it runs."""

from symbiont.cli import main
from symbiont.delivery.setup_command import CLI_PROGRAMS, CommandResult, main_setup
from symbiont.readers.harnesses import HARNESSES, harness


class Recorder:
    """A command runner that logs argv and answers from a script of exit codes."""

    def __init__(self, results: dict[tuple[str, ...], CommandResult] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._results = results or {}

    def __call__(self, argv: tuple[str, ...]) -> CommandResult:
        self.calls.append(argv)
        return self._results.get(argv, CommandResult(0, ""))


def _on_path(*names: str):
    return lambda name: f"/bin/{name}" if name in names else None


def test_setup_runs_each_found_harness_commands_in_order(capsys):
    runner = Recorder()
    code = main_setup(["--harness", "auto"], runner, _on_path("claude", "muse"))
    expected = [*harness("muse_code").plugin_setup, *harness("claude_code").plugin_setup]
    assert code == 0
    assert sorted(runner.calls) == sorted(expected)
    claude_calls = [call for call in runner.calls if call[0] == "claude"]
    assert claude_calls == list(harness("claude_code").plugin_setup)
    printed = capsys.readouterr().out
    assert "claude plugin install symbiont@ai-symbiont" in printed


def test_setup_prints_the_commands_for_a_harness_whose_cli_is_missing_and_exits_0(capsys):
    runner = Recorder()
    code = main_setup(["--harness", "all"], runner, _on_path("muse"))
    printed = capsys.readouterr().out
    assert code == 0
    assert all(call[0] == "muse" for call in runner.calls)
    assert "claude is not on PATH" in printed
    assert "claude plugin marketplace add https://github.com/smalls257/ai-symbiont" in printed


def test_setup_with_no_harness_cli_anywhere_prints_every_command_and_exits_0(capsys):
    runner = Recorder()
    code = main_setup([], runner, _on_path())
    printed = capsys.readouterr().out
    assert code == 0
    assert runner.calls == []
    assert "muse plugins approve symbiont" in printed
    assert "claude plugin install symbiont@ai-symbiont" in printed


def test_none_runs_and_prints_nothing_to_do(capsys):
    runner = Recorder()
    assert main_setup(["--harness", "none"], runner, _on_path("claude", "muse")) == 0
    assert runner.calls == []


def test_a_failing_plugin_command_is_named_and_setup_exits_1(capsys):
    failing = harness("claude_code").plugin_setup[1]
    runner = Recorder({failing: CommandResult(3, "boom")})
    code = main_setup(["--harness", "claude_code"], runner, _on_path("claude"))
    printed = capsys.readouterr()
    assert code == 1
    assert "exit 3" in printed.out + printed.err
    assert "claude plugin install symbiont@ai-symbiont" in printed.err
    assert "boom" in printed.out + printed.err


def test_a_failure_does_not_skip_the_other_harness(capsys):
    failing = harness("muse_code").plugin_setup[0]
    runner = Recorder({failing: CommandResult(2, "bad")})
    code = main_setup(["--harness", "all"], runner, _on_path("claude", "muse"))
    assert code == 1
    assert harness("claude_code").plugin_setup[0] in runner.calls


def test_a_marketplace_that_already_exists_counts_as_success(capsys):
    adding = harness("claude_code").plugin_setup[0]
    runner = Recorder({adding: CommandResult(1, "Marketplace already added")})
    assert main_setup(["--harness", "claude_code"], runner, _on_path("claude")) == 0


def test_an_unknown_harness_id_is_refused_naming_the_known_ones(capsys):
    runner = Recorder()
    code = main_setup(["--harness", "vim"], runner, _on_path("claude"))
    err = capsys.readouterr().err
    assert code == 2
    assert runner.calls == []
    assert "vim" in err and "claude_code" in err and "muse_code" in err


def test_the_symbiont_command_registers_setup(capsys):
    assert main(["setup", "--harness", "none"]) == 0
    assert "nothing to register" in capsys.readouterr().out


def test_every_registered_harness_cli_has_a_program_runner():
    # Why: the subprocess gate wants a literal program name at each call site, so the runner keeps
    # a table; this test is what stops a new harness from being silently unrunnable.
    registered = {entry.plugin_setup[0][0] for entry in HARNESSES}
    assert registered <= set(CLI_PROGRAMS)
