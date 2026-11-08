"""A fetched review lesson quotes its own comment, never the tail of the whole `gh` output.

Failure guarded against: Silent Fallback (a quote of another comment's JSON standing in for the
lesson's evidence, carrying a teammate's login into the page, the candidate and Route B rows).
Synthetic comments only.
"""

import json
from dataclasses import replace
from datetime import date

from record_builders import edit, run, session
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.painpoint import Signal
from symbiont.routeb.signal_texts import CORRECTION_BY_SIGNAL, RECALL_BY_SIGNAL, quote_record
from symbiont.service.dashboard_view import RepoView, dashboard_snapshot
from symbiont.service.review_candidate import review_candidate
from symbiont.service.review_view import reviews_snapshot
from symbiont.service.rule_view import Triaged

BOT_BODY = "_⚠️ Potential issue_ | _🟠 Major_\n\n**Batch delete publishes once per item.**"
HUMAN_BODY = "@dev-person-two please fix the cache key here, it collides across tenants."
OUTPUT = json.dumps(
    [
        {
            "id": 11,
            "user": {"login": "coderabbitai[bot]"},
            "body": BOT_BODY,
            "path": "src/batch.ts",
        },
        {"id": 12, "user": {"login": "dev-person"}, "body": HUMAN_BODY, "path": "src/other.ts"},
    ],
    separators=(",", ":"),
)


def review_lessons():
    steps = session(
        run("gh api repos/o/r/pulls/3/comments", output=OUTPUT),
        edit("src/batch.ts"),
        edit("src/other.ts"),
    )
    steps = [replace(step, project="demo", session_id="s1") for step in steps]
    flags = [
        p for p in mine_history(sessions_of(steps), {}) if p.signature.signal is Signal.REVIEW_FLAG
    ]
    return lessons_from(flags, steps, frozenset()), steps


def by_file(lessons, path):
    return next(lesson for lesson in lessons if lesson.pain_point.signature.key[0] == path)


def test_each_lesson_quotes_its_own_comment():
    lessons, _ = review_lessons()
    bot, human = by_file(lessons, "src/batch.ts"), by_file(lessons, "src/other.ts")
    assert bot.quote.startswith("CodeRabbit on src/batch.ts: ")
    assert "Batch delete" in bot.quote and "cache key" not in bot.quote
    assert human.quote.startswith("a teammate on src/other.ts: ")
    assert (bot.error_lines, bot.complaint, bot.failed_command) == ((), "", "")


def test_no_login_or_json_key_reaches_the_snapshot_candidate_or_rows():
    lessons, steps = review_lessons()
    snapshot = dashboard_snapshot(RepoView("demo", lessons, {}, {}), date(2026, 11, 7))
    reviews = reviews_snapshot(lessons, {}, Triaged())
    candidates = [review_candidate(lesson, None) for lesson in lessons]
    rows = [_route_b_texts(lesson, steps) for lesson in lessons]
    shown = json.dumps([snapshot, reviews, candidates, rows], ensure_ascii=False)
    for leaked in ('"login"', "login", "dev-person", '"path"', '"body"', "@"):
        assert leaked not in shown, leaked
    assert "Batch delete publishes once per item" in shown


def quote(record):
    return quote_record(record, 400)


def _route_b_texts(lesson, steps):
    by_ref = {(r.session_id, r.step): r for r in steps}
    cited = [by_ref[ref] for ref in lesson.pain_point.record_refs]
    pain = lesson.pain_point
    recall = RECALL_BY_SIGNAL[Signal.REVIEW_FLAG](pain, cited, quote)
    situation, _, _ = CORRECTION_BY_SIGNAL[Signal.REVIEW_FLAG](pain, cited, steps, quote)
    return [*recall, situation]
