"""GET /dashboard/session reads one session's log on demand, scrubbed and local only.

Failures guarded against: Silent Fallback (a vanished log answered with an empty page) and
Leaky Narrative (a credential or a log's text in the event log).
"""

import json
from dataclasses import replace
from datetime import date

import pytest

from record_builders import edit, run, session, user
from symbiont.miner.mine import sessions_of
from symbiont.miner.session_summary import SessionSummary, SummaryOutcome
from symbiont.miner.struggle import facts_of
from symbiont.miner.themes import Codebase
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.service.dashboard_page import Live, dashboard_page
from symbiont.store.held_back import MiningOutcome
from symbiont.store.local import Source, Store
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery
PROJECT = "demo"
TOKEN = "Bearer " + "abcdefghij0123456789klmnop"


def read_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def rig(tmp_path, stance=RepoStance.GIVEN, reader="muse-code"):
    steps = session(
        user("fix the parser please"),
        run("pytest tests/test_p.py", 1, f"E   AssertionError: {TOKEN}"),
        edit("/home/dev/demo/src/p.py"),
    )
    records = [replace(r, project=PROJECT, session_id="s1", ts="2026-01-05T10:00:00+00:00")
               for r in steps]  # fmt: skip
    log = tmp_path / "log.jsonl"
    with log.open("w") as fh:
        dump_jsonl(records, fh)
    store = Store.open(tmp_path / "s.db")
    facts = facts_of(sessions_of(records), [], Codebase(frozenset({PROJECT})), frozenset())
    source = Source(PROJECT, reader, str(log))
    store.mined.save(PROJECT, [source], MiningOutcome([], facts=facts), held_out_tasks=frozenset())
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, stance)
    return store, registry, log


def get(store, registry, query, lines=None):
    live = Live(
        readers={"muse-code": read_jsonl, "swe-chat": read_jsonl},
        session_sensor=lambda project, line: lines.append((project, line)),
    )
    page = dashboard_page(store, registry, f"/dashboard/session?{query}", date(2026, 11, 7), live)
    return page.status, json.loads(page.body)


def test_a_known_session_answers_with_its_detail_and_a_sizes_only_sensor_line(tmp_path):
    store, registry, _ = rig(tmp_path)
    store.review.summaries.save(
        PROJECT, [SessionSummary("s1", "Fix the parser", SummaryOutcome.DONE, "flaky test", False)]
    )
    lines = []

    status, body = get(store, registry, f"project={PROJECT}&id=s1", lines)

    assert status == 200 and body["goal"] == "Fix the parser" and body["date"] == "2026-01-05"
    assert body["outcome"] == "done" and body["friction"] == "flaky test"
    assert body["counts"]["failed"] == 1 and "abcdefghij0123456789klmnop" not in json.dumps(body)
    assert len(lines) == 1 and lines[0][0] == PROJECT and "parser" not in lines[0][1]


def test_unsummarized_session_has_null_outcome(tmp_path):
    store, registry, _ = rig(tmp_path)

    _, body = get(store, registry, f"project={PROJECT}&id=s1", [])

    assert body["outcome"] is None and body["friction"] is None


@pytest.mark.parametrize("query", ["project=nope&id=s1", "id=s1", f"project={PROJECT}&id="])
def test_an_unknown_project_is_a_400_and_an_unknown_session_a_404(tmp_path, query):
    store, registry, _ = rig(tmp_path)

    status, body = get(store, registry, query, [])

    assert status == (404 if query.startswith("project=demo") else 400) and body["error"]


def test_a_project_not_allowed_is_a_400(tmp_path):
    store, registry, _ = rig(tmp_path, stance=RepoStance.DECLINED)

    status, body = get(store, registry, f"project={PROJECT}&id=s1", [])

    assert status == 400 and "allow" in body["error"]


def test_unknown_session_id_is_404_no_such_session(tmp_path):
    store, registry, _ = rig(tmp_path)

    assert get(store, registry, f"project={PROJECT}&id=zzz", []) == (
        404,
        {"error": "no such session"},
    )


def test_session_detail_missing_log(tmp_path):
    store, registry, log = rig(tmp_path)
    log.unlink()

    assert get(store, registry, f"project={PROJECT}&id=s1", []) == (
        404,
        {"error": "this session's log is no longer readable"},
    )


def test_dataset_history_is_never_shown(tmp_path):
    store, registry, _ = rig(tmp_path, reader="swe-chat")

    status, body = get(store, registry, f"project={PROJECT}&id=s1", [])

    assert status == 404 and body["error"] == "no such session"
