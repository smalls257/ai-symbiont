"""QG-SCI-02 claim-tag lint. Prevents Paper Tiger: the deliverable is the claim, so a
number with a unit must say how much to trust it.

Scans prose in docs/, results/*.md, README.md and prereg/ (markdown and HTML). A line (or
a table row) containing a quantity (a number with %, x, ms, s, tasks, tokens, or a dollar
amount) must carry [measured], [established] or [hypothesis] on that line or in that row;
in HTML, `<span class="t m|e|h">` counts as a tag. Fenced code blocks, mermaid, HTML
style and script blocks are skipped. Forbidden phrases: "learns in seconds", "the
connectome makes it smarter", and the bare word "Doom" in a document that never says
"Freedoom via ViZDoom".

Usage: check_claims.py FILE ...   (files outside the scoped paths are ignored)
"""

import re
import sys
from pathlib import Path

# docs/standards/ states thresholds and quotes the forbidden phrases it forbids: it is the rule
# book, not a claim about results, so linting it would only make the rule flag itself.
SCOPE = re.compile(r"^(docs/(?!standards/)|results/[^/]+\.md$|README\.md$|prereg/)")
SUFFIXES = {".md", ".html"}
QUANTITY = re.compile(r"\d+(?:\.\d+)?\s*(?:%|(?:x|ms|s|tasks|tokens)\b)|\$\s?\d")
TAG = re.compile(
    r"\[(?:measured|established|hypothesis)\]|class=\"[^\"]*\bt\b[^\"]*\b[meh]\b", re.IGNORECASE
)
FORBIDDEN = ("learns in seconds", "the connectome makes it smarter")
BARE_DOOM = re.compile(r"(?<![A-Za-z])Doom(?![A-Za-z])")
HTML_BLOCKS = re.compile(r"<(style|script)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
HTML_TAGS = re.compile(r"<[^>]+>")
URLS = re.compile(r"https?://\S+")


def in_scope(relpath: str) -> bool:
    return bool(SCOPE.match(relpath)) and Path(relpath).suffix in SUFFIXES


def _outside_code_fences(text: str) -> list[tuple[int, str]]:
    kept, in_fence = [], False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            kept.append((number, line))
    return kept


def _group_html_rows(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Join the lines of each <tr>...</tr> into one unit so a tag in any cell covers the row."""
    units: list[tuple[int, str]] = []
    row: list[tuple[int, str]] = []
    for number, line in lines:
        opens = "<tr" in line and "</tr>" not in line
        if opens or row:
            row.append((number, line))
        else:
            units.append((number, line))
        if row and "</tr>" in line:
            units.append((row[0][0], " ".join(text for _, text in row)))
            row = []
    return units


def prose_units(text: str, *, is_html: bool) -> list[tuple[int, str]]:
    """(line number, raw unit) pairs: lines outside code fences; an HTML <tr> is one unit."""
    if not is_html:
        return _outside_code_fences(text)
    blank_blocks = HTML_BLOCKS.sub(lambda block: "\n" * block.group(0).count("\n"), text)
    return _group_html_rows(_outside_code_fences(blank_blocks))


def untagged_quantities(units: list[tuple[int, str]], *, is_html: bool) -> list[int]:
    found = []
    for number, raw in units:
        text = HTML_TAGS.sub(" ", raw) if is_html else raw
        text = URLS.sub(" ", text)
        if QUANTITY.search(text) and not TAG.search(raw):
            found.append(number)
    return found


def problems_in(relpath: str, text: str) -> list[str]:
    is_html = relpath.endswith(".html")
    units = prose_units(text, is_html=is_html)
    found = [
        f"{relpath}:{n}: quantity without [measured]/[established]/[hypothesis]"
        for n in untagged_quantities(units, is_html=is_html)
    ]
    lowered = text.lower()
    found += [f"{relpath}: forbidden phrase '{p}'" for p in FORBIDDEN if p in lowered]
    prose = HTML_TAGS.sub(" ", HTML_BLOCKS.sub("", text)) if is_html else text
    if BARE_DOOM.search(prose) and "freedoom via vizdoom" not in lowered:
        found.append(f"{relpath}: says 'Doom' but never 'Freedoom via ViZDoom'")
    return found


def main(argv: list[str], root: Path) -> int:
    problems = []
    for name in argv:
        relpath = str(Path(name).resolve().relative_to(root))
        if in_scope(relpath):
            problems += problems_in(relpath, Path(name).read_text())
    for line in problems:
        print(f"QG-SCI-02: {line}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], Path(__file__).resolve().parents[2]))
