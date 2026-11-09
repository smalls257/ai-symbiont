"""Commands that change nothing: they cannot be what made a failed command pass."""

import re

from symbiont.miner.commands import Stage, command_stages
from symbiont.miner.probes import PROBES
from symbiont.miner.resolutions import bare_arguments

# Each Bash call starts a fresh shell, so these leave no state behind for the next call.
SHELL_PLUMBING = frozenset(
    {"cd", "pushd", "popd", "pwd", "echo", "printf", "sleep", "true", ":", "wait"}
    | {"export", "set", "unset", "source", "."}
    | {"[", "[[", "test", "read"}
)
# They only report; the pass that follows cannot be owed to them.
READ_ONLY_PROGRAMS = PROBES | {"jq", "tree", "env", "ps", "lsof", "pgrep"}
READ_ONLY_GIT = frozenset(
    {"status", "log", "diff", "show", "blame", "rev-parse", "ls-files", "add"}
)
READ_ONLY_GH = {
    "pr": {"view", "list", "checks", "status", "diff"},
    "run": {"view", "list"},
    "issue": {"view", "list", "status"},
}
_GH_WRITE_FLAGS = {"-f", "-F", "--field", "--raw-field"}
_GIT_REMOTE_READS = {"show", "get-url"}
# After a pipe these only reshape what the first stage printed.
OUTPUT_FILTERS = frozenset(
    {"sort", "uniq", "cut", "tr", "head", "tail", "grep", "wc", "column", "jq", "less", "cat"}
)
_INFO_FLAGS = {"--version", "--help"}
_SED_IN_PLACE = re.compile(r"-[A-Za-z]*i|--in-place")


def is_read_only(command: str) -> bool:
    """True when every working segment is plumbing, a look-around or a report."""
    return all(_stage_reads(stage) for stage in command_stages(command))


def changing_command(command: str) -> str:
    """The first step of the command that changes something, as `program args`; "" when none does.

    A chain such as `git commit -m x && git log -1` changes things through its commit; naming
    the working (last) segment would credit the read-only `git log`.
    """
    for stage in command_stages(command):
        if not _stage_reads(stage):
            return " ".join((stage.program, *stage.args))
    return ""


def _stage_reads(stage: Stage) -> bool:
    if stage.piped and stage.program in OUTPUT_FILTERS:
        return True
    return _segment_reads(stage.program, stage.args)


def _segment_reads(program: str, args: tuple[str, ...]) -> bool:
    if _INFO_FLAGS & set(args) or program in SHELL_PLUMBING | READ_ONLY_PROGRAMS:
        return True
    words = bare_arguments(args)
    if program == "sed":
        return "-n" in args and not any(_SED_IN_PLACE.match(arg) for arg in args)
    if program == "git":
        return _git_only_reads(words)
    return program == "gh" and _gh_only_reads(words, args)


def _git_only_reads(words: list[str]) -> bool:
    if not words:
        return False
    if words[0] == "branch":
        return len(words) == 1
    if words[0] == "remote":
        return len(words) == 1 or words[1] in _GIT_REMOTE_READS
    if words[0] == "stash":
        return words[1:2] == ["list"]
    return words[0] in READ_ONLY_GIT


def _gh_only_reads(words: list[str], args: tuple[str, ...]) -> bool:
    if words[:1] == ["api"]:
        return not _writes_through_gh_api(args)
    return len(words) > 1 and words[1] in READ_ONLY_GH.get(words[0], ())


def _writes_through_gh_api(args: tuple[str, ...]) -> bool:
    """A non-GET method or a body field turns `gh api` from a read into a write."""
    if _GH_WRITE_FLAGS & set(args):
        return True
    for index, arg in enumerate(args):
        if arg in ("-X", "--method") and index + 1 < len(args):
            method = args[index + 1]
        elif arg.startswith("--method="):
            method = arg.removeprefix("--method=")
        elif arg.startswith("-X") and len(arg) > 2:
            method = arg[2:]
        else:
            continue
        if method.upper() != "GET":
            return True
    return False
