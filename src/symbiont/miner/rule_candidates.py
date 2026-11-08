"""Standing rules a developer states to the agent: the turns worth offering as a rule.

A turn qualifies by directive wording or because `find_corrections` flags it. Text is scrubbed,
one line and capped before it is kept. Pure: records in, candidates out.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from symbiont.miner.credential_patterns import scrub
from symbiont.miner.empty_correction import is_bare_acknowledgment
from symbiont.miner.rule_terms import salient_terms
from symbiont.miner.session_digest import typed_message
from symbiont.miner.signals.correction import find_corrections
from symbiont.records.schema import Record

MAX_TEXT_CHARS = 240
RULE_WORDS = "rule_words"
CORRECTION = "correction"
_ITEM = r"[\w./-]+"

# Directive language, each alternative one way developers state a standing rule: always, never,
# don't / do not, stop, from now on, make sure, must, should(n't) be, instead of, prefer, avoid,
# no more, every time, remember to, we use, "use X not Y" and "X, not Y".
DIRECTIVE = re.compile(
    r"\b(?:always|never|don'?t|do not|stop|from now on|make sure|must|should(?:n'?t)? be"
    r"|instead of|prefer|avoid|no more|every time|remember to|we use)\b"
    rf"|\buse {_ITEM},? not {_ITEM}|{_ITEM}, not {_ITEM}",
    re.IGNORECASE,
)
# Phrases that contain a directive word without stating a rule; blanked before the directive
# test so "never mind, always use pnpm" still counts.
NOT_A_RULE = re.compile(
    r"\bnever mind\b|\bi (?:do not|don'?t) (?:know|think)\b|\bnot sure\b"
    r"|\bstop (?:the|that|this|it)(?: \w+)? (?:run|job|process|command)\b|\bstop it\b",
    re.IGNORECASE,
)
# Words that say "rule" and nothing about its subject; kept out of the terms that group rules.
DIRECTIVE_WORDS = frozenset(
    {"prefer", "avoid", "instead", "remember", "stop", "make", "sure", "every", "time", "must"}
)
TOOLS = frozenset(
    [
        "pnpm",
        "npm",
        "yarn",
        "bun",
        "node",
        "git",
        "uv",
        "pip",
        "pipx",
        "poetry",
        "pytest",
        "ruff",
        "mypy",
        "make",
        "docker",
        "cargo",
        "go",
        "gh",
        "brew",
        "curl",
        "sed",
        "grep",
        "rg",
    ]
)
_FILE = re.compile(rf"{_ITEM}\.[A-Za-z]{{2,5}}\b|[\w.-]+/{_ITEM}")
_WORD = re.compile(r"[\w'-]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n")


@dataclass(frozen=True)
class RuleCandidate:
    """A user turn that may state a standing rule; `source` is "rule_words" or "correction"."""

    session_id: str
    step: int
    text: str
    terms: frozenset[str]
    source: str


def find_rule_candidates(session: Sequence[Record]) -> list[RuleCandidate]:
    """The typed user turns of one session that read as a rule or were a correction."""
    corrected = {pain.step for pain in find_corrections(session)}
    found = []
    for record in session:
        typed = typed_message(record)
        if typed is None or is_bare_acknowledgment(typed):
            continue
        if _states_rule(typed):
            source = RULE_WORDS
        elif record.step in corrected:
            source = CORRECTION
        else:
            continue
        text = " ".join(scrub(typed).split())[:MAX_TEXT_CHARS]
        found.append(RuleCandidate(record.session_id, record.step, text, rule_terms(text), source))
    return found


def rule_terms(text: str) -> frozenset[str]:
    """Distinctive words, identifiers, file names and tool names of a rule."""
    named = {word.lower() for word in _WORD.findall(text)} & TOOLS
    files = {match.lower() for match in _FILE.findall(text)}
    return (salient_terms(text) | named | files) - DIRECTIVE_WORDS


def _states_rule(text: str) -> bool:
    """Directive wording that is not a question (unless an earlier clause is imperative)."""
    blanked = NOT_A_RULE.sub(" ", text)
    if not text.rstrip().endswith("?"):
        return bool(DIRECTIVE.search(blanked))
    earlier = _SENTENCE_END.split(blanked.rstrip())[:-1]
    return any(DIRECTIVE.search(sentence) for sentence in earlier)
