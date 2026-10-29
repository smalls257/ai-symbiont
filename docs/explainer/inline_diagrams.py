"""Inline the pre-rendered diagram SVGs into the explainer page.

Why: the page must open from a file with no network fetch, and the repo refuses files over
1 MB, so each diagram is kept as a mermaid source (`diagrams/*.mmd`), rendered once by
`diagrams/render.sh`, and written between the markers `<!-- diagram:NAME -->` and
`<!-- /diagram -->` in `index.html`. Re-running replaces what sits between the markers, so
the page stays the single hand-edited source (no generated copy to drift from it).

Raises `DiagramMissingError` when a marker names an SVG that has not been rendered, rather
than leaving an empty figure that would look like a design choice.

Usage: python docs/explainer/inline_diagrams.py
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE / "index.html"
MARKER = re.compile(r"<!-- diagram:([\w-]+) -->.*?<!-- /diagram -->", re.S)


class DiagramMissingError(FileNotFoundError):
    """A marker in index.html names a diagram with no rendered SVG beside it."""


def inlined_page(page_text: str, diagrams_dir: Path) -> str:
    """Return the page with every diagram marker filled from its rendered SVG."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        svg_path = diagrams_dir / f"{name}.svg"
        if not svg_path.exists():
            raise DiagramMissingError(f"{svg_path} is missing; run diagrams/render.sh first")
        svg = svg_path.read_text().strip()
        # Short lines keep the secrets-scan regexes from timing out on one 26 KB line.
        svg = re.sub(r"(/>|</g>)(?=<)", r"\1\n", svg)
        return f"<!-- diagram:{name} -->\n{svg}\n<!-- /diagram -->"

    return MARKER.sub(replace, page_text)


def main() -> int:
    """Rewrite index.html in place and report the diagram count and page size."""
    after = inlined_page(PAGE.read_text(), HERE / "diagrams")
    PAGE.write_text(after)
    count = len(MARKER.findall(after))
    size_kb = len(after.encode()) // 1024
    sys.stdout.write(f"inlined {count} diagrams; index.html is {size_kb} KB\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
