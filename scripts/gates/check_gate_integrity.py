"""QG-GATE-01 gate integrity. Prevents Paper Tiger: a gate whose thresholds, waivers or floor
can be loosened by the commit that needs the loosening proves nothing.

Every commit in merge-base..HEAD is judged on its own diff against its parent, and so is the
pending (staged or uncommitted) work against HEAD. A merge of main (or an ancestor of it) is judged
only on what is new against both parents: main's own gate changes were approved where they landed.
A change is a loosening when it
  * ADDS a waiver entry to .lizard-whitelist.txt or .naming-waivers.txt (removals pass),
  * LOWERS the test-count floor in scripts/gates/test-floor.txt (raising passes),
  * changes any other protected file: gate scripts and hooks, gitleaks config and baseline,
    semgrep rules, .importlinter, Claude hook scripts, or the ruff/mypy/coverage/pytest tables
    in pyproject.toml.
THAT commit's own message must carry `GATE-CHANGE: <reason>`; a trailer on an earlier commit
unlocks nothing. The pending work is judged against the message passed with --message-file
(the commit-msg hook). A commit listed in scripts/gates/accepted-gate-changes.txt (owner
ledger, itself a protected file) is accepted without a trailer. The Claude hook that denies edits
to these files is only a first line of defense: a shell edit bypasses it, this check does not.

Usage: check_gate_integrity.py [--message-file FILE | --list]
  (exit 1 on a loosening, 2 if it cannot run; --list prints every GATE-CHANGE commit in range)
"""

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

PROTECTED_PREFIXES = (
    "scripts/gates/",
    "scripts/hooks/",
    "scripts/publish/",
    ".semgrep/",
    ".claude/hooks/",
)
PROTECTED_FILES = frozenset(
    {
        ".gitleaks.toml",
        ".gitleaks-baseline.json",
        ".importlinter",
        ".gitattributes",
        ".claude/settings.json",
        ".claude/settings.json.proposed",
    }
)
WAIVER_FILES = (".lizard-whitelist.txt", ".naming-waivers.txt")
FLOOR_FILE = "scripts/gates/test-floor.txt"
LEDGER = "scripts/gates/accepted-gate-changes.txt"
TOOL_TABLES = ("ruff", "mypy", "coverage", "pytest")
TRAILER = re.compile(r"^GATE-CHANGE:\s*(\S.*)$", re.MULTILINE)


class IntegrityError(RuntimeError):
    """The check cannot run (no repo, unknown base): it must not pass silently."""


def run_git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise IntegrityError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def gate_base_ref() -> str:
    return os.environ.get("SYMBIONT_GATE_BASE", "main")


def base_commit(root: Path) -> str:
    return run_git(root, "merge-base", gate_base_ref(), "HEAD").strip()


def text_at(root: Path, ref: str | None, path: str) -> str | None:
    """File content at `ref`, or in the working tree when ref is None; None if absent."""
    if ref is None:
        target = root / path
        return target.read_text() if target.is_file() else None
    out = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout if out.returncode == 0 else None


def is_protected(path: str) -> bool:
    return path in PROTECTED_FILES or path.startswith(PROTECTED_PREFIXES)


def changed_paths(root: Path, before: str, after: str | None) -> set[str]:
    if after is not None:
        return {p for p in run_git(root, "diff", "--name-only", before, after).split("\n") if p}
    tracked = run_git(root, "diff", "--name-only", before).split("\n")
    fresh = run_git(root, "ls-files", "--others", "--exclude-standard").split("\n")
    return {p for p in tracked + fresh if p}


def entries(text: str | None) -> set[str]:
    lines = (line.partition("#")[0].strip() for line in (text or "").splitlines())
    return {line for line in lines if line}


def floor_of(text: str | None) -> int:
    return int((text or "0").partition("#")[0].strip() or 0)


def tool_tables(text: str | None) -> dict:
    tool = tomllib.loads(text or "").get("tool", {})
    return {name: tool.get(name) for name in TOOL_TABLES}


def protected_file_findings(root: Path, before: str, after: str | None, path: str) -> list[str]:
    old, new = text_at(root, before, path), text_at(root, after, path)
    if path in WAIVER_FILES:
        return []  # judged by waiver_findings: removals pass, additions do not
    if new is None:
        return [f"{path}: gate file deleted"]
    if path != FLOOR_FILE:
        return [f"{path}: gate configuration changed"]
    if floor_of(new) < floor_of(old):
        return [f"{path}: floor lowered {floor_of(old)} -> {floor_of(new)}"]
    return []


def waiver_findings(root: Path, before: str, after: str | None) -> list[str]:
    found = []
    for path in WAIVER_FILES:
        added = entries(text_at(root, after, path)) - entries(text_at(root, before, path))
        found += [f"{path}: waiver added: {entry}" for entry in sorted(added)]
    return found


