"""Rule relevance: which stored rules apply to the work in front of the agent.

A lesson with the developer's words is relevant when a named file is its file, in its area
(a non-generic directory) or has its stem, or when the text shares MIN_SHARED_TERMS salient
terms with the rule (its words plus the lesson's file stems, stopwords out). Two is the least
that is not one coincidental word. Pure: text, paths and lessons in, ranked matches out.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from symbiont.miner.lesson_context import AuthoredLesson, LessonContext, Priority, Severity
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
_CAPS = re.compile(r"\b[A-Z][A-Z0-9]{1,4}\b")
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
    terms = situation_terms(text + " " + " ".join(named))
    everything = frozenset(
        _stem(word.lower()) for word in _ANY_WORD.findall(text + " " + " ".join(named))
    )
    situation = _Situation(named, terms, everything, focus)
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
    """The salient terms of a text: words of four letters or more and short all-caps codes."""
    long = {
        _stem(word.lower())
        for word in _WORD.findall(text)
        if len(word) >= MIN_TERM_CHARS and word.lower() not in STOPWORDS
    }
    return frozenset(long | {code.lower() for code in _CAPS.findall(text)})


@dataclass(frozen=True)
class _Situation:
    """What the agent is working on, as the matcher sees it."""

    named: Sequence[str]
    terms: frozenset[str]
    everything: frozenset[str]
    focus: frozenset[str]


def _match(rule: Rule, situation: _Situation) -> RuleMatch | None:
    """How the rule relates to the situation, or None when it does not."""
    bonus = len(situation.focus & situation_terms(rule.words.text + " " + " ".join(rule.files)))
    tags = rule.words.applies
    related = _related_file(situation.named, rule.files) or _tagged_area(
        situation.named, tags.areas
    )
    if related is not None:
        return RuleMatch(rule, related, MIN_SHARED_TERMS + 1 + bonus)
    wanted = situation_terms(rule.words.text) | {_stem(_stem_of(path)) for path in rule.files}
    shared = set(wanted & situation.terms - {""}) | _tagged_terms(tags.terms, situation.everything)
    if len(shared) >= MIN_SHARED_TERMS:
        return RuleMatch(rule, "terms: " + ", ".join(sorted(shared)), len(shared) + bonus)
    return None


def _tagged_terms(tags: Sequence[str], everything: frozenset[str]) -> set[str]:
    """The writer's applicability terms present in the situation (a phrase needs all its words)."""
    hit = set()
    for tag in tags:
        parts = [_stem(word) for word in _ANY_WORD.findall(tag.lower())]
        if parts and all(part in everything for part in parts):
            hit.add(tag.lower())
    return hit


def _tagged_area(named: Sequence[str], areas: Sequence[str]) -> str | None:
    """`area tag: <prefix>` when a named path lies under one of the writer's path prefixes."""
    for path in named:
        for area in areas:
            prefix = area.strip().lstrip("./")
            if prefix and (path.lstrip("./").startswith(prefix) or f"/{prefix}" in path):
                return f"area tag: {area}"
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
