"""Summaries in batches of 40, then one topic request: the routes the session's model loops over.

Failures guarded against: Silent Fallback (a session lost from every topic, a bad write accepted),
Computational Friction (one request per session) and Infected Core of the privacy rule (history
of another harness shown to this session's model).
"""

from dataclasses import replace

import pytest

from record_builders import edit, say, session, user
from symbiont.miner.mine import sessions_of
from symbiont.miner.struggle import facts_of
from symbiont.miner.themes import Codebase
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.service.curation_routes import CurationRoutes
from symbiont.service.request_shapes import BadRequestError
from symbiont.service.summary_routes import MIN_TOPIC_SESSIONS, SUMMARY_BATCH, SummaryRoutes
from symbiont.store.held_back import MiningOutcome
from symbiont.store.local import Source, Store
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import CorrectionSettings

pytestmark = pytest.mark.periphery
PROJECT = "demo"
RUNNING = {"project": PROJECT, "running_in": "muse_code"}


def read_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def records_of(count, prefix="s"):
    out = []
    for number in range(count):
        steps = session(
            user(f"please make feature number {number} work properly"),
            edit(f"/home/dev/demo/src/f{number}.py"),
            say("done"),
            user("no, that is wrong, undo it", ("correction",)),
            user("thanks"),
        )
        stamp = f"2026-01-{1 + number % 28:02d}T10:00:00Z"
        out += [
            replace(r, project=PROJECT, session_id=f"{prefix}{number:03d}", ts=stamp) for r in steps
        ]
    return out


def rig(tmp_path, count, settings=None):
    records = records_of(count)
    log = tmp_path / "log.jsonl"
    with log.open("w") as fh:
        dump_jsonl(records, fh)
    store = Store.open(tmp_path / "s.db")
    facts = facts_of(sessions_of(records), [], Codebase(frozenset({PROJECT})), frozenset())
    source = Source(PROJECT, "muse-code", str(log))
    store.mined.save(PROJECT, [source], MiningOutcome([], facts=facts), held_out_tasks=frozenset())
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    readers = {"muse-code": read_jsonl}
    curation = CurationRoutes(store, registry, lambda: settings or CorrectionSettings(), readers)
    return SummaryRoutes(curation, store, readers), store


def summary(ident, **changes):
    item = {
        "session_id": ident,
        "goal": "Build a feature",
        "outcome": "done",
        "friction": "",
        "noise": False,
    }
    return item | changes


def test_candidates_come_in_batches_of_forty_oldest_first_and_stop_at_summarized(tmp_path):
    routes, _ = rig(tmp_path, 95)

    first = routes.session_candidates(RUNNING)
    routes.save_summaries(
        {"project": PROJECT, "summaries": [summary(c["session_id"]) for c in first["candidates"]]}
    )
    second = routes.session_candidates(RUNNING)

    assert len(first["candidates"]) == SUMMARY_BATCH == 40 and first["remaining"] == 55
    assert [c["date"] for c in first["candidates"]] == sorted(
        c["date"] for c in first["candidates"]
    )
    assert not {c["session_id"] for c in first["candidates"]} & {
        c["session_id"] for c in second["candidates"]
    }
    assert second["remaining"] == 15
    digest = first["candidates"][0]
    assert digest["asks"] and digest["files"][0].startswith("src/f")
    assert digest["last_turns"][-1] == "developer: thanks" and digest["corrections"]


def test_another_harness_history_is_not_shown_to_this_session(tmp_path):
    routes, _ = rig(tmp_path, 3)

    held = routes.session_candidates({"project": PROJECT, "running_in": "claude_code"})

    assert held["candidates"] == [] and "muse_code history is not shown" in held["not_shown"][0]


def test_a_bad_summary_is_refused_with_advice_and_nothing_is_stored(tmp_path):
    routes, store = rig(tmp_path, 3)
    bad = [
        summary("s000", goal=" ".join(["word"] * 30)),
        summary("nope"),
        summary("s001", outcome="great"),
    ]

    for item, message in zip(bad, ["goal", "no session nope", "outcome"], strict=True):
        with pytest.raises(BadRequestError, match=message) as refused:
            routes.save_summaries({"project": PROJECT, "summaries": [summary("s002"), item]})
        assert "resend" in str(refused.value)
    assert store.review.summaries.summarized(PROJECT) == frozenset()


def summarize_all(routes, count, noisy=0):
    items = [summary(f"s{n:03d}", noise=n < noisy) for n in range(count)]
    routes.save_summaries({"project": PROJECT, "summaries": items})


def test_topics_wait_for_enough_summaries_and_say_how_many_more(tmp_path):
    routes, _ = rig(tmp_path, 40)
    summarize_all(routes, 12)

    answer = routes.topic_candidates(RUNNING)

    assert (
        answer["candidates"] == [] and answer["summaries_still_needed"] == MIN_TOPIC_SESSIONS - 12
    )


def test_topic_candidates_carry_each_sessions_corrections_with_their_step(tmp_path):
    routes, _ = rig(tmp_path, 40)
    summarize_all(routes, 35, noisy=3)

    answer = routes.topic_candidates(RUNNING)

    assert len(answer["candidates"]) == 32
    first = answer["candidates"][0]
    assert first["corrections"] == [{"step": 3, "text": "no, that is wrong, undo it"}]
    assert first["goal"] == "Build a feature" and first["date"].startswith("2026-")


