"""Exit codes for test and build runs piped through a pager, where the shell reports a clean 0.

`pytest -q 2>&1 | head -n 200` exits 0, so the output is read instead, for that shape only.
Precision first: only a runner's own failure lines count (pytest, unittest, jest, vitest, mocha,
tsc, cargo, go) or a traceback that ends the output; `test_failed_login` matches nothing.
"""

import re

PIPED_FAILURE_CODE = 1

_PIPE = re.compile(r"(?<!\|)\|(?!\|)")
_FILTER_STAGE = re.compile(r"^\s*(?:head|tail|tee|cat|less|more)\b")
_RUNNER = re.compile(
    r"\b(?:pytest|py\.test|unittest|jest|vitest|mocha|tsc|"
    r"cargo\s+(?:test|build)|go\s+(?:test|build)|"
    r"(?:npm|yarn|pnpm)\s+(?:run\s+)?(?:test|build)|"
    r"make\s+(?:test|check|build))\b"
)
_FAILURE_LINES = re.compile(
    r"""
    ^(?:=+\s*)?[1-9]\d*\s+(?:failed|errors?)\b.*\bin\s+[\d.]+s   # pytest summary
    | ^(?:FAILED|ERROR)\s+\S+::\S+                                 # pytest short summary
    | ^\S+::\S+\s+(?:FAILED|ERROR)\b                               # pytest -v
    | ^FAILED\s+\((?:failures|errors)=\d+                          # unittest
    | ^Tests:\s+.*\b[1-9]\d*\s+failed\b                            # jest
    | ^Test\ Suites:\s+.*\b[1-9]\d*\s+failed\b                     # jest
    | ^\s*Tests\s+.*\b[1-9]\d*\s+failed\b                          # vitest
    | ^\s*[1-9]\d*\s+failing\b                                     # mocha
    | ^\S.*\berror\s+TS\d+:                                        # tsc
    | ^test\ result:\s+FAILED\b                                    # cargo
    | ^---\s+FAIL:\s+\S+                                           # go
    """,
    re.MULTILINE | re.VERBOSE,
)
_TRACEBACK = re.compile(r"^Traceback \(most recent call last\):", re.MULTILINE)
_EXCEPTION_LAST_LINE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt)\b.*$")


def exit_code_with_output(command: str, output: str, reported: int | None) -> int | None:
    """The exit code to record: `reported`, unless a piped runner's output shows it failed.

    Only a reported 0 or an unreported code (None) can be overridden; a non-zero code stands.
    Returns PIPED_FAILURE_CODE for a detected failure.
    """
    if reported not in (0, None):
        return reported
    if _piped_runner(command) and shows_failure(output):
        return PIPED_FAILURE_CODE
    return reported


def shows_failure(output: str) -> bool:
    """Whether a test or build runner's own output says it failed."""
    return bool(_FAILURE_LINES.search(output)) or _ends_in_traceback(output)


def _piped_runner(command: str) -> bool:
    """A test or build runner whose output goes through a pager or filter at the end."""
    stages = _PIPE.split(command)
    if len(stages) < 2 or not _FILTER_STAGE.match(stages[-1]):
        return False
    return any(_RUNNER.search(stage) for stage in stages[:-1])


def _ends_in_traceback(output: str) -> bool:
    """A traceback is in the output and an exception line is where the output stops."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines or not _TRACEBACK.search(output):
        return False
    return bool(_EXCEPTION_LAST_LINE.match(lines[-1]))
