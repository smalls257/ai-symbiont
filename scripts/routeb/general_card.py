"""The general lesson card: one short prose text every evaluation task gets, before its issue.

It is assembled from the lessons' own counts, so it can claim nothing they do not show, and it
must stay under MAX_WORDS so it does not crowd out the issue. Pure.
"""

from collections.abc import Mapping

from general_lesson import GeneralLesson

MAX_WORDS = 250  # dispatch limit for the prompt card
TEST = "cd /testbed && python -m unittest tests.dialects.test_<dialect>"


class CardTooLongError(ValueError):
    """The card is over MAX_WORDS."""


def card(lessons: Mapping[str, GeneralLesson]) -> str:
    """The card text; raises KeyError if a lesson it cites is missing, CardTooLongError if long."""
    found = lessons["habit-edit-once-found"].support
    shared = lessons["repo-shared-layer"].support
    text = "\n".join(
        [
            "LESSONS FROM YOUR EARLIER WORK IN THIS REPO (sqlglot), for any bug or feature:",
            f"1. Edit once you have found it. In {found['never_edited_runs']} "
            f"of {found['of_runs']} earlier runs you never edited a file and none solved, though "
            f"nearly all had already opened the right file. Runs that first edited by step 30 "
            f"solved {found['early_solved']} of {found['early_runs']}. When a read shows the code "
            "that builds the wrong output, or where the new case belongs, make the smallest edit "
            "there; aim to edit by step 25.",
            '2. Reproduce once with `python -c "import sqlglot; ..."`, not a new scratch script.',
            "3. Find the layer first: `repr(sqlglot.parse_one(SQL, read='<d>'))`. Wrong tree: the "
            "parser or tokenizer. Right tree, wrong SQL text: the generator.",
            "4. A dialect's output is its `<Dialect>.Generator` (`TRANSFORMS` entries, "
            "`<name>_sql` "
            "methods); its parsing is `<Dialect>.Parser` (`FUNCTIONS`, `_parse_<thing>`) and "
            f"`<Dialect>.Tokenizer.KEYWORDS`. In {shared['tasks']} of {shared['of_tasks']} fixes "
            "for a dialect's test, the code was shared: `sqlglot/parser.py`, `generator.py` or "
            "`expressions.py`.",
            "5. New support: grep `sqlglot/expressions.py` for an existing class first; copy the "
            "closest existing entry in the same map; a new keyword or clause runs token, then "
            "`_parse_<thing>`, then `arg_types`, then `<name>_sql`.",
            f"6. Test with `{TEST}` (no pytest, no apply_patch; edit with `sed -i` or python). "
            "Add `validate_identity` or `validate_all` lines beside similar ones.",
            "7. When that module passes and `git diff` shows only your fix, submit.",
        ]
    )
    words = len(text.split())
    if words > MAX_WORDS:
        raise CardTooLongError(f"the card has {words} words, limit {MAX_WORDS}")
    return text