def topic_request(ids, **changes):
    body = {
        "project": PROJECT,
        "running_in": "muse_code",
        "topics": [{"name": "Feature work", "description": "features", "session_ids": ids}],
        "frictions": [],
        "correction_groups": [{"name": "Undo it", "description": "reverts", "refs": [[ids[0], 3]]}],
    }
    return body | changes


def test_save_topics_refuses_a_missing_and_a_doubled_session_then_keeps_a_complete_map(tmp_path):
    routes, store = rig(tmp_path, 40)
    summarize_all(routes, 31)
    ids = [f"s{n:03d}" for n in range(31)]

    with pytest.raises(BadRequestError, match="missing: s030"):
        routes.save_topics(topic_request(ids[:30]))
    doubled = [{"name": "More work", "description": "x", "session_ids": ids[:1]}]
    with pytest.raises(BadRequestError, match="placed twice: s000"):
        routes.save_topics(topic_request(ids, topics=topic_request(ids)["topics"] + doubled))
    assert store.review.summaries.topics(PROJECT).topics == ()

    saved = routes.save_topics(topic_request(ids))

    assert saved == {"topics": 1, "frictions": 0, "correction_groups": 1}
    assert store.review.summaries.topics(PROJECT).topics[0].name == "Feature work"


def rig_mixed(tmp_path, muse=31, claude=3, unmined=1):
    """Muse, Claude Code and swe-chat logs; `unmined` Muse sessions are missing from the facts."""
    logs = {
        "muse-code": records_of(muse + unmined, "m"),
        "claude-code": records_of(claude, "c"),
        "swe-chat": records_of(2, "w"),
    }
    store = Store.open(tmp_path / "s.db")
    sources, mined = [], []
    for reader, records in logs.items():
        path = tmp_path / f"{reader}.jsonl"
        with path.open("w") as fh:
            dump_jsonl(records, fh)
        sources.append(Source(PROJECT, reader, str(path)))
        mined += [
            r for r in records if not r.session_id.startswith("m") or int(r.session_id[1:]) < muse
        ]
    facts = facts_of(sessions_of(mined), [], Codebase(frozenset({PROJECT})), frozenset())
    store.mined.save(PROJECT, sources, MiningOutcome([], facts=facts), held_out_tasks=frozenset())
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    readers = dict.fromkeys(logs, read_jsonl)
    settings = CorrectionSettings(cross_harness=False)
    curation = CurationRoutes(store, registry, lambda: settings, readers)
    return SummaryRoutes(curation, store, readers), store


def test_sessions_that_were_never_mined_are_not_offered_and_are_counted(tmp_path):
    routes, _ = rig_mixed(tmp_path)

    answer = routes.session_candidates(RUNNING)
    ids = {c["session_id"] for c in answer["candidates"]}

    assert "m031" not in ids and len(ids) == 31
    assert answer["not_mined"] == "re-mine to include 1 sessions"
    routes.save_summaries({"project": PROJECT, "summaries": [summary(i) for i in sorted(ids)]})


def test_swe_chat_history_is_said_to_be_withheld_with_its_session_count(tmp_path):
    routes, _ = rig_mixed(tmp_path)

    shown = routes.session_candidates(RUNNING)["not_shown"]

    assert "swe-chat dataset history is not shown to a session model (2 sessions)" in shown


def summarize_mixed(routes):
    muse = [f"m{n:03d}" for n in range(31)]
    routes.save_summaries({"project": PROJECT, "summaries": [summary(i) for i in muse]})
    routes.save_summaries(
        {"project": PROJECT, "summaries": [summary(f"c{n:03d}") for n in range(3)]}
    )
    return muse


def test_topic_candidates_and_the_map_cover_only_sessions_this_harness_may_read(tmp_path):
    routes, store = rig_mixed(tmp_path)
    muse = summarize_mixed(routes)

    offered = routes.topic_candidates(RUNNING)
    complete = topic_request(muse)
    saved = routes.save_topics(complete)
    with_foreign = topic_request(muse + ["c000"])

    assert {c["session_id"] for c in offered["candidates"]} == set(muse)
    assert saved["topics"] == 1
    with pytest.raises(BadRequestError, match="unknown session ids.*c000"):
        routes.save_topics(with_foreign)
    assert store.review.summaries.topics(PROJECT).topics[0].session_ids == tuple(muse)


def test_the_models_own_words_are_scrubbed_on_save(tmp_path):
    routes, store = rig_mixed(tmp_path)
    secret = "ghp_" + "a" * 36
    routes.save_summaries(
        {
            "project": PROJECT,
            "summaries": [summary("m000", goal=f"Use {secret} now", friction=f"token={secret}")],
        }
    )
    muse = [f"m{n:03d}" for n in range(31)]
    routes.save_summaries({"project": PROJECT, "summaries": [summary(i) for i in muse[1:]]})
    request = topic_request(muse)
    request["topics"][0]["name"] = "Feature work"
    request["topics"][0]["description"] = f"uses {secret}"
    request["correction_groups"][0]["description"] = f"key {secret}"

    routes.save_topics(request)

    stored = store.review.summaries.all(PROJECT)
    text = repr(stored) + repr(store.review.summaries.topics(PROJECT))
    assert secret not in text and "[secret]" in text


def test_a_correction_ref_to_a_step_that_was_not_offered_is_refused_by_name(tmp_path):
    routes, _ = rig_mixed(tmp_path)
    muse = summarize_mixed(routes)
    request = topic_request(muse)
    request["correction_groups"][0]["refs"] = [["m000", 3], ["m001", 99]]

    with pytest.raises(BadRequestError, match=r"unknown corrections.*m001:99"):
        routes.save_topics(request)
