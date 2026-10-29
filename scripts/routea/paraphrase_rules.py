"""When a paraphrased question still asks about its lesson. Pure, stdlib only, so both the MLX
venv (paraphrase_questions.py) and the repo's tests import it.

A paraphrase that drops the repo or a backticked command asks about nothing in particular; it is
refused here, never patched up.
"""

import re

_BACKTICKED = re.compile(r"`[^`]+`")


def keeps_details(original: str, paraphrase: str, repo: str, file: str) -> bool:
    """True when the paraphrase is new wording that still names the repo and every backticked
    part of the original (or, when the original has none, the file it asks about)."""
    spans = _BACKTICKED.findall(original)
    named = all(span in paraphrase for span in spans) if spans else file in paraphrase
    return repo in paraphrase and named and paraphrase.strip() != original.strip()
