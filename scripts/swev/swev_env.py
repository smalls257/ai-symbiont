"""Per-task SWE-bench images: hide refs past HEAD for the agent, grade with the hidden tests.

Grading is the benchmark's own: the row's eval_script, the official apply order and
get_eval_report. Unlike the official run_instance, a docker failure or unparsed test output
raises ScorerError instead of returning None; a patch that does not apply is an outcome.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calibration"))  # taskenv

from swebench.harness.grading import get_eval_report  # noqa: E402
from swebench.harness.run_evaluation import GIT_APPLY_CMDS  # noqa: E402
from swebench.harness.utils import make_test_spec  # noqa: E402
from taskenv import Container, TaskEnvError, write_file_cmd  # noqa: E402

EVAL_TIMEOUT_S = 1800  # the official harness default (SWEBENCH_DOCKER_TIMEOUT); Django runs ~1 min
PATCH_PATH = "/tmp/patch.diff"  # noqa: S108  inside the throwaway container
RESET_TREE = "cd /testbed && git checkout -- . && git clean -fdq"
F2P, P2P = "FAIL_TO_PASS", "PASS_TO_PASS"

# Counts only: refs, tags and commits reachable from any ref but not from HEAD (future history).
HISTORY_COUNTS = """cd /testbed
echo "refs=$(git for-each-ref | wc -l) tags=$(git tag | wc -l) \
future=$(git rev-list --all --not HEAD | wc -l)"
"""


class ScorerError(RuntimeError):
    """Grading could not happen (docker, timeout, unreadable test output); never a pass or fail."""


def scrub_history_script() -> str:
    """Shell that leaves only HEAD's history in /testbed; exits non-zero if future commits stay."""
    return """set -euo pipefail
cd /testbed
keep=$(git symbolic-ref -q HEAD || true)
git for-each-ref --format='%(refname)' | while read -r ref; do
  [ "$ref" = "$keep" ] || git update-ref -d "$ref"
done
rm -f .git/ORIG_HEAD .git/FETCH_HEAD .git/MERGE_HEAD
git reflog expire --expire=now --all
git gc -q --prune=now
test "$(git rev-list --all --not HEAD | wc -l)" = 0
"""


class Outcome(StrEnum):
    """What grading found; a patch that does not apply is an outcome, not an error."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    PATCH_NOT_APPLIED = "patch_not_applied"


@dataclass(frozen=True)
class Grade:
    """One graded patch: the official outcome plus (passed, total) per test list."""

    outcome: Outcome
    f2p: tuple[int, int] = (0, 0)
    p2p: tuple[int, int] = (0, 0)

    @property
    def resolved(self) -> bool:
        """The official SWE-bench verdict: every FAIL_TO_PASS and PASS_TO_PASS test passes."""
        return self.outcome is Outcome.RESOLVED


def counts_of(tests_status: dict, key: str) -> tuple[int, int]:
    """(passed, total) of one test list in the official report's tests_status."""
    found = tests_status[key]
    passed = len(found["success"])
    return passed, passed + len(found["failure"])


def _apply_patch(box: Container, patch: str) -> bool:
    """The official apply chain; True once a command (or the reverse check) says it applied."""
    box.sh(write_file_cmd(PATCH_PATH, patch))
    for attempt, command in enumerate(GIT_APPLY_CMDS):
        if attempt:
            box.sh(RESET_TREE, check=False)  # a failed --reject leaves partial state behind
        if box.sh(f"cd /testbed && {command} {PATCH_PATH}", check=False)[0] == 0:
            return True
    return box.sh(f"cd /testbed && git apply --check --reverse {PATCH_PATH}", check=False)[0] == 0


def _report(row: dict, patch: str, log: str) -> dict:
    """The official report for this row and test log; raises if no test output could be parsed."""
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as handle:
        handle.write(log)
    prediction = {"instance_id": row["instance_id"], "model_patch": patch}
    report = get_eval_report(
        make_test_spec(row), prediction, handle.name, include_tests_status=True
    )
    Path(handle.name).unlink()
    found = report[row["instance_id"]]
    if not found["patch_successfully_applied"]:  # the official flag for "no parseable output"
        reason = found.get("infra_failure_reason", "unparsed")
        raise ScorerError(f"{row['instance_id']}: no test results parsed ({reason}): {log[-600:]}")
    return found


def grade(row: dict, patch: str) -> Grade:
    """Grade `patch` (may be empty: tests run on the base tree) with the row's hidden tests."""
    try:
        box = Container(row["image"], network=True)  # the official eval may pip install
    except TaskEnvError as error:
        raise ScorerError(f"container for {row['instance_id']}: {error}") from error
    try:
        if patch.strip() and not _apply_patch(box, patch):
            return Grade(Outcome.PATCH_NOT_APPLIED)
        box.sh(write_file_cmd("/eval.sh", row["eval_script"]))
        _, log = box.sh("/bin/bash /eval.sh", timeout=EVAL_TIMEOUT_S, check=False)
        found = _report(row, patch, log)
        status = found["tests_status"]
        outcome = Outcome.RESOLVED if found["resolved"] else Outcome.UNRESOLVED
        return Grade(outcome, counts_of(status, F2P), counts_of(status, P2P))
    except TaskEnvError as error:
        raise ScorerError(f"grading {row['instance_id']}: {error}") from error
    finally:
        box.stop()
