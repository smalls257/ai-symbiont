"""Rule relevance: which stored rules apply to the work in front of the agent.

A lesson with the developer's words is relevant when a named file is its file, in its area
(a non-generic directory) or has its stem, or when the text shares MIN_SHARED_TERMS salient
terms with the rule (its words plus the lesson's file stems, stopwords out). Two is the least
that is not one coincidental word. Pure: text, paths and lessons in, ranked matches out.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from symbiont.miner.lesson_context import LessonContext, Priority
from symbiont.miner.lessons import Lesson
from symbiont.miner.trained import lesson_id

MIN_SHARED_TERMS = 2
MIN_TERM_CHARS = 4
GENERIC_DIRS = frozenset({"", ".", "src", "lib", "tests", "test", "app", "pkg"})
_STOP_TEXT = (
    "this that with from have must should would could into when then than they them their "
    "there here what which while where will your you are not never always only also each "
    "any all can use used using make made keep kept stay stays does done being been were was "
    "for and the but its our out about over under after before without within"
)
STOPWORDS = frozenset(_STOP_TEXT.split())
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_PATH = re.compile(r"[\w.\-]+(?:/[\w.\-]+)+|\b[\w\-]+\.(?:py|js|ts|tsx|go|rs|java|rb|c|h|cpp|md)\b")
_TICKED = re.compile(r"`([^`]+)`")
_RANK = {Priority.HIGH: 0, Priority.NORMAL: 1, Priority.LOW: 2}


@dataclass(frozen=True)
class RuleMatch:
    """A relevant rule: its lesson, the developer's words, and why it matched."""

    lesson: Lesson
    words: LessonContext
    why: str
    strength: int


def paths_in(text: str) -> tuple[str, ...]:
    """File paths and bare file names mentioned in `text`, in order, without repeats."""
    return tuple(dict.fromkeys(match.strip(".,:;)") for match in _PATH.findall(text)))


def lesson_files(lesson: Lesson) -> tuple[str, ...]:
    """The files a lesson is about: paths in its signature and in its recorded fix."""
    key = lesson.pain_point.signature.key
    found = [part for part in key if _looks_like_path(part)]
    for step in lesson.resolution:
        found += [part for part in _TICKED.findall(step) if _looks_like_path(part)]
    return tuple(dict.fromkeys(found))


def relevant_rules(
    text: str,
    files: Sequence[str],
    lessons: Sequence[Lesson],
    contexts: Mapping[str, LessonContext],
) -> list[RuleMatch]:
    """Rules relevant to the situation, high priority first, then the stronger match.

    Lessons the developer marked intentional, or gave no words, are never rules here.
    """
    named = tuple(dict.fromkeys([*files, *paths_in(text)]))
    terms = situation_terms(text + " " + " ".join(named))
    matches = []
    for lesson in lessons:
        words = contexts.get(lesson_id(lesson))
        if words is None or words.intentional or not words.text.strip():
            continue
        match = _match(lesson, words, named, terms)
        if match is not None:
            matches.append(match)
    return sorted(matches, key=lambda item: (_RANK[item.words.priority], -item.strength))


def rule_sentence(words: LessonContext) -> str:
    """The note: the developer's rule as prose."""
    return f"[symbiont] In this repo: {words.text.strip().rstrip(' .')}."


def situation_terms(text: str) -> frozenset[str]:
    """The salient terms of a text: words of four letters or more, stopwords out, stemmed."""
    return frozenset(
        _stem(word.lower())
        for word in _WORD.findall(text)
        if len(word) >= MIN_TERM_CHARS and word.lower() not in STOPWORDS
    )


def _match(
    lesson: Lesson, words: LessonContext, named: Sequence[str], terms: frozenset[str]
) -> RuleMatch | None:
    """How the lesson relates to the situation, or None when it does not."""
    own = lesson_files(lesson)
    related = _related_file(named, own)
    if related is not None:
        return RuleMatch(lesson, words, related, MIN_SHARED_TERMS + 1)
    wanted = situation_terms(words.text) | {_stem(_stem_of(path)) for path in own}
    shared = sorted(wanted & terms - {""})
    if len(shared) >= MIN_SHARED_TERMS:
        return RuleMatch(lesson, words, "terms: " + ", ".join(shared), len(shared))
    return None


def _related_file(named: Sequence[str], own: Sequence[str]) -> str | None:
    """`file`, `area` or None: how a named path relates to the lesson's files."""
    for path in named:
        for mine in own:
            if path == mine or _stem_of(path) == _stem_of(mine):
                return f"file: {mine}"
            if _same_area(_dir(path), _dir(mine)):
                return f"area: {_dir(mine)}"
    return None


def _same_area(first: str, second: str) -> bool:
    """Two directories are one area when equal, or one holds the other, and not generic."""
    if not first or not second or first in GENERIC_DIRS or second in GENERIC_DIRS:
        return False
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


def _dir(path: str) -> str:
    """The directory part of a path, empty for a bare file name."""
    return path.rpartition("/")[0]


def _stem_of(path: str) -> str:
    """A file's name without directory, extension and `test_` / `_test`."""
    name = path.rpartition("/")[2].rpartition(".")[0] or path.rpartition("/")[2]
    return name.removeprefix("test_").removesuffix("_test").lower()


def _stem(word: str) -> str:
    """A crude plural stem so `refunds` and `refund` are one term."""
    return word[:-1] if len(word) > MIN_TERM_CHARS + 1 and word.endswith("s") else word


def _looks_like_path(part: str) -> bool:
    """Whether a signature or fix word is a file path or file name."""
    return part != "-" and ("/" in part or bool(_PATH.fullmatch(part)))
