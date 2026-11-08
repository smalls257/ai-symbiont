"""Standing rules a developer states to the agent: the turns worth offering as a rule.

A turn qualifies by directive wording; a correction counts only when it also carries that
wording (a bare "no, not that file" is not a rule). Text is scrubbed, one line and capped.
Pure: records in, candidates out.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

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

# Directive language, one way each to state a standing rule: always, never, don't / do not, stop
# (only "stop committing"; "stop the dev server" is a one-off), from now on, make sure, must,
# should(n't) be, instead of, prefer, avoid, no more, every time, remember to, we use, "X, not Y".
DIRECTIVE = re.compile(
    r"\b(?:always|never|don'?t|do not|stop \w+ing|from now on|make sure|must|should(?:n'?t)? be"
    r"|instead of|prefer|avoid|no more|every time|remember to|we use)\b"
    rf"|\buse {_ITEM},? not {_ITEM}|{_ITEM}, not {_ITEM}",
    re.IGNORECASE,
)
# Phrases that contain a directive word without stating a rule; blanked before the directive
# test so "never mind, always use pnpm" still counts.
NOT_A_RULE = re.compile(
    r"\bnever mind\b|\bi (?:do not|don'?t) (?:know|think)\b|\bnot sure\b",
    re.IGNORECASE,
)
# Words that say "rule" and nothing about its subject; kept out of the terms that group rules.
DIRECTIVE_WORDS = frozenset(
    {"prefer", "avoid", "instead", "remember", "stop", "make", "sure", "every", "time", "must"}
)
# Politeness and filler: they say how the developer asked, never what about, so two rules
# that differ only by "please" must not look different.
FILLER_WORDS = frozenset(
    [
        *("please", "mind", "thanks", "thank", "sorry", "okay", "just", "also", "ahead", "sure"),
        *("now", "then", "maybe", "really", "again", "yeah", "ahhh", "lets", "dont", "doesnt"),
        *("cant", "wont", "theres", "able", "already", "seems", "looks"),
    ]
)
# Harness text that is not the developer's: the reminder block is cut out and the rest judged.
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_HARNESS_TURN = ("<task-notification", "<local-command", "<command-stdout")
_URL = re.compile(r"https?://\S+")
_HAS_DIGIT = re.compile(r"\d")
_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'"})
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
    """The typed user turns of one session that state a rule; `source` says if it was pushback."""
    corrected = {pain.step for pain in find_corrections(session)}
    found = []
    for record in session:
        typed = _developer_text(record)
        if typed is None or is_bare_acknowledgment(typed) or not _states_rule(typed):
            continue
        text = " ".join(scrub(typed).split())[:MAX_TEXT_CHARS]
        source = CORRECTION if record.step in corrected else RULE_WORDS
        found.append(RuleCandidate(record.session_id, record.step, text, rule_terms(text), source))
    return found


def _developer_text(record: Record) -> str | None:
    """What the developer typed, with injected reminder blocks and harness turns left out."""
    stripped = _REMINDER.sub(" ", record.raw).strip()
    if stripped.startswith(_HARNESS_TURN):
        return None
    return typed_message(replace(record, raw=stripped)) if stripped else None


def rule_terms(text: str) -> frozenset[str]:
    """Distinctive words, identifiers, file names and tool names of a rule."""
    prose = _URL.sub(" ", text.translate(_QUOTES))
    named = {word.lower() for word in _WORD.findall(prose)} & TOOLS
    files = {match.lower() for match in _FILE.findall(prose)}
    terms = salient_terms(prose) | named | files
    return frozenset(t for t in terms - DIRECTIVE_WORDS - FILLER_WORDS if not _HAS_DIGIT.search(t))


def _states_rule(text: str) -> bool:
    """Directive wording that is not a question (unless an earlier clause is imperative)."""
    blanked = NOT_A_RULE.sub(" ", text.translate(_QUOTES))
    if not text.rstrip().endswith("?"):
        return bool(DIRECTIVE.search(blanked))
    earlier = _SENTENCE_END.split(blanked.rstrip())[:-1]
    return any(DIRECTIVE.search(sentence) for sentence in earlier)
