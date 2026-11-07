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
from symbiont.miner.lesson_context import (
    AuthoredLesson,
    LessonContext,
    LessonKind,
    Priority,
    Severity,
)
from symbiont.miner.lessons import Lesson
from symbiont.miner.trained import lesson_id

STRONG_WEIGHT = 3
# The lesson's own file outranks its module: a sibling file is related, not the same place.
FILE_WEIGHT = STRONG_WEIGHT + 1
AREA_WEIGHT = STRONG_WEIGHT
# Two notes per event: one slot let the lesson about the file being edited starve a second,
# equally relevant lesson (live sympy run). More than two turns notes into noise the agent skips.
MAX_RULE_NOTES = 2
# Two notes share the agent's context, so each stays a few sentences. 320 cut a real 348-char
# lesson mid-clause (live sympy preflight) and dropped its last instruction; 600 fits typical
# lessons, and anything longer is cut at a sentence or clause boundary, never mid-sentence.
MAX_NOTE_CHARS = 600
_BOUNDARY = re.compile(r"[.!?;:]\s|,\s")
IDENTIFIER_WEIGHT = 2
WORD_WEIGHT = 1
MIN_WEAK_SCORE = 3
GENERIC_DIRS = frozenset({"", ".", "src", "lib", "tests", "test", "app", "pkg"})
_ANY_WORD = re.compile(r"[A-Za-z0-9]+")
_PATH = re.compile(r"[\w.\-]+(?:/[\w.\-]+)+|\b[\w\-]+\.(?:py|js|ts|tsx|go|rs|java|rb|c|h|cpp|md)\b")
_RANK = {Priority.HIGH: 0, Priority.NORMAL: 1, Priority.LOW: 2}


@dataclass(frozen=True)
class Rule:
    """A stored rule: the words to say, the files it is about, and the lesson it came from."""

    ident: str
    words: LessonContext
    files: tuple[str, ...]
    lesson: Lesson | None = None
    # Set for written lessons only: a user correction is told apart from a model's reflection.
    kind: LessonKind | None = None
    # The pull request a written lesson was learned from; a ruling there is the team's word.
    source_url: str = ""
    # The reviewer's own words behind a PR lesson, and their role; see miner.review_quote.
    quote: str = ""
    quote_role: str = ""

    @property
    def is_pr_ruling(self) -> bool:
        """Whether a PR review taught this lesson, whatever kind it was saved as."""
        return bool(self.source_url)


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
    found += [path for path in lesson.files if _looks_like_path(path)]
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
        words = _written_words(item, own)
        rules.append(
            Rule(
                item.ident,
                words,
                item.files,
                kind=item.kind,
                source_url=item.source_url,
                quote=item.quote,
                quote_role=item.quote_role,
            )
        )
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


def file_scoped_rules(files: Sequence[str], rules: Sequence[Rule]) -> list[RuleMatch]:
    """Rules whose own file was just touched, relative or absolute, by whole trailing path parts."""
    matches = []
    for rule in rules:
        mine = next((own for own in rule.files if _is_one_of(own, files)), None)
        if mine is not None:
            matches.append(RuleMatch(rule, f"file: {mine} (+{FILE_WEIGHT})", FILE_WEIGHT))
    return sorted(matches, key=lambda item: _RANK[item.rule.words.priority])


def _is_one_of(own: str, touched: Sequence[str]) -> bool:
    """Whether `own` is the same file as one of `touched`, by whole trailing path parts."""
    mine = _slashed(own)
    return any(_ends_with_parts(_slashed(path), mine) for path in touched)


def _slashed(path: str) -> str:
    """The path with forward slashes and no leading `./`."""
    return path.replace("\\", "/").removeprefix("./")


def _ends_with_parts(path: str, mine: str) -> bool:
    """Whether one path is the other or ends with it after a `/`: a short form of the same file."""
    longer, shorter = (path, mine) if len(path) >= len(mine) else (mine, path)
    return bool(shorter) and (longer == shorter or longer.endswith("/" + shorter))


def why_none(rules: Sequence[Rule]) -> str:
    """Why no rule was relevant: no rule has files to compare, or the files are unrelated."""
    if not any(rule.files for rule in rules):
        return "no files recorded on the rule's lesson; only shared terms could match"
    return "the rule's files and words are unrelated to this work"


def rule_sentence(words: LessonContext) -> str:
    """The note: the rule as prose, cut at a sentence or clause boundary past MAX_NOTE_CHARS."""
    text = words.text.strip().rstrip(" .")
    if len(text) > MAX_NOTE_CHARS:
        return f"[symbiont] In this repo: {_cut_at_boundary(text)}"
    return f"[symbiont] In this repo: {text}."


def _cut_at_boundary(text: str) -> str:
    """The longest whole-sentence (else clause, else word) prefix within the cap, then '...'."""
    head = text[: MAX_NOTE_CHARS + 1]
    for strong in (True, False):
        ends = [
            m.start() + 1
            for m in _BOUNDARY.finditer(head)
            if (m.group()[0] != ",") == strong and m.start() + 1 <= MAX_NOTE_CHARS
        ]
        if ends and ends[-1] >= MAX_NOTE_CHARS // 3:
            return head[: ends[-1]].rstrip(" ,;:") + " ..."
    return head[:MAX_NOTE_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:") + " ..."


def areas_of_files(files: Sequence[str]) -> tuple[str, ...]:
    """The module directories of the files, without repeats; generic directories are left out.

    A lesson about one file is about its module, so work on a sibling file reaches it.
    """
    found = (_dir(path.lstrip("./")) for path in files)
    return tuple(dict.fromkeys(area for area in found if area and area not in GENERIC_DIRS))


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
        found.append(related)
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


def _related_file(named: Sequence[str], own: Sequence[str]) -> _Signal | None:
    """The lesson's own file (strongest), else a sibling in its module directory, else None."""
    for path in named:
        for mine in own:
            if path == mine or _stem_of(path) == _stem_of(mine):
                return _Signal(f"file: {mine}", FILE_WEIGHT)
    for path in named:
        for mine in own:
            if _same_area(_dir(path), _dir(mine)):
                return _Signal(f"area: {_dir(mine)}", AREA_WEIGHT)
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
