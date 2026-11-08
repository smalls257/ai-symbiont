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
_COMMENT_OR_FENCE = re.compile(r"<!--.*?-->|```.*?(?:```|\Z)", re.DOTALL)
_INNER_DETAILS = re.compile(r"<details\b(?:(?!<details\b).)*?</details>", re.DOTALL | re.I)
_OPEN_DETAILS = re.compile(r"<details\b.*\Z", re.DOTALL | re.I)
# Only real HTML: a generic such as `parse::<u64>` is not a tag.
_HTML_TAG = re.compile(
    r"</?(?:details|summary|sub|sup|img|a|br|p|div|span|b|i|em|strong|code|pre|blockquote|table"
    r"|thead|tbody|tr|td|th|ul|ol|li|h[1-6]|hr|picture|source)\b[^>]*>",
    re.I,
)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_CODE_SPAN = re.compile(r"(`[^`\n]*`)")
_LEADING_BADGE = re.compile(r"^\W*\**P\d\b\**[:\s-]*")
_P_BADGE = re.compile(
    r"""(?:\bP([0-3])\s+Badge|badge/P([0-3])\b|alt=["']P([0-3])["']|^\W*\**P([0-3])\b)""", re.I
)
_BADGE_SEVERITY = {"0": "critical", "1": "major", "2": "minor", "3": "nitpick"}
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
    """The severity a marker states: CodeRabbit's `_🟠 Major_` or a P0-P3 badge in the opening."""
    opening = body.lstrip()[:300]
    first_line = opening.split("\n", 1)[0].lower()
    if "|" in first_line or "_" in first_line:
        marked = next((s for s in Severity if s is not Severity.UNSTATED and s in first_line), None)
        if marked is not None:
            return marked
    badge = _P_BADGE.search(opening)
    if badge is None:
        return Severity.UNSTATED
    return Severity(_BADGE_SEVERITY[next(g for g in badge.groups() if g)])


def gist_of(body: str) -> str:
    """One scrubbed line, at most GIST_CHARS, cut on a whole word: the comment's real point."""
    for paragraph in _visible(body).split("\n\n"):
        text = _paragraph_gist(paragraph)
        if text:
            return _shortened(scrub(text))
    return ""


def _visible(body: str) -> str:
    """The body without comments, code fences and details blocks (nested ones included)."""
    text = _COMMENT_OR_FENCE.sub("", body)
    while (stripped := _INNER_DETAILS.sub("", text)) != text:
        text = stripped
    return _OPEN_DETAILS.sub("", text)


def _without_markup(text: str) -> str:
    """Images and HTML tags removed everywhere except inside backtick code spans."""
    parts = _CODE_SPAN.split(text)
    for index in range(0, len(parts), 2):
        parts[index] = _HTML_TAG.sub("", _MARKDOWN_IMAGE.sub("", parts[index]))
    return "".join(parts)


def _shortened(text: str) -> str:
    if len(text) <= GIST_CHARS:
        return text
    cut = cut_whole(text, GIST_CHARS - 1)
    if text[len(cut)] != " ":
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def _paragraph_gist(paragraph: str) -> str:
    text = _without_markup(paragraph).strip()
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
