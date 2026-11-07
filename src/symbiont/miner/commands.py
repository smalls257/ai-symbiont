"""Shell commands reduced to what they *do*: the program and the first file it targets.

`cd repo && python -m pytest tests/test_x.py::test_y -v 2>&1 | tail` and
`pytest tests/test_x.py -q` are the same attempt. Flags, numbers, temp paths,
test node ids and line numbers vary from run to run; they are dropped so the
same mistake gets the same key across sessions.
"""

import os
import re
import shlex

from symbiont.miner.shell_text import shell_text

NO_PATH = "-"

# Segments that set up the shell rather than do the work.
_SETUP_PROGRAMS = {"cd", "source", ".", "export", "set", "pushd", "popd"}
# Reserved words that open a segment; the command is whatever follows them.
_SHELL_KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "}"}
# A segment starting with one is loop or case syntax; its words are not a command.
_SHELL_HEADERS = {"for", "select", "case", "done", "fi", "esac", "in"}
# Banners and pauses around the real work; they never carry the failure.
_PASSIVE_PROGRAMS = {"echo", "printf", "sleep", "true", ":", "wait", "[", "[["}
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


def final_program_words(command: str) -> tuple[str, tuple[str, ...]]:
    """Like `program_words`, but of the last `;`/newline list that does work.

    Every list runs and the exit status, usually the printed error too, comes from the last one.
    """
    tokens = _tokens(command)
    for each in reversed(_semicolon_lists(tokens)):
        segment = _working_segment(each)
        if segment and _does_work(segment):
            program, args = _program_and_args(segment)
            return (program, tuple(args))
    return program_words(command)


def inline_script_program(command: str) -> str | None:
    """`python` when the command runs a script typed into it (`python - <<EOF`, `python -c`).

    Such scripts have no file name to key on, and each one is different, so they share one key.
    """
    program, args = program_words(command)
    if not _PYTHONS.match(program) or not args:
        return None
    return "python" if args[0] == "-" or args[0] == "-c" else None


def status_program(command: str) -> str | None:
    """The program whose exit status the shell reports for `command`, or None if unclear."""
    chain = _final_and_or_list(_tokens(command))
    if not chain:
        return None
    last_stage, joiner = chain[-1]
    if joiner == "&&" and (len(chain) < 2 or not _only_sets_up(chain[-2][0])):
        return None
    if last_stage[0] in _SHELL_HEADERS:
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
    """True when a stage only sets up the shell (cd, export, ...)."""
    return os.path.basename(stage[0]) in _SETUP_PROGRAMS


def _tokens(command: str) -> list[str]:
    """Shell tokens of the whole command, heredoc bodies and comment lines removed."""
    line = shell_text(command)
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # An unbalanced quote (the shell would reject it too); plain
        # whitespace still yields the program and its targets.
        return line.split()


def _semicolon_lists(tokens: list[str]) -> list[list[str]]:
    """The tokens cut at each `;` (newlines are already `;`)."""
    lists: list[list[str]] = [[]]
    for token in tokens:
        if set(token) == {";"}:
            lists.append([])
        else:
            lists[-1].append(token)
    return lists


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
    """True for a token made only of redirection characters."""
    return set(token) <= set("<>&") and bool(set(token) & set("<>"))


def _working_segment(tokens: list[str]) -> list[str]:
    """The first segment that does real work, skipping setup, banners and loop syntax."""
    segments = [_without_keywords(segment) for segment in _segments(tokens)]
    segments = [segment for segment in segments if segment]
    # Setup-only commands (`export X=1`) and banners (`echo hi`) are still that program.
    fallbacks = (_does_work, _is_not_header_or_setup, _is_not_header)
    return next((s for test in fallbacks for s in segments if test(s)), [])


def _does_work(segment: list[str]) -> bool:
    return not _is_scaffolding(segment) and not _only_assignments(segment)


def _is_not_header_or_setup(segment: list[str]) -> bool:
    return not _is_header_or_setup(segment)


def _is_not_header(segment: list[str]) -> bool:
    return segment[0] not in _SHELL_HEADERS


def _without_keywords(segment: list[str]) -> list[str]:
    """The segment minus leading reserved words such as `do` and `then`."""
    start = 0
    while start < len(segment) and segment[start] in _SHELL_KEYWORDS:
        start += 1
    return segment[start:]


def _is_header_or_setup(segment: list[str]) -> bool:
    return segment[0] in _SHELL_HEADERS or os.path.basename(segment[0]) in _SETUP_PROGRAMS


def _is_scaffolding(segment: list[str]) -> bool:
    """Header, setup or passive segment: shell structure or a banner, not the work."""
    return _is_header_or_setup(segment) or os.path.basename(segment[0]) in _PASSIVE_PROGRAMS


def _only_assignments(segment: list[str]) -> bool:
    return all(_ENV_ASSIGNMENT.match(token) for token in segment)


def _program_and_args(segment: list[str]) -> tuple[str, list[str]]:
    """The program and its arguments, after env assignments and wrappers."""
    rest = _without_wrappers([token for token in segment if not _ENV_ASSIGNMENT.match(token)])
    if not rest:
        return (NO_PATH, [])
    program, args = os.path.basename(rest[0]), rest[1:]
    if _PYTHONS.match(program) and len(args) >= 2 and args[0] == "-m":
        return (args[1], args[2:])
    return (program, args)


def _without_wrappers(words: list[str]) -> list[str]:
    """Drop leading `timeout`/`time`/`env`/`nohup`, timeout's duration and env's own flags."""
    while len(words) > 1 and os.path.basename(words[0]) in _WRAPPERS:
        wrapper, words = words[0], words[1:]
        if wrapper == "timeout":
            words = [w for w in words if not _NUMBER.match(w)]
        elif wrapper == "env":
            words = _without_env_flags(words)
    return words


def _without_env_flags(words: list[str]) -> list[str]:
    """Drop env's `-i`, `-`, `-u NAME`, `--unset NAME` and `--unset=NAME` from the front."""
    index = 0
    while index < len(words):
        word = words[index]
        if word in ("-u", "--unset"):
            index += 2
        elif word in ("-i", "-") or word.startswith("--unset="):
            index += 1
        else:
            break
    return words[index:]


def _first_path(args: list[str]) -> str:
    """The first argument that is a stable path, or NO_PATH."""
    for arg in args:
        if path := _as_stable_path(arg):
            return path
    return NO_PATH


def _as_stable_path(arg: str) -> str | None:
    """The argument as a path stable across runs; flags, numbers and temp paths are not."""
    if arg.startswith("-") or _NUMBER.match(arg) or arg.startswith(_TEMP_DIRS):
        return None
    path = _LINE_SUFFIX.sub("", arg.split("::")[0])
    if not _PATHISH.match(path):
        return None
    if "/" not in path and not _HAS_EXTENSION.search(path):
        return None
    return path.removeprefix("./")
