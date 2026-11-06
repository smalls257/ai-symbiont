"""Which themes to offer, and which few sessions to draw so every selection has an example.

Drawing a strip for every session of a large
history would ship megabytes the page never shows; the densest session of each theme, each pattern
and each theme-pattern cell is enough to show any click, about a hundred strips for sqlglot.
"""

from collections import Counter
from collections.abc import Iterable, Sequence

from symbiont.miner.patterns import StrugglePattern
from symbiont.miner.strips import (
    MAX_STRIP_STEPS,
    READABLE_STEPS,
    SessionStrip,
    burstiness,
    strip_of,
)
from symbiont.miner.struggle import SessionFacts
from symbiont.miner.themes import Codebase
from symbiont.records.schema import Record

# Tuned once on sqlglot OpenHands traces (2,678 sessions); Step 6 of the plan re-measures them.
THEMES_OFFERED = 40
MIN_THEME_SESSIONS = 2  # fewer sessions than this is an anecdote, not a theme
MAX_THEME_SHARE = 0.3  # a word in more than this share of sessions is the project, not a theme
SHARE_NEEDS_SESSIONS = 10  # with fewer sessions there is no "everything" to be distinct from
SHOWN_SHARE = 0.02  # the page lists a theme only when this share of sessions has it


def theme_words(facts: Sequence[SessionFacts]) -> list[str]:
    """The most frequent themes that are neither anecdotes nor the whole project."""
    seen = Counter(word for fact in facts for word in fact.themes)
    ceiling = (
        max(MAX_THEME_SHARE * len(facts), 0) if len(facts) >= SHARE_NEEDS_SESSIONS else len(facts)
    )
    ranked = [(word, n) for word, n in seen.most_common() if MIN_THEME_SESSIONS <= n <= ceiling]
    return [word for word, _ in ranked[:THEMES_OFFERED]]


def min_sessions_shown(session_count: int) -> int:
    """The fewest sessions a theme needs to be listed on the page."""
    return max(MIN_THEME_SESSIONS, round(SHOWN_SHARE * session_count))


def representative_strips(
    sessions: Sequence[Sequence[Record]], facts: Sequence[SessionFacts], codebase: Codebase
) -> list[SessionStrip]:
    """The strip of the densest session of everything a click can select."""
    chosen = {_densest(sessions, group) for group in _groups(facts)} - {None}
    return [
        _strip(sessions[n], facts[n], codebase) for n in sorted(n for n in chosen if n is not None)
    ]


def _groups(facts: Sequence[SessionFacts]) -> list[list[int]]:
    """Session indexes of: all, each theme, each pattern, each theme-pattern cell."""
    words = theme_words(facts)
    by_word = {word: _having(facts, range(len(facts)), word=word) for word in words}
    by_pattern = {p: _having(facts, range(len(facts)), pattern=p) for p in StrugglePattern}
    cells = [_having(facts, by_word[w], pattern=p) for w in words for p in StrugglePattern]
    return [list(range(len(facts))), *by_word.values(), *by_pattern.values(), *cells]


def _having(
    facts: Sequence[SessionFacts],
    among: Iterable[int],
    *,
    word: str | None = None,
    pattern: StrugglePattern | None = None,
) -> list[int]:
    """The sessions among `among` that have the theme `word` or the `pattern` asked for."""
    return [
        index
        for index in among
        if (word is None or word in facts[index].themes)
        and (pattern is None or pattern in facts[index].patterns)
    ]


def _densest(sessions: Sequence[Sequence[Record]], group: Sequence[int]) -> int | None:
    """The group's most bursty session, preferring one short enough to read on a page."""
    readable = [n for n in group if len(sessions[n]) in READABLE_STEPS] or list(group)
    return max(readable, key=lambda index: burstiness(sessions[index]), default=None)


def _strip(session: Sequence[Record], facts: SessionFacts, codebase: Codebase) -> SessionStrip:
    """The strip of one session with its label and density."""
    steps = strip_of(session, codebase)
    return SessionStrip(
        facts.session_id, facts.task_label, burstiness(session), steps[:MAX_STRIP_STEPS], len(steps)
    )
