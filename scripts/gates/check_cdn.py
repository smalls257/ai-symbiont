"""QG-FE-02: no external load in dashboard/ or docs/**/*.html (docs/explainer/ is built offline).

Counts script/link/img-style tags, CSS @import and url(), JS fetch and import; <a href> passes.
Pages listed in cdn-legacy-pages.txt load mermaid from a CDN today: reported, not failed.
Exit 0 clean, 1 findings, 2 cannot run.
Usage: check_cdn.py [FILE ...]   default: every tracked file in scope
"""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
LEGACY_FILE = Path(__file__).with_name("cdn-legacy-pages.txt")  # delete-only, like the waivers
LOADING_TAG = r"<(?:script|link|img|iframe|source|video|audio|embed|object|track)\b[^>]*>"
EXTERNAL = r"""(?:https?:)?//[^\s"'<>)]+"""
TAG_ATTR = re.compile(rf"(?:src|href|poster|data)\s*=\s*[\"']?({EXTERNAL})", re.I)
CSS_REFS = re.compile(
    rf"@import\s+(?:url\()?\s*[\"']?({EXTERNAL})|url\(\s*[\"']?({EXTERNAL})", re.I
)
JS_LOADS = re.compile(
    rf"(?:fetch|import|importScripts)\s*\(\s*[\"'`]({EXTERNAL})|from\s+[\"']({EXTERNAL})"
)
TAGS = re.compile(LOADING_TAG, re.I | re.S)


class GateError(RuntimeError):
    """The gate cannot judge (git failed, unreadable file)."""


def policy_for(path: str) -> frozenset[str] | None:
    """Allowed hosts for a path, or None when the path is out of scope."""
    if path.startswith("dashboard/") and path.endswith((".html", ".css", ".js")):
        if "node_modules/" in path:
            return None
        return frozenset()
    if path.startswith("docs/") and path.endswith(".html"):
        return frozenset()
    return None


def references(text: str) -> list[tuple[int, str]]:
    """(line, url) for every external load in the text."""
    found: set[tuple[int, str]] = set()

    def note(offset: int, match: re.Match[str]) -> None:
        url = next(group for group in match.groups() if group)
        found.add((text.count("\n", 0, offset) + 1, url))

    for pattern in (CSS_REFS, JS_LOADS):
        for match in pattern.finditer(text):
            note(match.start(), match)
    for tag in TAGS.finditer(text):
        for match in TAG_ATTR.finditer(tag.group(0)):
            note(tag.start() + match.start(), match)
    return sorted(found)


def host_of(url: str) -> str:
    return urlparse(url if not url.startswith("//") else "https:" + url).hostname or ""


def problems_in(path: str, text: str) -> list[str]:
    allowed = policy_for(path)
    if allowed is None:
        return []
    return [
        f"{path}:{line}: external load of {url} (allowed hosts here: {sorted(allowed) or 'none'})"
        for line, url in references(text)
        if host_of(url) not in allowed
    ]


def tracked_in_scope() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if out.returncode != 0:
        raise GateError(f"git ls-files failed: {out.stderr.strip()}")
    return [f for f in out.stdout.splitlines() if policy_for(f) is not None]


def findings_in(files: list[str]) -> list[str]:
    return [
        p
        for name in files
        if (ROOT / name).is_file()
        for p in problems_in(name, (ROOT / name).read_text())
    ]


def main(argv: list[str]) -> int:
    try:
        legacy = set(LEGACY_FILE.read_text().split()) if LEGACY_FILE.is_file() else set()
        files = argv[1:] or tracked_in_scope()
        found = findings_in(files)
    except (GateError, OSError, UnicodeDecodeError) as err:
        print(f"QG-FE-02 cannot judge: {err}", file=sys.stderr)
        return 2
    failing = [p for p in found if p.split(":")[0] not in legacy]
    for problem in found:
        print(f"QG-FE-02: {'' if problem in failing else 'legacy, not failing: '}{problem}")
    if not failing:
        print(f"QG-FE-02: OK ({len(files)} file(s) checked)")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
