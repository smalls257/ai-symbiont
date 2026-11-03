"""Whether a later passing command is "the same check" as an earlier failing one.

Generic on purpose, with no per-runner parsing: a command is a tool (wrappers that only launch
another program peeled off) plus path-or-identifier targets (flags and their values dropped).
Loose by design; the delivery-time judge filters over-proposals. Rule in miner/AGENTS.md.
"""

import os
import re
from dataclasses import dataclass

from symbiont.miner.commands import NO_PATH, program_words
from symbiont.records.output_failure import shows_failure
from symbiont.records.schema import Kind, Record

_LAUNCHERS = {"uv", "poetry", "pipenv", "pdm", "hatch", "rye"}  # `<launcher> run <program>`
_LAUNCH_VERBS = {"run", "exec"}
_LAUNCHER_VALUE_FLAGS = {
    "--group",
    "--with",
    "--python",
    "-p",
    "--extra",
    "--project",
    "--directory",
}
_NODE_LAUNCHERS = {"npx", "bunx", "pnpx"}
_PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
_PACKAGE_EXEC_VERBS = {"exec", "dlx", "x"}
_SCRIPT_VERBS = {"run", "run-script"}
# Programs whose first bare word is the tool: `go test` and `go build` are different checks.
_SUBCOMMAND_TOOLS = {"go", "cargo", "dotnet", "swift", "mix", "deno", "mvn", "gradle", "make"}
_PYTHONS = re.compile(r"^python(\d+(\.\d+)?)?$")
_BARE_WORD = re.compile(r"^[a-z][a-z0-9-]*$")
_IDENTIFIER_OR_PATH = re.compile(r"^[\w./~+@-]+$")
_LINE_SUFFIX = re.compile(r":\d+(:\d+)?$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?[smh]?$")
_TEMP_DIRS = ("/tmp/", "/var/folders/", "/private/tmp/")
# A package script named `test` runs whatever the project tests with, so it covers a node tool
# the failed run launched directly (`npx jest a.test.ts` fails, `npm test` passes).
_UMBRELLA_SCRIPT = "test"


@dataclass(frozen=True)
class Check:
    """A command reduced to what it checks: which tool, aimed at which targets."""

    tool: str
    targets: frozenset[str]
    node_launched: bool = False


def reruns_same_check(failed: Record, later: Record) -> bool:
    """True when `later` is a clean pass of the check that `failed` ran, however it was spelled."""
    if later.kind != Kind.COMMAND or later.exit_code != 0 or shows_failure(later.raw):
        return False
    before, after = check_of(failed.command or ""), check_of(later.command or "")
    if before is None or after is None:
        return False
    return _tool_covers(before, after) and _targets_cover(before.targets, after.targets)


def check_of(command: str) -> Check | None:
    """The tool and targets of `command`; None when it names no program."""
    first, words = program_words(command)
    if first == NO_PATH:
        return None
    program, args, node_launched = _peel_launchers(first, list(words))
    tool, rest = _tool_and_rest(program, args)
    return Check(tool, _targets(rest), node_launched)


def _peel_launchers(program: str, args: list[str]) -> tuple[str, list[str], bool]:
    """Strip wrappers that only start another program; report whether npx and kin did."""
    node_launched = False
    for _ in range(3):
        peeled = _peel_once(program, args)
        if peeled is None:
            break
        program, args, via_node = peeled
        node_launched = node_launched or via_node
    return program, args, node_launched


def _peel_once(program: str, args: list[str]) -> tuple[str, list[str], bool] | None:
    """One wrapper layer removed, or None when `program` is not a wrapper."""
    verb = args[0] if args else ""
    if program in _LAUNCHERS and verb in _LAUNCH_VERBS:
        return (*_first_program(args[1:], _LAUNCHER_VALUE_FLAGS), False)
    if program == "bundle" and verb == "exec":
        return (*_first_program(args[1:], set()), False)
    if program in _NODE_LAUNCHERS:
        return (*_first_program(args, set()), True)
    if program in _PACKAGE_MANAGERS and verb in _PACKAGE_EXEC_VERBS:
        return (*_first_program(args[1:], set()), True)
    return None


def _first_program(args: list[str], value_flags: set[str]) -> tuple[str, list[str]]:
    """The first non-flag word as the program, with the rest as its arguments."""
    rest = list(args)
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag in value_flags and rest:
            rest.pop(0)
    if not rest:
        return (NO_PATH, [])
    program, rest = os.path.basename(rest[0]), rest[1:]
    if _PYTHONS.match(program) and len(rest) >= 2 and rest[0] == "-m":
        return (rest[1], rest[2:])
    return (program, rest)


def _tool_and_rest(program: str, args: list[str]) -> tuple[str, list[str]]:
    """The tool name (with its subcommand or package script) and the arguments after it."""
    word = args[0] if args and _BARE_WORD.match(args[0]) else None
    if program in _PACKAGE_MANAGERS and word:
        if word in _SCRIPT_VERBS and len(args) > 1:
            return (f"script {args[1]}", args[2:])
        return (f"script {word}", args[1:])
    if program in _SUBCOMMAND_TOOLS and word:
        return (f"{program} {word}", args[1:])
    return (program, args)


def _targets(args: list[str]) -> frozenset[str]:
    """Positional path or identifier arguments; a flag's value is dropped unless it is a path."""
    found: set[str] = set()
    after_flag = False
    for arg in args:
        if arg.startswith("-"):
            after_flag = "=" not in arg and arg != "--"
            continue
        was_after_flag, after_flag = after_flag, False
        target = _as_target(arg)
        if target and not (was_after_flag and not _pathlike(arg)):
            found.add(target)
    return frozenset(found)


def _pathlike(arg: str) -> bool:
    """True when the word names a file, directory or node id rather than a plain value."""
    return "/" in arg or "::" in arg or bool(re.search(r"\.[A-Za-z]\w{0,5}(:\d+)?$", arg))


def _as_target(arg: str) -> str | None:
    """The argument as a stable target: node id, line number and `/...` wildcard removed."""
    if _NUMBER.match(arg) or arg.startswith(_TEMP_DIRS):
        return None
    base = _LINE_SUFFIX.sub("", arg.split("::")[0])
    base = base.removeprefix("./").removesuffix("...").rstrip("/")
    if base in ("", ".") or not _IDENTIFIER_OR_PATH.match(base):
        return None
    return base


def _tool_covers(before: Check, after: Check) -> bool:
    """Same tool, or the package `test` script standing in for a node tool run directly."""
    if before.tool == after.tool:
        return True
    return before.node_launched and after.tool == f"script {_UMBRELLA_SCRIPT}"


def _targets_cover(before: frozenset[str], after: frozenset[str]) -> bool:
    """A broader run (no targets) or any overlap; a narrower run than the failure does not."""
    if not after:
        return True
    return any(_related(first, second) for first in before for second in after)


def _related(first: str, second: str) -> bool:
    """Equal, one inside the other, or the same file stem (`a.test.ts` and `a.ts`)."""
    return (
        first == second
        or first.startswith(second + "/")
        or second.startswith(first + "/")
        or first.endswith("/" + second)
        or second.endswith("/" + first)
        or _stem(first) == _stem(second)
    )


def _stem(path: str) -> str:
    return os.path.basename(path).split(".")[0]
