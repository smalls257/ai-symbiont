"""Whether a typed message pushes back on what the agent did, rather than just asking for more.

The SWE-chat dataset labels a third of typed messages "correction" ("please push and open a
pr"); only wording that refuses, undoes, restates or reports a failure is a real correction.
Reuses the rule wording of `rule_language`. Pure: text in, verdict out.
"""

import re

from symbiont.miner.rule_language import QUOTES, instructs

# Past this, a pasted log or file is talking, not the developer.
INSPECTED_CHARS = 300
_OPENER = re.compile(
    r"^\W*(?:no+|nope|wait|revert|undo|wrong|not (?:that|this|the)"
    r"|why (?:did|are|would) you|that'?s (?:wrong|not))\b",
    re.IGNORECASE,
)
_PHRASE = re.compile(
    r"\byou (?:forgot|missed|broke|didn'?t|did not|failed to)\b"
    r"|\bnot what i\b|\bi (?:said|asked|told you)\b"
    r"|\b(?:still|is|are) (?:failing|broken|not working)\b"
    r"|\b(?:does|did)n'?t work\b|\bplease (?:revert|undo)\b"
    r"|\bshould (?:always|never) \w+|\bstop\b",
    re.IGNORECASE,
)


def pushes_back(text: str) -> bool:
    """True when the first lines refuse, undo, restate or report a failure; a request is not."""
    head = text[:INSPECTED_CHARS].translate(QUOTES)
    return bool(_OPENER.match(head) or _PHRASE.search(head) or instructs(head))
