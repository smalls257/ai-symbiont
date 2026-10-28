"""Deterministic scoring for the lesson-capacity probe: recall of key details, invented details.

A fuzzy or model-judged match would let a vague answer ("check your imports") count as recall.
A hit needs the exact error class or every token the fix added; an answer naming an error class,
file or flag that no lesson holds counts as invented, so confabulated recall cannot look good.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from lessons import ERROR_CLASS, Lesson
from questions import Asks

_FILE = re.compile(r"[\w./-]*\w\.(?:py|cfg|toml|ini|txt|json|ya?ml|rst|md|sh)\b")
_FLAG = re.compile(r"(?<![\w-])--?[A-Za-z][\w-]*")
_QUOTES = re.compile(r"[`'\"]")


@dataclass(frozen=True)
class Verdict:
    """How one answer scored."""

    hit: bool
    invented: tuple[str, ...]


def details_in(text: str) -> set[str]:
    """Error classes, file names and flags an answer or lesson names."""
    clean = _QUOTES.sub(" ", text)
    return {*ERROR_CLASS.findall(clean), *_FILE.findall(clean), *_FLAG.findall(clean)}


def vocabulary(lessons: Iterable[Lesson]) -> frozenset[str]:
    """Every detail any lesson names: an answer may say these without inventing."""
    return frozenset(detail for lesson in lessons for detail in details_in(lesson.text()))


def recalled(answer: str, lesson: Lesson, asks: Asks) -> bool:
    """True when the answer carries the key details `asks` names, verbatim."""
    flat = " ".join(_QUOTES.sub(" ", answer).split())
    has_error = lesson.error_class in flat
    has_fix = all(" ".join(_QUOTES.sub(" ", token).split()) in flat for token in lesson.added)
    if asks == Asks.FIX:
        return has_fix
    if asks == Asks.ERROR:
        return has_error
    return has_fix and has_error


def score(answer: str, lesson: Lesson, asks: Asks, known: frozenset[str]) -> Verdict:
    """Recall of `lesson` plus the details the answer names that no lesson holds."""
    invented = tuple(sorted(details_in(answer) - known))
    return Verdict(hit=recalled(answer, lesson, asks), invented=invented)
