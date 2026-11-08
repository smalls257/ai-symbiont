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
from symbiont.miner.incident_words import REMINDER
from symbiont.miner.rule_language import ITEM, QUOTES, states_rule
from symbiont.miner.rule_terms import salient_terms
from symbiont.miner.session_digest import typed_message
from symbiont.miner.signals.correction import find_corrections
from symbiont.records.schema import Record

MAX_TEXT_CHARS = 240
RULE_WORDS = "rule_words"
CORRECTION = "correction"

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
# Harness turns that are not the developer's; injected reminder blocks are cut out (REMINDER).
_HARNESS_TURN = ("<task-notification", "<local-command", "<command-stdout")
_URL = re.compile(r"https?://\S+")
_HAS_DIGIT = re.compile(r"\d")
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
_FILE = re.compile(rf"{ITEM}\.[A-Za-z]{{2,5}}\b|[\w.-]+/{ITEM}")
_WORD = re.compile(r"[\w'-]+")


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
        if typed is None or is_bare_acknowledgment(typed) or not states_rule(typed):
            continue
        text = " ".join(scrub(typed).split())[:MAX_TEXT_CHARS]
        source = CORRECTION if record.step in corrected else RULE_WORDS
        found.append(RuleCandidate(record.session_id, record.step, text, rule_terms(text), source))
    return found


def _developer_text(record: Record) -> str | None:
    """What the developer typed, with injected reminder blocks and harness turns left out."""
    stripped = REMINDER.sub(" ", record.raw).strip()
    if stripped.startswith(_HARNESS_TURN):
        return None
    return typed_message(replace(record, raw=stripped)) if stripped else None


def rule_terms(text: str) -> frozenset[str]:
    """Distinctive words, identifiers, file names and tool names of a rule."""
    prose = _URL.sub(" ", text.translate(QUOTES))
    named = {word.lower() for word in _WORD.findall(prose)} & TOOLS
    files = {match.lower() for match in _FILE.findall(prose)}
    terms = salient_terms(prose) | named | files
    return frozenset(t for t in terms - DIRECTIVE_WORDS - FILLER_WORDS if not _HAS_DIGIT.search(t))
