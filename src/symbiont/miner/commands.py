"""Shell commands reduced to what they *do*: the program and the first file it targets.

`cd repo && python -m pytest tests/test_x.py::test_y -v 2>&1 | tail` and
`pytest tests/test_x.py -q` are the same attempt. Flags, numbers, temp paths,
test node ids and line numbers vary from run to run; they are dropped so the
same mistake gets the same key across sessions.
"""

import os
import re
import shlex

NO_PATH = "-"

# Segments that set up the shell rather than do the work.
_SETUP_PROGRAMS = {"cd", "source", ".", "export", "set", "pushd", "popd"}
# Wrappers whose own arguments come before the real program.
_WRAPPERS = {"timeout", "time", "env", "nohup"}
_PYTHONS = re.compile(r"^python(\d+(\.\d+)?)?$")
_ENV_ASSIGNMENT = re.compile(r"^\w+=")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?[smh]?$")
_HAS_EXTENSION = re.compile(r"\.[A-Za-z]\w{0,5}$")
_PATHISH = re.compile(r"^[\w./~+@-]+$")
_TEMP_DIRS = ("/tmp/", "/var/folders/", "/private/tmp/")
_LINE_SUFFIX = re.compile(r":\d+(:\d+)?$")


def normalise_command(command: str) -> tuple[str, str]:
    """Return (program, first path-like argument or "-")."""
    program, args = program_words(command)
    return (program, _first_path(list(args)))


def program_words(command: str) -> tuple[str, tuple[str, ...]]:
    """Return (program, its arguments) for the segment that does the work; ("-", ()) if none."""
    segment = _working_segment(_tokens(command))
    if not segment:
        return (NO_PATH, ())
    program, args = _program_and_args(segment)
    return (program, tuple(args))


def status_program(command: str) -> str | None:
    """Name the program whose exit status the shell reports for `command`.

    None when the text cannot tell.

    `a | b` and `a; b` report b. `a || b` failing means b ran and failed.
    `a && b` failing may be a's failure with b never run, so b is the reporter
    only when a just sets up the shell (`cd repo && grep ...`). `git grep` is
    named as one program because its exit codes are grep's.
    """
    chain = _final_and_or_list(_tokens(command))
    if not chain:
        return None
    last_stage, joiner = chain[-1]
    if joiner == "&&" and (len(chain) < 2 or not _only_sets_up(chain[-2][0])):
        return None
    program, args = _program_and_args(last_stage)
    if program == "git" and args[:1] == ["grep"]:
        return "git grep"
    return program


def _final_and_or_list(tokens: list[str]) -> list[tuple[list[str], str]]:
    """Give the last `;`-separated list as (final pipeline stage, joining operator) pairs.

    The operator is the one joining the stage to the previous one. Earlier pipeline
    stages never decide the status, so only the final stage of each pipeline is kept.
    """
    chain: list[tuple[list[str], str]] = []
    stage: list[str] = []
    joiner = ""
    for token in tokens:
        if _is_redirection(token) or token in ("(", ")"):
            continue
        stage, joiner = _advance_chain(chain, stage, joiner, token)
    if stage:
        chain.append((stage, joiner))
    return [(done, how) for done, how in chain if done]


def _advance_chain(
    chain: list[tuple[list[str], str]], stage: list[str], joiner: str, token: str
) -> tuple[list[str], str]:
    """Fold one token into the chain; returns the new (current stage, joiner)."""
    if token == "|":
        return [], joiner
    if token in ("&&", "||"):
        chain.append((stage, joiner))
        return [], token
    if all(ch in "&|;" for ch in token):
        chain.clear()
        return [], ""
    stage.append(token)
    return stage, joiner


def _only_sets_up(stage: list[str]) -> bool:
    return os.path.basename(stage[0]) in _SETUP_PROGRAMS


def _tokens(command: str) -> list[str]:
    # Only the first line matters: later lines are heredoc bodies or
    # continuations, and their free text often has unbalanced quotes.
    first_line = command.strip().splitlines()[0] if command.strip() else ""
    lexer = shlex.shlex(first_line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # An unbalanced quote on the first line (the shell would reject it
        # too); plain whitespace still yields the program and its targets.
        return first_line.split()


def _segments(tokens: list[str]) -> list[list[str]]:
    """Split on command separators (`&&`, `|`, `;` ...).

    Redirection operators are dropped but their targets stay: `cat > notes.py`
    targets notes.py.
    """
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if _is_redirection(token):
            continue
        if all(ch in "&|;()" for ch in token):
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    return [segment for segment in segments if segment]


def _is_redirection(token: str) -> bool:
    return set(token) <= set("<>&") and bool(set(token) & set("<>"))


def _working_segment(tokens: list[str]) -> list[str]:
    segments = _segments(tokens)
    for segment in segments:
        if os.path.basename(segment[0]) not in _SETUP_PROGRAMS:
            return segment
    return segments[0] if segments else []


def _program_and_args(segment: list[str]) -> tuple[str, list[str]]:
    rest = _without_wrappers([token for token in segment if not _ENV_ASSIGNMENT.match(token)])
    if not rest:
        return (NO_PATH, [])
    program, args = os.path.basename(rest[0]), rest[1:]
    if _PYTHONS.match(program) and len(args) >= 2 and args[0] == "-m":
        return (args[1], args[2:])
    return (program, args)


def _without_wrappers(words: list[str]) -> list[str]:
    """Drop leading `timeout`/`time`/`env`/`nohup`, and timeout's duration."""
    while len(words) > 1 and os.path.basename(words[0]) in _WRAPPERS:
        is_timeout = words[0] == "timeout"
        words = [w for w in words[1:] if not (is_timeout and _NUMBER.match(w))]
    return words


def _first_path(args: list[str]) -> str:
    for arg in args:
        if path := _as_stable_path(arg):
            return path
    return NO_PATH


def _as_stable_path(arg: str) -> str | None:
    if arg.startswith("-") or _NUMBER.match(arg) or arg.startswith(_TEMP_DIRS):
        return None
    path = _LINE_SUFFIX.sub("", arg.split("::")[0])
    if not _PATHISH.match(path):
        return None
    if "/" not in path and not _HAS_EXTENSION.search(path):
        return None
    return path.removeprefix("./")
