"""A PR lesson that carries the reviewer's exact words says them first, whole.

A paraphrase narrower than the ruling (a general "don't copy in generator code" saved as "don't
copy properties in a DuckDB sub-method") did not stop the violation in 4 of 4 runs. The quote is
never cut to make room: over MAX_NOTE_CHARS, the lesson's own sentence gives way.
Pure: a rule in, a sentence out.
"""

import re

from symbiont.core.rule_relevance import MAX_NOTE_CHARS, Rule, rule_sentence
from symbiont.miner.review_quote import ReviewerRole, pull_number

NOTE_LEAD = "[symbiont] In this repo, "
_SENTENCE = re.compile(r".+?(?:[.!?](?=\s|$)|$)", re.DOTALL)
_DEFAULT_ROLE = ReviewerRole.REVIEWER


def has_quote(rule: Rule) -> bool:
    """Whether the rule can be said with the reviewer's words: a quote and a PR to cite."""
    return bool(rule.quote) and pull_number(rule.source_url) is not None


def rule_note(rule: Rule) -> str:
    """The note for a relevant rule: the reviewer's words first when it has them, else the rule.

    `[symbiont] In this repo, a maintainer said on PR #N: "<quote>" (<lesson>).`
    """
    if not has_quote(rule):
        return rule_sentence(rule.words)
    return NOTE_LEAD + _said(rule)


def quoted_house_rule(rule: Rule, room: int) -> str | None:
    """The rule as one house-rules entry within `room` characters, or None if it won't fit."""
    entry = _said(rule, room)
    return entry[0].upper() + entry[1:] if len(entry) <= room else None


def _said(rule: Rule, room: int = MAX_NOTE_CHARS - len(NOTE_LEAD)) -> str:
    """'a maintainer said on PR #N: "quote"' plus as many whole lesson sentences as fit."""
    role = rule.quote_role or _DEFAULT_ROLE
    said = f'a {role} said on PR #{pull_number(rule.source_url)}: "{rule.quote}"'
    sentences = [s for s in _SENTENCE.findall(rule.words.text.strip().rstrip(" .")) if s.strip()]
    kept = ""
    for sentence in sentences:
        candidate = f"{kept} {sentence.strip()}".strip()
        if len(said) + len(f" ({candidate}).") > room:
            break
        kept = candidate
    return f"{said} ({kept})." if kept else f"{said}."
