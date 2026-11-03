"""Test and CI failure output pasted into a prompt: the failing check and a short excerpt.

Pure: prompt text in, a PastedFailure or None out. Runners: pytest, jest and vitest, cargo, go,
plus plain "CI failed" or red-check sentences. It names the check; it never judges whose fault
the failure is.
"""

import re
from dataclasses import dataclass

from symbiont.miner.credential_scrub import scrub
from symbiont.miner.failure_excerpt import EXCERPT_CHARS, assertion_excerpt
from symbiont.records.output_failure import shows_failure

NO_FILE = "-"
GENERIC_CHECK = "ci"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Each pattern's first group names the failing check; the earliest one in the text wins.
_CHECK_IDS = (
    re.compile(r"^(?:SUB)?(?:FAILED|ERROR)(?:\[[^\n]*?\])?[ \t]+(\S+\.py(?:::\S+)?)", re.MULTILINE),
    re.compile(r"^[ \t]*FAIL[ \t]+(\S+\.(?:[jt]sx?|mjs|cjs))\b", re.MULTILINE),
    re.compile(r"^test[ \t]+(\S+)[ \t]+\.\.\.[ \t]+FAILED\b", re.MULTILINE),
    re.compile(r"^---- (\S+) stdout ----$", re.MULTILINE),
    re.compile(r"^--- FAIL: (\S+)", re.MULTILINE),
)
_RED_CHECK_SENTENCE = re.compile(
    r"^.*(?:\bCI\b[^.\n]{0,40}\b(?:failed|failing|is red|went red)\b"
    r"|\b(?:checks?|pipeline|workflow|build)\b[^.\n]{0,30}\b(?:failed|failing|not successful)\b"
    r"|\bfailing checks?\b).*$",
    re.MULTILINE | re.IGNORECASE,
)
_SENTENCE_CHARS = 120


@dataclass(frozen=True)
class PastedFailure:
    """The failing check a prompt carried, where it lives, and what it expected versus got."""

    check: str
    file: str
    excerpt: tuple[str, ...]


def pasted_failure(prompt: str) -> PastedFailure | None:
    """The failure a prompt pastes, or None without a runner's failure or a red-check sentence."""
    text = _ANSI.sub("", prompt)
    if shows_failure(text):
        check = _first_check_id(text)
        return PastedFailure(check, _file_of(check), assertion_excerpt(text))
    sentence = _RED_CHECK_SENTENCE.search(text)
    if sentence is None:
        return None
    said = scrub(" ".join(sentence.group(0).split()))[:_SENTENCE_CHARS]
    return PastedFailure(GENERIC_CHECK, NO_FILE, (said,))


def quote_of(failure: PastedFailure) -> str:
    """What a lesson quotes for a pasted failure: the check and its excerpt, within the cap."""
    said = f"CI reported {failure.check} failing: " + " / ".join(failure.excerpt)
    return said[:EXCERPT_CHARS]


def _first_check_id(text: str) -> str:
    """The earliest failing check named in the text; GENERIC_CHECK when only the summary shows."""
    found = [(m.start(1), m.group(1)) for pattern in _CHECK_IDS for m in pattern.finditer(text)]
    return min(found)[1] if found else GENERIC_CHECK


def _file_of(check: str) -> str:
    """The file part of a pytest node id or a path-like check; NO_FILE for a bare test name."""
    path = check.split("::")[0]
    return path if "/" in path or "." in path.rsplit("/", 1)[-1] else NO_FILE
