"""The plain one-line gist, the severity and the product name of a review comment body.

Pure text in, text out. Reviewer bots open with badges, HTML and details blocks; the gist is the
first real sentence after them, so a lesson reads as prose and a login never reaches it.
"""

import re
from enum import StrEnum

from symbiont.miner.credential_patterns import scrub
from symbiont.miner.tool_messages import cut_whole

GIST_CHARS = 160
TEAMMATE = "a teammate"
# Longest-first is irrelevant: logins match one product each. Order only decides ties.
_PRODUCTS = (
    ("coderabbit", "CodeRabbit"),
    ("copilot", "Copilot"),
    ("greptile", "Greptile"),
    ("codex", "Codex"),
    ("claude", "Claude"),
)
_HIDDEN = re.compile(
    r"<!--.*?-->|<details\b.*?</details>|<details\b.*\Z|```.*?(?:```|\Z)", re.DOTALL | re.IGNORECASE
)
_TAG = re.compile(r"<[^>]+>")
_LEADING_BADGE = re.compile(r"^\W*\**P\d\b\**[:\s-]*")
_BOLD_TITLE = re.compile(r"^\*\*(.+?)\*\*")
_EMPHASIS = re.compile(r"(\*\*|__)(.+?)\1|(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")
_SEVERITY_WORD = re.compile(
    r"(?<![A-Za-z])(?:nitpick|minor|major|critical|potential issue|suggestion)(?![A-Za-z])", re.I
)


class Severity(StrEnum):
    """How strongly the reviewer said it mattered; UNSTATED when the body says nothing."""

    NITPICK = "nitpick"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"
    UNSTATED = "unstated"


def reviewer_name(login: str) -> str:
    """The product behind a bot login, or "a teammate": a human login is never kept."""
    lowered = login.lower()
    return next((name for key, name in _PRODUCTS if key in lowered), TEAMMATE)


def severity_of(body: str) -> Severity:
    """The severity a CodeRabbit-style marker (`_🟠 Major_`) states in the opening line."""
    opening = body.lstrip().split("\n", 1)[0].lower()
    if "|" not in opening and "_" not in opening:
        return Severity.UNSTATED
    return next(
        (s for s in Severity if s is not Severity.UNSTATED and s in opening), Severity.UNSTATED
    )


def gist_of(body: str) -> str:
    """One scrubbed line, at most GIST_CHARS, cut on a whole word: the comment's real point."""
    for paragraph in _HIDDEN.sub("", body).split("\n\n"):
        text = _paragraph_gist(paragraph)
        if text:
            return cut_whole(scrub(text), GIST_CHARS)
    return ""


def _paragraph_gist(paragraph: str) -> str:
    text = _TAG.sub("", paragraph).strip()
    if _is_badge(text):
        return ""
    text = _LEADING_BADGE.sub("", text)
    title = _BOLD_TITLE.match(text)
    if title:
        return _plain(title.group(1))
    return _plain(_SENTENCE_END.split(" ".join(text.split()), maxsplit=1)[0])


def _is_badge(text: str) -> bool:
    if not re.search(r"[A-Za-z]", text):
        return True
    return "|" in text and len(text) < 80 and bool(_SEVERITY_WORD.search(text))


def _plain(text: str) -> str:
    unemphasized = _EMPHASIS.sub(lambda match: match.group(2) or match.group(3), text)
    return " ".join(unemphasized.split())
