"""The one added line of a fix that tells a new teammate what changed.

A fix card says "added `host: this.configService.get(...)`", not the whole diff. The first added
line that is real code wins; a lone brace, a bare import or a comment is the last resort.
"""

from collections.abc import Sequence

from symbiont.miner.credential_patterns import scrub
from symbiont.records.schema import Kind, Record

# One short quoted line in a card; longer and the card stops being one line.
ADDED_CHARS = 70
_TRIVIAL_STARTS = ("import ", "from ", "#", "//", "/*", "*", "export {")
_BRACES = frozenset("{}()[]:,;")


def telling_added_line(steps: Sequence[Record]) -> str:
    """The first non-trivial added line of the edit steps, scrubbed and short; "" when none."""
    lines = [line for step in steps if step.kind == Kind.EDIT for line in _added(step)]
    real = [line for line in lines if not _trivial(line)]
    return _short(next(iter(real or lines), ""))


def _added(step: Record) -> list[str]:
    """The lines the edit added, in order (a diff's `+++` header is not one)."""
    marked = (line for line in (step.diff or "").splitlines() if line.startswith("+"))
    return [line[1:].strip() for line in marked if not line.startswith("+++") and line[1:].strip()]


def _trivial(line: str) -> bool:
    return set(line) <= _BRACES or line.startswith(_TRIVIAL_STARTS)


def _short(line: str) -> str:
    text = scrub(line.rstrip(",;"))
    return text if len(text) <= ADDED_CHARS else text[: ADDED_CHARS - 1].rstrip() + "…"
