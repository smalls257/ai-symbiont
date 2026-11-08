"""Whether a typed message pushes back on what the agent did, rather than just asking for more.

The SWE-chat dataset labels a third of typed messages "correction" ("please push and open a
pr"); only wording that refuses, undoes, restates or reports a failure is a real correction.
A rule-shaped clause counts only when it refuses ("don't", "never", "stop"); a reminder
("make sure", "don't forget") rides along with a request. Pure: text in, verdict out.
"""

import re

from symbiont.miner.rule_language import NOT_A_RULE, QUOTES, refuses

# Past this, a pasted log or file is talking, not the developer.
INSPECTED_CHARS = 300
# "No problem" and "wait for the build" acknowledge; "no," "noooo" and "wait a second" refuse.
_OPENER = re.compile(
    r"^\W*(?:no{2,}\b|no(?=\s*[,.!])(?!,?\s+(?:problem|worries|thanks|thank you|need)\b)"
    r"|nope\b|wait(?:\s*,|\s+(?:a (?:second|sec|minute|moment)|what|that|why)\b)"
    r"|revert\b|undo\b|wrong\b|not (?:that|this|the)\b"
    r"|why (?:did|are|would) you\b|that'?s (?:wrong|not)\b)",
    re.IGNORECASE,
)
# What follows "no," or "wait," when the developer is answering the agent's question and agreeing:
# "no, go ahead", "no, that all checks out". The opener then refuses nothing.
_ASSENT = re.compile(
    r"^\W*(?:that'?s (?:fine|good|ok(?:ay)?|it|all)|that all|it'?s (?:fine|ok(?:ay)?)"
    r"|(?:looks|sounds|all) (?:good|great|fine)|go ahead|not yet|let'?s|move on"
    r"|i haven'?t|nothing|worries|problem|all set|we'?re good)\b",
    re.IGNORECASE,
)
_PHRASE = re.compile(
    r"\b(?:you|that|this) (?:forgot|missed|broke|didn'?t|did not|failed to)\b"
    r"|\bnot what i\b|\bi (?:said|asked|told you)\b"
    r"|\bstill (?:failing|broken|not working)\b|\b(?:is|are) not working\b"
    r"|\b(?:does|did)n'?t work\b|\bplease (?:revert|undo)\b",
    re.IGNORECASE,
)


def pushes_back(text: str) -> bool:
    """True when the first lines refuse, undo, restate or report a failure; a request is not."""
    head = _after_assenting_opener(text[:INSPECTED_CHARS].translate(QUOTES))
    if _OPENER.match(head) or _PHRASE.search(head):
        return True
    return refuses(NOT_A_RULE.sub(" ", head))


def _after_assenting_opener(head: str) -> str:
    """The text after "no," or "wait," when assent follows it ("no, not yet"), else all of it."""
    opener = _OPENER.match(head)
    if opener is None or not _ASSENT.match(head[opener.end() :]):
        return head
    return head[opener.end() :]
