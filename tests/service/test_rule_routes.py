"""Standing rules through the session model: refusals, validation and the stored round trip.

Failures guarded against: Silent Fallback (dataset or barred history quietly offered, an
invented ref or an over-long rule accepted) and Paper Tiger (a dropped candidate offered again).
"""

import json
from dataclasses import dataclass, replace
from datetime import date

import pytest

from record_builders import say, session, user
from symbiont.miner.stated_rule import StatedRule
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.service.curation_routes import CurationRoutes
from symbiont.service.request_shapes import BadRequestError
from symbiont.service.rule_routes import RuleRoutes
from symbiont.service.summary_routes import SummaryRoutes
from symbiont.store.held_back import MiningOutcome
from symbiont.store.local import Source, Store
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import CorrectionSettings

pytestmark = pytest.mark.periphery
PROJECT = "demo"
REQUEST = {"project": PROJECT, "running_in": "muse_code"}
TODAY = date(2026, 11, 7)


def read_jsonl(path, project):
    with open(path, encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


@dataclass(frozen=True)
class Candidate:
    session_id: str
    step: int
    text: str
    terms: frozenset[str] = frozenset()
    source: str = "message"


def rule(text="Never mock the database.", refs=(("a", 1),), **more):
    return {"rule": text, "scope": "repo", "refs": [list(r) for r in refs]} | more


def rig(tmp_path, candidates, logs=None):
    store = Store.open(tmp_path / "s.db")
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    logs = logs or {"muse-code": ["a", "b"]}
    sources = []
    for reader, ids in logs.items():
        records = [
            replace(r, project=PROJECT, session_id=ident)
            for ident in ids
            for r in session(user("hi"), say("ok"))
        ]
        path = tmp_path / f"{reader}.jsonl"
        with path.open("w") as fh:
            dump_jsonl(records, fh)
        sources.append(Source(PROJECT, reader, str(path)))
    store.mined.save(PROJECT, sources, MiningOutcome([]), held_out_tasks=frozenset())
    readers = {"swe-chat": read_jsonl, "muse-code": read_jsonl, "claude-code": read_jsonl}
    curation = CurationRoutes(store, registry, lambda: CorrectionSettings(), readers)
    summaries = SummaryRoutes(curation, store, readers, lambda: TODAY)
    return RuleRoutes(curation, summaries, store, lambda _: candidates), store


def pair():
    return [Candidate("a", 1, "Never mock the database."), Candidate("b", 4, "no db mocks")]


def test_candidates_carry_ref_text_and_date_and_a_saved_rule_covers_its_refs(tmp_path):
    routes, store = rig(tmp_path, pair())

    answer = routes.rule_candidates(REQUEST)

    assert answer["remaining"] == 0 and answer["not_shown"] == []
    assert answer["candidates"][0] == {
        "ref": ["a", 1], "text": "Never mock the database.", "date": "date unknown"
    }  # fmt: skip
    saved = routes.save_rules(REQUEST | {"rules": [rule(refs=(("a", 1), ("b", 4)))]})
    assert saved == {"saved": 1, "dropped": 0}
    assert routes.rule_candidates(REQUEST)["candidates"] == []
    (kept,) = store.review.rules.rules(PROJECT)
    assert kept.key == "rule:a:1" and kept.refs == (("a", 1), ("b", 4))


def test_a_dropped_candidate_is_not_offered_again_and_rules_are_optional_per_batch(tmp_path):
    routes, _ = rig(tmp_path, pair())

    routes.save_rules(REQUEST | {"rules": [rule(dropped=[["b", 4]])]})

    assert routes.rule_candidates(REQUEST)["candidates"] == []


def test_dataset_history_is_refused_like_session_candidates(tmp_path):
    logs = {"muse-code": ["a", "b"], "swe-chat": ["z"]}
    routes, _ = rig(tmp_path, pair(), logs=logs)

    with pytest.raises(BadRequestError, match="swe-chat dataset history is not shown"):
        routes.rule_candidates(REQUEST)


def test_a_barred_harness_is_not_offered_and_is_named(tmp_path):
    logs = {"muse-code": ["a"], "claude-code": ["b"]}
    routes, _ = rig(tmp_path, pair(), logs=logs)

    answer = routes.rule_candidates(REQUEST)

    assert [c["ref"] for c in answer["candidates"]] == [["a", 1]]
    assert "claude_code history is not shown to a muse_code session" in answer["not_shown"][0]
    assert "no db mocks" not in json.dumps(answer)
    with pytest.raises(BadRequestError, match="no candidate"):
        routes.save_rules(REQUEST | {"rules": [rule(refs=(("b", 4),))]})


@pytest.mark.parametrize(
    ("item", "message"),
    [
        (rule("x" * 121), "over 120"),
        (rule("one.\ntwo."), "one line"),
        (rule(""), "rule must be text"),
        (rule(scope="team"), "scope must be repo or area"),
        (rule(scope="area"), "area must be a path"),
        (rule(refs=()), "needs at least one ref"),
        (rule(refs=(("nope", 9),)), "no candidate .*nope"),
        (rule(dropped=[["a"]]), "dropped must be"),
    ],
)
def test_a_bad_rule_is_refused_with_advice_and_nothing_is_stored(tmp_path, item, message):
    routes, store = rig(tmp_path, pair())

    with pytest.raises(BadRequestError, match=message) as refused:
        routes.save_rules(REQUEST | {"rules": [rule(), item]})

    assert "resend" in str(refused.value)
    assert store.review.rules.rules(PROJECT) == [] and store.review.rules.covered(PROJECT) == set()


def test_candidates_need_running_in_and_a_credential_in_a_rule_is_scrubbed(tmp_path):
    routes, store = rig(tmp_path, pair())
    secret = "ghp_" + "a1B2c3D4e5F6g7H8i9J0" * 2

    with pytest.raises(BadRequestError, match="running_in must be"):
        routes.rule_candidates({"project": PROJECT})
    routes.save_rules(REQUEST | {"rules": [rule(f"Use token {secret} for pushes.")]})

    (kept,) = store.review.rules.rules(PROJECT)
    assert secret not in kept.rule


def test_a_batch_with_two_rules_for_one_key_is_refused(tmp_path):
    routes, _ = rig(tmp_path, pair())

    with pytest.raises(BadRequestError, match="more than one rule for rule:a:1"):
        routes.save_rules(REQUEST | {"rules": [rule(), rule("Same again.")]})


def test_more_than_eighty_candidates_leave_a_remainder(tmp_path):
    many = [Candidate("a", n, f"m{n}") for n in range(85)]
    routes, _ = rig(tmp_path, many)

    answer = routes.rule_candidates(REQUEST)

    assert len(answer["candidates"]) == 80 and answer["remaining"] == 5


def test_stated_rule_is_a_value():
    assert StatedRule("r", "repo", "", (("b", 2), ("a", 9))).key == "rule:a:9"
