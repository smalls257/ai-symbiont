"""QG-SEC-05 the owner's own identifiers (user names, e-mail local parts, LAN host names).

Violation prevented: Silent Fallback at the publish boundary. Regex rules cannot know the owner's
name, and writing the name into a tracked config would publish it. The terms therefore live
OUTSIDE the repo, in a file every worktree shares, and this check fails closed when that file is
missing or holds no term: a scan with nothing to look for reports "clean" and means nothing.

  check_private_terms.py staged          added lines of the staged diff (pre-commit)
  check_private_terms.py files F [F ...] the working copy of those files
  check_private_terms.py files0          the same, names NUL-delimited on stdin (any file name)
  check_private_terms.py tree DIR        every file under DIR (an exported tree)

Terms file: $SYMBIONT_PRIVATE_TERMS or ~/.config/symbiont/private-terms.txt, one term per line,
`#` comments, case-insensitive substrings of at least 4 characters. A finding prints path and line
but never the term or the line, so a log of the scan leaks nothing. Exit 1 on a finding, 2 if the
check cannot run.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

MIN_TERM_CHARS = 4  # shorter terms match ordinary words and train people to ignore the gate
DEFAULT_TERMS_FILE = Path.home() / ".config" / "symbiont" / "private-terms.txt"


class PrivateTermsError(RuntimeError):
    """The check cannot run: no terms file, or no term in it."""


def terms_path() -> Path:
    return Path(os.environ.get("SYMBIONT_PRIVATE_TERMS") or DEFAULT_TERMS_FILE)


def warn_if_readable_by_others(path: Path) -> None:
    if path.stat().st_mode & 0o077:
        print(
            f"QG-SEC-05: warning: {path} is readable by other users; run: chmod 600 {path}",
            file=sys.stderr,
        )


def load_terms(path: Path) -> list[str]:
    if not path.is_file():
        raise PrivateTermsError(
            f"no private-terms file at {path}: create it with one owner identifier per line "
            "(user name, e-mail local part, LAN host name); it stays outside the repo"
        )
    warn_if_readable_by_others(path)
    terms = [
        t.strip().lower()
        for t in path.read_text().splitlines()
        if t.strip() and not t.startswith("#")
    ]
    short = [t for t in terms if len(t) < MIN_TERM_CHARS]
    if short or not terms:
        raise PrivateTermsError(
            f"{path} must hold at least one term, each of {MIN_TERM_CHARS}+ characters"
        )
    return terms


def hits_in(label: str, text: str, terms: list[str]) -> Iterator[str]:
    for number, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        if any(term in lowered for term in terms):
            yield f"{label}:{number}: owner private term (Silent Fallback at the publish boundary)"


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def added_lines_of(patch: str) -> list[str]:
    """Added lines of ONE file's patch, by hunk structure: everything before the first `@@` is the
    header (`--- a/x`, `+++ b/x`); inside a hunk a line starting with `+` is an added line whatever
    follows, so a staged `++ term` or `+++ term` is scanned (`-U0` hunks carry no context lines)."""
    added, in_hunk = [], False
    for line in patch.splitlines():
        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            added.append(line[1:])
    return added


def staged_added_lines() -> dict[str, str]:
    """Added lines per staged path. Names come NUL-delimited and each diff is asked for by literal
    pathspec, so a non-ASCII name, a space or a quote cannot hide a file (git would print a quoted,
    escaped name in the patch header that a header parser does not recognize)."""
    names = git_bytes("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    texts = {}
    for raw in filter(None, names):
        name = raw.decode("utf-8", errors="surrogateescape")
        patch = git_bytes("diff", "--cached", "-U0", "--no-color", "--", f":(literal){name}")
        texts[name] = "\n".join(added_lines_of(patch.decode("utf-8", errors="ignore")))
        texts[f"{name} (path)"] = name
    return texts


def read_texts(paths: list[Path], base: Path | None) -> dict[str, str]:
    texts = {}
    for path in paths:
        label = str(path.relative_to(base)) if base else str(path)
        texts[label] = path.read_bytes().decode("utf-8", errors="ignore")
        texts[f"{label} (path)"] = label
    return texts


def existing_files(names: list[str]) -> list[Path]:
    return [Path(name) for name in names if name and Path(name).is_file()]


def stdin_names() -> list[str]:
    return [os.fsdecode(raw) for raw in sys.stdin.buffer.read().split(b"\0")]


def tree_texts(rest: list[str]) -> dict[str, str]:
    if len(rest) != 1 or not Path(rest[0]).is_dir():
        raise PrivateTermsError("tree needs one existing directory")
    root = Path(rest[0])
    return read_texts([p for p in sorted(root.rglob("*")) if p.is_file()], root)


def collect(mode: str, rest: list[str]) -> dict[str, str]:
    if mode == "staged":
        return staged_added_lines()
    if mode == "files0":
        return read_texts(existing_files(stdin_names()), None)
    if mode == "files":
        return read_texts(existing_files(rest), None)
    if mode == "tree":
        return tree_texts(rest)
    raise PrivateTermsError("usage: check_private_terms.py staged | files F... | files0 | tree DIR")


def main(argv: list[str]) -> int:
    try:
        terms = load_terms(terms_path())
        texts = collect(argv[0] if argv else "", argv[1:])
    except (PrivateTermsError, subprocess.CalledProcessError, OSError) as error:
        print(f"QG-SEC-05: cannot run: {error}", file=sys.stderr)
        return 2
    found = [hit for label, text in sorted(texts.items()) for hit in hits_in(label, text, terms)]
    for line in found:
        print(f"QG-SEC-05: {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
