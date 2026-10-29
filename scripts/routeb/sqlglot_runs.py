"""Facts about one Glimmer run on a sqlglot task, read from its public mini-SWE-agent trajectory.

A lesson must say where the run spent its steps (the file it kept re-reading, the scratch scripts,
the late or wrong first edit) and which test proved the fix; only paths, step numbers, counts and
test commands are kept, never command output or model text. Detection is by command-string
patterns (glimmer-analysis.md, section 3), so an edit through an unusual command can be missed: the
facts say what was seen, never what was guessed. Pure: parsed json in, facts out.
"""

import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

SOURCE = re.compile(r"(?<![\w/.])(?:/testbed/)?(sqlglot/[\w/]+\.py)")
EDIT = re.compile(
    r"sed\s+-i|apply_patch|write_text|open\([^)]*['\"]w|cat\s*>>?\s*\S*sqlglot|tee\s|perl\s+-pi"
    r"|git\s+apply|\bpatch\s+-|\.replace\(|>\s*sqlglot/"
)
READ_ONLY = re.compile(r"\s*(grep|sed -n|cat \S+\s*(\||$)|find)")
SCRATCH = re.compile(r"(?:cat\s*>|tee\s+|open\(\s*['\"])\s*['\"]?([\w./-]+\.py)\b")
UNITTEST = re.compile(r"python3?\s+-m\s+unittest(?:\s+-\w+)*((?:\s+tests[\w.]*)+)")
SUBMIT = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


class Trap(StrEnum):
    """A tool-environment trap of the sqlglot task image that costs a step every time it is hit."""

    PYTEST_MISSING = "pytest-missing"
    APPLY_PATCH_MISSING = "apply-patch-missing"
    SQLGLOT_NOT_IMPORTABLE = "sqlglot-not-importable"


_TRAP_SIGNS = {
    Trap.PYTEST_MISSING: re.compile(r"No module named pytest|pytest: command not found"),
    Trap.APPLY_PATCH_MISSING: re.compile(r"apply_patch: command not found"),
    Trap.SQLGLOT_NOT_IMPORTABLE: re.compile(r"No module named .?sqlglot"),
}


@dataclass(frozen=True)
class Step:
    """One bash action and what it returned."""

    command: str
    exit_code: int | None
    output: str


@dataclass(frozen=True)
class RunFacts:
    """Where one run spent its steps; step numbers count from 1."""

    instance_id: str
    run_id: str
    resolved: bool
    step_limit: int
    steps: int
    first_view: dict[str, int]
    rereads: dict[str, int]
    first_edit: int | None
    edited: tuple[str, ...]
    scratch_scripts: int
    verified_test: str | None  # every unittest module that passed after the first edit
    traps: tuple[Trap, ...]


def steps_from_messages(messages: list[dict]) -> list[Step]:
    """Every bash action with the tool reply that answered it, in order."""
    commands: list[str] = []
    replies: list[tuple[int | None, str]] = []
    for message in messages:
        extra = message.get("extra") or {}
        if message["role"] == "assistant":
            commands += [action["command"] for action in extra.get("actions") or []]
        elif message["role"] == "tool" and len(replies) < len(commands):
            replies.append((extra.get("returncode"), extra.get("raw_output") or message["content"]))
    replies += [(None, "")] * (len(commands) - len(replies))
    return [Step(command, *reply) for command, reply in zip(commands, replies, strict=True)]


def edited_files(step: Step) -> list[str]:
    """Source files under sqlglot/ a successful command wrote to."""
    if step.exit_code != 0:
        return []
    if "apply_patch" in step.command:
        found = re.findall(r"\*\*\* (?:Update|Add) File: (\S+)", step.command)
        return sorted({path for path in found if path.startswith("sqlglot/")})
    if not EDIT.search(step.command):
        return []
    if READ_ONLY.match(step.command) and not re.search(r"sed\s+-i", step.command):
        return []
    return sorted(set(SOURCE.findall(step.command)))


def passing_modules(step: Step) -> list[str]:
    """The unittest modules this step ran, when they all passed; empty otherwise."""
    found = UNITTEST.search(step.command)
    if found is None or step.exit_code != 0 or "FAILED (" in step.output:
        return []
    if not re.search(r"(?m)^OK\b", step.output):
        return []
    return found.group(1).split()


def _views(steps: list[Step]) -> tuple[dict[str, int], dict[str, int]]:
    first: dict[str, int] = {}
    seen: Counter[str] = Counter()
    for number, step in enumerate(steps, start=1):
        if edited_files(step):
            continue
        for path in set(SOURCE.findall(step.command)):
            first.setdefault(path, number)
            seen[path] += 1
    return first, {path: count - 1 for path, count in seen.items() if count > 1}


def _scratch_scripts(steps: list[Step]) -> int:
    written = {
        path
        for step in steps
        for path in SCRATCH.findall(step.command)
        if not path.startswith(("sqlglot/", "tests/", "/testbed/sqlglot/", "/testbed/tests/"))
    }
    return len(written)


def _traps(steps: list[Step]) -> tuple[Trap, ...]:
    return tuple(
        trap for trap, sign in _TRAP_SIGNS.items() if any(sign.search(s.output) for s in steps)
    )


def _edits(steps: list[Step]) -> tuple[int | None, tuple[str, ...]]:
    numbered = [(number, edited_files(step)) for number, step in enumerate(steps, start=1)]
    hits = [(number, paths) for number, paths in numbered if paths]
    files = tuple(sorted({path for _, paths in hits for path in paths}))
    return (hits[0][0] if hits else None), files


def _verified_test(steps: list[Step], first_edit: int | None) -> str | None:
    if first_edit is None:
        return None
    modules = [module for step in steps[first_edit:] for module in passing_modules(step)]
    unique = list(dict.fromkeys(modules))
    return "python -m unittest " + " ".join(unique) if unique else None


def run_facts(result: dict, run_id: str, messages: list[dict]) -> RunFacts:
    """Facts for one graded run: `result` is its calibration.jsonl row."""
    steps = [step for step in steps_from_messages(messages) if SUBMIT not in step.command]
    first_view, rereads = _views(steps)
    first_edit, edited = _edits(steps)
    return RunFacts(
        instance_id=result["instance_id"],
        run_id=run_id,
        resolved=bool(result.get("resolved")),
        step_limit=int(result["step_limit"]),
        steps=int(result.get("steps") or len(steps)),
        first_view=first_view,
        rereads=rereads,
        first_edit=first_edit,
        edited=edited,
        scratch_scripts=_scratch_scripts(steps),
        verified_test=_verified_test(steps, first_edit),
        traps=_traps(steps),
    )
