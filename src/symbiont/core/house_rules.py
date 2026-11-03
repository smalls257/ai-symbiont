"""House rules: what a developer's own corrections mean for the repository's other lessons."""

from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.core.quoted_rule import has_quote, quoted_house_rule, rule_note
from symbiont.core.rule_relevance import (
    IDENTIFIER_WEIGHT,
    MAX_NOTE_CHARS,
    MIN_WEAK_SCORE,
    WORD_WEIGHT,
    Rule,
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
LEAD = "[symbiont] House rules for this repo (from your corrections and PR reviews): "
_PRIORITY_FIRST = {Priority.HIGH: 0, Priority.NORMAL: 1, Priority.LOW: 2}
# Your own correction outranks a PR ruling: it is the developer's word for their work, while a
# ruling is one reviewer's word on one pull request (and may be file-scoped, which the file
# trigger delivers when the work reaches that file).
_OWN_WORD, _PR_RULING = 0, 1


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
        later = (rule for rule in rules[index + 1 :] if _may_retire(rule, older))
        newer = next((rule for rule in later if _same_subject(older, rule)), None)
        if newer is not None:
            retired[older.ident] = _supersession(older, newer)
    return retired


def _may_retire(newer: Rule, older: Rule) -> bool:
    """Whether `newer` can put `older` aside: two PR rulings never retire each other.

    The D3 store lost a DuckDB copy ruling to an unrelated DuckDB null-guard ruling.
    """
    if newer.kind is not LessonKind.CORRECTION:
        return False
    return not (older.is_pr_ruling and newer.is_pr_ruling)


def standing_corrections(rules: Sequence[Rule], leave_out: frozenset[str]) -> list[Rule]:
    """House rules: own corrections, then PR rulings, by priority then newest; not `leave_out`."""
    corrections = [rule for rule in rules if _is_correction(rule) and rule.ident not in leave_out]
    newest_first = corrections[::-1]
    ranked = sorted(newest_first, key=_standing_rank)
    return ranked[:MAX_STANDING]


def _is_correction(rule: Rule) -> bool:
    """A developer's correction, or a review ruling saved as a rule.

    A PR-linked mistake or friction (often from CI) says what went wrong, not what the team decided.
    """
    return rule.kind is LessonKind.CORRECTION or (
        rule.kind is LessonKind.RULE and rule.is_pr_ruling
    )


def _standing_rank(rule: Rule) -> tuple[int, int]:
    """Own word before PR ruling, then priority; sorted is stable, so newest stays first."""
    group = _PR_RULING if rule.is_pr_ruling else _OWN_WORD
    return group, _PRIORITY_FIRST[rule.words.priority]


def standing_sentence(corrections: Sequence[Rule]) -> str:
    """One note with as many whole rules as fit MAX_NOTE_CHARS; a lone long rule is cut as usual.

    A rule with the reviewer's words says them first and whole (see core.quoted_rule).
    """
    if not corrections:
        raise ValueError("no corrections to say")
    kept: list[str] = []
    for rule in corrections:
        used = len(LEAD) + len(" ".join(kept)) + (1 if kept else 0)
        entry = _entry(rule, MAX_NOTE_CHARS - used)
        if entry is None:
            break
        kept.append(entry)
    if not kept:
        return rule_note(corrections[0])
    return LEAD + " ".join(kept)


def _entry(rule: Rule, room: int) -> str | None:
    """The rule as one house-rules entry within `room` characters, or None if it does not fit."""
    if has_quote(rule):
        return quoted_house_rule(rule, room)
    text = rule.words.text.strip().rstrip(" .") + "."
    return text if len(text) <= room else None


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