def violations(root: Path, before: str, after: str | None = None) -> list[str]:
    """Loosenings between `before` and `after` (None means the working tree)."""
    paths = changed_paths(root, before, after)
    found = []
    for path in sorted(p for p in paths if is_protected(p)):
        found += protected_file_findings(root, before, after, path)
    found += waiver_findings(root, before, after)
    if "pyproject.toml" in paths:
        old, new = text_at(root, before, "pyproject.toml"), text_at(root, after, "pyproject.toml")
        if tool_tables(new) != tool_tables(old):
            found.append("pyproject.toml: ruff/mypy/coverage/pytest configuration changed")
    return found


def accepted_commits(root: Path) -> set[str]:
    return {entry.split()[0] for entry in entries(text_at(root, None, LEDGER))}


def commits_in_range(root: Path, base: str) -> list[str]:
    return run_git(root, "log", "--reverse", "--format=%H", f"{base}..HEAD").split()


def is_ancestor(root: Path, sha: str, of: str) -> bool:
    out = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", sha, of], check=False
    )
    return out.returncode == 0


def new_in_merge(root: Path, ours: str, theirs: str, after: str | None) -> list[str]:
    """Loosenings of a merge result that neither parent already carried."""
    against_ours = set(violations(root, ours, after))
    floor_resolved = text_at(root, after, FLOOR_FILE) != text_at(root, ours, FLOOR_FILE)
    return [
        line
        for line in violations(root, theirs, after)
        if line in against_ours or (line.startswith(FLOOR_FILE) and floor_resolved)
    ]


def commit_findings(root: Path, sha: str, gate_base: str) -> list[str]:
    """A commit's loosenings; a merge that brings in the gate base is judged by new_in_merge."""
    parents = run_git(root, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    if len(parents) == 2 and is_ancestor(root, parents[1], gate_base):
        return new_in_merge(root, parents[0], parents[1], sha)
    return violations(root, f"{sha}^", sha)


def merge_head(root: Path) -> str | None:
    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "-q", "--verify", "MERGE_HEAD^{commit}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip() or None


def pending_findings(root: Path, gate_base: str) -> list[str]:
    """Uncommitted work's loosenings; during a merge of the gate base, only what is new."""
    theirs = merge_head(root)
    if theirs and is_ancestor(root, theirs, gate_base):
        return new_in_merge(root, "HEAD", theirs, None)
    return violations(root, "HEAD")


def message_of(root: Path, sha: str) -> str:
    return run_git(root, "log", "-1", "--format=%B", sha)


def unmarked_commits(root: Path, base: str) -> list[str]:
    """One line per loosening in a commit whose own message lacks the trailer."""
    accepted = accepted_commits(root)
    found = []
    gate_base = gate_base_ref()
    for sha in commits_in_range(root, base):
        loosenings = commit_findings(root, sha, gate_base)
        if loosenings and sha not in accepted and not TRAILER.search(message_of(root, sha)):
            found += [f"{sha[:10]}: {line}" for line in loosenings]
    return found


def gate_change_report(root: Path, base: str) -> list[str]:
    """Every commit in range that carries the trailer: sha, reason, protected files touched."""
    lines = []
    for sha in commits_in_range(root, base):
        match = TRAILER.search(message_of(root, sha))
        if not match:
            continue
        files = run_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).split()
        touched = ", ".join(f for f in files if is_protected(f) or f in WAIVER_FILES)
        lines.append(f"{sha[:10]}  {match.group(1).strip()}  [{touched or 'no protected files'}]")
    return lines


def main(argv: list[str]) -> int:
    root = Path(run_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    base = base_commit(root)
    if argv[:1] == ["--list"]:
        print(
            "\n".join(
                ["GATE-CHANGE commits in range (every loosening):", *gate_change_report(root, base)]
            )
        )
        return 0
    extra = Path(argv[1]).read_text() if argv[:1] == ["--message-file"] else ""
    problems = unmarked_commits(root, base)
    if not TRAILER.search(extra):
        problems += [f"pending work: {line}" for line in pending_findings(root, gate_base_ref())]
    for line in problems:
        print(f"QG-GATE-01: {line}", file=sys.stderr)
    if problems:
        print(
            "QG-GATE-01: fix the code, not the gate. Only the owner changes a gate, in the commit "
            "whose own message carries `GATE-CHANGE: <reason>`.",
            file=sys.stderr,
        )
        return 1
    print("QG-GATE-01: OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except IntegrityError as err:
        print(f"gate error: {err}", file=sys.stderr)
        sys.exit(2)
