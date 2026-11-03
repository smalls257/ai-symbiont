"""Saving a lesson with the reviewer's exact words: kept, delivered, and refused loudly when unfit.

Failures guarded against: Forensic Coding (the ruling narrowed by the model's paraphrase) and
Silent Fallback (a quote with a handle, no PR link or over the cap kept or cut without a word).
The service never sees the review text, so no check against it is claimed. All payloads are
synthetic.
"""

import sqlite3

import pytest

from symbiont.core.quoted_rule import rule_note
from symbiont.core.rule_relevance import rules_of
from symbiont.service.curation_routes import CurationRoutes
from symbiont.service.pr_learning import PR_INSTRUCTIONS, UnusableQuoteError, checked_quote
from symbiont.service.request_shapes import BadRequestError
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import CorrectionSettings

pytestmark = pytest.mark.periphery
PROJECT = "shop"
URL = "https://github.com/acme/shop/pull/7396"
QUOTE = "Don't copy expressions in generator code; the generator already copies the whole tree."
LESSON = {
    "text_in_plain_words": "Do not copy expressions in any generator method.",
    "kind": "rule",
    "files": ["src/ledger/gen.py"],
    "source_label": "from PR #7396 review",
    "source_url": URL,
    "quote": QUOTE,
    "quote_role": "maintainer",
}


@pytest.fixture
def rig(tmp_path):
    store = Store.open(tmp_path / "s.db")
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    return CurationRoutes(store, registry, CorrectionSettings, {}), store


def save(routes, **changes):
    return routes.add_lessons({"project": PROJECT, "lessons": [LESSON | changes]})


def test_a_lesson_saved_with_a_quote_keeps_it_and_delivers_it_first(rig):
    routes, store = rig
    save(routes)

    (kept,) = store.curation.authored(PROJECT)
    (rule,) = rules_of([], {}, [kept])

    assert (kept.quote, kept.quote_role) == (QUOTE, "maintainer")
    assert rule_note(rule) == (
        f'[symbiont] In this repo, a maintainer said on PR #7396: "{QUOTE}" '
        "(Do not copy expressions in any generator method)."
    )


def test_a_lesson_without_a_quote_stores_none_and_a_missing_role_defaults_to_reviewer(rig):
    routes, store = rig
    save(routes, quote="", quote_role="", text_in_plain_words="Plain one.")
    save(routes, quote_role="", text_in_plain_words="Quoted, no role.")

    plain, unroled = store.curation.authored(PROJECT)

    assert (plain.quote, plain.quote_role) == ("", "")
    assert unroled.quote_role == "reviewer"


def test_whitespace_in_a_quote_is_folded_to_single_spaces():
    assert checked_quote("Copy  nothing\n here.", "maintainer", URL) == (
        "Copy nothing here.",
        "maintainer",
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source_url": ""}, "pull request address"),
        ({"source_url": "https://github.com/acme/shop/issues/9"}, "pull request address"),
        ({"quote": "As @alice said, do not copy."}, "names a person"),
        ({"quote": "Ask bob@example.com about copying."}, "names a person"),
        ({"quote": "Use token ghp_" + "a1B2" * 9 + " here."}, "credential"),
        ({"quote_role": "owner"}, "maintainer, reviewer"),
        ({"quote": 7}, "must be text"),
        ({"quote": "Copy nothing here. " * 30}, "over 300; keep its first"),
        ({"quote": "word " * 80}, "quote one shorter sentence"),
        ({"quote": "", "quote_role": "maintainer"}, "without a quote"),
    ],
)
def test_an_unfit_quote_is_refused_with_a_message_and_nothing_is_stored(rig, changes, message):
    routes, store = rig

    with pytest.raises(BadRequestError, match=message):
        save(routes, **changes)

    assert store.curation.authored(PROJECT) == []


def test_the_cap_boundary_is_inclusive():
    at_cap = "x" * 299 + "."
    assert checked_quote(at_cap, "", URL)[0] == at_cap
    with pytest.raises(UnusableQuoteError):
        checked_quote("x" * 300 + ".", "", URL)


def test_the_instructions_ask_for_the_exact_words_and_a_general_rule():
    for must in ("exact words", "Do not narrow the rule", "state", "quote_role", "maintainer"):
        assert must in PR_INSTRUCTIONS
    assert "Write the rule in your own words" not in PR_INSTRUCTIONS


def test_a_store_made_before_quotes_gains_the_columns_and_keeps_its_lessons(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE authored (id TEXT PRIMARY KEY, project TEXT NOT NULL, text TEXT NOT NULL, "
        "kind TEXT NOT NULL, files TEXT NOT NULL, source_label TEXT NOT NULL, "
        "severity TEXT NOT NULL, applies TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '')"
    )
    db.execute(
        "INSERT INTO authored VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("w1", "shop", "Old.", "rule", "[]", "", "medium", '{"terms": [], "areas": []}', URL),
    )
    db.commit()
    db.close()

    (old,) = Store.open(path).curation.authored("shop")

    assert (old.text, old.quote, old.quote_role) == ("Old.", "", "")
