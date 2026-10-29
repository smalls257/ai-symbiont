"""Public action labels and repeat tags for the commands of a mini-SWE-agent trajectory.

Labels come from a command's shape and the public repo paths in it, never its text. The repeat
definitions are in dashboard/AGENTS.md.
"""

import re
from dataclasses import dataclass, field

SUBMIT_MARK = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
MOST_OF_A_RANGE = 0.5  # share of a re-read line range already seen that counts as a repeat

TEST_RUN = re.compile(r"(?:unittest|pytest)\s+(.*)")
SOURCE_PATH = re.compile(r"(?:/testbed/)?((?:sqlglot|tests)/[\w/]+\.py)")
SED_RANGE = re.compile(r"sed -n '(\d+),(\d+)p'\s+(\S+)")
SCRIPT_FILE = re.compile(r"(?:python3?|cat >)\s+(\S+\.py)")


@dataclass
class RunMemory:
    """What this run has already done since its last source edit."""

    reads: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    commands: set[str] = field(default_factory=set)


def _repo_path(command: str) -> str | None:
    found = SOURCE_PATH.search(command)
    return found.group(1) if found else None


def _test_target(command: str) -> str:
    tail = TEST_RUN.search(command)
    first = tail.group(1).split()[0] if tail else ""
    return first.replace(".", "/") + ".py" if first.startswith("tests.") else first


def _is_write(command: str) -> bool:
    return bool(
        re.search(r"sed -i|write_text|open\([^)]*['\"]w['\"]\)|\.write\(|writelines", command)
    )


def action_label(command: str) -> str:
    """A short public label for one shell command, shaped by what the step did."""
    path = _repo_path(command)
    if SUBMIT_MARK in command:
        return "Submit the patch"
    if "git diff" in command or "patch.txt" in command:
        return "Write out the patch" if "git diff" in command else "Review the patch"
    if TEST_RUN.search(command) and "python -m" in command:
        return f"Run {_test_target(command)}"
    if _is_write(command) and path and path.startswith("sqlglot/"):
        return f"Edit {path}"
    if re.search(r"cat > |<< ?'?\w+'?", command):
        return "Write a scratch script"
    return _read_or_search_label(command, path)


def _read_or_search_label(command: str, path: str | None) -> str:
    ranged = SED_RANGE.search(command)
    if ranged:
        low, high, target = ranged.groups()
        return f"Read {_repo_path(target) or target} lines {low}-{high}"
    if re.match(r"(cd \S+ && )?(cat|head|tail|awk)\b", command) and path:
        return f"Read {path}"
    if "grep" in command:
        return f"Search {path}" if path else "Search the code"
    if re.match(r"(cd \S+ && )?(ls|find)\b", command):
        return _listing_label(command)
    if "git log" in command:
        return "Check the git history"
    return _run_label(command)


def _listing_label(command: str) -> str:
    tokens = _normalized(command).split("|")[0].split()
    args = [t for t in tokens[1:] if not t.startswith("-")]
    where = args[0].removeprefix("/testbed").strip("/") if args else ""
    verb = "Find files in" if tokens[0] == "find" else "List"
    return f"{verb} {where}" if where and where != "." else f"{verb} the repository root"


def _run_label(command: str) -> str:
    script = SCRIPT_FILE.search(command)
    if script:
        name = script.group(1).split("/")[-1]
        return "Run the reproduction" if "reproduce" in name else "Run a scratch script"
    if "python" in command and " -c " in command:
        return "Check the example query"
    if command.startswith("cp "):
        return "Back up a file"
    if "pip install" in command:
        return "Install the package"
    return "Run a shell command"


def failed_test_run(command: str, output: str, returncode: int) -> bool:
    if returncode != 0:
        return True
    ran_tests = bool(TEST_RUN.search(command)) and "python -m" in command
    return ran_tests and bool(re.search(r"^(FAILED|ERROR)|\nFAILED|\nERROR:|Traceback", output))


def _normalized(command: str) -> str:
    return " ".join(command.removeprefix("cd /testbed &&").split()).replace("/testbed/", "")


def _shared_fraction(low: int, high: int, seen: list[tuple[int, int]]) -> float:
    """How much of the new line range an earlier read of the same file already covered."""
    covered = {n for start, end in seen for n in range(max(low, start), min(high, end) + 1)}
    return len(covered) / (high - low + 1)


def _rereads_most_of_a_range(command: str, memory: RunMemory) -> bool:
    ranged = SED_RANGE.search(command)
    if not ranged:
        return False
    target = ranged.group(3).removeprefix("/testbed/")
    low, high = int(ranged.group(1)), int(ranged.group(2))
    again = _shared_fraction(low, high, memory.reads.get(target, [])) >= MOST_OF_A_RANGE
    memory.reads.setdefault(target, []).append((low, high))
    return again


def _written_paths(command: str) -> set[str]:
    """File names a command writes: `cat > path`, `sed -i`, or a python heredoc that writes."""
    names = {m.split("/")[-1] for m in re.findall(r"cat\s*>>?\s*(\S+)", command)}
    if _is_write(command):
        names |= {m.split("/")[-1] for m in re.findall(r"['\"]([\w./-]+\.\w+)['\"]", command)}
        names |= {m.split("/")[-1] for m in re.findall(r"sed -i\b.*\s(\S+\.\w+)\s*$", command)}
    return names


def _forget_files(names: set[str], memory: RunMemory) -> None:
    """A rewritten file is a new file: commands and reads that mention it start over."""
    memory.commands = {k for k in memory.commands if not any(n in k for n in names)}
    for target in [t for t in memory.reads if t.split("/")[-1] in names]:
        del memory.reads[target]


def mistake_tag(command: str, memory: RunMemory, *, failed: bool) -> str:
    """repeated / new / none under the definitions in dashboard/AGENTS.md."""
    _forget_files(_written_paths(command), memory)
    key = _normalized(command)
    rerun = key in memory.commands
    reread = _rereads_most_of_a_range(command, memory)
    memory.commands.add(key)
    if action_label(command).startswith("Edit "):
        memory.commands.clear()
        memory.reads.clear()
    if rerun or reread:
        return "repeated"
    return "new" if failed else "none"
