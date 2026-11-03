"""What the session's model is told to do to learn from PR reviews and CI, and the bounds on it.

symbiont reaches no network (only `symbiont.egress` may); the harness agent reads GitHub with the
developer's own `gh` access and saves lessons through `symbiont_add_lessons`. The route refuses
an unsafe link, so a PR lesson is traceable or rejected, never kept without provenance.
"""

import re

from symbiont.miner.review_quote import (
    MAX_QUOTE_CHARS,
    ReviewerRole,
    capped_at_sentence,
    pull_number,
)
from symbiont.miner.secrets import scrub

PR_QUESTION = (
    "Want me to learn from this repository's recent pull-request reviews and CI failures? "
    "Ask the developer in your own words. On yes, follow the steps from `symbiont learn-from-prs`. "
    "On no, do nothing; they can ask any time with `/symbiont learn-from-prs`."
)

MAX_PRS = 30
MAX_LESSONS = 20
MAX_URL = 300
# https, a host, then path/query without whitespace or '@' (no embedded credentials).
HTTPS_LINK = re.compile(r"https://[A-Za-z0-9.-]+(:\d+)?(/[^\s@]*)?")

PR_INSTRUCTIONS = f"""\
Learn from this repository's recent pull-request reviews and CI failures. You read GitHub with the
developer's own access (the `gh` command); symbiont reads nothing from GitHub and only stores what
you save.

1. List the most recent merged pull requests, at most {MAX_PRS}:
   `gh pr list --state merged --limit {MAX_PRS}`.
2. For each one, read the review: `gh pr view N --comments`, and the line comments:
   `gh api repos/OWNER/REPO/pulls/N/comments`. For CI, look at failed check runs and read a summary
   of the failing log (`gh pr checks N`, `gh run view RUN --log-failed`, cut to the failing lines).
3. Keep ONLY durable, repo-specific corrections:
   - a review comment that asked for a change, where a later commit on the pull request made it
     (the request plus the commit that addressed it is a confirmed mistake), or
   - a CI failure with a known cause that was then fixed.
4. Skip: comments from bots, nits and style-only remarks (naming taste, whitespace, typos,
   formatting a linter already enforces), praise, questions that got no change, one-off fixes that
   say nothing about how this repository works, and anything you cannot tie to a later fix.
5. Save at most {MAX_LESSONS} lessons in total, in one or a few calls to `symbiont_add_lessons`.
   Each lesson: text_in_plain_words (one or two sentences a teammate would say before touching
   this area), quote (see 6), quote_role, kind (`correction` for a
   reviewer's requested change, `rule` for a standing convention, `mistake` for a CI failure),
   files (repo-relative paths), applies_to {{terms, areas}}, source_label ("from PR #412 review"
   or "from CI on PR #415") and source_url (that pull request's web address).
6. The reviewer's words are the rule; your sentence is only a pointer to them. Save `quote`:
   quote the reviewer's exact words that state the rule, copied character for character from the
   comment, at most {MAX_QUOTE_CHARS} characters, ending at a sentence end. Do not narrow the rule
   to the case at hand: if the reviewer stated it generally ("don't copy expressions in generator
   code"), your sentence states it generally too, not for one dialect, file or function. Set
   `quote_role` to `maintainer` when the reviewer maintains the repository, else `reviewer`. A
   quote needs a source_url that is a pull request address.
   Never store reviewer or author names, user handles, email addresses, tokens or long comment
   text: if the sentence that states the rule names someone, quote another sentence.
7. Tell the developer how many lessons you saved and from which pull requests. Say "nothing worth
   keeping" and save nothing when nothing qualifies.
"""

# A handle or an address in a quote would name a person, which the instructions forbid storing.
_PERSON = re.compile(r"(?<![\w`])@[A-Za-z0-9][\w-]*|[\w.+-]+@[\w-]+\.[\w.]+")


class UnsafeSourceUrlError(ValueError):
    """A lesson's source_url is not a plain https web address."""


def checked_source_url(value: object) -> str:
    """The pull-request link as given, or '' when none; raises on anything but https.

    Raises UnsafeSourceUrlError for a non-https scheme, embedded credentials or an over-long link:
    the dashboard shows it as a link, so a `javascript:` address must never be stored.
    """
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise UnsafeSourceUrlError("source_url must be text")
    url = value.strip()
    if not HTTPS_LINK.fullmatch(url):
        raise UnsafeSourceUrlError("source_url must be a plain https address")
    if len(url) > MAX_URL:
        raise UnsafeSourceUrlError(f"source_url is longer than {MAX_URL} characters")
    return url


class UnusableQuoteError(ValueError):
    """A lesson's quote cannot be kept; the message says what to send instead."""


def checked_quote(quote: object, role: object, source_url: str) -> tuple[str, str]:
    """(quote, role) to store, or ('', '') for no quote; raises UnusableQuoteError on a bad one.

    The review text never reaches the service, so the quote is model-supplied, not verified.
    """
    if quote is None or quote == "":
        if role not in (None, ""):
            raise UnusableQuoteError("quote_role was given without a quote")
        return "", ""
    if not isinstance(quote, str):
        raise UnusableQuoteError("quote must be text")
    text = " ".join(quote.split())
    if pull_number(source_url) is None:
        raise UnusableQuoteError("a quote needs a source_url that is a pull request address")
    if _PERSON.search(text) or scrub(text) != text:
        raise UnusableQuoteError(
            "quote names a person or holds a credential; quote another sentence of the comment"
        )
    return _within_cap(text), _role(role)


def _within_cap(text: str) -> str:
    """The quote itself when it fits the cap; otherwise an error saying where to cut."""
    kept = capped_at_sentence(text)
    if kept == text:
        return text
    where = f"keep its first {len(kept)} characters" if kept else "quote one shorter sentence"
    raise UnusableQuoteError(
        f"quote is {len(text)} characters, over {MAX_QUOTE_CHARS}; "
        f"{where}, ending at a sentence end"
    )


def _role(role: object) -> str:
    """The reviewer's role by name; 'reviewer' when the model did not say."""
    if role in (None, ""):
        return ReviewerRole.REVIEWER.value
    try:
        if not isinstance(role, str):
            raise ValueError(role)
        return ReviewerRole(role).value
    except ValueError as unknown:
        choices = ", ".join(member.value for member in ReviewerRole)
        raise UnusableQuoteError(f"quote_role must be one of: {choices}") from unknown
