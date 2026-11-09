"""The program a failure is keyed by: `git add`, not `git`, when the first word picks the tool."""

from symbiont.miner.commands import final_program_words
from symbiont.miner.resolutions import subcommand_after

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
    """`git add` for a subcommand program with a subcommand, else the program alone.

    Named after the last `;` list that does work, where the shell's status comes from.
    """
    program, args = final_program_words(command)
    if program not in SUBCOMMAND_PROGRAMS:
        return program
    subcommand = subcommand_after(program, args)
    return program if subcommand == "-" else f"{program} {subcommand}"
