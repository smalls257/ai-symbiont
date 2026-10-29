"""The general lesson card: one short prose text every evaluation task gets, before its issue.

Each point rests on a lesson whose counts support it (the counts stay out of the text), and it
must stay under MAX_WORDS so it does not crowd out the issue. Pure.
"""

from collections.abc import Mapping

from general_lesson import GeneralLesson

MAX_WORDS = 250  # dispatch limit for the prompt card
RESTS_ON = ("habit-edit-once-found", "repo-shared-layer", "impl-new-function")
TEST = "cd /testbed && python -m unittest tests.dialects.test_<dialect>"


class CardTooLongError(ValueError):
    """The card is over MAX_WORDS."""


def card(lessons: Mapping[str, GeneralLesson]) -> str:
    """The card text; raises KeyError if a lesson it rests on is missing, CardTooLongError if long.

    Domain prose only: the counts behind each point stay in the lessons' support and the report.
    """
    for lesson_id in RESTS_ON:
        lessons[lesson_id]
    text = "\n".join(
        [
            "LESSONS FROM YOUR EARLIER WORK IN THIS REPO (sqlglot), for any bug or feature:",
            "1. Edit once you have found it. Runs that never edited the code never solved the "
            "task, even when they had already opened the right file. When a read shows the code "
            "that builds the wrong output, or where the new case belongs, make the smallest edit "
            "there, early, while there are steps left to test and submit.",
            '2. Reproduce once with `python -c "import sqlglot; ..."`, not a new scratch script.',
            "3. Find the layer first: `repr(sqlglot.parse_one(SQL, read='<d>'))`. Wrong tree: the "
            "parser or tokenizer. Right tree, wrong SQL text: the generator.",
            "4. A dialect's output is its `<Dialect>.Generator` (`TRANSFORMS` entries, "
            "`<name>_sql` methods); its parsing is `<Dialect>.Parser` (`FUNCTIONS`, "
            "`_parse_<thing>`) and `<Dialect>.Tokenizer.KEYWORDS`. A dialect's failing test is "
            "often fixed in shared code instead: `sqlglot/parser.py`, `generator.py` or "
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
