"""A slash command reads as typed; the Working on line never shows harness markup."""

from symbiont.miner.slash_command import typed_text
from symbiont.miner.story import working_on_line

COMMAND = (
    "<command-message>bmad-help</command-message> <command-name>/bmad-help</command-name> "
    "<command-args>we just started to plan the release</command-args>"
)


def test_a_slash_command_reads_as_typed():
    assert typed_text(COMMAND) == "/bmad-help we just started to plan the release"
    assert typed_text("fix the parser") == "fix the parser"


def test_a_working_on_line_never_shows_command_markup():
    assert working_on_line("", COMMAND, "") == "/bmad-help we just started to plan the release"
