"""Learning from PR reviews and CI failures: the session's model reads GitHub, symbiont stores.

Failures guarded against: Leaky Narrative (reviewer names and nits saved as lessons because the
instructions never said not to), Silent Fallback (a lesson with no usable PR link kept anyway, a
`javascript:` address stored for the dashboard to render) and an Infected Core (symbiont itself
reaching GitHub). All payloads are synthetic.
"""

import json
import re
from datetime import date
from pathlib import Path

import pytest

from symbiont.service.curation_routes import CurationRoutes
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.onboarding import Announcements, Lookups
from symbiont.service.pr_learning import (
    MAX_LESSONS,
    MAX_PRS,
    PR_INSTRUCTIONS,
    PR_QUESTION,
    UnsafeSourceUrlError,
    checked_source_url,
)
from symbiont.service.request_shapes import BadRequestError
from symbiont.store.local import Store
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import CorrectionSettings

pytestmark = pytest.mark.periphery
PROJECT = "shop"
PR_URL = "https://github.com/acme/shop/pull/412"
CI_URL = "https://github.com/acme/shop/pull/415"
SYNTHETIC_REVIEW = {
    "text_in_plain_words": "Refund amounts are integer cents; float math was rejected in review.",
    "kind": "correction",
    "files": ["src/billing/refund.py"],
    "applies_to": {"terms": ["refund"], "areas": ["src/billing/"]},
    "source_label": "from PR #412 review",
    "source_url": PR_URL,
}
SYNTHETIC_CI = {
    "text_in_plain_words": "CI fails when a migration lacks a down step; add one.",
    "kind": "mistake",
    "files": ["db/migrations/0042_add_refund.sql"],
    "source_label": "from CI on PR #415",
    "source_url": CI_URL,
}


@pytest.fixture
def rig(tmp_path):
    store = Store.open(tmp_path / "s.db")
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    routes = CurationRoutes(store, registry, CorrectionSettings, {})
    return routes, store, registry


def test_the_instructions_tell_the_model_what_to_read_keep_skip_and_never_store():
    for must in ("gh pr list --state merged --limit 30", "gh pr view N --comments"):
        assert must in PR_INSTRUCTIONS
    assert "gh api repos/OWNER/REPO/pulls/N/comments" in PR_INSTRUCTIONS
    assert "failed check runs" in PR_INSTRUCTIONS and "symbiont_add_lessons" in PR_INSTRUCTIONS
    for skipped in ("bots", "nits", "style-only"):
        assert skipped in PR_INSTRUCTIONS
    assert "Never store reviewer or author names" in PR_INSTRUCTIONS
    for field in ("source_label", "source_url", "files", "applies_to", "kind"):
        assert field in PR_INSTRUCTIONS
    assert (MAX_PRS, MAX_LESSONS) == (30, 20) and "at most 20 lessons" in PR_INSTRUCTIONS


def test_the_instructions_are_domain_prose_with_no_scores_or_thresholds():
    assert not re.search(r"threshold|score|activation|\bk=", PR_INSTRUCTIONS, re.IGNORECASE)


def test_lessons_from_a_review_and_from_ci_keep_their_label_and_link(rig):
    routes, store, _ = rig

    result = routes.add_lessons({"project": PROJECT, "lessons": [SYNTHETIC_REVIEW, SYNTHETIC_CI]})

    review, ci = store.curation.authored(PROJECT)
    assert result["added"] == 2
    assert (review.source_label, review.source_url) == ("from PR #412 review", PR_URL)
    assert (ci.source_label, ci.source_url, ci.kind.value) == (
        "from CI on PR #415",
        CI_URL,
        "mistake",
    )
    assert review.applies.areas == ("src/billing/",)


@pytest.mark.parametrize(
    "bad",
    ["javascript:alert(1)", "http://github.com/a/b/pull/1", "https://user" + "@github.com/x", 7],
)
def test_an_unsafe_link_is_refused_not_stored(rig, bad):
    routes, store, _ = rig

    with pytest.raises(BadRequestError, match="source_url"):
        routes.add_lessons(
            {"project": PROJECT, "lessons": [SYNTHETIC_REVIEW | {"source_url": bad}]}
        )
    assert store.curation.authored(PROJECT) == []


