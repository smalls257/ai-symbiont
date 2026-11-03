"""Rule relevance: which stored rules apply to the work in front of the agent.

Fires on one strong signal (STRONG_WEIGHT: the lesson's own file or area, or a hit on the
writer's term or area tags) or on weak shared words worth MIN_WEAK_SCORE; `why` lists each
signal with its weight. Pure: text, paths and lessons in, ranked matches out.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from symbiont.core.rule_terms import (
    common_terms,
    identifiers_in,
    plain_terms,
    salient_terms,
    stem,
)
from symbiont.miner.lesson_context import AuthoredLesson, LessonContext, Priority, Severity
from symbiont.miner.lessons import Lesson
from symbiont.miner.trained import lesson_id

STRONG_WEIGHT = 3
IDENTIFIER_WEIGHT = 2
WORD_WEIGHT = 1
MIN_WEAK_SCORE = 3
GENERIC_DIRS = frozenset({"", ".", "src", "lib", "tests", "test", "app", "pkg"})
_ANY_WORD = re.compile(r"[A-Za-z0-9]+")
_PATH = re.compile(r"[\w.\-]+(?:/[\w.\-]+)+|\b[\w\-]+\.(?:py|js|ts|tsx|go|rs|java|rb|c|h|cpp|md)\b")
_TICKED = re.compile(r"`([^`]+)`")
_RANK = {Priority.HIGH: 0, Priority.NORMAL: 1, Priority.LOW: 2}


@dataclass(frozen=True)
class Rule:
    """A stored rule: the words to say, the files it is about, and the lesson it came from."""

    ident: str
    words: LessonContext
    files: tuple[str, ...]
    lesson: Lesson | None = None


@dataclass(frozen=True)
class RuleMatch:
    """A relevant rule and why it matched."""

    rule: Rule
    why: str
    strength: int


_PRIORITY_OF = {
    Severity.HIGH: Priority.HIGH,
    Severity.MEDIUM: Priority.NORMAL,
    Severity.LOW: Priority.LOW,
}


def paths_in(text: str) -> tuple[str, ...]:
    """File paths and bare file names mentioned in `text`, in order, without repeats."""
    return tuple(dict.fromkeys(match.strip(".,:;)") for match in _PATH.findall(text)))


def lesson_files(lesson: Lesson) -> tuple[str, ...]:
    """The files a lesson is about: signature, fix, and the edits between failure and pass."""
    found = [part for part in lesson.pain_point.signature.key if _looks_like_path(part)]
    for step in (*lesson.resolution, *lesson.changed_alongside):
        found += [part for part in _TICKED.findall(step) if _looks_like_path(part)]
    return tuple(dict.fromkeys(found))


def rules_of(
    lessons: Sequence[Lesson],
    contexts: Mapping[str, LessonContext],
    authored: Sequence[AuthoredLesson] = (),
) -> list[Rule]:
    """The rule-bearing lessons (the developer's words, not intentional) and the written ones."""
    rules = []
    for lesson in lessons:
        words = contexts.get(lesson_id(lesson))
        if words is not None and not words.intentional and words.text.strip():
            rules.append(Rule(lesson_id(lesson), words, lesson_files(lesson), lesson))
    for item in authored:
        own = contexts.get(item.ident)
        if own is not None and own.intentional:
            continue
        rules.append(Rule(item.ident, _written_words(item, own), item.files))
    return rules


def _written_words(item: AuthoredLesson, own: LessonContext | None) -> LessonContext:
    """A written lesson as a rule: its text, then the developer's words, priority and tags."""
    if own is None:
        return LessonContext(item.text, priority=_PRIORITY_OF[item.severity], applies=item.applies)
    text = ". ".join(part for part in (item.text.strip(" ."), own.text.strip(" .")) if part)
    applies = own.applies if own.applies.terms or own.applies.areas else item.applies
    return LessonContext(text, priority=own.priority, applies=applies)


def relevant_rules(
    text: str, files: Sequence[str], rules: Sequence[Rule], focus: frozenset[str] = frozenset()
) -> list[RuleMatch]:
    """Rules relevant to the situation: high priority first, then the stronger match.

    Terms the developer asked symbiont to pay attention to (`focus`) strengthen a match.
    """
    named = tuple(dict.fromkeys([*files, *paths_in(text)]))
    whole = text + " " + " ".join(named)
    situation = _Situation(
        named=named,
        plain=plain_terms(whole),
        identifiers=identifiers_in(whole),
        everything=frozenset(stem(word.lower()) for word in _ANY_WORD.findall(whole)),
        focus=focus,
        common=common_terms(rule.words.text for rule in rules),
    )
    matches = [match for rule in rules if (match := _match(rule, situation)) is not None]
    return sorted(matches, key=lambda item: (_RANK[item.rule.words.priority], -item.strength))


def why_none(rules: Sequence[Rule]) -> str:
    """Why no rule was relevant: no rule has files to compare, or the files are unrelated."""
    if not any(rule.files for rule in rules):
        return "no files recorded on the rule's lesson; only shared terms could match"
    return "the rule's files and words are unrelated to this work"


def rule_sentence(words: LessonContext) -> str:
    """The note: the developer's rule as prose."""
    return f"[symbiont] In this repo: {words.text.strip().rstrip(' .')}."


def situation_terms(text: str) -> frozenset[str]:
    """The salient terms of a text: distinctive words and identifier-like tokens."""
    return salient_terms(text)


@dataclass(frozen=True)
class _Situation:
    """What the agent is working on, as the matcher sees it."""

    named: Sequence[str]
    plain: frozenset[str]
    identifiers: frozenset[str]
    everything: frozenset[str]
    focus: frozenset[str]
    common: frozenset[str]


@dataclass(frozen=True)
class _Signal:
    """One reason a rule relates to the work, and how much it counts."""

    label: str
    weight: int

    @property
    def strong(self) -> bool:
        """Whether this signal alone is enough to fire the rule."""
        return self.weight >= STRONG_WEIGHT

    def shown(self) -> str:
        """`label (+weight)`, the form the event log carries."""
        return f"{self.label} (+{self.weight})"


def _match(rule: Rule, situation: _Situation) -> RuleMatch | None:
    """How the rule relates to the situation, or None when it does not."""
    signals = [*_strong_signals(rule, situation), *_weak_signals(rule, situation)]
    score = sum(signal.weight for signal in signals)
    if not any(signal.strong for signal in signals) and score < MIN_WEAK_SCORE:
        return None
    bonus = len(situation.focus & salient_terms(rule.words.text + " " + " ".join(rule.files)))
    why = "; ".join(signal.shown() for signal in signals)
    return RuleMatch(rule, why, score + bonus)


def _strong_signals(rule: Rule, situation: _Situation) -> list[_Signal]:
    """The lesson's own file or area, and the writer's tags, hit by the work."""
    tags = rule.words.applies
    found = []
    related = _related_file(situation.named, rule.files)
    if related is not None:
        found.append(_Signal(related, STRONG_WEIGHT))
    area = _tagged_area(situation.named, tags.areas, situation.everything)
    if area is not None:
        found.append(_Signal(area, STRONG_WEIGHT))
    hits = sorted(_tagged_terms(tags.terms, situation.everything))
    found.extend(_Signal(f"tag: {tag}", STRONG_WEIGHT) for tag in hits)
    return found


def _weak_signals(rule: Rule, situation: _Situation) -> list[_Signal]:
    """Identifiers and distinctive words the rule text shares with the work."""
    own = rule.words.text + " " + " ".join(_stem_of(path) for path in rule.files)
    tagged = {tag.lower() for tag in rule.words.applies.terms}
    codes = (identifiers_in(own) & situation.identifiers) - tagged
    words = (plain_terms(own, situation.common) & situation.plain) - codes - tagged
    found = []
    if codes:
        found.append(
            _Signal("identifiers: " + ", ".join(sorted(codes)), IDENTIFIER_WEIGHT * len(codes))
        )
    if words:
        found.append(_Signal("words: " + ", ".join(sorted(words)), WORD_WEIGHT * len(words)))
    return found


def _tagged_terms(tags: Sequence[str], everything: frozenset[str]) -> set[str]:
    """The writer's applicability terms present in the situation (a phrase needs all its words)."""
    hit = set()
    for tag in tags:
        parts = [stem(word) for word in _ANY_WORD.findall(tag.lower())]
        if parts and all(part in everything for part in parts):
            hit.add(tag.lower())
    return hit


def _tagged_area(
    named: Sequence[str], areas: Sequence[str], everything: frozenset[str]
) -> str | None:
    """`area tag: <area>` when the work is in a tagged path prefix or names a tagged area.

    A descriptive area such as `sqlite schema editor` matches when the work mentions every word.
    """
    for area in areas:
        if _under_prefix(named, area) or _all_mentioned(area, everything):
            return f"area tag: {area}"
    return None


def _under_prefix(named: Sequence[str], area: str) -> bool:
    """Whether a named path lies under the area read as a path prefix."""
    prefix = area.strip().lstrip("./")
    return bool(prefix) and any(
        path.lstrip("./").startswith(prefix) or f"/{prefix}" in path for path in named
    )


def _all_mentioned(area: str, everything: frozenset[str]) -> bool:
    """Whether the work mentions every word of the area."""
    parts = [stem(word) for word in _ANY_WORD.findall(area.lower())]
    return bool(parts) and all(part in everything for part in parts)


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


def _looks_like_path(part: str) -> bool:
    """Whether a signature or fix word is a file path or file name."""
    return part != "-" and ("/" in part or bool(_PATH.fullmatch(part)))
