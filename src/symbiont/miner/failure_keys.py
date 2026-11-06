"""What a failed command broke, as the last element of its signature, and what that implies.

A key is only worth counting when it says something: a bare `exit 1` is the same string for a
hundred unrelated failures, so such a group is marked not comparable instead of being
counted as one trap. A wrong invocation (no tests collected, a bad path) is fixed by running the
program correctly, which is its own kind of known fix.
"""

import re

from symbiont.miner.failure_signature import failure_signature
from symbiont.records.schema import Record

_ERROR_CLASS = re.compile(r"\b([A-Z]\w*Error)\b")
_BARE_EXIT = re.compile(r"^exit \d+$")
_MESSAGE_CHARS = 60
INTERRUPTS = frozenset({"C-c", "C-d", "C-z"})
SIGINT_EXIT = 130  # 128 + SIGINT: the shell's report of a Ctrl-C

# (program, exit code) -> what it means. pytest exit codes: "Exit code 4: pytest command line
# usage error", "Exit code 5: No tests were collected"
# (https://docs.pytest.org/en/stable/reference/exit-codes.html).
EXIT_MEANINGS = {
    ("pytest", 4): "usage error or bad path",
    ("pytest", 5): "no tests collected",
}
# A wrong invocation, not a wrong program: the later pass is the same program run correctly.
# The first two are EXIT_MEANINGS above (pytest exit 4 and 5); the classes are Python's own
# "no such file" and "no such module" errors, which a corrected path or module name resolves.
INVOCATION_FAILURES = frozenset(
    {*EXIT_MEANINGS.values(), "FileNotFoundError", "ModuleNotFoundError"}
)


def what_broke(record: Record, program: str, *, inline: bool) -> str:
    """The error class, else the exit-code meaning, else the message line, else `exit N`.

    A script typed into the command (`inline`) is keyed by its error class only: its message
    names that one script's variables and would never repeat.
    """
    errors = _ERROR_CLASS.findall(record.raw)
    if errors:
        return str(errors[-1])
    meaning = EXIT_MEANINGS.get((program, record.exit_code or 0))
    if meaning is not None:
        return meaning
    signature = None if inline else failure_signature(record.raw)
    if signature is not None:
        return str(signature.message[:_MESSAGE_CHARS])
    return f"exit {record.exit_code}"


def is_bare_exit(broke: str) -> bool:
    """True for `exit N` with no message or meaning: it cannot tell failures apart."""
    return _BARE_EXIT.match(broke) is not None


def is_invocation_failure(broke: str) -> bool:
    """True when the failure was a wrong invocation, not a wrong program."""
    return broke in INVOCATION_FAILURES


def is_interrupt(record: Record) -> bool:
    """A Ctrl-C and friends typed as a command, or a SIGINT exit: the user stopped it."""
    return (record.command or "").strip() in INTERRUPTS or record.exit_code == SIGINT_EXIT