def test_checked_source_url_allows_none_and_rejects_long_links():
    assert checked_source_url(None) == "" and checked_source_url("") == ""
    with pytest.raises(UnsafeSourceUrlError):
        checked_source_url("https://github.com/" + "a" * 400)


def test_more_than_the_cap_of_pr_lessons_in_one_call_is_refused(rig):
    routes, store, _ = rig
    too_many = [SYNTHETIC_REVIEW | {"text_in_plain_words": f"rule {n}"} for n in range(21)]

    with pytest.raises(BadRequestError, match="at most 20"):
        routes.add_lessons({"project": PROJECT, "lessons": too_many})
    assert store.curation.authored(PROJECT) == []


def test_a_pr_lesson_is_scrubbed_of_credentials_before_it_is_stored(rig):
    routes, store, _ = rig
    leaky = SYNTHETIC_REVIEW | {"text_in_plain_words": "Use token ghp_" + "a1B2" * 9 + " for CI."}

    routes.add_lessons({"project": PROJECT, "lessons": [leaky]})

    (kept,) = store.curation.authored(PROJECT)
    assert "ghp_" + "a1B2" * 9 not in kept.text


def test_the_dashboard_shows_the_label_and_link_and_it_is_the_lesson_not_a_context_suggestion(rig):
    routes, store, _ = rig
    routes.add_lessons({"project": PROJECT, "lessons": [SYNTHETIC_REVIEW]})

    data = dashboard_snapshot(
        RepoView(PROJECT, [], {}, {}, written=store.curation.authored(PROJECT)), date(2026, 11, 2)
    )

    (lesson,) = data["lessons"]
    assert (lesson["sourceLabel"], lesson["sourceUrl"]) == ("from PR #412 review", PR_URL)
    assert lesson["exampleContext"] == ""
    script = (Path(__file__).parents[2] / "src/symbiont/service/static/dashboard.js").read_text(
        encoding="utf-8"
    )
    assert "sourceChip" in script and "^https:" in script and "noopener" in script
    json.dumps(data)


def test_a_store_made_before_pr_lessons_gains_the_column_and_keeps_its_lessons(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE authored (id TEXT PRIMARY KEY, project TEXT NOT NULL, text TEXT NOT NULL, "
        "kind TEXT NOT NULL, files TEXT NOT NULL, source_label TEXT NOT NULL, "
        "severity TEXT NOT NULL, applies TEXT NOT NULL)"
    )
    db.execute(
        "INSERT INTO authored VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("w1", "shop", "Old rule.", "rule", "[]", "", "medium", '{"terms": [], "areas": []}'),
    )
    db.commit()
    db.close()

    (old,) = Store.open(path).curation.authored("shop")

    assert old.text == "Old rule." and old.source_url == ""


def test_the_pr_question_follows_the_focus_question_once(tmp_path):
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    start = Announcements(registry, Lookups()).at_session_start

    first, second, third = start(PROJECT), start(PROJECT), start(PROJECT)

    assert PR_QUESTION not in first and any("pay attention" in line for line in first)
    assert PR_QUESTION in second and PR_QUESTION not in third
    assert "learn-from-prs" in PR_QUESTION


def test_the_command_prints_the_steps_and_the_plugin_command_lists_it(capsys, tmp_path):
    from symbiont import cli

    code = cli.main(["learn-from-prs", "--project", PROJECT, "--data-dir", str(tmp_path)])

    assert code == 0 and "gh pr list --state merged" in capsys.readouterr().out
    plugin = Path(__file__).parents[2] / "plugin/symbiont/commands/symbiont.md"
    assert "learn-from-prs" in plugin.read_text(encoding="utf-8")


def test_symbiont_itself_reaches_no_network_for_this(tmp_path):
    source = (Path(__file__).parents[2] / "src/symbiont/service/pr_learning.py").read_text(
        encoding="utf-8"
    )
    assert not re.search(
        r"^\s*(import|from)\s+(urllib\.request|http|socket|subprocess)", source, re.M
    )
