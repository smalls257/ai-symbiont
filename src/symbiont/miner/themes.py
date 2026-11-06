"""Themes: what a session was about, in the codebase's own words.

"Where does the agent struggle" needs a "what was it doing".
A theme is a word from the task that the codebase itself uses (a file stem or a part of a
def/class name seen in its edits), so issue-template words ("official", "reference") and the
developer's chatter never become themes. Pure: records in, words out.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from symbiont.miner.changes import applied_edit
from symbiont.miner.codebase import repo_relative
from symbiont.miner.generic_words import GENERIC_WORDS, STOPWORDS
from symbiont.miner.secrets import scrub
from symbiont.records.schema import Kind, Record
from symbiont.records.session_tags import BRANCH_PREFIX, TITLE_PREFIX, tag_values

# Sightings of a name part in codebase edits to call it the codebase's own word: 5 on large
# histories (tuned once on sqlglot traces), scaled down on small ones; Step 6 re-measures it.
VOCABULARY_MIN_SEEN = 5
VOCABULARY_FLOOR = 2
SESSIONS_PER_SIGHTING = 10  # one sighting per this many sessions, between the floor and 5
MIN_WORD_CHARS = 4
TASK_TEXT_CHARS = 1500
LABEL_CHARS = 90
_ISSUE = re.compile(r"<issue_description>(.*?)</issue_description>", re.S)
_FENCE = re.compile(r"```.*?```", re.S)
_WORD = re.compile(rf"[A-Za-z]{{{MIN_WORD_CHARS},}}")
_DEFINED = re.compile(r"(?:def|class)\s+(\w+)")
_CAMEL_PART = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")
_TEST_DIRS = frozenset({"tests", "test"})


@dataclass(frozen=True)
class Codebase:
    """The files that are the project itself, decided by the one repo-relative rule."""

    repo_names: frozenset[str]

    def relative(self, path: str) -> str | None:
        """`path` relative to the repo root, or None when it lies outside the codebase."""
        return repo_relative(path, self.repo_names)

    def contains(self, path: str) -> bool:
        """True when `path` is inside the codebase."""
        return self.relative(path) is not None


def is_test_path(relative: str) -> bool:
    """A repo-relative path that is a test: below a tests directory or named like a test."""
    path = PurePosixPath(relative)
    named = path.stem.startswith("test_") or path.stem.endswith("_test")
    return named or bool(_TEST_DIRS & set(path.parts[:-1]))


def codebase_vocabulary(sessions: Sequence[Sequence[Record]], codebase: Codebase) -> frozenset[str]:
    """File stems and parts of def/class names in codebase edits, each seen often enough."""
    seen: Counter[str] = Counter()
    for session in sessions:
        for record in session:
            seen.update(_words_edited(record, codebase))
    needed = vocabulary_min_seen(len(sessions))
    return frozenset(word for word, count in seen.items() if count >= needed)


def vocabulary_min_seen(session_count: int) -> int:
    """Sightings a name part needs: 5 on a large history, down to 2 on a very small one."""
    scaled = session_count // SESSIONS_PER_SIGHTING
    return max(VOCABULARY_FLOOR, min(VOCABULARY_MIN_SEEN, scaled))


def _words_edited(record: Record, codebase: Codebase) -> list[str]:
    """The usable name parts one applied codebase edit shows."""
    if not applied_edit(record) or not record.files:
        return []
    relative = codebase.relative(record.files[0])
    if relative is None or is_test_path(relative):
        return []
    names = [PurePosixPath(relative).stem, *_DEFINED.findall(record.diff or "")]
    return [part for name in names for part in _usable_parts(name)]


def _usable_parts(name: str) -> Iterable[str]:
    """Lowercase parts of a snake_case or CamelCase name, minus generic words."""
    for piece in name.split("_"):
        for part in _CAMEL_PART.findall(piece):
            word = part.lower()
            if len(word) >= MIN_WORD_CHARS and word not in STOPWORDS | GENERIC_WORDS:
                yield word


def task_text(session: Sequence[Record]) -> str:
    """What the session was asked.

    The first user turn (the issue body when present), plus the title Claude Code gave the
    session and the git branch it ran on.
    """
    first = next((r.raw for r in session if r.kind == Kind.USER_TURN), "")
    issue = _ISSUE.search(first)
    asked = (issue.group(1) if issue else first)[:TASK_TEXT_CHARS]
    tags = tuple(tag for record in session for tag in record.tags)
    named = tag_values(tags, TITLE_PREFIX)[:1] + tag_values(tags, BRANCH_PREFIX)[:1]
    return "\n".join([asked, *named])


def themes_of(text: str, vocabulary: frozenset[str]) -> frozenset[str]:
    """The words of `text` (pasted code left out) that the codebase's own vocabulary has."""
    prose = _FENCE.sub(" ", text)
    return frozenset(word.lower() for word in _WORD.findall(prose)) & vocabulary


def task_label(session: Sequence[Record]) -> str:
    """A short, scrubbed line saying what the session was for: its title, else the first line."""
    tags = tuple(tag for record in session for tag in record.tags)
    title = tag_values(tags, TITLE_PREFIX)[:1]
    lines = (line.strip() for line in task_text(session).splitlines())
    line = title[0] if title else next((entry for entry in lines if entry), "")
    return scrub(line)[:LABEL_CHARS]
