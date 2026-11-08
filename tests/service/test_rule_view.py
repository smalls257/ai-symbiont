"""The `rules` snapshot: confirmed beats grouped, a dismissal survives a re-mine, quotes are safe.

Failures guarded against: Silent Fallback (a dismissed rule coming back under a new key, a
credential in a quote) and Paper Tiger (single remarks listed as repeated rules).
"""

from dataclasses import replace
from datetime import date

import pytest

from record_builders import session, user
from symbiont.core.triage import GroupState, TriageRow
from symbiont.miner.rule_candidates import RuleCandidate
from symbiont.miner.stated_rule import RuleScope, StatedRule
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.service.rule_view import (
    Triaged,
    member_refs,
    rule_entries,
    rules_listing,
    rules_snapshot,
)
from symbiont.store.local import Source, Store
from symbiont.store.mining import MiningRules, remine

SECRET = "abcd1234" + "efgh5678"  # built at runtime so no secret scanner reads a literal


def cand(session_id, step, text, terms=("pnpm",)):
    return RuleCandidate(session_id, step, text, frozenset(terms), "rule_words")


DATES = {"s1": date(2026, 1, 1), "s2": date(2026, 2, 1), "s3": date(2026, 3, 1)}
PAIR = [cand("s1", 1, "always use pnpm, never npm"), cand("s2", 2, "use pnpm")]


NONE = Triaged()


def snapshot(entries, candidates, triaged=NONE, dates=DATES):
    return rules_snapshot(entries, candidates, dates, triaged)


def test_confirmed_rules_replace_the_grouped_fallback():
    rule = StatedRule("Use pnpm.", RuleScope.AREA, "web/", (("s1", 1), ("s2", 2)))
    shown = snapshot(rule_entries([rule], PAIR), PAIR)
    assert shown["confirmed"] is True
    (item,) = shown["items"]
    assert (item["text"], item["confirmed"], item["scope"], item["area"]) == (
        "Use pnpm.", True, "area", "web/",
    )  # fmt: skip


def test_groups_of_one_message_are_hidden_and_groups_of_two_are_unconfirmed():
    lonely = [cand("s3", 1, "never mock the database", ("mock", "database"))]
    shown = snapshot(rule_entries([], [*PAIR, *lonely]), [*PAIR, *lonely])
    assert shown["confirmed"] is False
    (item,) = shown["items"]
    assert item["confirmed"] is False and item["text"] == "use pnpm"


def test_counts_dates_and_examples_come_from_the_sessions_newest_first():
    many = [cand(f"s{n}", 1, f"always use pnpm {n}") for n in (1, 2, 3)] + [
        cand("s3", 5, "use pnpm please")
    ]
    (item,) = snapshot(rule_entries([], many), many)["items"]
    assert (item["times"], item["sessions"]) == (4, 3)
    assert (item["first"], item["last"]) == ("2026-01-01", "2026-03-01")
    assert len(item["examples"]) == 3
    assert [e["sessionId"] for e in item["examples"]] == ["s3", "s3", "s2"]
    assert item["examples"][0]["step"] == 5 and item["examples"][0]["date"] == "2026-03-01"


def test_undated_sessions_stay_null_and_rules_sort_by_sessions_then_last():
    wide = [cand(f"s{n}", 1, "use pnpm") for n in (1, 2, 3)]
    narrow = [cand("n1", 1, "never rm", ("rm",)), cand("n2", 1, "never rm -rf", ("rm",))]
    shown = snapshot(rule_entries([], wide + narrow), wide + narrow)
    assert [i["sessions"] for i in shown["items"]] == [3, 2]
    assert shown["items"][1]["last"] is None and shown["items"][1]["examples"][0]["date"] is None


def test_quotes_are_scrubbed_one_line_and_capped():
    secret_line = f"always use pnpm\ntoken={SECRET} " + "x" * 300
    pair = [cand("s1", 1, secret_line), cand("s2", 2, secret_line)]
    rule = StatedRule(f"Use pnpm token={SECRET}", RuleScope.REPO, "", (("s1", 1), ("s2", 2)))
    (item,) = snapshot(rule_entries([rule], pair), pair)["items"]
    for text in (item["text"], item["examples"][0]["text"]):
        assert SECRET not in text and "\n" not in text and len(text) <= 120


def test_a_dismissed_rule_is_counted_not_listed_and_a_taught_one_is_marked():
    first = StatedRule("Use pnpm.", RuleScope.REPO, "", (("s1", 1),))
    second = StatedRule("No mocks.", RuleScope.REPO, "", (("s2", 2),))
    entries = rule_entries([first, second], PAIR)
    shown = snapshot(entries, PAIR, Triaged(dismissed=[first.key], taught=[second.key]))
    assert shown["dismissed"] == 1
    assert [(i["key"], i["state"]) for i in shown["items"]] == [(second.key, "taught")]


def test_a_rule_whose_member_was_dismissed_under_another_key_stays_dismissed():
    moved = StatedRule("Use pnpm.", RuleScope.REPO, "", (("s0", 1), ("s1", 1)))
    triaged = Triaged(dismissed=["rule:s1:1"], members={"rule:s1:1": frozenset({("s1", 1)})})
    shown = snapshot(rule_entries([moved], PAIR), PAIR, triaged)
    assert shown["items"] == [] and shown["dismissed"] == 1


# --- through the store: dismiss, add an earlier session, re-mine ---
PROJECT = "demo"
READER = "records-jsonl"


def read_records_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def mine(tmp_path, store, name, *turns):
    records = [replace(r, session_id=name) for r in session(*(user(t) for t in turns))]
    path = tmp_path / name
    with path.open("w") as fh:
        dump_jsonl(records, fh)
    rules = MiningRules({READER: read_records_jsonl}, frozenset())
    remine(store, PROJECT, rules, adding=[Source(PROJECT, READER, str(path))])


def dismiss(store, key, day=date(2026, 11, 7)):
    store.review.rules.remember_members(PROJECT, key, member_refs(store, PROJECT, key))
    row = TriageRow(GroupState.ARCHIVED, None, None, day, None)
    store.review.triage.save(PROJECT, key, row)


@pytest.mark.periphery
def test_dismiss_then_an_earlier_session_changes_the_key_and_it_stays_dismissed(tmp_path):
    store = Store.open(tmp_path / "s.db")
    mine(tmp_path, store, "m-b.jsonl", "always use pnpm, never npm")
    mine(tmp_path, store, "m-c.jsonl", "use pnpm instead of npm")
    (before,) = rules_listing(store, PROJECT, {})["items"]
    dismiss(store, before["key"])

    mine(tmp_path, store, "m-a.jsonl", "always use pnpm, never npm here")
    after = rules_listing(store, PROJECT, {})

    assert after["items"] == [] and after["dismissed"] == 1
    renamed = {e.key for e in rule_entries([], store.mined.rule_candidates(PROJECT))}
    assert before["key"] not in renamed
