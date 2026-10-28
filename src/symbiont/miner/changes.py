"""Which steps change the workspace: what can explain a command passing after it failed.

A command that fails and later passes was fixed by something in between: an
edit, an install, a configuration change, or a different way of running it.
Read-only steps (listing, searching, viewing, re-running the same failure)
change nothing and are left out, so a resolution names only what moved.
"""

from symbiont.miner.commands import program_words
from symbiont.records.schema import Kind, Record

# Program -> first arguments that install a dependency.
_INSTALL_VERBS = {
    "pip": {"install"},
    "pip3": {"install"},
    "uv": {"add", "sync", "pip"},
    "npm": {"install", "i", "ci", "add"},
    "yarn": {"add", "install"},
    "pnpm": {"add", "install", "i"},
    "apt": {"install"},
    "apt-get": {"install"},
    "brew": {"install"},
    "conda": {"install"},
    "poetry": {"add", "install"},
    "cargo": {"add", "install"},
    "go": {"get", "install"},
    "gem": {"install"},
}
# Program -> first arguments that change configuration.
_CONFIG_VERBS = {
    "git": {"config", "checkout", "switch", "apply"},
    "npm": {"config"},
    "pip": {"config"},
    "poetry": {"config"},
    "conda": {"config"},
}
# Programs that change files or the environment whatever their arguments.
_CHANGING_PROGRAMS = {"export", "ln", "chmod", "mkdir", "touch", "mv", "cp", "rm", "patch"}


def applied_edit(record: Record) -> bool:
    """True for an edit the harness applied (exit 1 means the editor refused it)."""
    return record.kind == Kind.EDIT and record.exit_code != 1 and record.diff is not None


def changes_workspace(record: Record) -> bool:
    """True when the step edited a file, installed something or changed configuration."""
    if record.kind == Kind.EDIT:
        return applied_edit(record)
    if record.kind != Kind.COMMAND or record.exit_code != 0:
        return False
    if record.files:  # the reader saw the command write these files
        return True
    program, args = program_words(record.command or "")
    if program in _CHANGING_PROGRAMS:
        return True
    verbs = _INSTALL_VERBS.get(program, set()) | _CONFIG_VERBS.get(program, set())
    return bool(args) and args[0] in verbs
