"""Which words of a rule or a prompt are distinctive: identifiers and uncommon plain words.

Generic talk and words most of the repo's lessons share count for nothing. Pure.
"""

import re
from collections import Counter
from collections.abc import Iterable

MIN_TERM_CHARS = 4
MIN_LESSONS_FOR_COMMON = 6
COMMON_SHARE = 0.4
MAX_CODE_CHARS = 5
MIN_CODE_CHARS = 2
_STOP_TEXT = (
    "this that with from have must should would could into when then than they them their "
    "there here what which while where will your you are not never always only also each "
    "any all can use used using make made keep kept stay stays does done being been were was "
    "for and the but its our out about over under after before without within"
)
STOPWORDS = frozenset(_STOP_TEXT.split())
_GENERIC_TEXT = (
    "because other field fields table tables file files test tests error errors value values "
    "fail fails failed failing failure code line lines name names type types data issue issues "
    "problem problems thing things result results case cases like just some more most many much "
    "such same different another change changes changed update updates updated check checks "
    "need needs want following add added remove removed return returns returned call calls "
    "function functions method methods class object list item items string number first second "
    "last next every sure still even very work works working make run runs running does "
    "check ensure instead rather make using"
)
GENERIC_WORDS = frozenset(_GENERIC_TEXT.split())
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def stem(word: str) -> str:
    """A crude plural stem so `refunds` and `refund` are one term."""
    return word[:-1] if len(word) > MIN_TERM_CHARS + 1 and word.endswith("s") else word


def identifiers_in(text: str) -> frozenset[str]:
    """Identifier-like tokens of a text, lowercased: snake_case, CamelCase, dotted, ALL-CAPS."""
    found = (_core(token) for token in _TOKEN.findall(text))
    return frozenset(core.lower() for core in found if core and _is_identifier(core))


def plain_terms(text: str, common: frozenset[str] = frozenset()) -> frozenset[str]:
    """Ordinary words that carry meaning: no stopwords, generic talk or `common` terms."""
    terms = set()
    for token in _TOKEN.findall(text):
        core = _core(token)
        if core and _is_identifier(core):
            continue
        terms |= {stem(word.lower()) for word in _WORD.findall(token) if _worth_keeping(word)}
    return frozenset(terms - common)


def salient_terms(text: str) -> frozenset[str]:
    """Distinctive plain words plus identifier-like tokens: what a text is about."""
    return plain_terms(text) | identifiers_in(text)


def common_terms(texts: Iterable[str]) -> frozenset[str]:
    """Words most of the repo's lessons share, so they separate none of them.

    Needs MIN_LESSONS_FOR_COMMON lessons to say anything; below that every word is rare by
    construction. Only lesson texts are counted: prompts are not stored, and the matcher is pure.
    """
    pools = [plain_terms(text) for text in texts]
    if len(pools) < MIN_LESSONS_FOR_COMMON:
        return frozenset()
    seen = Counter(term for pool in pools for term in pool)
    return frozenset(term for term, count in seen.items() if count > COMMON_SHARE * len(pools))


def _worth_keeping(word: str) -> bool:
    """Whether a plain word is long enough and neither a stopword nor generic talk."""
    lower = word.lower()
    if len(word) < MIN_TERM_CHARS or lower in STOPWORDS:
        return False
    return lower not in GENERIC_WORDS and stem(lower) not in GENERIC_WORDS


def _core(token: str) -> str:
    """A token without sentence punctuation or leading underscores."""
    return token.strip("._")


def _is_identifier(core: str) -> bool:
    """snake_case, dotted path, CamelCase or short ALL-CAPS code."""
    if "_" in core:
        return True
    if "." in core:
        return all(len(part) >= MIN_CODE_CHARS for part in core.split("."))
    if core.isupper():
        return MIN_CODE_CHARS <= len(core) <= MAX_CODE_CHARS
    return any(char.isupper() for char in core[1:]) and any(char.islower() for char in core)
