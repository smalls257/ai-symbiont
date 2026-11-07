"""The program a failure is keyed by: `git add`, not `git`, when the first word picks the tool."""

from symbiont.miner.commands import program_words
from symbiont.miner.resolutions import subcommand_of

# Their first word picks a different tool: `git add` and `git push` fail for unrelated reasons.
SUBCOMMAND_PROGRAMS = frozenset(
    {
        "git",
        "gh",
        "docker",
        "kubectl",
        "cargo",
        "npm",
        "pnpm",
        "yarn",
        "uv",
        "go",
        "brew",
        "terraform",
        "helm",
    }
)


def failing_program(command: str) -> str:
    """`git add` for a subcommand program with a subcommand, else the program alone."""
    program, _ = program_words(command)
    if program not in SUBCOMMAND_PROGRAMS:
        return program
    subcommand = subcommand_of(command)
    return program if subcommand == "-" else f"{program} {subcommand}"
