"""The wording of a standing rule: instruction openers, contrast forms, hedges and non-rules.

Shared by the rule candidates and the pushback test, so "always / never / don't / stop" means
one thing everywhere. Pure: text in, verdict out.
"""

import re

ITEM = r"[\w./-]+"
QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'"})
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n")

# An instruction: one of these opens a clause ("always use pnpm", "please never commit", "you
# should never push", "stop committing"). Mid-clause directive words ("it was never moved", "I
# always do") describe, so only the openers and the two contrast forms below count.
_OPENERS = (
    r"(?:always|never|don'?t|do not|stop \w+ing|make sure|remember to|from now on|every time"
    r"|avoid|prefer|no more|we use|you(?: should(?:n'?t)?| must(?:n'?t)?) (?:always |never )?\w+)"
)
_LEAD_IN = r"(?:(?:please|also|and|but|so|then|ok|okay|now|just|yeah|oh)\b[,\s]*)*"
OPENER = re.compile(rf"^{_LEAD_IN}{_OPENERS}\b", re.IGNORECASE)
# "not only", "not just", "not yet" widen or delay; they do not name the thing to avoid.
_NOT_A_CONTRAST = r"(?!(?:only|just|yet|sure|really|necessarily|always)\b)"
CONTRAST = re.compile(
    rf"\binstead of\b|\buse {ITEM},? not {_NOT_A_CONTRAST}{ITEM}"
    rf"|{ITEM}, not {_NOT_A_CONTRAST}{ITEM}",
    re.IGNORECASE,
)
_CLAUSE_END = re.compile(r"[.!?;:\n]+|,\s|\s-\s")
# A refusal: the openers that turn the agent away from what it did. "make sure", "remember to",
# "always" and "don't forget" ask for more work, so a request that carries them is not pushback.
# "(I) don't remember / know / have" describes the speaker, with the subject dropped.
_SELF_STATE = (
    r"(?! (?:forget|worry|remember|know|think|have|see|understand|mind|need|care|recall|get))"
)
_REFUSALS = (
    rf"(?:never|don'?t{_SELF_STATE}|do not{_SELF_STATE}|stop (?:it|that|this|the|\w+ing)"
    r"|no more|avoid|you (?:should|must)(?:n'?t| not| never) \w+|instead\b)"
)
REFUSAL = re.compile(rf"^{_LEAD_IN}{_REFUSALS}\b", re.IGNORECASE)
# The one contrast that is itself an instruction; "docker, not the host" mid-sentence describes.
USE_CONTRAST = re.compile(
    rf"(?:^|[.!?;\n]\s*){_LEAD_IN}use {ITEM},? not {_NOT_A_CONTRAST}{ITEM}", re.IGNORECASE
)
# Phrases that contain a directive word without stating a rule; blanked before the directive
# test so "never mind, always use pnpm" still counts. "never moved" is a past participle (a
# description of what happened); "should be able to" and "should have" are hedges.
NOT_A_RULE = re.compile(
    r"\bnever mind\b|\bdon'?t worry\b|\bi (?:do not|don'?t) (?:know|think)\b|\bnot sure\b"
    r"|\bnever (?:\w*[^e\W]ed|been|done|seen|gone|made|taken|given|written|shown|found)\b"
    r"|\bshould be able to\b|\bshould have\b",
    re.IGNORECASE,
)
# A hedged turn guesses or describes; it does not instruct.
HEDGES = re.compile(r"\b(?:would|could|might|likely)\b|\bit seems\b|\bseems to\b", re.IGNORECASE)


def states_rule(text: str) -> bool:
    """An instruction, not a hedge or a question (unless an earlier clause is imperative)."""
    plain = text.translate(QUOTES)
    if HEDGES.search(plain):
        return False
    blanked = NOT_A_RULE.sub(" ", plain)
    if not text.rstrip().endswith("?"):
        return instructs(blanked)
    earlier = _SENTENCE_END.split(blanked.rstrip())[:-1]
    return any(instructs(sentence) for sentence in earlier)


def instructs(text: str) -> bool:
    """A clause that opens with directive wording, or a contrast such as "use X, not Y"."""
    clauses = (clause.strip() for clause in _CLAUSE_END.split(text))
    return any(OPENER.match(clause) for clause in clauses) or bool(CONTRAST.search(text))


def refuses(text: str) -> bool:
    """A clause that opens by turning the agent away ("don't", "never", "stop", "use X, not Y")."""
    clauses = (clause.strip() for clause in _CLAUSE_END.split(text))
    return any(REFUSAL.match(clause) for clause in clauses) or bool(USE_CONTRAST.search(text))
