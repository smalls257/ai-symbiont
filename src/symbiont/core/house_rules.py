"""House rules: what a developer's own corrections mean for the repository's other lessons."""

from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.core.rule_relevance import (
    IDENTIFIER_WEIGHT,
    MAX_NOTE_CHARS,
    MIN_WEAK_SCORE,
    WORD_WEIGHT,
    Rule,
    rule_sentence,
)
from symbiont.core.rule_terms import identifiers_in, plain_terms
from symbiont.miner.lesson_context import LessonKind, Priority

# Three short house rules fit one note under MAX_NOTE_CHARS and still read as a list a person
# keeps in mind; more turns the first prompt into a wall of text the agent skims.
MAX_STANDING = 3
# The bar a weak match needs to fire a rule is also the bar for two lessons being one subject:
# fewer shared words would retire a reflection over a single common word.
SAME_SUBJECT_SCORE = MIN_WEAK_SCORE
EXCERPT_CHARS = 120
LEAD = "[symbiont] House rules you gave in this repo: "
_PRIORITY_FIRST = {Priority.HIGH: 0, Priority.NORMAL: 1, Priority.LOW: 2}


@dataclass(frozen=True)
class Supersession:
    """A written lesson put aside because a later correction of the developer's covers it."""

    older: str
    newer: str
    older_excerpt: str
    newer_excerpt: str


def retired_by_corrections(rules: Sequence[Rule]) -> dict[str, Supersession]:
    """Older written rule id -> the later correction on its subject; `rules` are oldest first.

    Write order stands in for "earlier in the session": reflections carry no session id.
    """
    retired: dict[str, Supersession] = {}
    for index, older in enumerate(rules):
        if older.kind is None or older.kind is LessonKind.CORRECTION:
            continue
        later = (rule for rule in rules[index + 1 :] if rule.kind is LessonKind.CORRECTION)
        newer = next((rule for rule in later if _same_subject(older, rule)), None)
        if newer is not None:
            retired[older.ident] = _supersession(older, newer)
    return retired


def standing_corrections(rules: Sequence[Rule], leave_out: frozenset[str]) -> list[Rule]:
    """The developer's corrections to say as house rules: high priority first, then newest.

    `leave_out` holds ids that must not be said (retired, or already speaking for this work).
    """
    corrections = [
        rule for rule in rules if rule.kind is LessonKind.CORRECTION and rule.ident not in leave_out
    ]
    newest_first = corrections[::-1]
    ranked = sorted(newest_first, key=lambda rule: _PRIORITY_FIRST[rule.words.priority])
    return ranked[:MAX_STANDING]


def standing_sentence(corrections: Sequence[Rule]) -> str:
    """One note with as many whole rules as fit MAX_NOTE_CHARS; a lone long rule is cut as usual."""
    if not corrections:
        raise ValueError("no corrections to say")
    kept: list[str] = []
    for rule in corrections:
        text = rule.words.text.strip().rstrip(" .") + "."
        if len(LEAD) + len(" ".join([*kept, text])) > MAX_NOTE_CHARS:
            break
        kept.append(text)
    if not kept:
        return rule_sentence(corrections[0].words)
    return LEAD + " ".join(kept)


def _same_subject(older: Rule, newer: Rule) -> bool:
    """Whether two rules share enough distinctive words to be about one thing."""
    first, second = _subject_text(older), _subject_text(newer)
    codes = identifiers_in(first) & identifiers_in(second)
    words = (plain_terms(first) & plain_terms(second)) - codes
    score = IDENTIFIER_WEIGHT * len(codes) + WORD_WEIGHT * len(words)
    return score >= SAME_SUBJECT_SCORE


def _subject_text(rule: Rule) -> str:
    """The rule's words plus the terms its writer tagged."""
    return rule.words.text + " " + " ".join(rule.words.applies.terms)


def _supersession(older: Rule, newer: Rule) -> Supersession:
    """The record of one rule put aside, with short excerpts for the event log."""
    return Supersession(
        older.ident,
        newer.ident,
        older.words.text.strip()[:EXCERPT_CHARS],
        newer.words.text.strip()[:EXCERPT_CHARS],
    )
