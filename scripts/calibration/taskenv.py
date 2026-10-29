"""Task containers: prepare a history-free checkout, install, and grade a patch.

sqlglot shares ONE image whose clone reaches past every fix, so its containers are re-checked-out
at the task's base commit; per-task SWE-rebench images keep future refs too, so they are scrubbed
(`history_scrub_script`). Every failure raises TaskEnvError with the command, return code and
output tail; nothing here swallows an error. verify_disk.py checks the shared-image results.
"""

from __future__ import annotations

import base64
import re
import subprocess
import uuid
from dataclasses import dataclass

ACTIVATE = "source /opt/miniconda3/bin/activate testbed"
# pytest -rA summary lines: a status word, then the test id (a FAILED line adds a message)
_SUMMARY = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) (\S+::\S+)")
# some rows' test_cmd runs pytest -v, which prints "tests/...::t PASSED" per test instead
_VERBOSE = re.compile(r"^(\S+::\S+) (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")


class TaskEnvError(RuntimeError):
    pass


def prepare_script(base_commit: str) -> str:
    """Shell that turns the image's full clone into a history-free checkout of base_commit."""
    # The image's editable install already resolves `sqlglot`; sqlglot/_version.py (gitignored,
    # setuptools_scm) is written from `git describe` before the history is deleted.
    return f"""set -euo pipefail
mv /testbed /opt/sqlglot_full
git -C /opt/sqlglot_full config uploadpack.allowAnySHA1InWant true
VER=$(git -C /opt/sqlglot_full describe --tags {base_commit} | sed 's/^v//')
mkdir /testbed && cd /testbed
git init -q && git fetch -q --depth 1 /opt/sqlglot_full {base_commit} && git checkout -q FETCH_HEAD
git checkout -q -b main
rm -rf /opt/sqlglot_full
! grep -q _version sqlglot/__init__.py || printf \\
  '__version__ = version = "%s"\\n__version_tuple__ = version_tuple = tuple("%s".split("."))\\n' \\
  "$VER" "$VER" > sqlglot/_version.py
test "$(git rev-parse HEAD)" = "{base_commit}"
test "$(git rev-list --all | wc -l)" = "1"
"""


def write_file_cmd(path: str, text: str) -> str:
    b64 = base64.b64encode(text.encode()).decode()
    return f"echo {b64} | base64 -d > {path}"


def apply_cmd(path: str) -> str:
    # Same fallback order as the SWE-bench harness: git apply, then patch with fuzz.
    return f"cd /testbed && (git apply --verbose {path} || patch --batch --fuzz=5 -p1 -i {path})"


def test_files(row: dict) -> list[str]:
    return sorted({t.split("::")[0] for t in list(row["FAIL_TO_PASS"]) + list(row["PASS_TO_PASS"])})


def parse_pytest_summary(output: str) -> dict[str, str]:
    status: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if found := _SUMMARY.match(line):
            status[found.group(2)] = found.group(1)
        elif found := _VERBOSE.match(line):
            status.setdefault(
                found.group(1), found.group(2)
            )  # the -rA summary, if also present, wins
    return status


@dataclass
class Grade:
    resolved: bool
    patch_applied: bool
    f2p_passed: int
    f2p_total: int
    p2p_passed: int
    p2p_total: int
    status: dict[str, str]


def score(row: dict, status: dict[str, str], *, patch_applied: bool = True) -> Grade:
    f2p, p2p = list(row["FAIL_TO_PASS"]), list(row["PASS_TO_PASS"])
    f_ok = sum(status.get(t) == "PASSED" for t in f2p)
    p_ok = sum(status.get(t) == "PASSED" for t in p2p)
    return Grade(
        resolved=patch_applied and f_ok == len(f2p) and p_ok == len(p2p),
        patch_applied=patch_applied,
        f2p_passed=f_ok,
        f2p_total=len(f2p),
        p2p_passed=p_ok,
        p2p_total=len(p2p),
        status={t: status.get(t, "MISSING") for t in f2p + p2p},
    )


class Container:
    """A throwaway container (docker run -d ... sleep); always call stop()."""

    def __init__(self, image: str, *, network: bool = False):
        self.name = f"calib-{uuid.uuid4().hex[:8]}"
        args = ["docker", "run", "-d", "--rm", "--name", self.name]
        if not network:
            args += ["--network", "none"]
        self._run(args + [image, "sleep", "2h"], timeout=900)

    def _run(self, args: list[str], timeout: int) -> str:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if proc.returncode:
            tail = (proc.stdout + proc.stderr)[-800:]
            raise TaskEnvError(f"{args[:4]}... rc={proc.returncode}: {tail}")
        return proc.stdout

    def sh(self, script: str, *, timeout: int = 600, check: bool = True) -> tuple[int, str]:
        proc = subprocess.run(
            ["docker", "exec", self.name, "bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = proc.stdout + proc.stderr
        if check and proc.returncode:
            raise TaskEnvError(f"rc={proc.returncode} running {script[:120]!r}: {out[-800:]}")
        return proc.returncode, out

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=120)


def history_scrub_script() -> str:
    """Shell that leaves only HEAD's history in /testbed; exits non-zero if a future commit stays
    (the per-task images keep refs that reach the gold fix)."""
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


def install_script(row: dict) -> str | None:
    """Re-install the checked-out package without network (SWE-rebench images leave src-layout
    packages unimportable until `pip install -e .` runs); None when the row installs nothing."""
    install = (row.get("install_config") or {}).get("install") or ""
    if "pip install" not in install:
        return None
    return f"{ACTIVATE}; cd /testbed; pip install --no-deps --no-build-isolation -e . -q"


def grade(image: str, row: dict, model_patch: str, *, prepare: bool) -> Grade:
    """Fresh container: (prepare), apply the model patch and the task's test patch, run F2P+P2P."""
    box = Container(image)
    try:
        if prepare:
            box.sh(prepare_script(row["base_commit"]), timeout=900)
        install = install_script(row)
        if install:
            box.sh(install, timeout=600, check=False)  # a failed install shows in the test run
        if model_patch.strip():
            box.sh(write_file_cmd("/tmp/model.patch", model_patch))
            rc, _ = box.sh(apply_cmd("/tmp/model.patch"), check=False)
            if rc:
                return score(row, {}, patch_applied=False)
        box.sh(write_file_cmd("/tmp/test.patch", row["test_patch"]))
        box.sh(apply_cmd("/tmp/test.patch"))
        test_cmd = row["install_config"]["test_cmd"]
        _, out = box.sh(
            f"{ACTIVATE}; cd /testbed; {test_cmd} {' '.join(test_files(row))}",
            timeout=1200,
            check=False,
        )  # pytest rc!=0 is a normal outcome; the summary decides
        status = parse_pytest_summary(out)
        if not status:
            raise TaskEnvError(f"no pytest summary lines in test output: {out[-800:]}")
        return score(row, status)
    finally:
        box.stop()
