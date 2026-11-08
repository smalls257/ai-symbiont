"""Words too common to say what a text is about: shared by rule matching and themes.

They sit in `miner` (the lower layer) so `miner.rule_terms` and `miner.themes` read one list
instead of keeping two that drift apart.
"""

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
